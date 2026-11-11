"""Product search: Channel3 when CHANNEL3_API_KEY is set, otherwise a local mock catalog.

Both sources return raw Channel3-shaped results, and `normalize` turns each into the
app's Product dict: id, title, brand, price_cents, currency, in_stock, url, image,
description, category.
"""
import json
import os
import re
from pathlib import Path

import httpx

from app.money import to_cents

CHANNEL3_URL = "https://api.trychannel3.com/v1/search"
MOCK_PATH = Path(__file__).with_name("mock_catalog.json")
STOPWORDS = {"a", "an", "the", "for", "and", "with", "of", "to", "in", "on", "my", "i", "me", "some", "good", "best"}


class CatalogError(Exception):
    """The search service failed."""


def enabled() -> bool:
    return bool(os.getenv("CHANNEL3_API_KEY"))


def search(query: str, limit: int = 10) -> list[dict]:
    """Return up to `limit` normalized products for one query."""
    raw = _channel3_search(query, limit) if enabled() else _mock_search(query, limit)
    return [normalize(r) for r in raw]


def _channel3_search(query: str, limit: int) -> list[dict]:
    # The budget is deliberately not sent as a filter: over-budget items must reach the hard filter
    # so the user can see them rejected with a reason.
    body = {"query": query, "limit": limit, "config": {"currency": "USD"}}
    try:
        resp = httpx.post(CHANNEL3_URL, json=body, headers={"x-api-key": os.getenv("CHANNEL3_API_KEY")}, timeout=30)
        resp.raise_for_status()
        return resp.json()["products"]
    except (httpx.HTTPError, ValueError, KeyError) as e:
        raise CatalogError(f"search failed: {e}") from e


def _tokens(text: str) -> set[str]:
    # Crude plural folding ("headphones" -> "headphone") so the mock matches either form.
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words if w not in STOPWORDS}


def _mock_search(query: str, limit: int) -> list[dict]:
    """Rank mock products by how many query words appear in their text."""
    products = json.loads(MOCK_PATH.read_text(encoding="utf-8"))
    q = _tokens(query)
    scored = []
    for p in products:
        other = " ".join([p["description"], p["category"]["title"], p["brands"][0]["name"]])
        # Title words count double, so "water bottle" ranks a bottle above a backpack with a bottle pocket.
        score = 2 * len(q & _tokens(p["title"])) + len(q & _tokens(other))
        if score:
            scored.append((score, p))
    scored.sort(key=lambda sp: -sp[0])  # stable sort keeps catalog order on ties
    return [p for _, p in scored[:limit]]


def _offer_cents(offer: dict) -> int | None:
    try:
        return to_cents(offer["price"]["price"])
    except (KeyError, TypeError, ValueError):
        return None


def normalize(raw: dict) -> dict:
    """Map one Channel3 result to a Product, choosing the cheapest in-stock USD offer.

    If no USD offer is in stock, the cheapest USD offer is kept with in_stock=False (reason: out of stock).
    If there is no USD offer at all, price_cents and currency are None (reason: no in-stock USD offer).
    """
    usd = [o for o in raw.get("offers") or [] if (o.get("price") or {}).get("currency") == "USD" and _offer_cents(o) is not None]
    in_stock = [o for o in usd if o.get("availability") == "InStock"]
    pool = in_stock or usd
    offer = min(pool, key=_offer_cents) if pool else None

    images = raw.get("images") or []
    main_image = next((i for i in images if i.get("is_main_image")), images[0] if images else {})
    brands = raw.get("brands") or []
    return {
        "id": str(raw["id"]),
        "title": raw.get("title") or "",
        "brand": (brands[0].get("name") or "") if brands else "",
        "price_cents": _offer_cents(offer) if offer else None,
        "currency": "USD" if offer else None,
        "in_stock": bool(in_stock),
        "url": offer.get("url", "") if offer else "",
        "image": main_image.get("url", ""),
        "description": raw.get("description") or "",
        "category": (raw.get("category") or {}).get("title", ""),
    }
