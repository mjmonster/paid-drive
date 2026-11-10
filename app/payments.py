"""ZPay / EasyPay-compatible adapter. No network is used in demo mode.

Protocol reference: https://z-pay.cn/doc.html
Match ZPAY_BASE_URL to the merchant's existing provider before going live.
"""
import hashlib
import hmac
import logging
from decimal import Decimal, InvalidOperation
from urllib.parse import urljoin

import httpx

from .config import Settings

# The provider's query API puts the merchant key in its query parameters.
# Never let HTTPX's informational request logging record that URL.
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


class ZPay:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def submit_url(self):
        return urljoin(self.settings.zpay_base_url.rstrip("/") + "/", "submit.php")

    def checkout_params(self, order, collection):
        values = {
            "pid": self.settings.zpay_pid,
            "type": order["payment_method"],
            "out_trade_no": order["reference"],
            "notify_url": self.settings.app_url + "/api/payments/zpay/notify",
            "return_url": self.settings.app_url + "/payment/return",
            "name": collection["title"][:100],
            "money": money_text(order["amount_cents"]),
            "sign_type": "MD5",
        }
        values["sign"] = sign_params(values, self.settings.zpay_key)
        return values

    def verify_notification(self, values):
        if values.get("sign_type", "MD5") != "MD5":
            raise PaymentError("支付签名类型不受支持。")
        signature = str(values.get("sign", ""))
        if not signature or not hmac.compare_digest(signature.lower(), sign_params(values, self.settings.zpay_key)):
            raise PaymentError("支付通知验证失败。")
        if str(values.get("pid")) != self.settings.zpay_pid or values.get("trade_status") != "TRADE_SUCCESS":
            raise PaymentError("尚未确认支付成功，请稍后查询。")

    async def query(self, order):
        url = urljoin(self.settings.zpay_base_url.rstrip("/") + "/", "api.php")
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
                response = await client.get(url, params={
                    "act": "order", "pid": self.settings.zpay_pid,
                    "key": self.settings.zpay_key, "out_trade_no": order["reference"],
                })
                response.raise_for_status()
                value = response.json()
                if not isinstance(value, dict):
                    raise ValueError
                return value
        except (httpx.HTTPError, ValueError):
            # Do not include the exception / request URL, which can contain a key.
            raise PaymentError("支付平台暂时无法连接，请稍后查询支付结果。") from None

    def validate_query(self, order, result, notification=None):
        if str(result.get("code")) != "1":
            raise PaymentError("支付平台尚未确认这笔订单，请稍后查询。")
        if str(result.get("status")) != "1":
            return False
        if str(result.get("pid")) != self.settings.zpay_pid:
            raise PaymentError("支付商户信息不一致，请联系微信客服。")
        if str(result.get("out_trade_no")) != order["reference"]:
            raise PaymentError("支付订单信息不一致，请联系微信客服。")
        if parse_cents(result.get("money")) != order["amount_cents"]:
            raise PaymentError("支付金额不一致，请联系微信客服。")
        trade = str(result.get("trade_no", ""))
        if not trade or len(trade) > 128:
            raise PaymentError("支付流水信息不完整，请稍后查询。")
        if result.get("type") and result["type"] != order["payment_method"]:
            raise PaymentError("支付方式信息不一致，请联系微信客服。")
        if notification:
            if str(notification.get("out_trade_no")) != order["reference"]:
                raise PaymentError("支付通知的订单信息不一致。")
            if parse_cents(notification.get("money")) != order["amount_cents"]:
                raise PaymentError("支付通知的金额不一致。")
            if str(notification.get("trade_no")) != trade:
                raise PaymentError("支付通知的流水信息不一致。")
        return True
