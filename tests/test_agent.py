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


def test_model_has_no_money_tools():
    names = {t["function"]["name"] for t in agent.TOOLS}
    assert not names & {"create_order", "capture", "refund", "pay"}


# --- F8 cart through the agent ---

def test_pick_prepares_cart_priced_by_server():
    s = Session()
    out = agent.handle_message(s, "noise cancelling headphones under $100")
    second = out["recommendations"][1]
    out = agent.handle_message(s, "I'll take the second one")
    assert out["cart"]["title"] == second["title"]
    assert out["cart"]["total_cents"] == second["price_cents"] and out["cart"]["quantity"] == 1


def test_prepare_cart_ignores_model_price_and_rejects_unknown_id():
    s = Session()
    agent.handle_message(s, "noise cancelling headphones under $100")
    pid = next(iter(s.products))
    ui = {}
    result = json.loads(agent.run_tool_call(s, call("prepare_cart", {"product_id": pid, "price": 0.01}), ui))
    assert ui["cart"]["unit_price_cents"] == s.products[pid]["price_cents"] != 1
    result = json.loads(agent.run_tool_call(s, call("prepare_cart", {"product_id": "made-up"}), {}))
    assert "Unknown product" in result["error"]
