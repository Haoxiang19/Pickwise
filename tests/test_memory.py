"""F18-F20 preference memory."""
import json

import pytest

from app import agent, checkout, memory, paypal_mock, store


# --- F18 write rules ---

def test_new_preference_starts_at_half_and_repeats_confirm():
    p = memory.remember("u1", "  Prefers   Sony headphones ")
    assert p["text"] == "Prefers Sony headphones" and p["strength"] == 0.5 and p["evidence_count"] == 1
    again = memory.remember("u1", "prefers sony headphones")  # same text, any case: a confirmation
    assert again["id"] == p["id"] and again["strength"] == 0.6 and again["evidence_count"] == 2


def test_confirm_and_contradict_by_id_with_clamping():
    p = memory.remember("u1", "Prefers wool")
    assert memory.remember("u1", "ignored", about_id=p["id"], stance="contradicts")["strength"] == 0.3
    for _ in range(10):
        p = memory.remember("u1", "x", about_id=p["id"], stance="supports")
    assert p["strength"] == 1.0  # clamped, and no float drift
    for _ in range(15):
        p = memory.remember("u1", "x", about_id=p["id"], stance="contradicts")
    assert p["strength"] == -1.0


def test_bad_input_is_refused():
    with pytest.raises(ValueError):
        memory.remember("u1", "   ")
    with pytest.raises(ValueError):
        memory.remember("u1", "x", stance="maybe")
    other = memory.remember("u2", "Prefers red")
    with pytest.raises(ValueError, match="no saved preference"):
        memory.remember("u1", "x", about_id=other["id"])  # another user's preference


def test_preferences_are_per_user_and_sorted_by_strength():
    weak = memory.remember("u1", "Dislikes plastic", stance="contradicts")
    strong = memory.remember("u1", "Prefers Sony")
    memory.remember("u2", "Prefers Bose")
    assert [p["id"] for p in memory.list_preferences("u1")] == [strong["id"], weak["id"]]
    assert weak["strength"] == -0.5
    assert "Bose" not in memory.prompt_block("u1") and f"[{strong['id']}] +0.50 Prefers Sony" in memory.prompt_block("u1")


def test_completed_purchase_supports_brand_preference():
    s = store.get_session("buyer")
    s.products["p1"] = {"id": "p1", "title": "Mat", "brand": "Gaiam", "price_cents": 2500, "in_stock": True, "currency": "USD"}
    for _ in range(2):
        cart = store.create_cart(s, "p1")
        order = checkout.confirm(s, "buyer", cart["id"], "http://t")
        paypal_mock.approve(order["paypal_order_id"])
        checkout.handle_return("buyer", order["id"])
    [pref] = memory.list_preferences("buyer")
    assert pref["text"] == "Likes the brand Gaiam" and pref["strength"] == 0.6 and pref["evidence_count"] == 2


def test_failed_payment_writes_no_memory():
    s = store.get_session("buyer")
    s.products["p1"] = {"id": "p1", "title": "Mat", "brand": "Gaiam", "price_cents": 2500, "in_stock": True, "currency": "USD"}
    order = checkout.confirm(s, "buyer", store.create_cart(s, "p1")["id"], "http://t")
    checkout.handle_return("buyer", order["id"])  # never approved -> CANCELLED
    assert memory.list_preferences("buyer") == []


# --- F18 through the agent (keyless mock) ---

def tool_calls(session):
    return [(c["function"]["name"], json.loads(c["function"]["arguments"]))
            for m in session.history for c in m.get("tool_calls") or []]


def test_stated_preference_is_saved_then_contradicted_by_id():
    s = store.get_session("u1")
    out = agent.handle_message(s, "I always buy Sony")
    assert out["memory_changed"] and "Prefers Sony" in out["reply"]
    [pref] = memory.list_preferences("u1")
    out = agent.handle_message(s, "I don't like Sony anymore")
    name, args = tool_calls(s)[-1]
    assert name == "remember_preference" and args["about_id"] == pref["id"] and args["stance"] == "contradicts"
    assert memory.list_preferences("u1")[0]["strength"] == 0.3


def test_system_prompt_lists_saved_preferences_with_ids():
    p = memory.remember("u9", "Prefers merino wool")
    prompt = agent.system_prompt("u9")
    assert f"[{p['id']}] +0.50 Prefers merino wool" in prompt and "never save health" in prompt
    assert "Saved preferences of this user: none." in agent.system_prompt("nobody")


def test_remember_tool_errors_go_back_to_the_model():
    s = store.get_session("u1")
    call = {"id": "c", "function": {"name": "remember_preference", "arguments": json.dumps({"text": "x", "about_id": 999})}}
    assert "no saved preference" in json.loads(agent.run_tool_call(s, call, {}))["error"]


# --- F19 use ---

def test_profile_is_top_three_positive():
    for text in ["A", "B", "C", "D"]:
        memory.remember("u1", f"Prefers {text}")
    memory.remember("u1", "Prefers D")  # D is strongest now
    memory.remember("u1", "Dislikes E", stance="contradicts")  # negative, never in the profile
    assert [p["text"] for p in memory.profile("u1")] == ["Prefers D", "Prefers A", "Prefers B"]


def test_memory_reaches_ranker_as_soft_preference_and_reason_names_it(monkeypatch):
    from app import recommend as rec
    seen = {}

    def fake_chat(messages, tools=None, temperature=0.0, mock=None):
        seen["user"] = messages[1]["content"]
        return {"role": "assistant", "content": '{"ranking": [{"id": "b", "reason": "Sony, as you like.", "memory": "m7"}, '
                                                '{"id": "a", "reason": "ok", "memory": "m999"}]}'}

    monkeypatch.setattr(rec.llm, "chat", fake_chat)
    products = [{"id": i, "title": f"Item {i}", "brand": "B", "price_cents": 1000, "currency": "USD", "in_stock": True,
                 "description": "", "url": "", "image": ""} for i in "abc"]
    request = rec.parse_request({"raw_request": "x", "budget_usd": 50})
    request["memory"] = [{"id": 7, "text": "Prefers Sony"}]
    flags = {"multi_query": True, "reasoning_rank": True, "rank_shuffles": 1, "use_memory": True}
    out = rec.recommend(request, flags, lambda q, limit: products, seed=1)
    assert "[m7] Prefers Sony" in seen["user"] and "current request wins" in seen["user"]
    first, second = out["recommendations"][:2]
    assert first["reason"] == 'Sony, as you like. Based on what I remember: "Prefers Sony".' and first["memory_used"] == "Prefers Sony"
    assert second["memory_used"] is None  # unknown memory ID ignored


def test_memory_off_hides_profile_and_never_affects_hard_filter(monkeypatch):
    from app import recommend as rec
    prompts = []

    def fake_chat(messages, tools=None, temperature=0.0, mock=None):
        prompts.append(messages[1]["content"])
        return {"role": "assistant", "content": '{"ranking": [{"id": "cheap"}]}'}

    monkeypatch.setattr(rec.llm, "chat", fake_chat)
    sony = {"id": "sony", "title": "Sony thing", "brand": "Sony", "price_cents": 9000, "currency": "USD", "in_stock": True,
            "description": "", "url": "", "image": ""}
    cheap = dict(sony, id="cheap", brand="Other", title="Other thing", price_cents=1000)
    request = rec.parse_request({"raw_request": "x", "budget_usd": 50})
    request["memory"] = [{"id": 1, "text": "Prefers Sony"}]
    on = rec.recommend(request, {"multi_query": True, "reasoning_rank": True, "use_memory": True}, lambda q, l: [sony, cheap], seed=1)
    assert [r["id"] for r in on["recommendations"]] == ["cheap"]
    assert on["rejected"][0]["id"] == "sony" and on["rejected"][0]["kind"] == "over_budget"  # memory cannot lift the budget
    rec.recommend(request, {"multi_query": True, "reasoning_rank": True, "use_memory": False}, lambda q, l: [sony, cheap], seed=1)
    assert "Remembered" in prompts[0] and "Remembered" not in prompts[1]


def test_new_conversation_uses_saved_preference_in_keyless_mode():
    s = store.get_session("u1")
    agent.handle_message(s, "I always buy Soundcore")
    assert s.memory_profile == []  # this conversation started before the preference existed
    s = store.new_conversation("u1")
    out = agent.handle_message(s, "noise cancelling headphones under $100")
    top = out["recommendations"][0]
    assert top["brand"] == "Soundcore" and top["memory_used"] == "Prefers Soundcore"
    assert 'Based on what I remember: "Prefers Soundcore"' in top["reason"]
    assert s.memory_profile and s.history[0]["content"] == "noise cancelling headphones under $100"


# --- F20 view and delete ---

def test_memory_endpoints_view_and_delete_own_entries_only():
    from fastapi.testclient import TestClient
    from app import main
    client = TestClient(main.app)
    client.post("/api/chat", json={"message": "I always buy Soundcore"})
    [entry] = client.get("/api/memory").json()
    assert entry["text"] == "Prefers Soundcore" and entry["strength"] == 0.5
    other = TestClient(main.app)
    assert other.get("/api/memory").json() == []
    assert other.delete(f"/api/memory/{entry['id']}").status_code == 404  # not theirs
    assert client.delete(f"/api/memory/{entry['id']}").json() == {"ok": True}
    assert client.get("/api/memory").json() == []
    assert client.delete(f"/api/memory/{entry['id']}").status_code == 404


def test_deleted_memory_stops_applying_to_current_conversation():
    from fastapi.testclient import TestClient
    from app import main
    client = TestClient(main.app)
    client.post("/api/chat", json={"message": "I always buy Soundcore"})
    client.post("/api/conversation/new")
    pref_id = client.get("/api/memory").json()[0]["id"]
    first = client.post("/api/chat", json={"message": "noise cancelling headphones under $100"}).json()
    assert first["recommendations"][0]["memory_used"] == "Prefers Soundcore"
    client.delete(f"/api/memory/{pref_id}")
    again = client.post("/api/chat", json={"message": "also no JBL"}).json()
    assert all(r["memory_used"] is None for r in again["recommendations"])
