"""Recommendation pipeline (requirements section 4): search, hard filter, rank, pick top 3."""
import re
from collections import Counter

from app import catalog
from app.money import to_cents, to_dollars

SEARCH_LIMIT = 10
MAX_CANDIDATES = 20
MAX_QUERIES = 4


def parse_request(args: dict) -> dict:
    """Turn the model's tool arguments into a clean structured request. Raises ValueError if unusable."""
    raw = str(args.get("raw_request") or "").strip()
    if not raw:
        raise ValueError("raw_request is required")
    budget = args.get("budget_usd")
    words = lambda key: [str(w).strip() for w in args.get(key) or [] if str(w).strip()]
    return {
        "raw_request": raw,
        "budget_cents": to_cents(budget) if budget is not None else None,
        "must_have": words("must_have"),
        "must_not": words("must_not"),
        "preferences": words("preferences"),
        "queries": words("queries")[:MAX_QUERIES] or [raw],
    }


def search_all(queries: list[str], search_fn=catalog.search) -> list[dict]:
    """F3: run every query, merge and de-duplicate by ID.

    A product found by several queries keeps the index of the first query that returned it.
    """
    merged = {}
    for qi, query in enumerate(queries):
        for p in search_fn(query, SEARCH_LIMIT):
            merged.setdefault(p["id"], {**p, "query_index": qi})
    return list(merged.values())


def rejection(p: dict, budget_cents: int | None, must_not: list[str]) -> tuple[str, str] | None:
    """F4: return (kind, reason) if a hard constraint removes the product, else None."""
    if p["price_cents"] is None:
        return "no_usd_offer", "no in-stock USD offer"
    if not p["in_stock"]:
        return "out_of_stock", "out of stock"
    if budget_cents is not None and p["price_cents"] > budget_cents:
        return "over_budget", f"over budget (${to_dollars(p['price_cents'])} > ${to_dollars(budget_cents)})"
    # Title and brand only: descriptions say things like "not leather" and would cause false matches.
    for kw in must_not:
        if re.search(rf"\b{re.escape(kw)}\b", f"{p['title']} {p['brand']}", re.IGNORECASE):
            return "excluded_keyword", f"matches excluded keyword '{kw}'"
    return None


def round_robin(products: list[dict]) -> list[dict]:
    """Interleave products by source query: 1st of q0, 1st of q1, ..., 2nd of q0, ..."""
    seen_per_query = Counter()
    keyed = []
    for p in products:
        keyed.append((seen_per_query[p["query_index"]], p["query_index"], p))
        seen_per_query[p["query_index"]] += 1
    return [p for _, _, p in sorted(keyed, key=lambda k: k[:2])]


def hard_filter(products: list[dict], budget_cents: int | None, must_not: list[str]) -> tuple[list[dict], list[dict]]:
    """F4: split products into passing candidates (round-robin, at most 20) and rejected ones with reasons."""
    passed, rejected = [], []
    for p in products:
        r = rejection(p, budget_cents, must_not)
        if r:
            rejected.append({"id": p["id"], "title": p["title"], "price_cents": p["price_cents"], "kind": r[0], "reason": r[1]})
        else:
            passed.append(p)
    return round_robin(passed)[:MAX_CANDIDATES], rejected
