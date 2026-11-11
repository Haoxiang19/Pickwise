"""Money flow: Confirm (create order), return from PayPal (verify, then capture), cancel, refund.

Only HTTP endpoints triggered by a user click call these functions; the model cannot.
"""
import logging
import threading

from app import paypal, store

log = logging.getLogger(__name__)

# One worker process (requirements section 10), so one lock is enough to stop a double click
# from passing the status check twice. PayPal-Request-Id is the second guard.
LOCK = threading.Lock()

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
                order["amount_cents"], order["currency"], request_id=f"create-{cart_id}",
                return_url=f"{base_url}/paypal/return?order_id={order['id']}",
                cancel_url=f"{base_url}/paypal/cancel?order_id={order['id']}")
        except paypal.PayPalError as e:
            # The row stays CREATED without a link, so clicking Confirm again retries with the same request ID.
            log.warning("create order %s failed: %s", order["id"], e)
            raise CheckoutError("Could not start the PayPal payment. Nothing was charged. Please try again.") from e
        store.update_order(order["id"], paypal_order_id=created["id"], approval_url=created["approve_url"])
        return store.get_order(order["id"], user_id)
