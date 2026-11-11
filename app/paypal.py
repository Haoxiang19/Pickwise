"""PayPal REST calls: Orders v2 and Payments v2. Sandbox only.

Without PAYPAL_CLIENT_ID / PAYPAL_CLIENT_SECRET, every call goes to `paypal_mock`,
which returns responses of the same shape so the checkout code runs unchanged.
"""
import os
import time

import httpx

from app import paypal_mock
from app.money import to_dollars

# Hard-coded on purpose: this app must never be pointed at live PayPal. Not configurable.
BASE_URL = "https://api-m.sandbox.paypal.com"
ITEM_NAME_MAX = 127  # PayPal accepts longer names but truncates them to 127 characters

_token = {"value": None, "expires_at": 0.0}


class PayPalError(Exception):
    """A PayPal call failed. `issue` is PayPal's error code, e.g. INSTRUMENT_DECLINED."""

    def __init__(self, issue: str, message: str = ""):
        super().__init__(f"{issue}: {message}")
        self.issue = issue


def enabled() -> bool:
    return bool(os.getenv("PAYPAL_CLIENT_ID") and os.getenv("PAYPAL_CLIENT_SECRET"))


def _access_token() -> str:
    """Client-credentials token, cached in memory until a minute before it expires."""
    if _token["value"] and time.time() < _token["expires_at"] - 60:
        return _token["value"]
    try:
        resp = httpx.post(f"{BASE_URL}/v1/oauth2/token", data={"grant_type": "client_credentials"},
                          auth=(os.getenv("PAYPAL_CLIENT_ID"), os.getenv("PAYPAL_CLIENT_SECRET")), timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise PayPalError("AUTH_FAILED", str(e)) from e
    _token.update(value=data["access_token"], expires_at=time.time() + int(data.get("expires_in", 0)))
    return _token["value"]


def _call(method: str, path: str, request_id: str | None = None, body: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_access_token()}", "Prefer": "return=representation"}
    if request_id:
        headers["PayPal-Request-Id"] = request_id
    try:
        resp = httpx.request(method, BASE_URL + path, headers=headers, json=body, timeout=30)
        data = resp.json() if resp.content else {}
    except (httpx.HTTPError, ValueError) as e:
        # No usable response: the request may or may not have happened at PayPal.
        raise PayPalError("NETWORK_ERROR", str(e)) from e
    if resp.status_code >= 500:
        raise PayPalError("NETWORK_ERROR", f"HTTP {resp.status_code}")
    if resp.status_code >= 400:
        details = data.get("details") or [{}]
        raise PayPalError(details[0].get("issue") or data.get("name") or f"HTTP_{resp.status_code}", data.get("message", ""))
    return data


def create_order(amount_cents: int, currency: str, items: list, request_id: str, return_url: str, cancel_url: str) -> dict:
    """Create an order with one line item per product; return {"id", "approve_url"}.

    `items` is the order row's snapshot. The buyer is redirected to the payer-action link.
    """
    # There is no tax or shipping, so the item total must equal the amount. Check before sending,
    # so a wrong order is never created at PayPal (PayPal would answer ITEM_TOTAL_MISMATCH).
    item_total = sum(i["unit_price_cents"] * i["quantity"] for i in items)
    if not items or item_total != amount_cents:
        raise PayPalError("ITEM_TOTAL_MISMATCH", f"items add up to {item_total} cents, order amount is {amount_cents}")
    body = {
        "intent": "CAPTURE",
        "purchase_units": [{
            "amount": {"currency_code": currency, "value": to_dollars(amount_cents),
                       "breakdown": {"item_total": {"currency_code": currency, "value": to_dollars(item_total)}}},
            "items": [{"name": i["title"][:ITEM_NAME_MAX],
                       "quantity": str(i["quantity"]),  # PayPal's schema types quantity as a string
                       "unit_amount": {"currency_code": currency, "value": to_dollars(i["unit_price_cents"])}}
                      for i in items],
        }],
        "payment_source": {"paypal": {"experience_context": {
            "return_url": return_url, "cancel_url": cancel_url,
            "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING",
        }}},
    }
    data = _call("POST", "/v2/checkout/orders", request_id, body) if enabled() else paypal_mock.create_order(body, request_id)
    link = next((l["href"] for l in data.get("links", []) if l.get("rel") == "payer-action"), None)
    if not link:
        raise PayPalError("NO_APPROVAL_LINK", f"order {data.get('id')} has no payer-action link")
    return {"id": data["id"], "approve_url": link}


def get_order(paypal_order_id: str) -> dict:
    return _call("GET", f"/v2/checkout/orders/{paypal_order_id}") if enabled() else paypal_mock.get_order(paypal_order_id)


def capture_order(paypal_order_id: str, request_id: str) -> dict:
    if not enabled():
        return paypal_mock.capture_order(paypal_order_id, request_id)
    return _call("POST", f"/v2/checkout/orders/{paypal_order_id}/capture", request_id, {})


def refund_capture(capture_id: str, request_id: str) -> dict:
    """Full refund: an empty body refunds the whole capture."""
    if not enabled():
        return paypal_mock.refund_capture(capture_id, request_id)
    return _call("POST", f"/v2/payments/captures/{capture_id}/refund", request_id, {})
