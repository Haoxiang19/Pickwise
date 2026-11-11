"""Sessions and carts in memory; orders in SQLite."""
import json
import logging
import secrets
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass, field

from app import catalog
from app.money import to_dollars

log = logging.getLogger(__name__)

CART_TTL_SECONDS = 15 * 60  # a cart is a price quote valid until the Confirm click
MAX_QUANTITY = 10
MAX_CART_LINES = 6  # F21: also the most items a set recommendation can have


class CartError(ValueError):
    """The cart request breaks a rule; the message is safe to show the user."""


@dataclass
class Session:
    user_id: str = ""                             # the cookie ID; orders are looked up by it
    history: list = field(default_factory=list)   # chat messages sent to the model, without the system prompt
    products: dict = field(default_factory=dict)  # every product returned by a search in this session, by ID
    budget_cents: int | None = None               # budget of the latest request; None means no limit
    carts: dict = field(default_factory=dict)     # cart ID -> cart
    memory_profile: list | None = None            # F19: strongest saved preferences, loaded at the first message


sessions: dict[str, Session] = {}


def get_session(user_id: str) -> Session:
    if user_id not in sessions:
        sessions[user_id] = Session(user_id=user_id)
    return sessions[user_id]


def new_conversation(user_id: str) -> Session:
    """Start a new conversation: clear history, search results and carts; orders and memory are kept."""
    sessions[user_id] = Session(user_id=user_id)
    return sessions[user_id]


def _refreshed(session: Session, product_id: str, fetch) -> dict:
    """Read the product back from the catalog and replace the session's stored copy."""
    try:
        fresh = (catalog.get_product if fetch is None else fetch)(product_id)
    except catalog.CatalogError as e:
        log.warning("price refresh for %s failed: %s", product_id, e)
        raise CartError("Could not check the current price. Please try again.") from e
    if fresh is None:
        raise CartError("That product is no longer available. Please choose another one.")
    session.products[product_id] = fresh
    return fresh


def _cart_item(session: Session, product_id: str, quantity, fetch) -> dict:
    """Check one line and return it priced from the catalog. Any failure raises CartError."""
    cached = session.products.get(product_id)
    if cached is None:
        raise CartError("Unknown product: only products from a search in this conversation can be ordered.")
    product = _refreshed(session, product_id, fetch)
    if not product["in_stock"] or product["price_cents"] is None or product["currency"] != "USD":
        raise CartError("That product is not available to order.")
    if not isinstance(quantity, int) or not 1 <= quantity <= MAX_QUANTITY:
        raise CartError(f"Quantity must be between 1 and {MAX_QUANTITY}.")
    item = {"product_id": product_id, "title": product["title"], "brand": product.get("brand", ""),
            "category": product.get("category", ""),  # scopes the brand preference a purchase writes (F18)
            "unit_price_cents": product["price_cents"], "quantity": quantity}
    if isinstance(cached["price_cents"], int) and cached["price_cents"] != product["price_cents"]:
        item["price_was_cents"] = cached["price_cents"]  # the page and the agent tell the user it moved
    return item


def create_cart_items(session: Session, lines: list, now: float | None = None, fetch=None) -> dict:
    """F8, F21: price a cart of 1 to 6 different products on the server.

    `lines` is a list of (product_id, quantity); the model and the page supply nothing else.
    Each price and stock is read back from the catalog first: a search result can be minutes old,
    and Channel3 asks for both to be refreshed before they are shown. `fetch` is for tests.
    One bad line refuses the whole cart, so the user never pays for a partial set by surprise.
    """
    if not lines:
        raise CartError("The cart is empty. Choose at least one product.")
    if len(lines) > MAX_CART_LINES:
        raise CartError(f"A cart can hold at most {MAX_CART_LINES} different products.")
    ids = [product_id for product_id, _ in lines]
    if len(set(ids)) != len(ids):
        raise CartError("The same product is listed twice. Set its quantity instead.")
    items = [_cart_item(session, product_id, quantity, fetch) for product_id, quantity in lines]
    total = sum(i["unit_price_cents"] * i["quantity"] for i in items)
    if session.budget_cents is not None and total > session.budget_cents:
        raise CartError(f"The total ${to_dollars(total)} is over your budget of ${to_dollars(session.budget_cents)}.")
    cart = {
        "id": "cart_" + secrets.token_hex(8),
        "items": items,
        "total_cents": total,
        "currency": "USD",
        "expires_at": (time.time() if now is None else now) + CART_TTL_SECONDS,
    }
    session.carts[cart["id"]] = cart
    return cart


def create_cart(session: Session, product_id: str, quantity: int = 1, now: float | None = None, fetch=None) -> dict:
    """A cart with one product (F8); kept so existing callers do not change."""
    return create_cart_items(session, [(product_id, quantity)], now=now, fetch=fetch)


def get_valid_cart(session: Session, cart_id: str, now: float | None = None) -> dict:
    """Return a cart of this session that has not expired, or raise CartError."""
    cart = session.carts.get(cart_id)
    if cart is None:
        raise CartError("Unknown cart.")
    if (time.time() if now is None else now) > cart["expires_at"]:
        raise CartError("This price quote has expired. Please choose the product again.")
    return cart


# --- Orders (SQLite) ---

DB_PATH = "orders.db"
SCHEMA = """CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    cart_id TEXT NOT NULL UNIQUE,  -- one order per cart: a second Confirm finds this row
    paypal_order_id TEXT,
    approval_url TEXT,
    capture_id TEXT,
    refund_id TEXT,
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    items TEXT NOT NULL,           -- JSON snapshot of the cart items at Confirm
    status TEXT NOT NULL,          -- CREATED, COMPLETED, CANCELLED, AMOUNT_MISMATCH, CAPTURE_FAILED, PARTIALLY_REFUNDED, REFUNDED
    note TEXT NOT NULL DEFAULT '', -- why a payment failed, shown to the user
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def _row(row) -> dict | None:
    if row is None:
        return None
    order = dict(row)
    order["items"] = json.loads(order["items"])
    return order


def create_order(user_id: str, cart: dict) -> dict:
    """Copy the cart onto a new order row with status CREATED. From now on the row is the reference."""
    now = time.time()
    with closing(_connect()) as conn, conn:
        cur = conn.execute(
            "INSERT INTO orders (user_id, cart_id, amount_cents, currency, items, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 'CREATED', ?, ?)",
            (user_id, cart["id"], cart["total_cents"], cart["currency"], json.dumps(cart["items"]), now, now))
        order_id = cur.lastrowid
    return get_order(order_id, user_id)


def get_order(order_id: int, user_id: str) -> dict | None:
    """An order of this user, or None. Users can only see their own orders."""
    with closing(_connect()) as conn:
        return _row(conn.execute("SELECT * FROM orders WHERE id = ? AND user_id = ?", (order_id, user_id)).fetchone())


def get_order_by_cart(cart_id: str, user_id: str) -> dict | None:
    with closing(_connect()) as conn:
        return _row(conn.execute("SELECT * FROM orders WHERE cart_id = ? AND user_id = ?", (cart_id, user_id)).fetchone())


def list_orders(user_id: str, limit: int = 5) -> list[dict]:
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, limit)).fetchall()
    return [_row(r) for r in rows]


# `items` is writable only so a refund (F23) can record each line's refund ID on the snapshot.
UPDATABLE = {"paypal_order_id", "approval_url", "capture_id", "refund_id", "status", "note", "items"}


def update_order(order_id: int, **fields) -> None:
    assert set(fields) <= UPDATABLE, fields  # column names come from code only, never from input
    sets = ", ".join(f"{k} = ?" for k in fields)
    values = [json.dumps(v) if k == "items" else v for k, v in fields.items()]  # stored as JSON, like create_order
    with closing(_connect()) as conn, conn:
        conn.execute(f"UPDATE orders SET {sets}, updated_at = ? WHERE id = ?", (*values, time.time(), order_id))
