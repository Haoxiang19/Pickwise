"""Money flow: Confirm (create order), return from PayPal (verify, then capture), cancel, refund.

Only HTTP endpoints triggered by a user click call these functions; the model cannot.
"""
import logging
import threading
import time

from app import memory, paypal, store
from app.money import to_cents

log = logging.getLogger(__name__)

# One worker process (requirements section 10), so one lock is enough to stop a double click
# from passing the status check twice. PayPal-Request-Id is the second guard.
LOCK = threading.Lock()
CAPTURE_WINDOW_SECONDS = 3 * 3600  # PayPal allows capture only within 3 hours of creation

MESSAGES = {
    "CREATED": "Waiting for your approval on PayPal. Nothing has been charged.",
    "COMPLETED": "Payment successful.",
    "CANCELLED": "Payment cancelled. Nothing was charged.",
    "CAPTURE_FAILED": "Payment failed. Nothing was charged.",
    "AMOUNT_MISMATCH": "The PayPal amount did not match your order, so it was not captured. Nothing was charged.",
    "REFUNDED": "This order was refunded.",
}


class CheckoutError(Exception):
    """A checkout step was refused; the message is safe to show the user."""


def order_view(order: dict) -> dict:
    """What the page and the agent may see of an order."""
    return {
        "order_id": order["id"], "status": order["status"], "amount_cents": order["amount_cents"],
        "currency": order["currency"], "items": order["items"], "paypal_order_id": order["paypal_order_id"],
        "message": " ".join(x for x in (MESSAGES[order["status"]], order["note"]) if x),
    }


def confirm(session: store.Session, user_id: str, cart_id: str, base_url: str) -> dict:
    """F9, F10: on the Confirm click, create the order row, then the PayPal order. Returns the order row.

    A second Confirm on the same cart returns the existing order and approval link.
    """
    with LOCK:
        order = store.get_order_by_cart(cart_id, user_id)
        if order is None:
            cart = store.get_valid_cart(session, cart_id)  # the 15-minute quote ends at this click
            order = store.create_order(user_id, cart)
        if order["status"] != "CREATED":
            raise CheckoutError(f"{MESSAGES[order['status']]} Please choose the product again to start a new order.")
        if order["approval_url"]:
            return order
        try:
            created = paypal.create_order(
                order["amount_cents"], order["currency"], items=order["items"], request_id=f"create-{cart_id}",
                return_url=f"{base_url}/paypal/return?order_id={order['id']}",
                cancel_url=f"{base_url}/paypal/cancel?order_id={order['id']}")
        except paypal.PayPalError as e:
            # The row stays CREATED without a link, so clicking Confirm again retries with the same request ID.
            log.warning("create order %s failed: %s", order["id"], e)
            raise CheckoutError("Could not start the PayPal payment. Nothing was charged. Please try again.") from e
        store.update_order(order["id"], paypal_order_id=created["id"], approval_url=created["approve_url"])
        return store.get_order(order["id"], user_id)


def _fail(order: dict, status: str, note: str = "") -> dict:
    store.update_order(order["id"], status=status, note=note)
    return store.get_order(order["id"], order["user_id"])


def _record_capture(order: dict, paypal_order: dict) -> dict:
    """Paid only if purchase_units[0].payments.captures[0].status is COMPLETED; the order status alone is not enough."""
    units = paypal_order.get("purchase_units") or [{}]
    captures = (units[0].get("payments") or {}).get("captures") or [{}]
    capture = captures[0]
    if capture.get("status") == "COMPLETED":
        store.update_order(order["id"], status="COMPLETED", capture_id=capture.get("id"), note="")
        memory.record_purchase(order["user_id"], order["items"])  # F18: a purchase supports a brand preference
        return store.get_order(order["id"], order["user_id"])
    return _fail(order, "CAPTURE_FAILED", f"PayPal reported the capture as {capture.get('status') or 'missing'}.")


def handle_return(user_id: str, order_id: int) -> dict:
    """F11: the buyer came back from PayPal. Verify the order, then capture. Returns the updated row."""
    with LOCK:
        order = store.get_order(order_id, user_id)
        if order is None:
            raise CheckoutError("Order not found.")
        if order["status"] != "CREATED" or not order["paypal_order_id"]:
            return order  # a refresh after the result: show what is stored, do not call PayPal again
        if time.time() - order["created_at"] > CAPTURE_WINDOW_SECONDS:
            return _fail(order, "CAPTURE_FAILED", "The payment window of 3 hours has passed.")
        # The PayPal order ID comes from our row, never from the return URL's query string.
        pp_id = order["paypal_order_id"]
        try:
            pp = paypal.get_order(pp_id)
        except paypal.PayPalError as e:
            log.warning("read back %s failed: %s", pp_id, e)
            return _keep_for_retry(order)
        if pp.get("status") == "COMPLETED":
            return _record_capture(order, pp)  # captured by an earlier attempt whose result we did not store
        if pp.get("status") != "APPROVED":
            return _fail(order, "CANCELLED", "The payment was not approved on PayPal.")
        amount = (pp.get("purchase_units") or [{}])[0].get("amount") or {}
        try:
            paypal_cents = to_cents(amount.get("value"))
        except ValueError:
            paypal_cents = None
        if paypal_cents != order["amount_cents"] or amount.get("currency_code") != order["currency"]:
            return _fail(order, "AMOUNT_MISMATCH")
        try:
            return _record_capture(order, paypal.capture_order(pp_id, f"capture-{order['id']}"))
        except paypal.PayPalError as e:
            log.warning("capture %s failed: %s", pp_id, e)
            issue = e.issue
        if issue == "ORDER_ALREADY_CAPTURED":
            try:
                return _record_capture(order, paypal.get_order(pp_id))  # show PayPal's real state
            except paypal.PayPalError:
                return _keep_for_retry(order)
        if issue == "ORDER_NOT_APPROVED":
            return _fail(order, "CANCELLED", "The payment was not approved on PayPal.")
        if issue == "INSTRUMENT_DECLINED":
            return _fail(order, "CAPTURE_FAILED", "Your payment method was declined.")
        if issue == "NETWORK_ERROR":
            return _keep_for_retry(order)
        return _fail(order, "CAPTURE_FAILED", f"PayPal error {issue}.")


def _keep_for_retry(order: dict) -> dict:
    # No answer from PayPal: the outcome is unknown, so the order is not marked failed or paid.
    # "Check again" on the page revisits the return URL; the same PayPal-Request-Id returns the earlier result.
    store.update_order(order["id"], note="Could not reach PayPal to confirm the payment.")
    return store.get_order(order["id"], order["user_id"])


def handle_cancel(user_id: str, order_id: int) -> dict:
    """F13: the buyer cancelled on PayPal. Nothing was captured."""
    with LOCK:
        order = store.get_order(order_id, user_id)
        if order is None:
            raise CheckoutError("Order not found.")
        if order["status"] == "CREATED":
            return _fail(order, "CANCELLED")
        return order


def refund_draft(user_id: str, order_id: int) -> dict:
    """F16, proposal only: check the order can be refunded and describe the refund. Calls nothing."""
    order = store.get_order(order_id, user_id)
    if order is None:
        raise CheckoutError("Order not found.")
    if order["status"] == "REFUNDED":
        raise CheckoutError(f"Order #{order_id} was already refunded.")
    if order["status"] != "COMPLETED":
        raise CheckoutError(f"Only paid orders can be refunded; order #{order_id} is {order['status']}.")
    return {"order_id": order["id"], "amount_cents": order["amount_cents"], "currency": order["currency"],
            "items": order["items"]}


def refund(user_id: str, order_id: int) -> dict:
    """F16: the user clicked "Confirm refund". Full refund of the stored capture. Returns the updated row."""
    with LOCK:
        refund_draft(user_id, order_id)  # same checks: own order, COMPLETED, not refunded before
        order = store.get_order(order_id, user_id)
        try:
            result = paypal.refund_capture(order["capture_id"], f"refund-{order['id']}")
        except paypal.PayPalError as e:
            log.warning("refund %s failed: %s", order_id, e)
            raise CheckoutError(f"The refund did not go through ({e.issue}). The order is unchanged; you can try again.") from e
        if result.get("status") != "COMPLETED":
            # e.g. PENDING: not marked refunded yet; a retry with the same request ID returns the latest status.
            store.update_order(order["id"], note=f"Refund status at PayPal: {result.get('status')}.")
            return store.get_order(order["id"], user_id)
        store.update_order(order["id"], status="REFUNDED", refund_id=result.get("id"), note="")
        return store.get_order(order["id"], user_id)
