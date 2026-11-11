"""Sessions and carts (in memory). Orders in SQLite are added with the payment features."""
import secrets
import time
from dataclasses import dataclass, field

from app.money import to_dollars

CART_TTL_SECONDS = 15 * 60  # a cart is a price quote valid until the Confirm click
MAX_QUANTITY = 10


class CartError(ValueError):
    """The cart request breaks a rule; the message is safe to show the user."""


@dataclass
class Session:
    history: list = field(default_factory=list)   # chat messages sent to the model, without the system prompt
    products: dict = field(default_factory=dict)  # every product returned by a search in this session, by ID
    budget_cents: int | None = None               # budget of the latest request; None means no limit
    carts: dict = field(default_factory=dict)     # cart ID -> cart


sessions: dict[str, Session] = {}


def get_session(user_id: str) -> Session:
    return sessions.setdefault(user_id, Session())


def create_cart(session: Session, product_id: str, quantity: int = 1, now: float | None = None) -> dict:
    """F8: price a cart on the server. The model only supplies a product ID and a quantity."""
    product = session.products.get(product_id)
    if product is None:
        raise CartError("Unknown product: only products from a search in this conversation can be ordered.")
    if not product["in_stock"] or product["price_cents"] is None or product["currency"] != "USD":
        raise CartError("That product is not available to order.")
    if not isinstance(quantity, int) or not 1 <= quantity <= MAX_QUANTITY:
        raise CartError(f"Quantity must be between 1 and {MAX_QUANTITY}.")
    total = product["price_cents"] * quantity
    if session.budget_cents is not None and total > session.budget_cents:
        raise CartError(f"The total ${to_dollars(total)} is over your budget of ${to_dollars(session.budget_cents)}.")
    cart = {
        "id": "cart_" + secrets.token_hex(8),
        "items": [{"product_id": product_id, "title": product["title"], "unit_price_cents": product["price_cents"], "quantity": quantity}],
        "total_cents": total,
        "currency": "USD",
        "expires_at": (time.time() if now is None else now) + CART_TTL_SECONDS,
    }
    session.carts[cart["id"]] = cart
    return cart


def get_valid_cart(session: Session, cart_id: str, now: float | None = None) -> dict:
    """Return a cart of this session that has not expired, or raise CartError."""
    cart = session.carts.get(cart_id)
    if cart is None:
        raise CartError("Unknown cart.")
    if (time.time() if now is None else now) > cart["expires_at"]:
        raise CartError("This price quote has expired. Please choose the product again.")
    return cart
