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
