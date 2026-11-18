"""Adapter for the ZPay (易支付) gateway. No network is used in demo mode.

Ported from soccer-match-analyzer's ZPayClient:
- Signing is local MD5: params sorted a-z, ``sign``/``sign_type``/empty values
  excluded, joined as ``k=v&k=v`` with raw (un-encoded) values, merchant key
  appended, lowercase hex digest.
- Order creation builds a signed page-jump URL for ``submit.php``. That URL *is*
  the cashier, so creating it makes no network call.
- Status is pulled from ``api.php?act=order`` by our merchant order number.
"""
import hashlib
import hmac
import logging
from decimal import Decimal, InvalidOperation
from typing import NamedTuple
from urllib.parse import urlencode, urljoin

import httpx

from .config import Settings

# The query API puts the merchant key in its query string. Never let HTTPX's
# informational request logging record that URL.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class PaymentError(Exception):
    pass


def money_text(cents: int):
    return f"{cents // 100}.{cents % 100:02d}"


def parse_cents(value):
    try:
        amount = Decimal(str(value))
        cents = amount * 100
        if not amount.is_finite() or cents != cents.to_integral_value() or amount < 0:
            raise ValueError
        return int(cents)
    except (InvalidOperation, ValueError, TypeError, OverflowError):
        raise PaymentError("支付金额无效。") from None


def sign_params(params, key: str):
    source = "&".join(f"{name}={params[name]}" for name in sorted(params)
                      if name not in {"sign", "sign_type"} and params[name] not in ("", None))
    # MD5 is required by this provider's protocol, not used for our access tokens.
    return hashlib.md5((source + key).encode("utf-8"), usedforsecurity=False).hexdigest()


class Notification(NamedTuple):
    """A ZPay notify / return parameter set after its signature check.

    ``valid`` is the MD5 check alone; ``success`` is ``trade_status == TRADE_SUCCESS``.
    ``cents`` is ``None`` when ``money`` is missing or malformed, so callers reject it.
    """
    valid: bool
    success: bool
    reference: str | None
    cents: int | None
    trade_no: str | None


class OrderStatus(NamedTuple):
    """Result of ``api.php?act=order``: ZPay reports only paid (1) or unpaid (0)."""
    paid: bool
    trade_no: str | None


class ZPay:
    def __init__(self, settings: Settings):
        self.settings = settings
        # Network seam: tests swap in httpx.MockTransport; None means real HTTP.
        self.transport = None

    def _endpoint(self, name):
        return urljoin(self.settings.zpay_base_url.rstrip("/") + "/", name)

    def pay_url(self, reference: str, cents: int, name: str):
        """Signed page-jump cashier URL for the browser to open."""
        values = {
            "pid": self.settings.zpay_pid,
            "type": self.settings.zpay_pay_type,
            "out_trade_no": reference,
            "notify_url": self.settings.app_url + "/api/payments/zpay/notify",
            "return_url": self.settings.app_url + "/payment/return",
            "name": name[:100],
            "money": money_text(cents),
        }
        values["sign"] = sign_params(values, self.settings.zpay_key)
        values["sign_type"] = "MD5"
        return self._endpoint("submit.php") + "?" + urlencode(values)

    async def query(self, reference: str) -> OrderStatus:
        """Ask ZPay whether an order is paid.

        Raises PaymentError on any transport or gateway failure; callers treat that
        as still pending (fail-soft) and let the client poll again.
        """
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=False, transport=self.transport) as client:
                response = await client.get(self._endpoint("api.php"), params={
                    "act": "order", "pid": self.settings.zpay_pid,
                    "key": self.settings.zpay_key, "out_trade_no": reference,
                })
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError):
            # Never include the exception: its request URL contains the merchant key.
            raise PaymentError("支付平台暂时无法连接。") from None
        if not isinstance(body, dict) or str(body.get("code")) != "1":
            raise PaymentError("支付平台未能查询这笔订单。")
        return OrderStatus(str(body.get("status")) == "1", str(body.get("trade_no") or "") or None)

    def parse_notify(self, values) -> Notification:
        signature = str(values.get("sign") or "")
        valid = bool(signature) and hmac.compare_digest(signature.lower(), sign_params(values, self.settings.zpay_key))
        try:
            cents = parse_cents(values.get("money")) if values.get("money") not in (None, "") else None
        except PaymentError:
            cents = None
        return Notification(valid, values.get("trade_status") == "TRADE_SUCCESS",
                            values.get("out_trade_no"), cents, values.get("trade_no") or None)
