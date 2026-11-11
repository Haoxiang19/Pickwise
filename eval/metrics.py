"""Metric functions for the eval (requirements section 9). Pure functions, unit-tested in tests/test_eval.py."""
import math
import re

from app import recommend as rec


def ndcg_at_3(recommended_ids: list[str], labels: dict[str, int]) -> float | None:
    """NDCG@3 with linear gain and log2(position + 1) discount.

    Returns None (incomplete) if a recommended product has no label; it is not counted as 0.
    The ideal DCG uses the 3 highest labels among all labelled products of the request.
    """
    top = recommended_ids[:3]
    if any(labels.get(pid) is None for pid in top):
        return None
    dcg = sum(labels[pid] / math.log2(pos + 1) for pos, pid in enumerate(top, start=1))
    best = sorted((v for v in labels.values() if v is not None), reverse=True)[:3]
    idcg = sum(rel / math.log2(pos + 1) for pos, rel in enumerate(best, start=1))
    return dcg / idcg if idcg > 0 else 0.0


def meets_constraints(product: dict, request: dict) -> bool:
    """Budget and must-not, with the same rule as the F4 hard filter."""
    return rec.rejection(product, request["budget_cents"], request["must_not"]) is None


def is_over_budget(product: dict, request: dict) -> bool:
    budget = request["budget_cents"]
    return budget is not None and product["price_cents"] is not None and product["price_cents"] > budget


def is_grounded(recommended: dict, pool: dict[str, dict]) -> bool:
    """The recommended ID was returned by the search (or injected) and its price matches that result."""
    source = pool.get(recommended["id"])
    return source is not None and source["price_cents"] == recommended["price_cents"]


def respects_preference(recommendations: list[dict], keyword: str) -> bool:
    """P1 adherence: the top recommendation's title or brand contains the remembered keyword (whole word)."""
    if not recommendations:
        return False
    top = recommendations[0]
    return re.search(rf"\b{re.escape(keyword)}\b", f"{top['title']} {top['brand']}", re.IGNORECASE) is not None


def mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None
