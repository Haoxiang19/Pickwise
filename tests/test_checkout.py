import pytest

from app import checkout, paypal, paypal_mock, store

BASE = "http://test"


def session_with_cart(price=2500, quantity=1):
    s = store.Session()
    s.products["p1"] = {"id": "p1", "title": "Mat", "price_cents": price, "in_stock": True, "currency": "USD"}
    return s, store.create_cart(s, "p1", quantity)


# --- F9, F10 Confirm ---

def test_confirm_creates_row_then_paypal_order():
    s, cart = session_with_cart(price=1999, quantity=2)
    order = checkout.confirm(s, "u1", cart["id"], BASE)
    assert order["status"] == "CREATED" and order["amount_cents"] == 3998 and order["currency"] == "USD"
    assert order["items"] == cart["items"] and order["cart_id"] == cart["id"]
    pp = paypal_mock.orders[order["paypal_order_id"]]
    assert pp["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "39.98"}
    assert paypal_mock.urls[pp["id"]] == {"return_url": f"{BASE}/paypal/return?order_id={order['id']}",
                                         "cancel_url": f"{BASE}/paypal/cancel?order_id={order['id']}"}
    assert f"create-{cart['id']}" in paypal_mock.responses
    assert order["approval_url"].startswith("/mock-paypal/checkout?token=")


def test_second_confirm_returns_same_order_and_link():
    s, cart = session_with_cart()
    first = checkout.confirm(s, "u1", cart["id"], BASE)
    second = checkout.confirm(s, "u1", cart["id"], BASE)
    assert second["id"] == first["id"] and second["approval_url"] == first["approval_url"]
    assert len(paypal_mock.orders) == 1 and len(store.list_orders("u1")) == 1


def test_expired_or_foreign_cart_is_refused():
    s, cart = session_with_cart()
    cart["expires_at"] = 0
    with pytest.raises(store.CartError, match="expired"):
        checkout.confirm(s, "u1", cart["id"], BASE)
    with pytest.raises(store.CartError, match="Unknown cart"):
        checkout.confirm(store.Session(), "u2", cart["id"], BASE)
    assert store.list_orders("u1") == []


def test_paypal_create_failure_keeps_row_and_retry_uses_same_request_id(monkeypatch):
    s, cart = session_with_cart()
    seen = []

    def failing(*args, request_id, **kwargs):
        seen.append(request_id)
        raise paypal.PayPalError("NETWORK_ERROR")

    monkeypatch.setattr(checkout.paypal, "create_order", failing)
    for _ in range(2):
        with pytest.raises(checkout.CheckoutError, match="Nothing was charged"):
            checkout.confirm(s, "u1", cart["id"], BASE)
    [row] = store.list_orders("u1")
    assert row["status"] == "CREATED" and row["paypal_order_id"] is None
    assert seen == [f"create-{cart['id']}"] * 2


def test_confirm_refused_when_order_no_longer_created():
    s, cart = session_with_cart()
    order = checkout.confirm(s, "u1", cart["id"], BASE)
    store.update_order(order["id"], status="CANCELLED")
    with pytest.raises(checkout.CheckoutError, match="choose the product again"):
        checkout.confirm(s, "u1", cart["id"], BASE)


def test_orders_are_private_to_their_user():
    s, cart = session_with_cart()
    order = checkout.confirm(s, "u1", cart["id"], BASE)
    assert store.get_order(order["id"], "u2") is None
    assert store.get_order_by_cart(cart["id"], "u2") is None
