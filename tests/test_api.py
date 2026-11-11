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
