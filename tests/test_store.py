import pytest

from app import catalog, store


def session_with(products, budget=None):
    s = store.Session(budget_cents=budget)
    for p in products:
        s.products[p["id"]] = p
    return s


def product(pid="p1", price=2500, in_stock=True, currency="USD"):
    return {"id": pid, "title": f"Item {pid}", "price_cents": price, "in_stock": in_stock, "currency": currency}


def cart(session, pid="p1", quantity=1, now=None):
    """create_cart with a stand-in for the catalog read-back: the catalog still says the same thing."""
    return store.create_cart(session, pid, quantity, now=now, fetch=session.products.get)


def test_cart_total_in_integer_cents():
    c = cart(session_with([product(price=1999)]), quantity=3, now=0)
    assert c["total_cents"] == 5997 and isinstance(c["total_cents"], int)
    assert c["items"][0]["unit_price_cents"] == 1999 and c["expires_at"] == store.CART_TTL_SECONDS


@pytest.mark.parametrize("pid,qty,msg", [("nope", 1, "Unknown product"), ("p1", 0, "Quantity"), ("p1", 11, "Quantity"), ("p1", "2", "Quantity")])
def test_cart_rejects_bad_input(pid, qty, msg):
    with pytest.raises(store.CartError, match=msg):
        cart(session_with([product()]), pid, qty)


def test_cart_rejects_unavailable_products():
    s = session_with([product("a", in_stock=False), product("b", price=None), product("c", currency="EUR")])
    for pid in "abc":
        with pytest.raises(store.CartError, match="not available"):
            cart(s, pid)


def test_budget_check_on_total():
    s = session_with([product(price=4000)], budget=10000)
    assert cart(s, quantity=2)["total_cents"] == 8000
    with pytest.raises(store.CartError, match=r"over your budget of \$100.00"):
        cart(s, quantity=3)
    s.budget_cents = None  # "no limit": check skipped
    assert cart(s, quantity=10)["total_cents"] == 40000


def test_cart_expires_after_15_minutes():
    s = session_with([product()])
    c = cart(s, now=1000)
    assert store.get_valid_cart(s, c["id"], now=1000 + 15 * 60) is c
    with pytest.raises(store.CartError, match="expired"):
        store.get_valid_cart(s, c["id"], now=1000 + 15 * 60 + 1)
    with pytest.raises(store.CartError, match="Unknown cart"):
        store.get_valid_cart(store.Session(), c["id"])


# --- The catalog read-back before a cart is priced ---

def test_cart_uses_the_refreshed_price_not_the_stored_one():
    s = session_with([product(price=2500)])
    fresh = product(price=3000)
    c = store.create_cart(s, "p1", 2, fetch=lambda pid: fresh)
    assert c["total_cents"] == 6000 and c["items"][0]["unit_price_cents"] == 3000
    assert c["price_was_cents"] == 2500          # so the page can say the price moved
    assert s.products["p1"]["price_cents"] == 3000  # the session now holds the fresh product


def test_unchanged_price_is_not_reported_as_a_change():
    s = session_with([product(price=2500)])
    assert "price_was_cents" not in cart(s)


def test_product_that_went_out_of_stock_or_over_budget_is_refused():
    s = session_with([product(price=2500)], budget=3000)
    with pytest.raises(store.CartError, match="not available"):
        store.create_cart(s, "p1", fetch=lambda pid: product(price=2500, in_stock=False))
    with pytest.raises(store.CartError, match="over your budget"):
        store.create_cart(s, "p1", fetch=lambda pid: product(price=3500))
    assert s.carts == {}


def test_product_that_disappeared_is_refused():
    s = session_with([product()])
    with pytest.raises(store.CartError, match="no longer available"):
        store.create_cart(s, "p1", fetch=lambda pid: None)


def test_catalog_failure_refuses_the_cart_instead_of_charging_a_stale_price():
    s = session_with([product()])

    def down(pid):
        raise catalog.CatalogError("search failed: HTTP 503")

    with pytest.raises(store.CartError, match="Could not check the current price"):
        store.create_cart(s, "p1", fetch=down)
    assert s.carts == {}


def test_default_fetch_reads_the_catalog(monkeypatch):
    s = session_with([product()])
    seen = []
    monkeypatch.setattr(store.catalog, "get_product", lambda pid: seen.append(pid) or product(price=1234))
    assert store.create_cart(s, "p1")["total_cents"] == 1234
    assert seen == ["p1"]
