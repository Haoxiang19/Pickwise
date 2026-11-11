"""Rule-based stand-in for the agent model, used only when no LLM key is configured.

It returns messages in the same shape as the real model (text, or tool_calls), so the
agent loop runs unchanged. It understands only simple phrasings; it is a demo aid, not the product.
"""
import json
import re

BUDGET_QUESTION = "What is your budget for this, in US dollars? You can also say there is no limit."

NO_LIMIT = re.compile(r"\b(no (budget|limit|price limit)|any price|unlimited|doesn'?t matter)\b", re.I)
AMOUNT = re.compile(
    r"\$\s*(\d+(?:\.\d{1,2})?)"                                          # $100
    r"|\b(\d+(?:\.\d{1,2})?)\s*(?:dollars|usd|bucks)\b"                  # 100 dollars
    r"|\b(?:under|below|less than|up to|max|budget(?: is| of)?)\s+(\d+(?:\.\d{1,2})?)\b",  # under 100
    re.I)
EXCLUDE = re.compile(r"\b(?:no|not|without|avoid)\s+([a-z0-9][\w-]*)", re.I)
NOT_KEYWORDS = {"budget", "limit", "price", "more", "too", "than", "idea"}
PICK = re.compile(r"\b(?:buy|take|choose|pick|get|want)\b.*?\b(first|1st|second|2nd|third|3rd|1|2|3)\b", re.I)
ORDINALS = {"first": 0, "1st": 0, "1": 0, "second": 1, "2nd": 1, "2": 1, "third": 2, "3rd": 2, "3": 2}


def text_message(content: str) -> dict:
    return {"role": "assistant", "content": content}


def tool_message(name: str, args: dict) -> dict:
    call = {"id": f"mock_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
    return {"role": "assistant", "content": None, "tool_calls": [call]}


def parse_budget(text: str) -> tuple[float | None, bool]:
    """Return (budget in dollars or None, whether the user said there is no limit)."""
    if NO_LIMIT.search(text):
        return None, True
    m = AMOUNT.search(text)
    if m:
        return float(next(g for g in m.groups() if g)), False
    bare = re.fullmatch(r"\s*\$?(\d+(?:\.\d{1,2})?)\s*", text)  # a bare "80" answering the budget question
    return (float(bare.group(1)), False) if bare else (None, False)


def build_request(text: str, budget: float | None) -> dict:
    must_not = [w.lower() for w in EXCLUDE.findall(text) if w.lower() not in NOT_KEYWORDS]
    # Queries: the request without budget and exclusion phrases, split on "and" / commas.
    core = NO_LIMIT.sub(" ", AMOUNT.sub(" ", EXCLUDE.sub(" ", text)))
    parts = [p.strip(" .!?") for p in re.split(r",|\band\b|\bor\b", core)]
    queries = [p for p in parts if len(p) > 2][:4] or [text]
    args = {"raw_request": text, "must_not": must_not, "queries": queries}
    if budget is not None:
        args["budget_usd"] = budget
    return args


def summarize(result: dict) -> str:
    """Reply after a tool result."""
    if "error" in result:
        return f"Sorry, something went wrong: {result['error']}"
    if "recommendations" in result:
        recs = result["recommendations"]
        if not recs:
            return "I could not find anything that fits. " + result["note"]
        names = "; ".join(f"{r['title']} ({r['price']})" for r in recs)
        return f"Here are {len(recs)} picks: {names}. {result['note']}".strip()
    if "cart_id" in result:
        return f"Your order summary is ready: {result['quantity']} x {result['title']}, total {result['total']}. Click Confirm to pay on PayPal."
    return "Done."


def last_recommendations(messages: list[dict]) -> list[dict]:
    """IDs shown most recently, read back from the latest recommend tool result in the history."""
    for m in reversed(messages):
        if m["role"] == "tool":
            result = json.loads(m["content"])
            if result.get("recommendations"):
                return result["recommendations"]
    return []


def reply(messages: list[dict]) -> dict:
    last = messages[-1]
    if last["role"] == "tool":
        return text_message(summarize(json.loads(last["content"])))

    text = last["content"]
    shown = last_recommendations(messages)
    pick = PICK.search(text)
    if pick and ORDINALS[pick.group(1).lower()] < len(shown):
        return tool_message("prepare_cart", {"product_id": shown[ORDINALS[pick.group(1).lower()]]["id"], "quantity": 1})

    previous = [m for m in messages[:-1] if m["role"] in ("user", "assistant")]
    # If the last thing we said was the budget question, this message answers it: join it to the request.
    if len(previous) >= 2 and (previous[-1].get("content") or "").endswith(BUDGET_QUESTION) and previous[-2]["role"] == "user":
        request_text = previous[-2]["content"]
        budget, no_limit = parse_budget(text)
    else:
        request_text = text
        budget, no_limit = parse_budget(text)
        if budget is None and not no_limit:
            return text_message(BUDGET_QUESTION)
    if budget is None and not no_limit:
        return text_message("Sorry, I did not catch a number. " + BUDGET_QUESTION)
    return tool_message("recommend", build_request(request_text, budget))
