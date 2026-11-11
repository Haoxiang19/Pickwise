"""F17: shuffle 3 times, rank in parallel, aggregate by mean rank (unlisted = 7)."""
import json
import threading

from app import llm
from app import recommend as rec


def r(*ids):
    return [{"id": i, "reason": f"{i} reason"} for i in ids]


def test_mean_rank_with_missing_as_seven():
    # a: 1, 2, 7 -> 3.33; b: 2, 1, 1 -> 1.33; c: 3, 7, 2 -> 4.0; d: 7, 7, 3 -> 5.67
    out = rec.aggregate([r("a", "b", "c"), r("b", "a"), r("b", "c", "d")])
    assert [x["id"] for x in out] == ["b", "a", "c", "d"]


def test_ties_keep_first_appearance_and_cap_at_six():
    out = rec.aggregate([r("a", "b"), r("b", "a")])  # both mean 1.5
    assert [x["id"] for x in out] == ["a", "b"]
    many = rec.aggregate([r(*"abcdefgh"[:6]), r(*"cdefgh")])
    assert len(many) == 6


def test_reason_comes_from_best_placement():
    first = [{"id": "a", "reason": "low"}, {"id": "b", "reason": None}]
    second = [{"id": "b", "reason": "b high"}, {"id": "a", "reason": "a high"}]
    out = {x["id"]: x["reason"] for x in rec.aggregate([first, second])}
    assert out == {"a": "low", "b": "b high"}


def test_single_ranking_is_unchanged():
    assert rec.aggregate([r("x", "y")]) == [dict(x, memory=None) for x in r("x", "y")]


def candidates(n=8):
    return [{"id": str(i), "title": f"T{i}", "brand": "B", "price_cents": 100, "currency": "USD", "in_stock": True,
             "description": "", "url": "", "image": "", "query_index": 0} for i in range(n)]


def test_three_parallel_rankings_with_consecutive_seeds(monkeypatch):
    orders, threads = [], set()

    def fake_chat(messages, tools=None, temperature=0.0, mock=None):
        lines = messages[1]["content"].split("one JSON object per line:\n")[1].splitlines()
        ids = [json.loads(line)["id"] for line in lines]
        orders.append(ids)
        threads.add(threading.get_ident())
        return {"role": "assistant", "content": json.dumps({"ranking": [{"id": i} for i in ids[:3]]})}

    monkeypatch.setattr(rec.llm, "chat", fake_chat)
    request = rec.parse_request({"raw_request": "x"})
    out = rec.rank_shuffled(request, candidates(), seed=10, shuffles=3)
    assert len(orders) == 3 and len({tuple(o) for o in orders}) == 3
    expected = []
    for s in (10, 11, 12):  # each shuffle is the plain F5 shuffle with its own seed
        cands = candidates()
        rec.random.Random(s).shuffle(cands)
        expected.append([c["id"] for c in cands])
    assert sorted(orders) == sorted(expected)
    assert 1 <= len(out) <= 6


def test_one_shuffle_equals_plain_rank(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    request = rec.parse_request({"raw_request": "x"})
    assert rec.rank_shuffled(request, candidates(), 5, 1) == rec.rank(request, candidates(), 5)


def test_recommend_counts_three_ranking_calls_in_mock_mode(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    search = lambda q, limit, cap=None: [dict(c, query_index=0) for c in candidates()][:limit]
    request = rec.parse_request({"raw_request": "x", "budget_usd": 10})
    llm.reset_usage()
    out = rec.recommend(request, {"multi_query": True, "reasoning_rank": True, "rank_shuffles": 3}, search, seed=1)
    assert llm.usage["calls"] == 3 and len(out["recommendations"]) == 3
