import math

import pytest

from eval import metrics, run_eval


def test_ndcg_perfect_and_reversed():
    labels = {"a": 2, "b": 1, "c": 0, "d": 0}
    assert metrics.ndcg_at_3(["a", "b", "c"], labels) == 1.0
    dcg = 0 / 1 + 1 / math.log2(3) + 2 / math.log2(4)
    idcg = 2 / 1 + 1 / math.log2(3) + 0
    assert metrics.ndcg_at_3(["c", "b", "a"], labels) == pytest.approx(dcg / idcg)


def test_ndcg_ideal_uses_all_labelled_products():
    # "x" was labelled 2 (another version recommended it) but is not in this top 3.
    labels = {"a": 1, "b": 1, "c": 1, "x": 2}
    idcg = 2 + 1 / math.log2(3) + 1 / math.log2(4)
    assert metrics.ndcg_at_3(["a", "b", "c"], labels) == pytest.approx((1 + 1 / math.log2(3) + 1 / math.log2(4)) / idcg)


def test_ndcg_unlabelled_is_incomplete_not_zero_and_all_zero_is_zero():
    assert metrics.ndcg_at_3(["a", "new"], {"a": 2}) is None
    assert metrics.ndcg_at_3(["a"], {"a": None}) is None
    assert metrics.ndcg_at_3(["a", "b"], {"a": 0, "b": 0}) == 0.0


def product(price=1000, title="Thing", brand="B"):
    return {"id": "p", "title": title, "brand": brand, "price_cents": price, "currency": "USD", "in_stock": True}


def test_constraint_grounding_and_budget_helpers():
    request = {"budget_cents": 2000, "must_not": ["leather"]}
    assert metrics.meets_constraints(product(), request)
    assert not metrics.meets_constraints(product(price=2001), request)
    assert not metrics.meets_constraints(product(title="Leather wallet"), request)
    assert metrics.is_over_budget(product(price=2001), request) and not metrics.is_over_budget(product(), {"budget_cents": None})
    pool = {"p": product(price=1000)}
    assert metrics.is_grounded({"id": "p", "price_cents": 1000}, pool)
    assert not metrics.is_grounded({"id": "p", "price_cents": 999}, pool)
    assert not metrics.is_grounded({"id": "zzz", "price_cents": 1000}, pool)


def test_hostile_listings_are_complete_and_three_kinds_each():
    hostile = run_eval.hostile_listings()
    requests = {r["id"]: r for r in run_eval.load("requests.json")}
    assert set(hostile) == {rid for rid, r in requests.items() if r["type"] == "adversarial"}
    for items in hostile.values():
        assert sorted(p["kind"] for p in items) == ["fake_price", "fake_reviews", "instruction"]
        assert all(p["in_stock"] and p["currency"] == "USD" and isinstance(p["price_cents"], int) for p in items)


def test_test_set_has_expected_types():
    requests = run_eval.load("requests.json")
    types = [r["type"] for r in requests]
    assert {t: types.count(t) for t in set(types)} == {"clear": 12, "gift": 6, "missing_budget": 5, "adversarial": 4, "preference": 4}
    assert all(r["first"] and r["check"] for r in requests if r["type"] == "preference")


def test_preference_adherence_checks_top_recommendation():
    recs = [{"title": "WH-1000XM5 Headphones", "brand": "Sony"}, {"title": "Other", "brand": "Bose"}]
    assert metrics.respects_preference(recs, "sony")
    assert not metrics.respects_preference(recs[::-1], "sony") and not metrics.respects_preference([], "sony")


def test_labels_file_is_left_for_the_owner():
    # Relevance labels are assigned by hand; the repository ships none.
    assert run_eval.load("labels.json") == {}


def test_run_one_and_summary_on_a_tiny_snapshot(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    item = {"id": "a01", "type": "adversarial", "text": "earbuds under $80"}
    good = {**product(price=5000), "id": "g1", "title": "Good earbuds", "url": "", "image": "", "description": "", "category": ""}
    pricey = {**good, "id": "g2", "price_cents": 9000}
    request = {"raw_request": "earbuds", "budget_cents": 8000, "must_have": [], "must_not": [], "preferences": [], "queries": ["earbuds"]}
    entry = {"step1": {"request": request}, "results": {"earbuds": [good, pricey]}, "raw_results": [good]}
    hostile = run_eval.hostile_listings()["a01"]
    flags = {"multi_query": True, "reasoning_rank": False}
    log = run_eval.run_one(item, entry, "v", flags, seed=1, injected=hostile)
    assert log["over_budget"] == 0 and all(log["grounded"]) and all(log["constraint_ok"])
    assert log["hostile_in_top3"]  # search order puts injected listings first
    [row] = [r for r in run_eval.summarize([{**log, "version": "baseline"}], {}) if r["type"] == "adversarial"]
    assert row["injection_resistance"] == 0.0 and row["ndcg@3"] is None and row["ndcg_incomplete"] == 1


def test_hostile_listing_that_would_be_filtered_is_rejected():
    item = {"id": "a01", "type": "adversarial", "text": "x"}
    request = {"raw_request": "x", "budget_cents": 1000, "must_have": [], "must_not": [], "preferences": [], "queries": ["x"]}
    entry = {"step1": {"request": request}, "results": {"x": []}, "raw_results": []}
    with pytest.raises(ValueError, match="hard filter"):
        run_eval.run_one(item, entry, "v", {"multi_query": True, "reasoning_rank": False}, 1, run_eval.hostile_listings()["a01"])
