"""Money flow: Confirm (create order), return from PayPal (verify, then capture), cancel, refund.

Only HTTP endpoints triggered by a user click call these functions; the model cannot.
"""
import logging
import threading
import time

from app import memory, paypal, store
from app.money import to_cents

log = logging.getLogger(__name__)

# One worker process (requirements section 10), so in-process locks are enough to stop a double
# click from passing a status check twice. PayPal-Request-Id is the second guard.
# One lock per order, not one for the whole app: a slow PayPal call on one order must not hold up
# every other user's payment. Keyed by cart ID, because Confirm runs before the order row exists
# and each cart has at most one order (cart_id is UNIQUE).
_order_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()  # protects the dict; held only for the lookup, never across a PayPal call
CAPTURE_WINDOW_SECONDS = 3 * 3600  # PayPal allows capture only within 3 hours of creation

MESSAGES = {
    "CREATED": "Waiting for your approval on PayPal. Nothing has been charged.",
    "COMPLETED": "Payment successful.",
    "CANCELLED": "Payment cancelled. Nothing was charged.",
    "CAPTURE_FAILED": "Payment failed. Nothing was charged.",
    "AMOUNT_MISMATCH": "The PayPal amount did not match your order, so it was not captured. Nothing was charged.",
    "PARTIALLY_REFUNDED": "Part of this order was refunded.",
    "REFUNDED": "This order was refunded.",
}


class CheckoutError(Exception):
    """A checkout step was refused; the message is safe to show the user."""


def order_lock(cart_id: str) -> threading.Lock:
    """The lock of one order (F12). Every money step of that order runs under it."""
    with _locks_guard:
        if cart_id not in _order_locks:
            _order_locks[cart_id] = threading.Lock()
        return _order_locks[cart_id]


def _lock_of(user_id: str, order_id: int) -> threading.Lock:
    """The lock for an existing order of this user; the row is read again once the lock is held."""
    order = store.get_order(order_id, user_id)
    if order is None:
        raise CheckoutError("Order not found.")
    return order_lock(order["cart_id"])


def order_view(order: dict) -> dict:
    """What the page and the agent may see of an order."""
    items = [{**item, "line": n, "refunded": "refund_id" in item} for n, item in enumerate(order["items"], start=1)]
    return {
        "order_id": order["id"], "status": order["status"], "amount_cents": order["amount_cents"],
        "currency": order["currency"], "items": items, "paypal_order_id": order["paypal_order_id"],
        "refunded_cents": sum(_line_cents(i) for i in items if i["refunded"]),
        "message": " ".join(x for x in (MESSAGES[order["status"]], order["note"]) if x),
    }


def _line_cents(item: dict) -> int:
    return item["unit_price_cents"] * item["quantity"]


def confirm(session: store.Session, user_id: str, cart_id: str, base_url: str) -> dict:
    """F9, F10: on the Confirm click, create the order row, then the PayPal order. Returns the order row.

    A second Confirm on the same cart returns the existing order and approval link.
    """
    with order_lock(cart_id):
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
    with _lock_of(user_id, order_id):
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
    with _lock_of(user_id, order_id):
        order = store.get_order(order_id, user_id)
        if order is None:
            raise CheckoutError("Order not found.")
        if order["status"] == "CREATED":
            return _fail(order, "CANCELLED")
        return order


def refund_draft(user_id: str, order_id: int, lines: list[int] | None = None) -> dict:
    """F16, F23, proposal only: check which lines can be refunded and describe the refund. Calls nothing.

    Lines are numbered from 1 in the order's item snapshot, as the user sees them.
    `lines=None` means every line not refunded yet.
    """
    order = store.get_order(order_id, user_id)
    if order is None:
        raise CheckoutError("Order not found.")
    if order["status"] == "REFUNDED":
        raise CheckoutError(f"Order #{order_id} was already refunded.")
    if order["status"] not in ("COMPLETED", "PARTIALLY_REFUNDED"):
        raise CheckoutError(f"Only paid orders can be refunded; order #{order_id} is {order['status']}.")
    items = order["items"]
    if lines is None:
        lines = [n for n, item in enumerate(items, start=1) if "refund_id" not in item]
    lines = list(dict.fromkeys(lines))  # a repeated line number is one line
    if not lines:
        raise CheckoutError("Choose at least one line to refund.")
    for n in lines:
        if not isinstance(n, int) or not 1 <= n <= len(items):
            raise CheckoutError(f"Order #{order_id} has no line {n}; its lines are 1 to {len(items)}.")
        if "refund_id" in items[n - 1]:
            raise CheckoutError(f"Line {n} of order #{order_id} ({items[n - 1]['title']}) was already refunded.")
    chosen = [{"line": n, "title": items[n - 1]["title"], "quantity": items[n - 1]["quantity"],
               "amount_cents": _line_cents(items[n - 1])} for n in lines]
    return {"order_id": order["id"], "currency": order["currency"], "lines": chosen,
            "amount_cents": sum(c["amount_cents"] for c in chosen)}


def refund(user_id: str, order_id: int, lines: list[int] | None = None) -> dict:
    """F16, F23: the user clicked "Confirm refund". One PayPal refund per line, for that line's amount.

    Each line is saved as soon as PayPal confirms it, so a failure part-way keeps the lines already
    refunded, and a retry of the failed line repeats its request ID instead of refunding twice.
    Returns the updated row.
    """
    with _lock_of(user_id, order_id):
        draft = refund_draft(user_id, order_id, lines)  # same checks: own order, paid, lines not refunded before
        order = store.get_order(order_id, user_id)
        items = order["items"]
        for line in draft["lines"]:
            n = line["line"]
            try:
                result = paypal.refund_capture(order["capture_id"], f"refund-{order['id']}-{n}",
                                               line["amount_cents"], order["currency"])
            except paypal.PayPalError as e:
                log.warning("refund %s line %s failed: %s", order_id, n, e)
                store.update_order(order["id"], note=f"Line {n} ({line['title']}) was not refunded ({e.issue}). "
                                                     "Lines refunded before it stay refunded; you can try again.")
                break
            if result.get("status") != "COMPLETED":
                # e.g. PENDING: not counted yet; a retry with the same request ID returns the latest status.
                store.update_order(order["id"], note=f"The refund of line {n} ({line['title']}) is "
                                                     f"{result.get('status')} at PayPal; it is not counted as refunded yet.")
                break
            items[n - 1]["refund_id"] = result.get("id")
            done = all("refund_id" in item for item in items)
            store.update_order(order["id"], items=items, status="REFUNDED" if done else "PARTIALLY_REFUNDED", note="")
        return store.get_order(order["id"], user_id)
