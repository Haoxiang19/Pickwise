import pytest

from app import recommend as rec


def product(pid, price=1000, in_stock=True, title=None, brand="B", currency="USD"):
    return {"id": pid, "title": title or f"Item {pid}", "brand": brand, "price_cents": price,
            "currency": currency if price is not None else None, "in_stock": in_stock,
            "url": "", "image": "", "description": "", "category": ""}


def fake_search(results_by_query):
    return lambda query, limit: results_by_query.get(query, [])[:limit]


def test_parse_request_converts_budget_and_cleans_lists():
    req = rec.parse_request({"raw_request": " shoes ", "budget_usd": 99.99, "must_not": ["leather", " "],
                             "queries": ["a", "b", "c", "d", "e"]})
    assert req["budget_cents"] == 9999
    assert req["must_not"] == ["leather"]
    assert req["queries"] == ["a", "b", "c", "d"]
    no_limit = rec.parse_request({"raw_request": "shoes", "budget_usd": None})
    assert no_limit["budget_cents"] is None and no_limit["queries"] == ["shoes"]
    with pytest.raises(ValueError):
        rec.parse_request({"raw_request": ""})


def test_search_all_merges_and_keeps_first_query():
    search = fake_search({"q0": [product("a"), product("b")], "q1": [product("b"), product("c")]})
    merged = rec.search_all(["q0", "q1"], search)
    assert [(p["id"], p["query_index"]) for p in merged] == [("a", 0), ("b", 0), ("c", 1)]


def test_rejection_reasons():
    assert rec.rejection(product("a", price=None), None, [])[0] == "no_usd_offer"
    assert rec.rejection(product("a", in_stock=False), None, [])[0] == "out_of_stock"
    kind, reason = rec.rejection(product("a", price=5001), 5000, [])
    assert kind == "over_budget" and reason == "over budget ($50.01 > $50.00)"
    assert rec.rejection(product("a", price=5000), 5000, []) is None  # equal to budget passes
    assert rec.rejection(product("a", price=10**9), None, []) is None  # no budget: check skipped


def test_must_not_is_whole_word_case_insensitive_title_and_brand_only():
    leather = product("a", title="Leather Backpack")
    assert rec.rejection(leather, None, ["leather"])[0] == "excluded_keyword"
    assert rec.rejection(product("b", title="Leatherette Bag"), None, ["leather"]) is None
    assert rec.rejection(product("c", brand="NIKE"), None, ["nike"])[0] == "excluded_keyword"
    in_description = {**product("d"), "description": "not leather"}
    assert rec.rejection(in_description, None, ["leather"]) is None


def test_hard_filter_round_robin_and_cap():
    products = [{**product(f"a{i}"), "query_index": 0} for i in range(15)]
    products += [{**product(f"b{i}"), "query_index": 1} for i in range(15)]
    products.append({**product("x", price=99999), "query_index": 1})
    passed, rejected = rec.hard_filter(products, budget_cents=5000, must_not=[])
    assert [p["id"] for p in passed[:4]] == ["a0", "b0", "a1", "b1"]
    assert len(passed) == 20
    assert [r["id"] for r in rejected] == ["x"] and rejected[0]["kind"] == "over_budget"
