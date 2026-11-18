"""Buyer-facing acceptance and access-control tests.

Run with ``python -m unittest discover -s tests -v`` from the project root.
Each test creates its own catalog and database; no real payment/email is sent.
"""

from contextlib import ExitStack
from dataclasses import replace
import base64
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, parse_qsl, urlsplit
import zipfile

from fastapi.testclient import TestClient
import httpx

from app.catalog import Catalog
from app.config import Settings
from app.db import Database


class IsolatedProject(unittest.TestCase):
    """Fixtures model two independently purchasable five-image collections."""

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.content = self.root / "content"
        (self.content / "images").mkdir(parents=True)
        self.collections = []
        for collection_id, price in (("alpha", 1200), ("beta", 2800)):
            items = []
            for index in range(1, 6):
                name = f"{collection_id}-{index}.svg"
                (self.content / "images" / name).write_text(
                    '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">'
                    f'<text x="1" y="10">{collection_id}-{index}</text></svg>',
                    encoding="utf-8",
                )
                items.append({"id": f"image-{index}", "file": f"images/{name}",
                              "title": f"{collection_id} {index}", "width": 20, "height": 20})
            self.collections.append({
                "id": collection_id, "slug": f"{collection_id}-collection", "version": "v1",
                "title": f"Collection {collection_id}", "price_cents": price,
                "currency": "CNY", "preview_count": 3, "items": items,
            })
        self.write_catalog()
        self.settings = Settings(
            app_url="http://testserver",
            database_path=self.root / "test.sqlite3",
            content_root=self.content,
            mail_file_dir=self.root / "outbox",
            run_background_jobs=False,
        )

    def write_catalog(self):
        (self.content / "collections.json").write_text(
            json.dumps({"collections": self.collections}), encoding="utf-8"
        )

    def rows(self, sql, parameters=()):
        with sqlite3.connect(self.settings.database_path) as con:
            con.row_factory = sqlite3.Row
            return [dict(row) for row in con.execute(sql, parameters)]

    def execute(self, sql, parameters=()):
        with sqlite3.connect(self.settings.database_path) as con:
            con.execute(sql, parameters)

    def start_app(self, settings=None):
        # main.py also exports a convenient module-level ASGI app. Import it
        # against disposable settings so tests never create/open a real site DB.
        with patch.dict(os.environ, {
            "APP_MODE": "demo", "APP_URL": "http://testserver",
            "CONTENT_ROOT": str(self.content),
            "DATABASE_PATH": str(self.root / "unused-module-app.sqlite3"),
            "MAIL_MODE": "disabled",
        }, clear=True):
            from app.main import create_app

        if settings is not None:
            self.settings = settings
        self.app = create_app(self.settings)
        self.client = self.stack.enter_context(
            TestClient(self.app, base_url=self.settings.app_url)
        )
        return self.client

    def other_client(self):
        return self.stack.enter_context(TestClient(self.app, base_url=self.settings.app_url))

    def bootstrap(self, client=None, collection_id="alpha"):
        client = client or self.client
        result = client.get("/api/bootstrap", params={"slug": f"{collection_id}-collection"})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def post(self, path, body=None, client=None):
        client = client or self.client
        token = self.bootstrap(client)["csrf_token"]
        return client.post(path, json=body or {}, headers={
            "X-CSRF-Token": token, "Origin": self.settings.app_url,
        })

    def create_order(self, collection_id="alpha", email=None, client=None):
        payload = {"collection_id": collection_id}
        if email is not None:
            payload["email"] = email
        response = self.post("/api/orders", payload, client)
        self.assertIn(response.status_code, (200, 201), response.text)
        return response.json()

    def buy_demo(self, collection_id="alpha", email=None, client=None):
        order = self.create_order(collection_id, email, client)
        self.assertEqual(order["status"], "paid")
        return order

    def latest_mail_token(self, email):
        jobs = self.rows("SELECT body FROM mail_jobs WHERE recipient=? ORDER BY rowid DESC LIMIT 1", (email,))
        self.assertEqual(len(jobs), 1, "Expected one queued email for this address")
        urls = re.findall(r"https?://[^\s<>\"]+", jobs[0]["body"])
        for url in urls:
            parsed = urlsplit(url)
            # Recovery credentials belong in fragments so HTTP access logs do
            # not record them during the initial navigation.
            self.assertNotIn("token", parse_qs(parsed.query))
            tokens = parse_qs(parsed.fragment).get("token")
            if tokens:
                return tokens[0]
        self.fail("The email did not contain a fragment-based recovery link")


class CatalogIntegrityTests(IsolatedProject):
    def setUp(self):
        super().setUp()
        self.db = Database(self.settings.database_path)
        self.catalog = Catalog(self.content, self.db)

    def test_reusing_version_after_original_bytes_change_is_rejected(self):
        image = self.content / "images" / "alpha-5.svg"
        image.write_text(image.read_text() + "\n<!-- changed -->", encoding="utf-8")
        with self.assertRaises(ValueError):
            Catalog(self.content, self.db)

    def test_file_mutation_is_rejected_before_serving_without_a_restart(self):
        item = self.catalog.get("alpha")["items"][4]
        image = self.content / item["file"]
        image.write_text(image.read_text() + "\n<!-- changed -->", encoding="utf-8")
        with self.assertRaises(FileNotFoundError):
            self.catalog.checked_file(item)

    def test_reordering_or_replacing_free_boundary_requires_a_new_version(self):
        self.collections[0]["preview_count"] = 4
        self.write_catalog()
        with self.assertRaises(ValueError):
            Catalog(self.content, self.db)

    def test_price_can_change_without_changing_sold_files(self):
        self.collections[0]["price_cents"] = 1500
        self.write_catalog()
        updated = Catalog(self.content, self.db)
        self.assertEqual(updated.get("alpha")["price_cents"], 1500)
        self.assertEqual(updated.get("alpha")["items"], self.catalog.get("alpha")["items"])

    def test_files_cannot_escape_content_directory(self):
        (self.root / "secret.svg").write_text("private", encoding="utf-8")
        self.collections[0]["items"][4]["file"] = "../secret.svg"
        self.write_catalog()
        with self.assertRaises(ValueError):
            Catalog(self.content, Database(self.root / "other.sqlite3"))


class GuestPurchaseTests(IsolatedProject):
    def setUp(self):
        super().setUp()
        self.start_app()

    def test_demo_purchase_unlocks_in_one_call_without_choosing_a_payment_method(self):
        response = self.post("/api/orders", {"collection_id": "alpha"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["status"], "paid")
        self.assertIsNone(response.json()["pay_url"])
        self.assertTrue(self.bootstrap()["access"]["unlocked"])
        self.assertEqual(self.client.get("/media/alpha/v1/image-5").status_code, 200)

    def test_bootstrap_without_slug_selects_the_first_configured_collection(self):
        response = self.client.get("/api/bootstrap")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["collection"]["id"], "alpha")
        self.assertEqual(body["collection"]["slug"], "alpha-collection")
        self.assertFalse(body["access"]["unlocked"])

    def test_three_previews_are_public_but_paid_originals_and_zip_are_private(self):
        bootstrap = self.bootstrap()
        self.assertFalse(bootstrap["access"]["unlocked"])
        self.assertEqual(len(bootstrap["collection"]["items"]), 5)
        for index in range(1, 6):
            with self.subTest(image=index):
                response = self.client.get(f"/media/alpha/v1/image-{index}")
                if index <= 3:
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(f"alpha-{index}", response.text)
                else:
                    self.assertIn(response.status_code, (401, 403, 404))
                    self.assertNotIn(f"alpha-{index}</text>", response.text)
        self.assertIn(self.client.get("/files/alpha/v1/download").status_code, (401, 403, 404))
        for direct_path in ("/content/images/alpha-4.svg", "/images/alpha-4.svg", "/static/alpha-4.svg"):
            with self.subTest(path=direct_path):
                self.assertNotIn("alpha-4</text>", self.client.get(direct_path).text)

    def test_anonymous_bootstrap_does_not_deliver_locked_image_material(self):
        body = self.bootstrap()
        collection = body["collection"]
        self.assertIsNone(collection["download_url"])
        self.assertEqual(sum(bool(item["url"]) for item in collection["items"]), 3)

        def string_values(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for nested in value.values():
                    yield from string_values(nested)
            elif isinstance(value, list):
                for nested in value:
                    yield from string_values(nested)

        delivered_text = "\n".join(string_values(body))
        self.assertNotIn(str(self.content), delivered_text)
        self.assertNotIn("data:image/", delivered_text.lower())
        for index, item in enumerate(collection["items"], 1):
            with self.subTest(image=index):
                if index <= 3:
                    self.assertTrue(item["is_preview"])
                    self.assertTrue(item["unlocked"])
                    self.assertEqual(item["url"], f"/media/alpha/v1/image-{index}")
                    continue
                self.assertFalse(item["is_preview"])
                self.assertFalse(item["unlocked"])
                self.assertIsNone(item["url"])
                original = self.content / "images" / f"alpha-{index}.svg"
                for hidden_value in (
                    f"/media/alpha/v1/image-{index}",
                    original.name,
                    f"images/{original.name}",
                    original.read_text(encoding="utf-8"),
                    base64.b64encode(original.read_bytes()).decode("ascii"),
                ):
                    self.assertNotIn(hidden_value, delivered_text)

    def test_download_and_range_requests_do_not_bypass_payment_or_share_another_buyers_access(self):
        stranger = self.other_client()
        paths = (
            "/media/alpha/v1/image-4",
            "/media/alpha/v1/image-4?download=1",
            "/media/alpha/v1/image-5?download=1",
            "/files/alpha/v1/download",
            "/files/alpha/v1/download?download=1",
        )
        for phase in ("before purchase", "after another browser purchases"):
            if phase == "after another browser purchases":
                self.buy_demo()
                paid_response = self.client.get("/media/alpha/v1/image-4?download=1")
                self.assertEqual(paid_response.status_code, 200)
                self.assertIn("no-store", paid_response.headers.get("cache-control", ""))
            self.assertFalse(self.bootstrap(stranger)["access"]["unlocked"])
            for path in paths:
                for headers in ({}, {"Range": "bytes=0-63"}):
                    with self.subTest(phase=phase, path=path, headers=headers):
                        response = stranger.get(path, headers=headers)
                        self.assertIn(response.status_code, (401, 403, 404))
                        self.assertNotIn("content-range", response.headers)
                        self.assertNotIn("alpha-4</text>", response.text)
                        self.assertNotIn("alpha-5</text>", response.text)
                        self.assertFalse(response.content.startswith(b"PK\x03\x04"))

    def test_private_content_and_manifest_are_not_exposed_by_static_routes(self):
        original = self.content / "images" / "alpha-4.svg"
        # Encoded traversal is deliberately aimed at the actual temporary file,
        # so a failing path boundary cannot be hidden by a nonexistent target.
        traversal = "/assets/" + "%2e%2e/" * 12 + str(original).lstrip("/")
        paths = (
            "/content/images/alpha-4.svg", "/images/alpha-4.svg",
            "/static/images/alpha-4.svg", "/assets/images/alpha-4.svg",
            "/assets/content/images/alpha-4.svg", "/content/collections.json",
            "/assets/collections.json", "/assets/content/collections.json", traversal,
        )
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertIn(response.status_code, (400, 403, 404))
                self.assertNotIn("alpha-4</text>", response.text)
                self.assertNotIn('"collections"', response.text)

    def test_private_content_cannot_overlap_public_assets_even_through_symlinks(self):
        from app.main import create_app

        nested_public = self.content / "public"
        nested_public.mkdir()
        public_alias = self.root / "public-alias"
        public_alias.symlink_to(self.content, target_is_directory=True)
        private_alias = self.root / "private-alias"
        private_alias.symlink_to(self.content, target_is_directory=True)
        cases = (
            ("same directory", self.content, self.content),
            ("public inside private", self.content, nested_public),
            ("private inside public", self.content, self.root),
            ("public symlink", self.content, public_alias),
            ("private symlink", private_alias, self.content),
        )
        for index, (label, private_root, public_root) in enumerate(cases):
            with self.subTest(layout=label):
                database_path = self.root / f"rejected-layout-{index}.sqlite3"
                settings = replace(self.settings, content_root=private_root, database_path=database_path)
                with patch("app.main.STATIC", public_root):
                    with self.assertRaisesRegex(ValueError, "CONTENT_ROOT"):
                        create_app(settings)
                self.assertFalse(database_path.exists(), "Unsafe layouts must fail before database initialization")

    def test_payment_grants_only_the_purchased_collection_in_the_buying_browser(self):
        self.buy_demo()
        self.assertTrue(self.bootstrap()["access"]["unlocked"])
        self.assertEqual(self.client.get("/media/alpha/v1/image-5").status_code, 200)
        self.assertFalse(self.bootstrap(collection_id="beta")["access"]["unlocked"])
        self.assertIn(self.client.get("/media/beta/v1/image-5").status_code, (401, 403, 404))
        stranger = self.other_client()
        self.assertFalse(self.bootstrap(stranger)["access"]["unlocked"])
        self.assertIn(stranger.get("/media/alpha/v1/image-5").status_code, (401, 403, 404))

    def test_zip_contains_exactly_the_purchased_collection_files(self):
        self.buy_demo()
        response = self.client.get("/files/alpha/v1/download")
        self.assertEqual(response.status_code, 200, response.text[:200] if response.status_code != 200 else "")
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            self.assertEqual(len(archive.namelist()), 5)
            bodies = [archive.read(name).decode("utf-8") for name in archive.namelist()]
            for index in range(1, 6):
                self.assertTrue(any(f"alpha-{index}</text>" in body for body in bodies))
            self.assertFalse(any("beta-" in body for body in bodies))
            self.assertTrue(all(not name.startswith("/") and ".." not in Path(name).parts for name in archive.namelist()))

    def test_price_and_order_snapshot_are_server_authoritative(self):
        tampered = self.post("/api/orders", {"collection_id": "alpha", "amount_cents": 1})
        self.assertEqual(tampered.status_code, 422)
        self.assertEqual(self.rows("SELECT id FROM orders"), [])
        order = self.create_order()
        stored = self.rows("SELECT * FROM orders WHERE id=?", (order["id"],))[0]
        self.assertEqual(stored["amount_cents"], 1200)
        self.assertEqual(stored["version"], "v1")
        self.collections[0]["price_cents"] = 1500
        self.write_catalog()
        Catalog(self.content, Database(self.settings.database_path))
        stored_after = self.rows("SELECT * FROM orders WHERE id=?", (order["id"],))[0]
        self.assertEqual(stored_after["amount_cents"], 1200)

    def test_state_changing_requests_require_csrf_and_reject_another_origin(self):
        boot = self.bootstrap()
        payload = {"collection_id": "alpha"}
        self.assertEqual(self.client.post("/api/orders", json=payload).status_code, 403)
        response = self.client.post("/api/orders", json=payload, headers={
            "X-CSRF-Token": boot["csrf_token"], "Origin": "https://attacker.example",
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.rows("SELECT id FROM orders"), [])

    def test_changed_file_is_not_returned_to_a_paid_buyer(self):
        self.buy_demo()
        altered = self.content / "images" / "alpha-5.svg"
        altered.write_text("private replacement must not be served", encoding="utf-8")
        response = self.client.get("/media/alpha/v1/image-5")
        self.assertNotEqual(response.status_code, 200)
        self.assertNotIn("private replacement must not be served", response.text)
        self.assertNotEqual(self.client.get("/files/alpha/v1/download").status_code, 200)


class EmailRecoveryTests(IsolatedProject):
    def setUp(self):
        super().setUp()
        self.start_app()

    def attach_and_verify(self, email="buyer@example.com"):
        self.buy_demo()
        purchase = self.bootstrap()["access"]["purchase_id"]
        response = self.post("/api/email/attach", {"purchase_id": purchase, "email": email})
        self.assertEqual(response.status_code, 200, response.text)
        token = self.latest_mail_token(email)
        self.assertNotIn(token, response.text)
        verified = self.post("/api/access/redeem", {"token": token})
        self.assertEqual(verified.status_code, 200, verified.text)
        self.assertTrue(self.bootstrap()["access"]["email_verified"])
        return purchase

    def test_email_is_optional_and_attaching_it_requires_a_purchase_session(self):
        self.buy_demo()
        boot = self.bootstrap()
        self.assertTrue(boot["access"]["unlocked"])
        self.assertFalse(boot["access"]["email_verified"])
        self.assertEqual(self.rows("SELECT id FROM mail_jobs"), [])
        stranger = self.other_client()
        response = self.post("/api/email/attach", {
            "purchase_id": boot["access"]["purchase_id"], "email": "attacker@example.com",
        }, stranger)
        self.assertIn(response.status_code, (403, 404))
        self.assertEqual(self.rows("SELECT id FROM mail_jobs"), [])

    def test_checkout_email_is_unverified_until_the_mailed_link_is_used(self):
        self.buy_demo(email="buyer@example.com")
        self.assertFalse(self.bootstrap()["access"]["email_verified"])
        stranger = self.other_client()
        result = self.post("/api/access/request", {"email": "buyer@example.com"}, stranger)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.rows("SELECT token_hash FROM recovery_tokens WHERE purpose='restore'"), [])
        self.assertFalse(self.bootstrap(stranger)["access"]["unlocked"])
        token = self.latest_mail_token("buyer@example.com")
        self.assertNotIn(token, result.text)
        self.assertEqual(self.post("/api/access/redeem", {"token": token}).status_code, 200)
        self.assertTrue(self.bootstrap()["access"]["email_verified"])

    def test_verified_email_restores_only_owned_purchases_and_link_is_single_use(self):
        self.attach_and_verify()
        stranger = self.other_client()
        request = self.post("/api/access/request", {"email": "buyer@example.com"}, stranger)
        self.assertEqual(request.status_code, 200, request.text)
        token = self.latest_mail_token("buyer@example.com")
        self.assertNotIn(token, request.text)
        self.assertNotIn(token, json.dumps(self.bootstrap(stranger)))
        self.assertFalse(self.bootstrap(stranger)["access"]["unlocked"])
        redeemed = self.post("/api/access/redeem", {"token": token}, stranger)
        self.assertEqual(redeemed.status_code, 200, redeemed.text)
        self.assertTrue(self.bootstrap(stranger)["access"]["unlocked"])
        self.assertFalse(self.bootstrap(stranger, "beta")["access"]["unlocked"])
        self.assertEqual(stranger.get("/media/alpha/v1/image-5").status_code, 200)
        fresh_browser = self.other_client()
        self.assertEqual(self.post("/api/access/redeem", {"token": token}, fresh_browser).status_code, 400)
        self.assertFalse(self.bootstrap(fresh_browser)["access"]["unlocked"])

    def test_expired_and_invented_links_cannot_restore_access(self):
        self.attach_and_verify()
        stranger = self.other_client()
        self.assertEqual(self.post("/api/access/request", {"email": "buyer@example.com"}, stranger).status_code, 200)
        token = self.latest_mail_token("buyer@example.com")
        self.execute("UPDATE recovery_tokens SET expires_at=0 WHERE purpose='restore'")
        self.assertEqual(self.post("/api/access/redeem", {"token": token}, stranger).status_code, 400)
        self.assertEqual(self.post("/api/access/redeem", {"token": "invented-token-value"}, stranger).status_code, 400)
        self.assertFalse(self.bootstrap(stranger)["access"]["unlocked"])

    def test_recovery_requests_do_not_disclose_whether_an_email_has_purchases(self):
        self.attach_and_verify()
        stranger = self.other_client()
        known = self.post("/api/access/request", {"email": "buyer@example.com"}, stranger)
        unknown = self.post("/api/access/request", {"email": "unknown@example.com"}, stranger)
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.json(), unknown.json())


class LivePaymentTests(IsolatedProject):
    def setUp(self):
        super().setUp()
        self.start_app(replace(self.settings, app_mode="live", app_url="https://testserver",
                               mail_mode="disabled", zpay_base_url="https://gateway.example",
                               zpay_pid="merchant-123", zpay_key="local-test-secret"))
        # Stub ZPay's network, not our adapter: requests are recorded, replies scripted.
        self.gateway_calls = []
        self.gateway_reply = lambda request: httpx.Response(200, json={"code": 1, "status": 0})

        def gateway(request):
            self.gateway_calls.append(request)
            return self.gateway_reply(request)
        self.app.state.gateway.transport = httpx.MockTransport(gateway)

    def gateway_paid(self, trade="T7"):
        def reply(request):
            ref = request.url.params["out_trade_no"]
            return httpx.Response(200, json={"code": 1, "msg": "查询订单号成功！", "trade_no": trade, "out_trade_no": ref,
                                             "type": "wxpay", "pid": self.settings.zpay_pid, "money": "12.00", "status": 1})
        self.gateway_reply = reply

    def notification(self, order, trade="provider-payment-1", **changes):
        from app.payments import sign_params

        cents = self.rows("SELECT amount_cents FROM orders WHERE id=?", (order["id"],))[0]["amount_cents"]
        values = {"pid": self.settings.zpay_pid, "out_trade_no": order["reference"], "trade_no": trade,
                  "money": f"{cents // 100}.{cents % 100:02d}", "type": "wxpay",
                  "trade_status": "TRADE_SUCCESS", "sign_type": "MD5", **changes}
        values["sign"] = sign_params(values, self.settings.zpay_key)
        return values

    def notify(self, notification):
        return self.client.get("/api/payments/zpay/notify", params=notification)

    def test_live_order_returns_signed_cashier_url_with_configured_pay_type(self):
        order = self.create_order()
        self.assertEqual(order["status"], "pending")
        url = urlsplit(order["pay_url"])
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "gateway.example", "/submit.php"))
        query = dict(parse_qsl(url.query))
        self.assertEqual((query["type"], query["out_trade_no"], query["money"]), ("wxpay", order["reference"], "12.00"))
        self.assertEqual(self.client.get(f"/api/orders/{order['id']}").json()["pay_url"], order["pay_url"])
        self.assertEqual(self.bootstrap()["latest_order"]["pay_url"], order["pay_url"])
        self.assertEqual(self.client.get(f"/checkout/zpay/{order['id']}").status_code, 404)

    def test_refresh_settles_the_order_once_the_gateway_reports_it_paid(self):
        order = self.create_order()
        self.gateway_paid()
        result = self.post(f"/api/orders/{order['id']}/refresh")
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "paid")
        query = self.gateway_calls[0].url
        self.assertEqual((query.path, query.params["act"], query.params["out_trade_no"]), ("/api.php", "order", order["reference"]))
        self.assertTrue(self.bootstrap()["access"]["unlocked"])

    def test_refresh_stays_pending_when_gateway_says_unpaid_errors_or_is_unreachable(self):
        order = self.create_order()

        def unreachable(request):
            raise httpx.ConnectError("down")
        replies = {"unpaid": lambda r: httpx.Response(200, json={"code": 1, "status": 0}),
                   "error code": lambda r: httpx.Response(200, json={"code": -1, "msg": "订单不存在"}),
                   "http 500": lambda r: httpx.Response(500, text="oops"),
                   "unreachable": unreachable}
        for label, reply in replies.items():
            with self.subTest(label):
                self.gateway_reply = reply
                result = self.post(f"/api/orders/{order['id']}/refresh")
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["status"], "pending")
                self.assertFalse(self.bootstrap()["access"]["unlocked"])

    def test_buying_again_reuses_the_open_order_after_checking_it_is_unpaid(self):
        first = self.create_order()
        self.assertEqual(self.gateway_calls, [])
        old = "UPDATE orders SET created_at=created_at-86400"  # age no longer matters
        with sqlite3.connect(self.settings.database_path) as con:
            con.execute(old)
        again = self.create_order()
        self.assertEqual((again["id"], again["status"], again["pay_url"]), (first["id"], "pending", first["pay_url"]))
        self.assertEqual(len(self.gateway_calls), 1)

    def test_buying_again_settles_an_order_paid_before_its_notify_arrived(self):
        first = self.create_order()
        self.gateway_paid()
        again = self.create_order()
        self.assertEqual((again["id"], again["status"], again["pay_url"]), (first["id"], "paid", None))
        self.assertTrue(self.bootstrap()["access"]["unlocked"])
        self.assertEqual(len(self.rows("SELECT id FROM orders")), 1)

    def test_forged_notification_cannot_grant_access_or_trigger_provider_query(self):
        order = self.create_order()
        notification = self.notification(order)
        notification["sign"] = "0" * 32
        self.assertEqual(self.notify(notification).text, "fail")
        self.assertEqual(self.gateway_calls, [])
        self.assertEqual(self.rows("SELECT id FROM purchases"), [])

    def test_oversized_callback_field_count_is_rejected_without_an_exception(self):
        response = self.notify({f"unexpected_{index}": "x" for index in range(33)})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.text, "fail")
        self.assertEqual(self.gateway_calls, [])
        self.assertEqual(self.rows("SELECT id FROM purchases"), [])

    def test_signed_notification_for_wrong_amount_or_unknown_order_is_rejected(self):
        order = self.create_order()
        for changes in ({"money": "0.01"}, {"out_trade_no": "unknown-order"}, {"money": "abc"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.notify(self.notification(order, **changes)).text, "fail")
                self.assertEqual(self.rows("SELECT id FROM purchases"), [])
                self.assertFalse(self.bootstrap()["access"]["unlocked"])

    def test_signed_unpaid_notification_is_acknowledged_without_unlocking(self):
        order = self.create_order()
        response = self.notify(self.notification(order, trade_status="WAIT_BUYER_PAY"))
        self.assertEqual(response.text, "success")
        self.assertEqual(self.rows("SELECT id FROM purchases"), [])
        self.assertFalse(self.bootstrap()["access"]["unlocked"])

    def test_signed_paid_notification_alone_settles_idempotently_and_collection_scoped(self):
        order = self.create_order()
        notification = self.notification(order)
        first = self.notify(notification)
        self.assertEqual(first.text, "success", first.text)
        repeated = self.notify(notification)
        self.assertEqual(repeated.text, "success", repeated.text)
        self.assertEqual(self.gateway_calls, [])
        self.assertEqual(len(self.rows("SELECT id FROM purchases")), 1)
        self.assertTrue(self.bootstrap()["access"]["unlocked"])
        self.assertFalse(self.bootstrap(collection_id="beta")["access"]["unlocked"])

    def test_one_provider_transaction_cannot_pay_for_two_orders(self):
        first = self.create_order()
        self.assertEqual(self.notify(self.notification(first, trade="T1")).text, "success")
        second = self.create_order("beta")
        self.assertEqual(self.notify(self.notification(second, trade="T1")).text, "fail")
        self.assertEqual(len(self.rows("SELECT id FROM purchases")), 1)
        self.assertFalse(self.bootstrap(collection_id="beta")["access"]["unlocked"])

    def test_order_selectors_route_only_the_owning_browser_without_unlocking_access(self):
        order = self.create_order("beta")
        stranger = self.other_client()
        for selector in ({"order_id": order["id"]}, {"order_reference": order["reference"]}):
            with self.subTest(selector=selector):
                own = self.client.get("/api/bootstrap", params=selector)
                self.assertEqual(own.status_code, 200, own.text)
                body = own.json()
                self.assertEqual(body["collection"]["id"], "beta")
                self.assertEqual(body["latest_order"]["id"], order["id"])
                self.assertEqual(body["latest_order"]["status"], "pending")
                self.assertFalse(body["access"]["unlocked"])
                other = stranger.get("/api/bootstrap", params=selector)
                self.assertEqual(other.status_code, 404, other.text)
                self.assertNotIn(order["reference"], other.text)
        self.assertIn(self.client.get("/media/beta/v1/image-5").status_code, (401, 403, 404))
        self.assertEqual(self.rows("SELECT id FROM purchases"), [])

    def test_pending_order_cannot_be_read_refreshed_or_paid_by_another_session(self):
        order = self.create_order()
        stranger = self.other_client()
        self.assertIn(stranger.get(f"/api/orders/{order['id']}").status_code, (403, 404))
        self.assertIn(self.post(f"/api/orders/{order['id']}/refresh", client=stranger).status_code, (403, 404))
        self.assertEqual(self.rows("SELECT status FROM orders WHERE id=?", (order["id"],))[0]["status"], "pending")
        self.assertEqual(self.rows("SELECT id FROM purchases"), [])

    def test_payment_return_url_never_grants_access(self):
        order = self.create_order()
        self.client.get("/payment/return", params={"out_trade_no": order["reference"], "trade_status": "TRADE_SUCCESS", "status": "paid"})
        self.assertFalse(self.bootstrap()["access"]["unlocked"])
        self.assertEqual(self.rows("SELECT id FROM purchases"), [])

class ModeIsolationTests(IsolatedProject):
    def test_demo_sessions_orders_and_email_tokens_cannot_unlock_live_content(self):
        self.start_app()
        demo_order = self.buy_demo(email="buyer@example.com")
        demo_token = self.latest_mail_token("buyer@example.com")
        demo_cookie = self.client.cookies.get("paiddrive_demo")
        self.assertTrue(self.bootstrap()["access"]["unlocked"])
        # Reuse the same database deliberately: changing deployment modes must
        # not turn simulated purchases into real purchases.
        self.start_app(replace(self.settings, app_mode="live", app_url="https://testserver",
                               mail_mode="disabled", zpay_base_url="https://gateway.example",
                               zpay_pid="merchant-123", zpay_key="local-test-secret"))
        self.client.cookies.set("paiddrive_live", demo_cookie)
        self.assertFalse(self.bootstrap()["access"]["unlocked"])
        self.assertIn(self.client.get("/media/alpha/v1/image-5").status_code, (401, 403, 404))
        self.assertEqual(self.client.get(f"/api/orders/{demo_order['id']}").status_code, 404)
        self.assertEqual(self.post("/api/access/redeem", {"token": demo_token}).status_code, 400)
        self.assertFalse(self.bootstrap()["access"]["unlocked"])


class ZPaySigningTests(unittest.TestCase):
    """Signatures are checked against MD5 literals computed outside the code, per the ZPay doc."""

    def setUp(self):
        from app.payments import ZPay
        self.gateway = ZPay(Settings(app_mode="live", app_url="https://shop.example",
                                     zpay_base_url="https://gw.example", zpay_pid="1001",
                                     zpay_key="TESTKEY", zpay_pay_type="wxpay"))

    def test_pay_url_is_a_signed_submit_get_with_raw_values_signed_and_url_encoded(self):
        url = urlsplit(self.gateway.pay_url("R20261118001", 1200, "Alpha 合集 & more"))
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "gw.example", "/submit.php"))
        self.assertEqual(dict(parse_qsl(url.query)), {
            "pid": "1001", "type": "wxpay", "out_trade_no": "R20261118001",
            "notify_url": "https://shop.example/api/payments/zpay/notify",
            "return_url": "https://shop.example/payment/return",
            "name": "Alpha 合集 & more", "money": "12.00",
            "sign": "e02938d20ad4ea4a669b3101ddc3d60b", "sign_type": "MD5",
        })

    def notification(self, **changes):
        values = {"pid": "1001", "name": "Alpha", "money": "12.00", "out_trade_no": "R20261118001",
                  "trade_no": "T9", "param": "", "trade_status": "TRADE_SUCCESS", "type": "wxpay",
                  "sign": "5786c97cb3198c792d2306fa686095a1", "sign_type": "MD5"}
        values.update(changes)
        return values

    def test_genuine_notification_is_valid_and_exposes_settlement_fields(self):
        result = self.gateway.parse_notify(self.notification())
        self.assertTrue(result.valid)
        self.assertTrue(result.success)
        self.assertEqual((result.reference, result.cents, result.trade_no), ("R20261118001", 1200, "T9"))

    def test_tampered_or_unsigned_notification_is_invalid(self):
        for changes in ({"money": "0.01"}, {"out_trade_no": "OTHER"}, {"sign": ""}, {"sign": "0" * 32}):
            with self.subTest(changes=changes):
                self.assertFalse(self.gateway.parse_notify(self.notification(**changes)).valid)

    def test_signed_non_success_status_is_valid_but_not_success(self):
        values = self.notification(trade_status="WAIT_BUYER_PAY", sign="")
        from app.payments import sign_params
        values["sign"] = sign_params(values, "TESTKEY")
        result = self.gateway.parse_notify(values)
        self.assertTrue(result.valid)
        self.assertFalse(result.success)

class ProductionSettingsTests(unittest.TestCase):
    def test_live_settings_require_https_payment_credentials_and_no_file_mail(self):
        valid = Settings(app_mode="live", app_url="https://example.com", mail_mode="disabled",
                         zpay_base_url="https://gateway.example", zpay_pid="merchant", zpay_key="secret")
        valid.validate()
        for overrides in ({"app_url": "http://example.com"}, {"zpay_key": ""},
                          {"zpay_base_url": "http://gateway.example"}, {"mail_mode": "file"},
                          {"zpay_pay_type": "bitcoin"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                replace(valid, **overrides).validate()


class AnalyticsTests(IsolatedProject):
    """51.la loads in the background; CSP permits its inline loader by hash, never 'unsafe-inline'."""

    # 51.la's own async loader, as published by 51.la; it queues the site id in LA.ids.
    OFFICIAL_SNIPPET = """<script>
!function(p){"use strict";!function(t){var s=window,e=document,i=p,c="".concat("https:"===e.location.protocol?"https://":"http://","sdk.51.la/js-sdk-pro.min.js"),n=e.createElement("script"),r=e.getElementsByTagName("script")[0];n.type="text/javascript",n.setAttribute("charset","UTF-8"),n.async=!0,n.src=c,n.id="LA_COLLECT",i.d=n;var o=function(){s.LA.ids.push(i)};s.LA?s.LA.ids&&o():(s.LA=p,s.LA.ids=[],o()),r.parentNode.insertBefore(n,r)}()}({id:"JqVcFfP1irXgU1KM",ck:"JqVcFfP1irXgU1KM"});
</script>"""

    def setUp(self):
        super().setUp()
        self.start_app()
        self.response = self.client.get("/")
        csp = self.response.headers["Content-Security-Policy"]
        self.directives = {d.split()[0]: d.split()[1:] for d in csp.split("; ")}

    def test_no_third_party_script_can_block_page_rendering(self):
        # A parser-blocking third-party <script src> left the storefront blank for
        # ~129s when sdk.51.la stalled. Only our own assets may load as plain tags.
        for tag in re.findall(r"<script\b[^>]*\bsrc=[^>]*>", self.response.text):
            src = re.search(r'src="([^"]+)"', tag).group(1)
            if not src.startswith("/assets/"):
                self.assertRegex(tag, r"\b(async|defer)\b", tag)

    def test_storefront_uses_51las_official_async_snippet_verbatim(self):
        self.assertIn(self.OFFICIAL_SNIPPET, self.response.text)

    def test_csp_allows_every_inline_script_on_the_page_by_hash(self):
        import hashlib
        inline = re.findall(r"<script>(.*?)</script>", self.response.text, re.S)
        self.assertTrue(inline)
        for body in inline:
            digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
            self.assertIn(f"'sha256-{digest}'", self.directives["script-src"])

    def test_csp_allows_51la_sdk_and_beacons_without_unsafe_inline(self):
        self.assertIn("sdk.51.la", self.directives["script-src"])
        self.assertNotIn("'unsafe-inline'", self.directives["script-src"])
        self.assertIn("*.51.la", self.directives["connect-src"])
        self.assertIn("*.51.la", self.directives["img-src"])

if __name__ == "__main__":
    unittest.main()
