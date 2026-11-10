import hashlib
import json
import re
import secrets
import time
import uuid

from fastapi import HTTPException


def now():
    return int(time.time())


def token_hash(raw: str):
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def normalize_email(value: str | None):
    if value is None or not value.strip():
        return None
    value = value.strip()
    if len(value) > 254 or not re.fullmatch(r"[^\s@<>\x00-\x1f]+@[^\s@<>\x00-\x1f]+\.[^\s@<>\x00-\x1f]+", value):
        raise HTTPException(422, "请输入有效的邮箱地址。")
    # Case-folding supports expected consumer mailbox behavior in this MVP.
    return value.casefold()


def email_hint(email):
    if not email:
        return None
    local, domain = email.split("@", 1)
    return local[:1] + "•••@" + domain


def audit(con, event: str, reference: str | None = None):
    con.execute("INSERT INTO audit_events(event,reference,created_at) VALUES(?,?,?)", (event, reference, now()))


def enqueue_link(con, settings, *, purpose: str, purchase_id=None, email=None, ttl=900):
    """Issue a single-use token. Only its hash is kept in the token table.

    The private mail queue necessarily contains its delivery URL until sent;
    the body is erased on success or expiry. Nothing is returned to a public API.
    """
    raw = secrets.token_urlsafe(32)
    stamp = now()
    if purpose == "verify":
        con.execute("UPDATE recovery_tokens SET used_at=? WHERE purpose='verify' AND purchase_id=? AND used_at IS NULL", (stamp, purchase_id))
    con.execute("INSERT INTO recovery_tokens(token_hash,mode,purpose,purchase_id,email,expires_at) VALUES(?,?,?,?,?,?)", (token_hash(raw), settings.app_mode, purpose, purchase_id, email, stamp + ttl))
    route = "/verify-email" if purpose == "verify" else "/recover"
    url = f"{settings.app_url}{route}#token={raw}"
    if purpose != "manual":
        subject = "PaidDrive｜验证恢复邮箱" if purpose == "verify" else "PaidDrive｜恢复已购买的合集"
        body = (("请打开下方链接，验证邮箱并保存这笔购买的恢复方式。" if purpose == "verify" else "请打开下方链接，在当前浏览器恢复已关联此邮箱的购买记录。")
                + f"\n\n{url}\n\n链接在 {ttl // 60} 分钟后过期，且只能使用一次。如果不是你本人操作，请忽略此邮件。\n"
                + "打开后需要点击确认，才会验证邮箱或恢复访问。\n\n你可以继续在原购买浏览器中查看和下载图片。\n")
        con.execute("INSERT INTO mail_jobs(id,mode,recipient,subject,body,created_at,expires_at,next_attempt_at) VALUES(?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, settings.app_mode, email, subject, body, stamp, stamp + ttl, stamp))
    return url


def fulfil_order(db, settings, order_id: str, provider_trade_no: str):
    with db.transaction() as con:
        order = con.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
        if not order:
            raise HTTPException(404, "未找到这笔订单。")
        purchase = con.execute("SELECT * FROM purchases WHERE order_id=?", (order_id,)).fetchone()
        if purchase:
            if order["provider_trade_no"] != provider_trade_no:
                raise HTTPException(409, "订单的支付记录不一致，请联系微信客服。")
            return dict(purchase)
        if order["status"] != "pending":
            raise HTTPException(409, "这笔订单暂时无法解锁，请联系微信客服。")
        duplicate = con.execute("SELECT id FROM orders WHERE provider_trade_no=?", (provider_trade_no,)).fetchone()
        if duplicate:
            raise HTTPException(409, "这笔支付已关联其他订单，请联系微信客服。")
        stamp = now()
        pid = uuid.uuid4().hex
        con.execute("UPDATE orders SET status='paid',paid_at=?,provider_trade_no=? WHERE id=?", (stamp, provider_trade_no, order_id))
        con.execute("INSERT INTO purchases(id,order_id,collection_id,version,created_at) VALUES(?,?,?,?,?)", (pid, order_id, order["collection_id"], order["version"], stamp))
        # Keep the original session record even if expired; its browser needs
        # recovery after expiry, but the purchase itself survives permanently.
        con.execute("INSERT INTO session_purchases(session_id,purchase_id) VALUES(?,?)", (order["session_id"], pid))
        if order["email"] and settings.email_enabled:
            enqueue_link(con, settings, purpose="verify", purchase_id=pid, email=order["email"], ttl=1800)
        audit(con, "payment_verified", order["reference"])
        return dict(con.execute("SELECT * FROM purchases WHERE id=?", (pid,)).fetchone())


def session_purchase(con, session_id, collection_id=None, version=None, purchase_id=None, mode=None):
    query = "SELECT p.*,o.reference FROM purchases p JOIN session_purchases sp ON sp.purchase_id=p.id JOIN orders o ON o.id=p.order_id WHERE sp.session_id=? AND p.revoked_at IS NULL AND o.status='paid'"
    args = [session_id]
    if mode is not None:
        query += " AND o.mode=?"
        args.append(mode)
    for field, value in (("collection_id", collection_id), ("version", version), ("id", purchase_id)):
        if value is not None:
            query += f" AND p.{field}=?"
            args.append(value)
    query += " ORDER BY p.created_at DESC,p.id DESC LIMIT 1"
    return con.execute(query, args).fetchone()


def order_payload(order, catalog):
    collection = catalog.get(order["collection_id"], order["version"])
    return {"id": order["id"], "reference": order["reference"], "status": order["status"],
            "mode": order["mode"], "collection_slug": collection["slug"] if collection else "",
            "paid_at": order["paid_at"],
            "payment_url": f"/checkout/{'demo' if order['mode'] == 'demo' else 'zpay'}/{order['id']}" if order["status"] == "pending" else None}
