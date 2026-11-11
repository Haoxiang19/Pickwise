import pytest

from app import store


def session_with(products, budget=None):
    s = store.Session(budget_cents=budget)
    for p in products:
        s.products[p["id"]] = p
    return s


def product(pid="p1", price=2500, in_stock=True, currency="USD"):
    return {"id": pid, "title": f"Item {pid}", "price_cents": price, "in_stock": in_stock, "currency": currency}


def test_cart_total_in_integer_cents():
    cart = store.create_cart(session_with([product(price=1999)]), "p1", 3, now=0)
    assert cart["total_cents"] == 5997 and isinstance(cart["total_cents"], int)
    assert cart["items"][0]["unit_price_cents"] == 1999 and cart["expires_at"] == store.CART_TTL_SECONDS


@pytest.mark.parametrize("pid,qty,msg", [("nope", 1, "Unknown product"), ("p1", 0, "Quantity"), ("p1", 11, "Quantity"), ("p1", "2", "Quantity")])
def test_cart_rejects_bad_input(pid, qty, msg):
    with pytest.raises(store.CartError, match=msg):
        store.create_cart(session_with([product()]), pid, qty)


def test_cart_rejects_unavailable_products():
    s = session_with([product("a", in_stock=False), product("b", price=None), product("c", currency="EUR")])
    for pid in "abc":
        with pytest.raises(store.CartError, match="not available"):
            store.create_cart(s, pid)


def test_budget_check_on_total():
    s = session_with([product(price=4000)], budget=10000)
    assert store.create_cart(s, "p1", 2)["total_cents"] == 8000
    with pytest.raises(store.CartError, match=r"over your budget of \$100.00"):
        store.create_cart(s, "p1", 3)
    s.budget_cents = None  # "no limit": check skipped
    assert store.create_cart(s, "p1", 10)["total_cents"] == 40000


def test_cart_expires_after_15_minutes():
    s = session_with([product()])
    cart = store.create_cart(s, "p1", now=1000)
    assert store.get_valid_cart(s, cart["id"], now=1000 + 15 * 60) is cart
    with pytest.raises(store.CartError, match="expired"):
        store.get_valid_cart(s, cart["id"], now=1000 + 15 * 60 + 1)
    with pytest.raises(store.CartError, match="Unknown cart"):
        store.get_valid_cart(store.Session(), cart["id"])
