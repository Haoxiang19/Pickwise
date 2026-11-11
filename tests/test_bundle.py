"""F22 set recommendation: parse_bundle, best_combo and recommend_bundle with a fake catalog."""
import time

import pytest

from app import recommend as rec


def product(pid, price, title=None):
    return {"id": pid, "title": title or f"Item {pid}", "brand": "B", "price_cents": price, "currency": "USD",
            "in_stock": True, "url": "", "image": "", "description": "", "category": ""}


def fake_search(catalog: dict):
    """search_fn over {query: [products]}; honours the price cap like the real catalog."""
    def search(query, limit, max_price_cents):
        return [p for p in catalog.get(query, []) if max_price_cents is None or p["price_cents"] <= max_price_cents][:limit]
    return search


def request(budget_usd=None, items=(("tent", 1), ("lamp", 1)), **extra):
    args = {"raw_request": "camping gear", "budget_usd": budget_usd,
            "items": [{"name": n, "quantity": q} for n, q in items], **extra}
    return rec.parse_bundle(args)


def ranker_in_price_order(descending=False):
    """Stand-in for rank_shuffled: ranks the candidates by price, recording each item's request."""
    seen = []

    def rank(item_request, candidates, seed, shuffles, memories=()):
        seen.append(item_request)
        ordered = sorted(candidates, key=lambda p: p["price_cents"], reverse=descending)
        return [{"id": p["id"], "reason": "fits", "memory": None} for p in ordered[:rec.MAX_RANKED]]
    return rank, seen


def must_not_rank(*args, **kwargs):
    raise AssertionError("the ranker must not be called")


# --- best_combo ---

def test_best_combo_takes_every_rank_1_when_affordable():
    assert rec.best_combo([[500, 100], [400, 50]], 1000) == (0, 0)


def test_tight_budget_moves_exactly_one_item_down():
    combo = rec.best_combo([[500, 100], [500, 400]], 950)
    assert sum(combo) == 1


def test_tie_on_rank_sum_takes_the_cheaper_set():
    # (1, 0) costs 700 and (0, 1) costs 950: both have rank sum 1.
    assert rec.best_combo([[500, 200], [500, 450]], 950) == (1, 0)


def test_none_when_nothing_fits_and_zeros_without_budget():
    assert rec.best_combo([[500, 400], [500, 400]], 700) is None
    assert rec.best_combo([[900, 1], [900, 1]], None) == (0, 0)


def test_six_items_with_six_options_finish_quickly():
    options = [[600 - 10 * k for k in range(6)] for _ in range(6)]
    start = time.perf_counter()
    combo = rec.best_combo(options, 3400)
    assert time.perf_counter() - start < 2
    assert sum(options[i][k] for i, k in enumerate(combo)) <= 3400


# --- parse_bundle ---

@pytest.mark.parametrize("n", [1, 7])
def test_one_or_seven_items_is_an_error_that_tells_the_model_what_to_do(n):
    with pytest.raises(ValueError, match="call recommend|split the request"):
        request(100, items=[(f"thing {i}", 1) for i in range(n)])


def test_queries_cut_to_two_and_approximate_budget_widened():
    req = rec.parse_bundle({"raw_request": "camping", "budget_usd": 100, "budget_is_strict": False, "items": [
        {"name": "tent", "queries": ["a", "b", "c"]}, {"name": "lamp"}]})
    assert req["items"][0]["queries"] == ["a", "b"] and req["items"][1]["queries"] == ["lamp"]
    assert req["budget_cents"] == 12000 and req["budget_stated_cents"] == 10000


def test_bad_quantity_is_an_error():
    with pytest.raises(ValueError, match="quantity of tent"):
        request(100, items=[("tent", 0), ("lamp", 1)])


# --- recommend_bundle ---

CATALOG = {
    "tent": [product("t1", 20000), product("t2", 15000), product("t3", 9000)],
    "lamp": [product("l1", 6000), product("l2", 3000), product("l3", 1500)],
}


def test_comfortable_budget_takes_rank_1_everywhere_and_total_is_server_prices_times_quantity(monkeypatch):
    rank, _ = ranker_in_price_order(descending=True)
    monkeypatch.setattr(rec, "rank_shuffled", rank)
    out = rec.recommend_bundle(request(1000, items=(("tent", 1), ("lamp", 2))), search_fn=fake_search(CATALOG), seed=1)
    assert [it["chosen"]["id"] for it in out["items"]] == ["t1", "l1"]
    assert out["total_cents"] == 20000 + 6000 * 2
    assert all("Chosen over" not in it["chosen"]["reason"] for it in out["items"])


def test_tight_budget_moves_one_item_down_and_says_why(monkeypatch):
    rank, _ = ranker_in_price_order(descending=True)
    monkeypatch.setattr(rec, "rank_shuffled", rank)
    out = rec.recommend_bundle(request(240), search_fn=fake_search(CATALOG), seed=1)
    assert out["total_cents"] <= 24000
    ranks = [[a["id"] for a in [it["chosen"]] + it["alternatives"]] for it in out["items"]]
    moved = [it for it in out["items"] if it["chosen"]["id"] not in ("t1", "l1")]
    assert len(moved) == 1 and "Chosen over higher-ranked options to keep the set within $240.00." in moved[0]["chosen"]["reason"]
    assert all(len(r) <= rec.MAX_RANKED for r in ranks)


def test_caps_are_budget_minus_the_other_floors_with_quantities(monkeypatch):
    rank, seen = ranker_in_price_order()
    monkeypatch.setattr(rec, "rank_shuffled", rank)
    # Floors: tent 9000 x 1, lamp 1500 x 2 = 3000. Budget 20000.
    out = rec.recommend_bundle(request(200, items=(("tent", 1), ("lamp", 2))), search_fn=fake_search(CATALOG), seed=1)
    assert sorted(r["budget_cents"] for r in seen) == sorted([20000 - 3000, (20000 - 9000) // 2])
    # Both are within the total budget, but above their item's limit ($170.00 and $55.00 each).
    limited = {r["id"]: r for r in out["rejected"] if r["kind"] == "item_limit"}
    assert set(limited) == {"t1", "l1"} and limited["t1"]["item"] == "tent" and limited["l1"]["item"] == "lamp"
    assert limited["t1"]["reason"] == "would leave too little for the other items (at most $170.00 for this item)"
    assert limited["l1"]["reason"] == "would leave too little for the other items (at most $55.00 for this item)"


def test_infeasible_request_does_not_call_the_ranker(monkeypatch):
    monkeypatch.setattr(rec, "rank_shuffled", must_not_rank)
    out = rec.recommend_bundle(request(100), search_fn=fake_search(CATALOG), seed=1)
    assert out["items"] == [] and out["total_cents"] is None
    assert out["note"] == "The cheapest set costs $105.00, over your budget of $100.00."


def test_item_with_no_search_result_gives_no_set_and_names_it(monkeypatch):
    monkeypatch.setattr(rec, "rank_shuffled", must_not_rank)
    out = rec.recommend_bundle(request(1000, items=(("tent", 1), ("stove", 1))), search_fn=fake_search(CATALOG), seed=1)
    assert out["items"] == [] and "stove" in out["note"] and "tent" not in out["note"]


def test_guarantee_keeps_the_set_within_budget_when_rankings_list_only_expensive_products(monkeypatch):
    many = {"tent": [product(f"t{i}", 10000 + 1000 * i) for i in range(8)],
            "lamp": [product(f"l{i}", 2000 + 1000 * i) for i in range(8)]}

    def expensive_only(item_request, candidates, seed, shuffles, memories=()):
        ordered = sorted(candidates, key=lambda p: -p["price_cents"])[:rec.MAX_RANKED]
        return [{"id": p["id"], "reason": "fits", "memory": None} for p in ordered]

    monkeypatch.setattr(rec, "rank_shuffled", expensive_only)
    out = rec.recommend_bundle(request(120), search_fn=fake_search(many), seed=1)
    assert [it["chosen"]["id"] for it in out["items"]] == ["t0", "l0"] and out["total_cents"] == 12000
    assert all(len(it["alternatives"]) + 1 <= rec.MAX_RANKED for it in out["items"])


def test_a_product_found_for_two_items_belongs_to_the_first():
    shared = product("kit", 5000, "Camping kit")
    out = rec.recommend_bundle(request(1000), search_fn=fake_search({"tent": [shared, product("t1", 9000)],
                                                                       "lamp": [shared, product("l1", 2000)]}), seed=1)
    ids = [[o["id"] for o in [it["chosen"]] + it["alternatives"]] for it in out["items"]]
    assert "kit" in ids[0] and "kit" not in ids[1]


def test_no_budget_picks_rank_1_and_keyless_ranker_runs():
    out = rec.recommend_bundle(request(None), search_fn=fake_search(CATALOG), seed=7)
    assert len(out["items"]) == 2 and out["budget_cents"] is None
    assert out["total_cents"] == sum(it["chosen"]["price_cents"] for it in out["items"])
    assert {p["id"] for p in out["products"]} == {"t1", "t2", "t3", "l1", "l2", "l3"}
