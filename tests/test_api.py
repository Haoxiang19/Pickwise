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


def test_refund_endpoint_after_purchase(client):
    rec, confirm = start_checkout(client)
    token = confirm["approve_url"].split("token=")[1]
    client.post("/mock-paypal/approve", content=f"token={token}", headers={"Content-Type": "application/x-www-form-urlencoded"})
    draft = client.post("/api/chat", json={"message": f"refund order {confirm['order_id']}"}).json()["refund_draft"]
    assert draft["amount_cents"] == rec["price_cents"]
    assert TestClient(main.app).post(f"/api/orders/{confirm['order_id']}/refund").status_code == 400  # not the owner
    done = client.post(f"/api/orders/{confirm['order_id']}/refund").json()
    assert done["status"] == "REFUNDED"
    again = client.post(f"/api/orders/{confirm['order_id']}/refund")
    assert again.status_code == 400 and "already refunded" in again.json()["detail"]


def test_page_states_concierge_simulation_and_trust_cues(client):
    page = client.get("/").text
    assert "concierge-style simulation" in page and "no real money moves" in page
    assert "Nothing is charged until you approve the payment on PayPal." in page
    assert "Confirm and pay with PayPal" in page and "Ruled out" in page and "Mock PayPal" in page


# --- F21 multi-item cart ---

def test_cart_endpoint_with_items_and_field_rules(client):
    recs = client.post("/api/chat", json={"message": "noise cancelling headphones under $1000"}).json()["recommendations"]
    cart = client.post("/api/cart", json={"items": [{"product_id": recs[0]["id"], "quantity": 2},
                                                    {"product_id": recs[1]["id"]}]}).json()
    assert cart["total_cents"] == recs[0]["price_cents"] * 2 + recs[1]["price_cents"]
    assert [i["quantity"] for i in cart["items"]] == [2, 1]
    both = client.post("/api/cart", json={"product_id": recs[0]["id"], "items": [{"product_id": recs[1]["id"]}]})
    neither = client.post("/api/cart", json={"quantity": 1})
    assert both.status_code == 400 and neither.status_code == 400


def test_full_mock_purchase_of_a_two_item_cart(client):
    recs = client.post("/api/chat", json={"message": "noise cancelling headphones under $1000"}).json()["recommendations"]
    cart = client.post("/api/cart", json={"items": [{"product_id": recs[0]["id"], "quantity": 2}, {"product_id": recs[1]["id"]}]}).json()
    confirm = client.post("/api/confirm", json={"cart_id": cart["cart_id"]}).json()
    token = confirm["approve_url"].split("token=")[1]
    r = client.post("/mock-paypal/approve", content=f"token={token}",
                    headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    client.get(r.headers["location"], follow_redirects=False)
    order = client.get(f"/api/orders/{confirm['order_id']}").json()
    assert order["status"] == "COMPLETED"
    assert order["amount_cents"] == recs[0]["price_cents"] * 2 + recs[1]["price_cents"]
    assert [(i["title"], i["quantity"]) for i in order["items"]] == [(recs[0]["title"], 2), (recs[1]["title"], 1)]


def test_order_list_shows_only_this_users_orders(client):
    recs = client.post("/api/chat", json={"message": "noise cancelling headphones under $1000"}).json()["recommendations"]
    cart = client.post("/api/cart", json={"product_id": recs[0]["id"]}).json()
    order_id = client.post("/api/confirm", json={"cart_id": cart["cart_id"]}).json()["order_id"]
    mine = client.get("/api/orders").json()
    assert mine[0]["order_id"] == order_id and mine[0]["amount_cents"] == recs[0]["price_cents"]
    stranger = TestClient(main.app)  # no cookie: a different user
    assert all(o["order_id"] != order_id for o in stranger.get("/api/orders").json())


# --- F22 set recommendation ---

def test_set_request_review_swap_confirm_and_pay(client):
    data = client.post("/api/chat", json={"message": "a tent, a sleeping bag and a lantern under $500"}).json()
    groups = data["bundle"]["items"]
    assert [g["name"] for g in groups] == ["tent", "sleeping bag", "lantern"]
    # The user swaps the lantern for an alternative, as the page's radio buttons do.
    picks = [g["chosen"] for g in groups[:2]] + [groups[2]["alternatives"][0]]
    cart = client.post("/api/cart", json={"items": [{"product_id": p["id"], "quantity": 1} for p in picks]}).json()
    assert cart["total_cents"] == sum(p["price_cents"] for p in picks)
    confirm = client.post("/api/confirm", json={"cart_id": cart["cart_id"]}).json()
    token = confirm["approve_url"].split("token=")[1]
    r = client.post("/mock-paypal/approve", content=f"token={token}",
                    headers={"Content-Type": "application/x-www-form-urlencoded"}, follow_redirects=False)
    client.get(r.headers["location"], follow_redirects=False)
    order = client.get(f"/api/orders/{confirm['order_id']}").json()
    assert order["status"] == "COMPLETED" and order["amount_cents"] == cart["total_cents"]
    assert [i["title"] for i in order["items"]] == [p["title"] for p in picks]


def test_refund_endpoint_with_and_without_lines(client):
    data = client.post("/api/chat", json={"message": "a tent, a sleeping bag and a lantern under $500"}).json()
    picks = [g["chosen"] for g in data["bundle"]["items"]]
    cart = client.post("/api/cart", json={"items": [{"product_id": p["id"]} for p in picks]}).json()
    confirm = client.post("/api/confirm", json={"cart_id": cart["cart_id"]}).json()
    token = confirm["approve_url"].split("token=")[1]
    client.post("/mock-paypal/approve", content=f"token={token}", headers={"Content-Type": "application/x-www-form-urlencoded"})
    oid = confirm["order_id"]
    draft = client.post("/api/chat", json={"message": f"refund item 2 of order {oid}"}).json()["refund_draft"]
    assert [l["line"] for l in draft["lines"]] == [2] and draft["amount_cents"] == picks[1]["price_cents"]
    part = client.post(f"/api/orders/{oid}/refund", json={"lines": [2]}).json()
    assert part["status"] == "PARTIALLY_REFUNDED" and part["refunded_cents"] == picks[1]["price_cents"]
    assert [i["refunded"] for i in part["items"]] == [False, True, False]
    rest = client.post(f"/api/orders/{oid}/refund").json()  # no body: every line not refunded yet
    assert rest["status"] == "REFUNDED" and rest["refunded_cents"] == rest["amount_cents"]


def test_set_over_the_budget_is_refused_by_the_server(client):
    data = client.post("/api/chat", json={"message": "a tent, a sleeping bag and a lantern under $180"}).json()
    groups = data["bundle"]["items"]
    # Rank 1 of every item costs $189.93 together, over the $180 budget.
    rank1 = [g["chosen"] if "Chosen over" not in g["chosen"]["reason"] else g["alternatives"][0] for g in groups]
    r = client.post("/api/cart", json={"items": [{"product_id": p["id"]} for p in rank1]})
    assert r.status_code == 400 and "over your budget of $180.00" in r.json()["detail"]


# --- Agent progress shown while the page waits ---

def test_progress_endpoint_is_empty_when_idle_and_per_user(client):
    assert client.get("/api/progress").json() == {"step": ""}
    store.get_session(client.cookies["uid"]).progress = "Searching the catalog: tents"
    assert client.get("/api/progress").json() == {"step": "Searching the catalog: tents"}
    assert TestClient(main.app).get("/api/progress").json() == {"step": ""}  # another browser sees nothing


def test_page_offers_entry_points_and_keeps_refund_cues(client):
    page = client.get("/").text
    for text in ("A smart mug, a notebook and a candle under $200", "Remember that I prefer balsam and cedar scents", "/api/orders", "Refund this item",
                 "Nothing is refunded until you click Confirm refund.", "nothing ships", "/api/progress"):
        assert text in page
    # Product text and images never go through innerHTML.
    assert "innerHTML" not in page
    # A9: the conversation is kept in the browser as the server's answers and cleared by New conversation.
    assert 'localStorage.setItem(SAVED_CHAT' in page and 'localStorage.removeItem(SAVED_CHAT)' in page
