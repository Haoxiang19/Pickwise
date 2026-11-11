"""In-memory stand-in for the PayPal sandbox, used when no PayPal credentials are set.

Responses copy the shape of the real API (status, purchase_units, links, captures), and a
repeated PayPal-Request-Id returns the stored response, like PayPal's idempotency.
The approval page is served by main.py at /mock-paypal/checkout.
"""
import copy
import secrets

from app.money import to_cents

orders: dict[str, dict] = {}     # PayPal order ID -> order JSON
urls: dict[str, dict] = {}       # PayPal order ID -> {"return_url", "cancel_url"}
responses: dict[str, dict] = {}  # PayPal-Request-Id -> earlier response


def _error(issue: str):
    from app.paypal import PayPalError  # imported here to avoid a circular import
    return PayPalError(issue, "mock PayPal")


def _check_item_totals(unit: dict) -> None:
    """The sum rules the Orders v2 docs state for items and breakdown, with their 422 issue names."""
    amount, items = unit["amount"], unit.get("items") or []
    item_total = (amount.get("breakdown") or {}).get("item_total")
    if items and item_total is None:
        raise _error("ITEM_TOTAL_REQUIRED")
    if items and to_cents(item_total["value"]) != sum(to_cents(i["unit_amount"]["value"]) * int(i["quantity"]) for i in items):
        raise _error("ITEM_TOTAL_MISMATCH")
    if item_total is not None and to_cents(amount["value"]) != to_cents(item_total["value"]):
        raise _error("AMOUNT_MISMATCH")  # no tax, shipping or discount in this app


def create_order(body: dict, request_id: str) -> dict:
    if request_id in responses:
        return copy.deepcopy(responses[request_id])
    _check_item_totals(body["purchase_units"][0])
    order_id = "MOCK-" + secrets.token_hex(6).upper()
    context = body["payment_source"]["paypal"]["experience_context"]
    urls[order_id] = {"return_url": context["return_url"], "cancel_url": context["cancel_url"]}
    orders[order_id] = {
        "id": order_id,
        "status": "PAYER_ACTION_REQUIRED",
        "purchase_units": copy.deepcopy(body["purchase_units"]),
        "links": [{"rel": "payer-action", "href": f"/mock-paypal/checkout?token={order_id}"}],
    }
    responses[request_id] = copy.deepcopy(orders[order_id])
    return copy.deepcopy(orders[order_id])


def approve(order_id: str) -> None:
    """What the buyer's click on PayPal's approval page does."""
    if orders[order_id]["status"] == "PAYER_ACTION_REQUIRED":
        orders[order_id]["status"] = "APPROVED"


def get_order(order_id: str) -> dict:
    if order_id not in orders:
        raise _error("RESOURCE_NOT_FOUND")
    return copy.deepcopy(orders[order_id])


def capture_order(order_id: str, request_id: str) -> dict:
    if request_id in responses:
        return copy.deepcopy(responses[request_id])
    order = orders.get(order_id)
    if order is None:
        raise _error("RESOURCE_NOT_FOUND")
    if order["status"] == "COMPLETED":
        raise _error("ORDER_ALREADY_CAPTURED")
    if order["status"] != "APPROVED":
        raise _error("ORDER_NOT_APPROVED")
    order["status"] = "COMPLETED"
    amount = order["purchase_units"][0]["amount"]
    order["purchase_units"][0]["payments"] = {"captures": [
        {"id": "MOCKCAP-" + secrets.token_hex(6).upper(), "status": "COMPLETED", "amount": dict(amount)}]}
    responses[request_id] = copy.deepcopy(order)
    return copy.deepcopy(order)


def refund_capture(capture_id: str, request_id: str) -> dict:
    if request_id in responses:
        return copy.deepcopy(responses[request_id])
    if any(r.get("capture_id") == capture_id for r in responses.values()):
        raise _error("CAPTURE_FULLY_REFUNDED")
    if not any(c["id"] == capture_id for o in orders.values()
               for c in o["purchase_units"][0].get("payments", {}).get("captures", [])):
        raise _error("RESOURCE_NOT_FOUND")
    refund = {"id": "MOCKREF-" + secrets.token_hex(6).upper(), "status": "COMPLETED", "capture_id": capture_id}
    responses[request_id] = refund
    return copy.deepcopy(refund)
