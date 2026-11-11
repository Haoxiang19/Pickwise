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
APPROX = re.compile(r"\b(around|about|roughly|approximately|or so|ish)\b|~", re.I)
PICK = re.compile(r"\b(?:buy|take|choose|pick|get|want)\b.*?\b(first|1st|second|2nd|third|3rd|1|2|3)\b", re.I)
ORDINALS = {"first": 0, "1st": 0, "1": 0, "second": 1, "2nd": 1, "2": 1, "third": 2, "3rd": 2, "3": 2}
CHEAPER = re.compile(r"\b(cheaper|less expensive|lower price)\b", re.I)
OTHER_BRAND = re.compile(r"\b(different|another|other) brands?\b", re.I)
FOLLOW_UP = re.compile(r"^\s*(but|also|and|actually|only|now)\b", re.I)
ORDER_QUESTION = re.compile(r"\b(order status|my orders?|where is my order|status of (my )?order|orders?\s*#?\s*\d+)\b", re.I)
ORDER_ID = re.compile(r"\border\s*#?\s*(\d+)\b|#(\d+)", re.I)
REFUND = re.compile(r"\b(refund|money back|return it)\b", re.I)
REFUND_LINE = re.compile(r"\b(?:item|line)\s*#?\s*(\d+)\b", re.I)  # F23: "refund item 2 of order 5"
PREFER = re.compile(r"\bi (?:always |really |usually )?(?:prefer|love|only buy|always buy)\s+([^.,!?]+)", re.I)
DISLIKE = re.compile(r"\bi (?:no longer|don'?t|do not) (?:like|prefer|want)\s+([^.,!?]+?)(?:\s+anymore)?(?:[.,!?]|$)", re.I)
SAVED = re.compile(r"^- \[(\d+)\] [+-][\d.]+ (.+)$", re.M)
SET_PART = re.compile(r"(a|an|\d+)\s+(.+)", re.I)  # "a tent", "2 sleeping bags": one item of a set (F22)
TRAILING_BUDGET_WORDS = re.compile(r"\s+(?:under|below|less than|up to|max|for|budget(?: is| of)?)\s*$", re.I)
TAKE_SET = re.compile(r"\b(?:buy|take|get|want|choose)\s+(?:the\s+)?(?:whole\s+)?set\b", re.I)


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
    core = APPROX.sub(" ", NO_LIMIT.sub(" ", AMOUNT.sub(" ", EXCLUDE.sub(" ", text))))
    parts = [p.strip(" .!?") for p in re.split(r",|\band\b|\bor\b", core)]
    queries = [p for p in parts if len(p) > 2][:4] or [text]
    args = {"raw_request": text, "must_not": must_not, "queries": queries}
    if budget is not None:
        args["budget_usd"] = budget
        args["budget_is_strict"] = not APPROX.search(text)
    return args


def build_bundle(text: str, budget: float | None) -> dict | None:
    """F22: read "a tent, 2 sleeping bags and a lantern under $300" as a set, or return None.

    A set needs 2 to 6 parts that each start with "a", "an" or a number, so "a gift for a coffee
    and tea lover" stays one request.
    """
    core = APPROX.sub(" ", NO_LIMIT.sub(" ", AMOUNT.sub(" ", EXCLUDE.sub(" ", text))))
    parts = [p.strip(" .!?") for p in re.split(r",|\band\b", core) if p.strip(" .!?")]
    matches = [SET_PART.fullmatch(p) for p in parts]
    if not 2 <= len(parts) <= 6 or not all(matches):
        return None
    items = []
    for m in matches:
        name = TRAILING_BUDGET_WORDS.sub("", m.group(2)).strip()
        quantity = int(m.group(1)) if m.group(1).isdigit() else 1
        items.append({"name": name, "queries": [name], "quantity": quantity})
    args = {"raw_request": text, "must_not": [w.lower() for w in EXCLUDE.findall(text) if w.lower() not in NOT_KEYWORDS],
            "items": items}
    if budget is not None:
        args["budget_usd"] = budget
        args["budget_is_strict"] = not APPROX.search(text)
    return args


def last_set(messages: list[dict]) -> list[dict]:
    """The set chosen most recently, read back from the latest recommend_bundle tool result."""
    for m in reversed(messages):
        if m["role"] == "tool":
            result = json.loads(m["content"])
            if result.get("set"):
                return result["set"]
    return []


def summarize(result: dict) -> str:
    """Reply after a tool result."""
    if "error" in result:
        return f"Sorry, something went wrong: {result['error']}"
    if "set" in result:
        if not result["set"]:
            return "I could not build a set that fits. " + result["note"]
        names = "; ".join(f"{s['quantity']} x {s['title']} ({s['price']} each)" for s in result["set"])
        note = " " + result["note"] if result["note"] else ""
        return (f"Here is a set for {result['total']}: {names}.{note} "
                "You can swap items on the cards, then click Review this set, or say \"buy the set\".")
    if "recommendations" in result:
        recs = result["recommendations"]
        if not recs:
            return "I could not find anything that fits. " + result["note"]
        names = "; ".join(f"{r['title']} ({r['price']})" for r in recs)
        return f"Here are {len(recs)} picks: {names}. {result['note']}".strip()
    if "saved" in result:
        return f"Noted. I will remember: {result['saved']['text']}"
    if "next_step" in result and "order_id" in result:
        what = ", ".join(f"line {x['line']} ({x['title']})" for x in result["lines"])
        return (f"I prepared a refund of {result['amount']} for order #{result['order_id']}: {what}. "
                "Click Confirm refund to send it.")
    if "orders" in result:
        if not result["orders"]:
            return "I could not find that order."
        return "Your orders: " + "; ".join(f"#{o['order_id']} {o['status']} {o['amount']}" for o in result["orders"]) + "."
    if "cart_id" in result:
        note = " " + result["price_note"] if result.get("price_note") else ""
        lines = ", ".join(f"{i['quantity']} x {i['title']}" for i in result["items"])
        return (f"Your order summary is ready: {lines}, "
                f"total {result['total']}.{note} Click Confirm to pay on PayPal.")
    return "Done."


def last_recommendations(messages: list[dict]) -> list[dict]:
    """IDs shown most recently, read back from the latest recommend tool result in the history."""
    for m in reversed(messages):
        if m["role"] == "tool":
            result = json.loads(m["content"])
            if result.get("recommendations"):
                return result["recommendations"]
    return []


def last_recommend_args(messages: list[dict]) -> dict | None:
    """Arguments of the latest recommend call, i.e. the conditions in force so far."""
    for m in reversed(messages):
        for call in m.get("tool_calls") or []:
            if call["function"]["name"] == "recommend":
                return json.loads(call["function"]["arguments"])
    return None


def refine(previous: dict, text: str, shown: list[dict]) -> dict:
    """F7: apply a follow-up condition on top of the earlier request, keeping the rest."""
    args = {**previous, "raw_request": f"{previous['raw_request']}; {text}"}
    budget, no_limit = parse_budget(text)
    if CHEAPER.search(text) and budget is None:
        prices = [float(r["price"].lstrip("$")) for r in shown]
        base = previous.get("budget_usd") or max(prices, default=0)
        budget = int(base * 0.8)  # "cheaper" read as 20% under the earlier budget
    if budget is not None:
        args["budget_usd"] = budget
    if no_limit:
        args.pop("budget_usd", None)
    excluded = [w.lower() for w in EXCLUDE.findall(text) if w.lower() not in NOT_KEYWORDS]
    if OTHER_BRAND.search(text):
        excluded += [r["brand"].lower() for r in shown if r.get("brand")]
    args["must_not"] = list(dict.fromkeys(previous.get("must_not", []) + excluded))
    return args


def preference_args(system_text: str, dislike, prefer) -> dict:
    """F18 in keyless mode: "I prefer X" saves or confirms; "I don't like X anymore" contradicts a saved one."""
    saved = SAVED.findall(system_text)  # [(id, text)] from the system prompt's preference list
    if dislike:
        thing = dislike.group(1).strip()
        match = next((pid for pid, text in saved if thing.lower() in text.lower()), None)
        if match:
            return {"text": f"Prefers {thing}", "about_id": int(match), "stance": "contradicts"}
        return {"text": f"Dislikes {thing}", "stance": "supports"}
    thing = prefer.group(1).strip()
    match = next((pid for pid, text in saved if text.lower() == f"prefers {thing}".lower()), None)
    return {"text": f"Prefers {thing}", "about_id": int(match)} if match else {"text": f"Prefers {thing}"}


def reply(messages: list[dict]) -> dict:
    last = messages[-1]
    if last["role"] == "tool":
        return text_message(summarize(json.loads(last["content"])))

    text = last["content"]
    # Order questions first, so "I want a refund for order 1" is not read as "want the 1st product".
    if REFUND.search(text):
        line = REFUND_LINE.search(text)
        m = ORDER_ID.search(REFUND_LINE.sub(" ", text))  # so "item #2" is not read as order 2
        if not m:
            return text_message("Which order should I refund? Give its number, e.g. 'refund order 2'.")
        args = {"order_id": int(m.group(1) or m.group(2))}
        if line:
            args["lines"] = [int(line.group(1))]
        return tool_message("draft_refund", args)

    if ORDER_QUESTION.search(text):
        m = ORDER_ID.search(text)
        return tool_message("get_orders", {"order_id": int(m.group(1) or m.group(2))} if m else {})

    dislike, prefer = DISLIKE.search(text), PREFER.search(text)
    if dislike or prefer:
        return tool_message("remember_preference", preference_args(messages[0]["content"], dislike, prefer))

    chosen_set = last_set(messages)
    if TAKE_SET.search(text) and chosen_set:
        return tool_message("prepare_cart", {"items": [{"product_id": s["id"], "quantity": s["quantity"]} for s in chosen_set]})

    shown = last_recommendations(messages)
    pick = PICK.search(text)
    if pick and ORDINALS[pick.group(1).lower()] < len(shown):
        return tool_message("prepare_cart", {"product_id": shown[ORDINALS[pick.group(1).lower()]]["id"], "quantity": 1})

    earlier = last_recommend_args(messages)
    if earlier and (CHEAPER.search(text) or OTHER_BRAND.search(text) or FOLLOW_UP.search(text)):
        return tool_message("recommend", refine(earlier, text, shown))

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
    bundle = build_bundle(request_text, budget)
    if bundle:
        return tool_message("recommend_bundle", bundle)
    return tool_message("recommend", build_request(request_text, budget))
