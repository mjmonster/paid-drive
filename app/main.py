import asyncio
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import hmac
import json
import mimetypes
from pathlib import Path
import secrets
import tempfile
from urllib.parse import parse_qsl
import uuid
import zipfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from .access import (audit, email_hint, enqueue_link, fulfil_order, normalize_email,
                     now, order_payload, session_purchase, token_hash)
from .catalog import Catalog
from .config import BASE_DIR, Settings
from .db import Database
from .mail import process_mail_jobs
from .payments import PaymentError, ZPay

STATIC = BASE_DIR / "app/static"


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrderRequest(Payload):
    collection_id: str = Field(max_length=80)
    email: str | None = Field(default=None, max_length=254)


class EmailRequest(Payload):
    email: str = Field(max_length=254)


class AttachRequest(EmailRequest):
    purchase_id: str = Field(max_length=64)


class RedeemRequest(Payload):
    token: str = Field(min_length=20, max_length=128)


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    settings.validate()
    # Originals must never be reachable through the public /assets mount,
    # including when an operator configures either directory via a symlink.
    private_root, public_root = settings.content_root.resolve(), STATIC.resolve()
    if private_root.is_relative_to(public_root) or public_root.is_relative_to(private_root):
        raise ValueError("CONTENT_ROOT 必须与公开静态资源目录分开，不能互相包含。")
    db = Database(settings.database_path)
    catalog = Catalog(settings.content_root, db)
    gateway = ZPay(settings)
    cookie_name = "paiddrive_live" if settings.app_mode == "live" else "paiddrive_demo"

    async def mail_worker():
        while True:
            await asyncio.to_thread(process_mail_jobs, db, settings)
            await asyncio.sleep(3)

    @asynccontextmanager
    async def lifespan(application):
        worker = asyncio.create_task(mail_worker()) if settings.run_background_jobs and settings.email_enabled else None
        try:
            yield
        finally:
            if worker:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker

    application = FastAPI(title="PaidDrive", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    application.state.settings = settings
    application.state.db = db
    application.state.catalog = catalog
    application.state.gateway = gateway

    def new_session(con):
        raw, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        sid = token_hash(raw)
        con.execute("INSERT INTO sessions(id,csrf_token,expires_at) VALUES(?,?,?)", (sid, csrf, now() + settings.session_days * 86400))
        return raw, sid, csrf

    def limit(bucket, maximum, seconds):
        # Persisted so changing cookies and app restarts do not erase limits.
        bucket = token_hash(bucket)
        stamp = now()
        with db.transaction() as con:
            row = con.execute("SELECT * FROM rate_limits WHERE bucket=?", (bucket,)).fetchone()
            if not row or stamp - row["window_start"] >= seconds:
                con.execute("INSERT INTO rate_limits(bucket,window_start,hits) VALUES(?,?,1) ON CONFLICT(bucket) DO UPDATE SET window_start=excluded.window_start,hits=1", (bucket, stamp))
            elif row["hits"] >= maximum:
                raise HTTPException(429, "操作有点频繁，请稍后再试。", headers={"Retry-After": str(seconds)})
            else:
                con.execute("UPDATE rate_limits SET hits=hits+1 WHERE bucket=?", (bucket,))

    def check_csrf(request):
        supplied = request.headers.get("x-csrf-token", "")
        if not supplied or not hmac.compare_digest(supplied, request.state.csrf):
            raise HTTPException(403, "请刷新页面后重试。")
        origin = request.headers.get("origin")
        allowed = {settings.app_url}
        if settings.app_mode == "demo":
            allowed.add(str(request.base_url).rstrip("/"))
        if origin and origin.rstrip("/") not in allowed:
            raise HTTPException(403, "请求来源无效，请在本站重新操作。")

    def owned_order(order_id, sid):
        with db.connection() as con:
            row = con.execute("SELECT * FROM orders WHERE id=? AND session_id=? AND mode=?", (order_id, sid, settings.app_mode)).fetchone()
        if not row:
            raise HTTPException(404, "当前浏览器找不到这笔订单，请通过邮箱恢复访问，或联系微信客服。")
        return row

    def public_order(order):
        pay_url = None
        if order["mode"] == "live" and order["status"] == "pending":
            collection = catalog.get(order["collection_id"], order["version"])
            pay_url = gateway.pay_url(order["reference"], order["amount_cents"], collection["title"] if collection else "PaidDrive")
        return order_payload(order, catalog, pay_url)

    async def settle_if_paid(order):
        """Ask ZPay about a pending order; settle it if paid. Fail-soft: gateway
        trouble leaves it pending so the browser simply polls again."""
        try:
            status = await gateway.query(order["reference"])
        except PaymentError:
            return False
        if not status.paid:
            return False
        fulfil_order(db, settings, order["id"], status.trade_no)
        return True

    def my_purchase(sid, **filters):
        with db.connection() as con:
            row = session_purchase(con, sid, mode=settings.app_mode, **filters)
        return row

    @application.middleware("http")
    async def browser_session(request, call_next):
        # Public CSS/JS and the provider callback need no browser session.
        path = request.url.path
        needs_session = not path.startswith("/assets/") and path not in {"/health", "/favicon.ico", "/api/payments/zpay/notify", "/support-qr"}
        if needs_session:
            raw = request.cookies.get(cookie_name, "")
            sid = token_hash(raw) if raw else ""
            with db.connection() as con:
                session = con.execute("SELECT * FROM sessions WHERE id=? AND expires_at>?", (sid, now())).fetchone()
            if not session:
                with db.transaction() as con:
                    raw, sid, csrf = new_session(con)
                request.state.new_cookie = raw
            else:
                csrf = session["csrf_token"]
            request.state.sid, request.state.csrf = sid, csrf
        # Limit large request bodies before JSON/form processing.
        if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", "0")) > 16384:
            response = JSONResponse({"detail": "请求内容过大。"}, status_code=413)
        else:
            response = await call_next(request)
        if getattr(request.state, "new_cookie", None):
            response.set_cookie(cookie_name, request.state.new_cookie, max_age=settings.session_days * 86400,
                                secure=settings.app_mode == "live", httponly=True, samesite="lax", path="/")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if settings.app_mode == "live":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self' sdk.51.la 'sha256-DqxOVKWrmOA5DRv+5piC2/d118OcghWPyNvbTM1CZWE='; style-src 'self'; img-src 'self' data: *.51.la; font-src 'self'; connect-src 'self' *.51.la; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if not path.startswith("/assets/"):
            response.headers["Cache-Control"] = "private, no-store"
        return response

    @application.get("/health")
    def health():
        with db.connection() as con:
            con.execute("SELECT 1")
        return {"status": "ok", "mode": settings.app_mode}

    @application.get("/api/bootstrap")
    def bootstrap(request: Request, slug: str | None = None, order_id: str | None = None, order_reference: str | None = None):
        limit("browse:" + (request.client.host if request.client else "unknown"), 600, 60)
        selected_order = None
        if order_id or order_reference:
            # A payment return parameter selects the original browser's order;
            # it is never proof of payment or a transferable access credential.
            column, value = ("id", order_id) if order_id else ("reference", order_reference)
            with db.connection() as con:
                selected_order = con.execute(f"SELECT * FROM orders WHERE {column}=? AND session_id=? AND mode=?", (value, request.state.sid, settings.app_mode)).fetchone()
            if not selected_order:
                raise HTTPException(404, "这笔订单不属于当前浏览器，请回到付款时的浏览器，或通过邮箱、微信客服恢复访问。")
            current = catalog.get(selected_order["collection_id"], selected_order["version"])
        else:
            current = catalog.for_slug(slug)
        if not current:
            raise HTTPException(404, "未找到这个合集。")
        purchase = my_purchase(request.state.sid, collection_id=current["id"], version=current["version"] if selected_order else None)
        collection = catalog.get(current["id"], purchase["version"]) if purchase else current
        items = []
        for index, item in enumerate(collection["items"]):
            preview = index < collection["preview_count"]
            allowed = bool(purchase) or preview
            items.append({"id": item["id"], "title": item["title"], "width": item["width"], "height": item["height"],
                          "is_preview": preview, "unlocked": allowed,
                          "url": f"/media/{collection['id']}/{collection['version']}/{item['id']}" if allowed else None})
        with db.connection() as con:
            latest = selected_order or con.execute("SELECT * FROM orders WHERE session_id=? AND collection_id=? AND mode=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (request.state.sid, current["id"], settings.app_mode)).fetchone()
        public = {k: collection[k] for k in ("id", "slug", "version", "title", "subtitle", "description", "creator", "price_cents", "currency", "preview_count")}
        public.update({"total_count": len(items), "items": items, "size_bytes": sum(i["size_bytes"] for i in collection["items"]),
                       "download_url": f"/files/{collection['id']}/{collection['version']}/download" if purchase else None})
        return {
            "site": {"name": "PaidDrive", "mode": settings.app_mode, "support_qr_url": "/support-qr",
                     "support_is_placeholder": settings.support_qr_path is None,
                     "email_enabled": settings.email_enabled, "mail_mode": settings.mail_mode},
            "csrf_token": request.state.csrf, "collection": public,
            "access": {"unlocked": bool(purchase), "purchase_id": purchase["id"] if purchase else None,
                       "order_reference": purchase["reference"] if purchase else None,
                       "email_hint": email_hint(purchase["verified_email"]) if purchase else None,
                       "email_verified": bool(purchase and purchase["verified_email"])},
            "latest_order": public_order(latest) if latest else None,
        }

    @application.post("/api/orders")
    async def create_order(payload: OrderRequest, request: Request):
        """Demo: the click that creates the order also pays it.
        Live: like soccer-match-analyzer's createForMatch: reuse this browser's open
        order (after asking ZPay whether it is already paid), else mint a new one,
        and hand back the signed cashier URL."""
        check_csrf(request)
        limit("orders:" + (request.client.host if request.client else "unknown"), 30, 3600)
        collection = catalog.get(payload.collection_id)
        if not collection:
            raise HTTPException(404, "未找到这个合集。")
        email = normalize_email(payload.email)
        if email and not settings.email_enabled:
            raise HTTPException(503, "邮箱恢复暂不可用。你可以不填邮箱继续购买，需要帮助时联系微信客服。")
        sid = request.state.sid
        with db.connection() as con:
            if session_purchase(con, sid, collection_id=collection["id"], version=collection["version"], mode=settings.app_mode):
                raise HTTPException(409, "当前浏览器已购买这个合集，请刷新页面查看。")
            existing = None if settings.app_mode == "demo" else con.execute(
                "SELECT * FROM orders WHERE session_id=? AND collection_id=? AND version=? AND amount_cents=? AND mode='live' AND status='pending' ORDER BY created_at DESC,rowid DESC LIMIT 1",
                (sid, collection["id"], collection["version"], collection["price_cents"])).fetchone()
        if existing:
            # The buyer may have paid before the notify reached us: settle instead of re-billing.
            if not await settle_if_paid(existing):
                with db.transaction() as con:
                    con.execute("UPDATE orders SET email=? WHERE id=? AND status='pending'", (email, existing["id"]))
            return public_order(owned_order(existing["id"], sid))
        order_id = uuid.uuid4().hex
        reference = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + f"{secrets.randbelow(10**14):014d}"
        method = "demo" if settings.app_mode == "demo" else settings.zpay_pay_type
        with db.transaction() as con:
            con.execute("INSERT INTO orders(id,reference,session_id,collection_id,version,amount_cents,currency,email,payment_method,mode,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (order_id, reference, sid, collection["id"], collection["version"], collection["price_cents"], "CNY", email, method, settings.app_mode, now()))
            audit(con, "order_created", reference)
        if settings.app_mode == "demo":
            fulfil_order(db, settings, order_id, "demo-" + order_id)
        return public_order(owned_order(order_id, sid))

    @application.get("/api/orders/{order_id}")
    def get_order(order_id: str, request: Request):
        return public_order(owned_order(order_id, request.state.sid))

    @application.post("/api/orders/{order_id}/refresh")
    async def refresh_order(order_id: str, request: Request):
        """Poll path, like soccer-match-analyzer's PaymentService.verify.

        Runs in parallel with the notify path; whichever sees payment first settles
        the order and the other finds it already paid.
        """
        check_csrf(request)
        limit("refresh:" + request.state.sid, 40, 60)
        order = owned_order(order_id, request.state.sid)
        if order["status"] == "pending" and order["mode"] == "live":
            await settle_if_paid(order)
        return public_order(owned_order(order_id, request.state.sid))

    @application.get("/api/payments/zpay/notify")
    def payment_notification(request: Request):
        """ZPay async notify, settled like soccer-match-analyzer's handleZPayCallback.

        Trusted only after the MD5 signature verifies AND the money equals our order.
        Reply ``success`` for anything genuine (including duplicates and non-success
        statuses) so ZPay stops retrying; ``fail`` makes ZPay retry later.
        """
        if settings.app_mode != "live":
            return PlainTextResponse("fail", status_code=404)
        raw = request.url.query
        if len(raw) > 8192:
            return PlainTextResponse("fail", status_code=400)
        try:
            pairs = parse_qsl(raw, keep_blank_values=True, max_num_fields=32)
        except ValueError:
            return PlainTextResponse("fail", status_code=400)
        if len({key for key, value in pairs}) != len(pairs):
            return PlainTextResponse("fail", status_code=400)
        notice = gateway.parse_notify(dict(pairs))
        if not notice.valid:
            return PlainTextResponse("fail", status_code=400)
        if not notice.success:
            return PlainTextResponse("success")
        with db.connection() as con:
            order = con.execute("SELECT * FROM orders WHERE reference=? AND mode='live'", (notice.reference,)).fetchone()
        if not order:
            return PlainTextResponse("fail", status_code=400)
        if order["status"] == "paid":
            return PlainTextResponse("success")
        if notice.cents is None or notice.cents != order["amount_cents"]:
            return PlainTextResponse("fail", status_code=400)
        try:
            fulfil_order(db, settings, order["id"], notice.trade_no)
        except HTTPException:
            # e.g. this gateway trade number already paid for another order
            return PlainTextResponse("fail", status_code=409)
        return PlainTextResponse("success")

    @application.post("/api/email/attach")
    def attach_email(payload: AttachRequest, request: Request):
        check_csrf(request)
        if not settings.email_enabled:
            raise HTTPException(503, "邮箱恢复暂不可用。")
        email = normalize_email(payload.email)
        if not email:
            raise HTTPException(422, "请输入邮箱地址。")
        limit("attach:" + request.state.sid, 8, 3600)
        limit("mailbox:" + email, 12, 3600)
        with db.transaction() as con:
            purchase = session_purchase(con, request.state.sid, purchase_id=payload.purchase_id, mode=settings.app_mode)
            if not purchase:
                raise HTTPException(403, "请先在已购买的浏览器中打开合集，再添加邮箱。")
            enqueue_link(con, settings, purpose="verify", purchase_id=purchase["id"], email=email, ttl=1800)
        return {"message": "请查收验证邮件。验证期间，当前浏览器仍可查看已购买的内容。"}

    @application.post("/api/access/request")
    def request_access(payload: EmailRequest, request: Request):
        check_csrf(request)
        if not settings.email_enabled:
            raise HTTPException(503, "邮箱恢复暂不可用，请联系微信客服。")
        email = normalize_email(payload.email)
        if not email:
            raise HTTPException(422, "请输入邮箱地址。")
        limit("restore:" + (request.client.host if request.client else "unknown"), 20, 3600)
        limit("mailbox:" + email, 12, 3600)
        with db.transaction() as con:
            existing = con.execute("SELECT p.id FROM purchases p JOIN orders o ON o.id=p.order_id WHERE p.verified_email=? AND p.revoked_at IS NULL AND o.status='paid' AND o.mode=? LIMIT 1", (email, settings.app_mode)).fetchone()
            if existing:
                enqueue_link(con, settings, purpose="restore", email=email)
        return {"message": "如果这个邮箱关联了已验证的购买记录，我们会发送恢复链接，请检查收件箱和垃圾邮件。"}

    @application.post("/api/access/redeem")
    def redeem(payload: RedeemRequest, request: Request):
        check_csrf(request)
        limit("redeem:" + (request.client.host if request.client else "unknown"), 40, 3600)
        with db.transaction() as con:
            token = con.execute("SELECT * FROM recovery_tokens WHERE token_hash=? AND mode=? AND used_at IS NULL AND expires_at>?", (token_hash(payload.token), settings.app_mode, now())).fetchone()
            if not token:
                raise HTTPException(400, "链接已过期或已使用，请重新获取链接，或联系微信客服。")
            if token["purpose"] in {"verify", "manual"}:
                rows = con.execute("SELECT p.* FROM purchases p JOIN orders o ON o.id=p.order_id WHERE p.id=? AND p.revoked_at IS NULL AND o.status='paid' AND o.mode=?", (token["purchase_id"], settings.app_mode)).fetchall()
                if token["purpose"] == "verify" and rows:
                    con.execute("UPDATE purchases SET verified_email=? WHERE id=?", (token["email"], token["purchase_id"]))
            elif token["purpose"] == "restore":
                rows = con.execute("SELECT p.* FROM purchases p JOIN orders o ON o.id=p.order_id WHERE p.verified_email=? AND p.revoked_at IS NULL AND o.status='paid' AND o.mode=? ORDER BY p.created_at DESC", (token["email"], settings.app_mode)).fetchall()
            else:
                raise HTTPException(400, "访问链接无效。")
            if not rows:
                raise HTTPException(400, "这笔购买暂不可用，请联系微信客服。")
            raw, sid, csrf = new_session(con)
            con.execute("INSERT OR IGNORE INTO session_purchases(session_id,purchase_id) SELECT ?,purchase_id FROM session_purchases WHERE session_id=?", (sid, request.state.sid))
            for purchase in rows:
                con.execute("INSERT OR IGNORE INTO session_purchases(session_id,purchase_id) VALUES(?,?)", (sid, purchase["id"]))
            # Rotate only this browser's session, preserving other devices.
            con.execute("UPDATE orders SET session_id=? WHERE session_id=?", (sid, request.state.sid))
            con.execute("DELETE FROM session_purchases WHERE session_id=?", (request.state.sid,))
            con.execute("UPDATE sessions SET expires_at=0 WHERE id=?", (request.state.sid,))
            con.execute("UPDATE recovery_tokens SET used_at=? WHERE token_hash=?", (now(), token["token_hash"]))
            audit(con, "email_verified" if token["purpose"] == "verify" else "access_restored")
        request.state.new_cookie = raw
        collection = catalog.get(rows[0]["collection_id"], rows[0]["version"])
        return {"message": "已恢复访问，可以在当前浏览器查看已购买的合集。", "collection_slug": collection["slug"]}

    @application.get("/media/{collection_id}/{version}/{item_id}")
    def media(collection_id: str, version: str, item_id: str, request: Request, download: bool = False):
        collection = catalog.get(collection_id, version)
        if not collection:
            raise HTTPException(404, "未找到这张图片。")
        found = next(((index, item) for index, item in enumerate(collection["items"]) if item["id"] == item_id), None)
        if found is None:
            raise HTTPException(404, "未找到这张图片。")
        index, item = found
        purchased = my_purchase(request.state.sid, collection_id=collection_id, version=version)
        if index >= collection["preview_count"] and not purchased:
            raise HTTPException(403, "购买合集后即可查看这张图片。")
        try:
            path = catalog.checked_file(item)
        except (FileNotFoundError, ValueError):
            raise HTTPException(410, "图片暂不可用，请联系微信客服。") from None
        headers = {}
        if path.suffix.lower() == ".svg":
            headers["Content-Security-Policy"] = "sandbox; default-src 'none'; style-src 'unsafe-inline'"
        return FileResponse(path, filename=path.name if download else None, headers=headers)

    @application.get("/files/{collection_id}/{version}/download")
    def download_collection(collection_id: str, version: str, request: Request):
        if not my_purchase(request.state.sid, collection_id=collection_id, version=version):
            raise HTTPException(403, "购买合集后即可下载。")
        limit("zip:" + request.state.sid, 15, 3600)
        collection = catalog.get(collection_id, version)
        if not collection:
            raise HTTPException(404, "未找到这个合集。")
        temp = tempfile.NamedTemporaryFile(prefix="paiddrive-", suffix=".zip", delete=False)
        archive_path = Path(temp.name)
        temp.close()
        try:
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_STORED) as archive:
                for index, item in enumerate(collection["items"]):
                    source = catalog.checked_file(item)
                    archive.write(source, arcname=f"{index+1:02d}-{item['id']}{source.suffix.lower()}")
        except (OSError, ValueError):
            archive_path.unlink(missing_ok=True)
            raise HTTPException(410, "合集暂不可用，请联系微信客服。") from None
        return FileResponse(archive_path, media_type="application/zip", filename=f"{collection['slug']}-{version}.zip", background=BackgroundTask(archive_path.unlink, missing_ok=True))

    @application.get("/support-qr")
    def support_qr(download: bool = False):
        path = settings.support_qr_path or STATIC / "support-placeholder.svg"
        return FileResponse(path, filename=path.name if download else None,
                            headers={"Content-Security-Policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'"})

    @application.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return PlainTextResponse("", status_code=204)

    @application.get("/")
    @application.get("/c/{slug}")
    @application.get("/payment/return")
    @application.get("/recover")
    @application.get("/verify-email")
    def page():
        return FileResponse(STATIC / "index.html", media_type="text/html")

    application.mount("/assets", StaticFiles(directory=STATIC), name="assets")
    return application


app = create_app()
