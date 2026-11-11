import pytest
from fastapi.testclient import TestClient

from app import main, store


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("CHANNEL3_API_KEY", raising=False)
    store.sessions.clear()
    return TestClient(main.app)


def test_cookie_is_set_httponly_and_reused(client):
    r = client.get("/api/status")
    cookie = r.headers["set-cookie"]
    assert "uid=" in cookie and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
    assert r.json()["mock_llm"] is True
    assert "set-cookie" not in client.get("/api/status").headers  # cookie kept by the client


def test_chat_flow_in_mock_mode(client):
    assert "budget" in client.post("/api/chat", json={"message": "a yoga mat"}).json()["reply"].lower()
    data = client.post("/api/chat", json={"message": "$130"}).json()
    assert len(data["recommendations"]) == 3
    assert all(r["price_cents"] <= 13000 for r in data["recommendations"])


def test_sessions_are_per_user(client):
    client.post("/api/chat", json={"message": "a yoga mat"})
    other = TestClient(main.app)
    # A different browser has no pending budget question, so "$130" alone is a new request.
    assert "budget" in other.post("/api/chat", json={"message": "hello"}).json()["reply"].lower()
    assert len(store.sessions) == 2


def test_index_served(client):
    assert "Shopping Agent" in client.get("/").text


def test_cart_endpoint_uses_session_products_only(client):
    data = client.post("/api/chat", json={"message": "noise cancelling headphones under $100"}).json()
    rec = data["recommendations"][0]
    cart = client.post("/api/cart", json={"product_id": rec["id"], "quantity": 1}).json()
    assert cart["total_cents"] == rec["price_cents"]
    # Another user's browser cannot use products found in this session.
    other = TestClient(main.app)
    r = other.post("/api/cart", json={"product_id": rec["id"]})
    assert r.status_code == 400 and "Unknown product" in r.json()["detail"]


def start_checkout(client):
    data = client.post("/api/chat", json={"message": "noise cancelling headphones under $100"}).json()
    rec = data["recommendations"][0]
    cart = client.post("/api/cart", json={"product_id": rec["id"]}).json()
    confirm = client.post("/api/confirm", json={"cart_id": cart["cart_id"]}).json()
    return rec, confirm


def test_full_purchase_flow_in_mock_mode(client):
    rec, confirm = start_checkout(client)
    assert "Mock PayPal" in client.get(confirm["approve_url"]).text
    token = confirm["approve_url"].split("token=")[1]
    # A PayPal order ID in the query string is ignored; the server uses the one stored on the order row.
    r = client.post("/mock-paypal/approve", content=f"token={token}",
                    headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    assert r.headers["location"].endswith(f"/paypal/return?order_id={confirm['order_id']}&token={token}&PayerID=MOCKPAYER")
    r = client.get(r.headers["location"].replace(token, "FORGED-ID"), follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/?order_id={confirm['order_id']}"
    order = client.get(f"/api/orders/{confirm['order_id']}").json()
    assert order["status"] == "COMPLETED" and order["amount_cents"] == rec["price_cents"]
    assert order["message"] == "Payment successful." and order["paypal_order_id"] == token


def test_cancel_flow_and_privacy(client):
    _, confirm = start_checkout(client)
    client.get(f"/paypal/cancel?order_id={confirm['order_id']}")
    order = client.get(f"/api/orders/{confirm['order_id']}").json()
    assert order["status"] == "CANCELLED" and "Nothing was charged" in order["message"]
    other = TestClient(main.app)
    assert other.get(f"/api/orders/{confirm['order_id']}").status_code == 404
    assert other.get(f"/paypal/return?order_id={confirm['order_id']}", follow_redirects=False).status_code == 404
