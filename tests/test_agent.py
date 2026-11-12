import json

import pytest

from app import agent, mock_agent
from app.store import Session


@pytest.fixture(autouse=True)
def keyless(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("CHANNEL3_API_KEY", raising=False)


def scripted(monkeypatch, replies):
    """Make the agent's model calls (those with tools) return the given messages; ranking keeps its mock."""
    it = iter(replies)
    monkeypatch.setattr(agent.llm, "chat", lambda messages, tools=None, temperature=0.0, mock=None:
                        next(it) if tools else mock(messages))


def call(name, args, cid="c1"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": args if isinstance(args, str) else json.dumps(args)}}


# --- F2 in keyless mode (rule-based mock) ---

def test_asks_for_budget_once_and_does_not_search():
    s = Session()
    out = agent.handle_message(s, "I need running shoes")
    assert out["reply"] == mock_agent.BUDGET_QUESTION
    assert "recommendations" not in out and s.products == {}


def test_budget_answer_triggers_search_with_earlier_request():
    s = Session()
    agent.handle_message(s, "I need running shoes")
    out = agent.handle_message(s, "$100")
    assert len(out["recommendations"]) == 3
    assert all(r["price_cents"] <= 10000 for r in out["recommendations"])
    assert s.budget_cents == 10000


def test_budget_in_first_message_searches_directly():
    out = agent.handle_message(Session(), "noise cancelling headphones under $100, no JBL")
    assert len(out["recommendations"]) == 3
    assert all(r["brand"] != "JBL" for r in out["recommendations"])
    assert any(x["kind"] == "over_budget" for x in out["rejected"])


def test_no_limit_answer_skips_budget_and_does_not_ask_again():
    s = Session()
    agent.handle_message(s, "a coffee maker")
    out = agent.handle_message(s, "no limit")
    assert out["recommendations"] and s.budget_cents is None
    assert not any(x["kind"] == "over_budget" for x in out["rejected"])


def test_mock_parses_request_into_fields():
    args = mock_agent.build_request("headphones and a backpack under $80, no leather", 80.0)
    assert args["budget_usd"] == 80.0 and args["must_not"] == ["leather"]
    assert args["queries"][:2] == ["headphones", "a backpack under"]


# --- Loop rules, with a scripted model ---

def test_assistant_message_appended_unchanged_and_tool_result_follows(monkeypatch):
    first = {"role": "assistant", "content": None, "reasoning_content": "thinking...",
             "tool_calls": [call("recommend", {"raw_request": "tent", "budget_usd": 500, "queries": ["camping tent"]})]}
    scripted(monkeypatch, [first, {"role": "assistant", "content": "Here you go."}])
    s = Session()
    out = agent.handle_message(s, "tent")
    assert out["reply"] == "Here you go." and out["recommendations"]
    assert s.history[1] is first
    assert s.history[2]["role"] == "tool" and s.history[2]["tool_call_id"] == "c1"
    assert "Coleman" in s.history[2]["content"]


def test_unknown_tool_and_bad_arguments_are_returned_to_model(monkeypatch):
    bad = {"role": "assistant", "content": None, "tool_calls": [call("pay_now", {}, "c1"), call("recommend", "{not json", "c2")]}
    scripted(monkeypatch, [bad, {"role": "assistant", "content": "Sorry."}])
    s = Session()
    assert agent.handle_message(s, "x")["reply"] == "Sorry."
    tool_msgs = [m for m in s.history if m["role"] == "tool"]
    assert "unknown tool: pay_now" in tool_msgs[0]["content"]
    assert "error" in json.loads(tool_msgs[1]["content"])


def test_tool_round_limit_gives_fixed_reply_and_valid_history(monkeypatch):
    looping = {"role": "assistant", "content": None, "tool_calls": [call("nope", {})]}
    scripted(monkeypatch, [looping] * 10)
    s = Session()
    out = agent.handle_message(s, "x")
    assert out["reply"] == agent.LIMIT_REPLY
    assert sum(1 for m in s.history if m["role"] == "tool") == agent.MAX_TOOL_ROUNDS
    assert s.history[-1] == {"role": "assistant", "content": agent.LIMIT_REPLY}


def test_blank_reply_retried_once_then_fallback(monkeypatch):
    scripted(monkeypatch, [{"role": "assistant", "content": "  "}, {"role": "assistant", "content": "ok"}])
    assert agent.handle_message(Session(), "x")["reply"] == "ok"
    scripted(monkeypatch, [{"role": "assistant", "content": ""}] * 2)
    s = Session()
    assert agent.handle_message(s, "x")["reply"] == agent.FALLBACK_REPLY
    assert s.history[-1]["role"] == "assistant"


def test_tool_calls_and_exclusions_are_logged(caplog):
    caplog.set_level("INFO")
    agent.handle_message(Session(), "noise cancelling headphones under $100, no JBL")
    assert any(r.getMessage().startswith("tool recommend ") and '"must_not": ["jbl"]' in r.getMessage() for r in caplog.records)
    assert any(r.getMessage().startswith("recommend ") and '"must_not": ["jbl"]' in r.getMessage() and '"budget": 10000' in r.getMessage()
               for r in caplog.records)


def test_model_has_no_money_tools():
    names = {t["function"]["name"] for t in agent.TOOLS}
    assert not names & {"create_order", "capture", "refund", "pay"}


# --- F8 cart through the agent ---

def test_pick_prepares_cart_priced_by_server():
    s = Session()
    out = agent.handle_message(s, "noise cancelling headphones under $100")
    second = out["recommendations"][1]
    out = agent.handle_message(s, "I'll take the second one")
    assert out["cart"]["items"][0]["title"] == second["title"] and len(out["cart"]["items"]) == 1
    assert out["cart"]["total_cents"] == second["price_cents"] and out["cart"]["items"][0]["quantity"] == 1


def test_prepare_cart_ignores_model_price_and_rejects_unknown_id():
    s = Session()
    agent.handle_message(s, "noise cancelling headphones under $100")
    pid = next(iter(s.products))
    ui = {}
    result = json.loads(agent.run_tool_call(s, call("prepare_cart", {"product_id": pid, "price": 0.01}), ui))
    assert ui["cart"]["items"][0]["unit_price_cents"] == s.products[pid]["price_cents"] != 1
    result = json.loads(agent.run_tool_call(s, call("prepare_cart", {"product_id": "made-up"}), {}))
    assert "Unknown product" in result["error"]


# --- F7 refine ---

def test_cheaper_keeps_earlier_conditions_and_lowers_budget():
    s = Session()
    first = agent.handle_message(s, "noise cancelling headphones under $100, no JBL")
    out = agent.handle_message(s, "cheaper please")
    assert s.budget_cents == 8000
    assert all(r["price_cents"] <= 8000 and r["brand"] != "JBL" for r in out["recommendations"])
    calls = [json.loads(c["function"]["arguments"]) for m in s.history for c in m.get("tool_calls") or []]
    assert calls[-1]["must_not"] == ["jbl"] and calls[-1]["queries"] == calls[0]["queries"]
    assert first["recommendations"] != out["recommendations"]


def test_different_brand_excludes_shown_brands():
    s = Session()
    first = agent.handle_message(s, "running shoes under $150")
    shown_brands = {r["brand"] for r in first["recommendations"]}
    out = agent.handle_message(s, "show me a different brand")
    assert out["recommendations"]
    assert not shown_brands & {r["brand"] for r in out["recommendations"]}
    assert s.budget_cents == 15000  # earlier budget kept


def test_follow_up_exclusion_is_added_to_earlier_ones():
    s = Session()
    agent.handle_message(s, "a backpack under $130, no leather")
    agent.handle_message(s, "also no Osprey")
    args = [json.loads(c["function"]["arguments"]) for m in s.history for c in m.get("tool_calls") or []][-1]
    assert args["must_not"] == ["leather", "osprey"] and args["budget_usd"] == 130


def test_refine_rule_is_in_system_prompt():
    assert "keep every earlier condition" in agent.SYSTEM_PROMPT


# --- F15 order status ---

def paid_order(s):
    from app import checkout, paypal_mock
    out = agent.handle_message(s, "noise cancelling headphones under $100")
    cart = agent.handle_message(s, "take the first")["cart"]
    order = checkout.confirm(s, s.user_id, cart["cart_id"], "http://t")
    paypal_mock.approve(order["paypal_order_id"])
    return checkout.handle_return(s.user_id, order["id"]), out["recommendations"][0]


def test_order_status_returns_id_status_and_amount():
    from app import store
    s = store.get_session("u1")
    order, rec = paid_order(s)
    out = agent.handle_message(s, f"what is the status of order #{order['id']}?")
    [view] = out["orders"]
    assert view["order_id"] == order["id"] and view["status"] == "COMPLETED" and view["amount_cents"] == rec["price_cents"]
    assert f"#{order['id']} COMPLETED" in out["reply"]
    assert agent.handle_message(s, "show my orders")["orders"][0]["order_id"] == order["id"]


def test_order_status_hides_other_users_orders():
    from app import store
    owner = store.get_session("owner")
    order, _ = paid_order(owner)
    other = store.get_session("other")
    out = agent.handle_message(other, f"status of order {order['id']}")
    assert out["orders"] == [] and "could not find" in out["reply"]


# --- F16 refund through the agent: draft only ---

def test_refund_request_only_drafts(monkeypatch):
    from app import checkout, store
    s = store.get_session("u1")
    order, _ = paid_order(s)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("the agent must not refund")

    monkeypatch.setattr(checkout.paypal, "refund_capture", fail_if_called)
    out = agent.handle_message(s, f"I want a refund for order {order['id']}")
    assert out["refund_draft"]["order_id"] == order["id"] and "Confirm refund" in out["reply"]
    assert store.get_order(order["id"], "u1")["status"] == "COMPLETED"
    assert "draft_refund" in {t["function"]["name"] for t in agent.TOOLS}
    assert "refund" not in agent.TOOL_FUNCTIONS
    # F23: a line refund is also only a draft.
    out = agent.handle_message(s, f"refund item 1 of order {order['id']}")
    assert [l["line"] for l in out["refund_draft"]["lines"]] == [1]
    assert store.get_order(order["id"], "u1")["status"] == "COMPLETED"


# --- What the user did on the page reaches the model through the system prompt ---

def test_prompt_is_unchanged_for_a_user_with_no_orders_and_no_cart():
    from app import store
    s = store.get_session("fresh")
    assert agent.activity_block(s) == ""
    assert agent.system_prompt("fresh", s) == agent.system_prompt("fresh")  # the eval's step 1 sees the same prompt


def test_prompt_shows_own_orders_with_lines_and_refunds_most_recent_first():
    from app import checkout, store
    s = store.get_session("u1")
    order, rec = paid_order(s)
    paid_order(store.get_session("someone-else"))
    block = agent.activity_block(s)
    assert f"Order #{order['id']} COMPLETED" in block and f"line 1: 1 x {rec['title'][:60]}" in block
    assert block.count("Order #") == 1  # another user's order is not shown
    checkout.refund("u1", order["id"], [1])
    assert f"Order #{order['id']} REFUNDED" in agent.activity_block(s) and "(refunded)" in agent.activity_block(s)
    assert "do not guess" in block and "untrusted" in block
    assert agent.activity_block(s) in agent.system_prompt("u1", s)


def test_prompt_shows_the_unpaid_summary_until_it_becomes_an_order():
    from app import checkout, store
    s = store.get_session("u1")
    agent.handle_message(s, "noise cancelling headphones under $100")
    pid = next(iter(s.products))
    s.products[pid]["title"] = "T" * 200  # a long seller title is cut
    cart = store.create_cart(s, pid, fetch=s.products.get)
    block = agent.activity_block(s)
    assert "Open order summary, not paid: 1 x " + "T" * 60 + "," in block and "Order #" not in block
    checkout.confirm(s, "u1", cart["id"], "http://t")
    block = agent.activity_block(s)
    assert "Open order summary" not in block and "CREATED" in block
    cart["expires_at"] = 0
    assert "Open order summary" not in agent.activity_block(s)


def test_get_orders_shows_line_numbers_and_refunded_lines():
    from app import checkout, store
    s = store.get_session("u1")
    order, _ = paid_order(s)
    checkout.refund("u1", order["id"], [1])
    result = json.loads(agent.run_tool_call(s, call("get_orders", {"order_id": order["id"]}), {}))
    assert result["orders"][0]["items"][0]["line"] == 1 and result["orders"][0]["items"][0]["refunded"] is True
    bad = json.loads(agent.run_tool_call(s, call("draft_refund", {"order_id": order["id"], "lines": "all"}), {}))
    assert "error" in bad


def test_approximate_budget_reaches_the_cart_check_too():
    """One limit everywhere: the widened budget also decides what can be ordered."""
    from app import store
    s = store.get_session("u1")
    out = agent.handle_message(s, "noise cancelling headphones around $70")
    assert s.budget_cents == 8400  # $70 + 20%
    assert "up to $84.00" in out["budget_note"]
    over = max(out["recommendations"], key=lambda r: r["price_cents"])
    assert 7000 < over["price_cents"] <= 8400  # a product the strict reading would have refused
    assert "cart" in agent.handle_message(s, f"buy the first")


# --- F21 multi-item cart through the agent ---

def test_prepare_cart_with_items_sums_server_prices_and_notes_each_item():
    s = Session()
    agent.handle_message(s, "noise cancelling headphones under $1000")
    a, b = list(s.products)[:2]
    ui = {}
    result = json.loads(agent.run_tool_call(s, call("prepare_cart", {"items": [
        {"product_id": a, "quantity": 2, "price": 1}, {"product_id": b}]}), ui))
    expected = s.products[a]["price_cents"] * 2 + s.products[b]["price_cents"]
    assert ui["cart"]["total_cents"] == expected
    assert [i["quantity"] for i in result["items"]] == [2, 1]
    assert result["total"] == "$" + agent.to_dollars(expected)


def test_prepare_cart_items_with_an_invented_id_is_an_error():
    s = Session()
    agent.handle_message(s, "noise cancelling headphones under $1000")
    pid = next(iter(s.products))
    result = json.loads(agent.run_tool_call(s, call("prepare_cart", {"items": [{"product_id": pid}, {"product_id": "made-up"}]}), {}))
    assert "Unknown product" in result["error"] and s.carts == {}


# --- F22 set recommendation through the agent ---

SET_REQUEST = "a tent, a sleeping bag and a lantern under $500"


def test_bundle_tool_stores_searched_products_and_the_total_budget():
    s = Session()
    ui = {}
    result = json.loads(agent.run_tool_call(s, call("recommend_bundle", {
        "raw_request": "camping set", "budget_usd": 300,
        "items": [{"name": "tent", "queries": ["tent"]}, {"name": "lantern", "queries": ["lantern"]}]}), ui))
    assert s.budget_cents == 30000  # the cart checks the set's total against this
    chosen = [it["chosen"]["id"] for it in ui["bundle"]["items"]]
    assert all(pid in s.products for pid in chosen) and [x["id"] for x in result["set"]] == chosen
    assert result["total"] == "$" + agent.to_dollars(ui["bundle"]["total_cents"])


def test_keyless_mock_sends_a_set_to_recommend_bundle_and_a_single_need_to_recommend():
    calls = []
    for text in (SET_REQUEST, "noise cancelling headphones under $100", "a gift for a coffee and tea lover under $50"):
        s = Session()
        agent.handle_message(s, text)
        calls.append([c["function"]["name"] for m in s.history for c in m.get("tool_calls") or []][0])
    assert calls == ["recommend_bundle", "recommend", "recommend"]
    args = mock_agent.build_bundle("a tent, 2 sleeping bags and a lantern under $300", 300.0)
    assert [(i["name"], i["quantity"]) for i in args["items"]] == [("tent", 1), ("sleeping bags", 2), ("lantern", 1)]


def test_set_request_without_budget_asks_first():
    out = agent.handle_message(Session(), "a tent, a sleeping bag and a lantern")
    assert out["reply"] == mock_agent.BUDGET_QUESTION and "bundle" not in out


def test_buy_the_set_prepares_a_cart_at_the_set_total():
    s = Session()
    shown = agent.handle_message(s, SET_REQUEST)["bundle"]
    out = agent.handle_message(s, "buy the set")
    assert out["cart"]["total_cents"] == shown["total_cents"]
    assert [i["title"] for i in out["cart"]["items"]] == [it["chosen"]["title"] for it in shown["items"]]


def test_bundle_tool_with_one_item_tells_the_model_to_use_recommend():
    result = json.loads(agent.run_tool_call(Session(), call("recommend_bundle", {
        "raw_request": "tent", "budget_usd": 100, "items": [{"name": "tent"}]}), {}))
    assert "call recommend instead" in result["error"]
