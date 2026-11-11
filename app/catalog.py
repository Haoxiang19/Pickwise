"""Product search: Channel3 when CHANNEL3_API_KEY is set, otherwise a local mock catalog.

Both sources return raw Channel3-shaped results, and `normalize` turns each into the
app's Product dict: id, title, brand, price_cents, currency, in_stock, url, image,
description, category.
"""
import json
import logging
import os
import re
import time
from pathlib import Path

import httpx

from app.money import to_cents

log = logging.getLogger(__name__)

CHANNEL3_URL = "https://api.trychannel3.com/v1/search"
MOCK_PATH = Path(__file__).with_name("mock_catalog.json")
STOPWORDS = {"a", "an", "the", "for", "and", "with", "of", "to", "in", "on", "my", "i", "me", "some", "good", "best"}
RETRY_STATUS = {429, 500, 502, 503, 504}  # Channel3 sends Retry-After on 429 and documents 503 as retryable
MAX_RETRY_WAIT = 10.0
# Channel3 counts an offer with no availability data as in stock, so only these values mean "cannot buy now".
UNAVAILABLE = {"OutOfStock", "SoldOut", "PreOrder", "BackOrder"}
_seen_availability: set[str] = set()


class CatalogError(Exception):
    """The search service failed."""


def enabled() -> bool:
    return bool(os.getenv("CHANNEL3_API_KEY"))


def search(query: str, limit: int = 10) -> list[dict]:
    """Return up to `limit` normalized products for one query."""
    raw = _channel3_search(query, limit) if enabled() else _mock_search(query, limit)
    return [normalize(r) for r in raw]


def _retry_after(resp: httpx.Response) -> float:
    """Seconds to wait before retrying; Channel3 sends `Retry-After: 5` on 429."""
    try:
        return min(float(resp.headers.get("Retry-After", 1)), MAX_RETRY_WAIT)
    except ValueError:  # the header may be an HTTP date, where a short wait is good enough
        return 1.0


def _error_code(resp: httpx.Response) -> str:
    """Channel3 errors look like {"error": {"code": ..., "message": ...}}."""
    try:
        return (resp.json().get("error") or {}).get("code", "")
    except (ValueError, AttributeError):
        return ""


def _channel3_search(query: str, limit: int) -> list[dict]:
    # The budget is deliberately not sent as a filter: over-budget items must reach the hard filter
    # so the user can see them rejected with a reason.
    body = {"query": query, "limit": limit, "config": {"currency": "USD", "country": "US"}}
    headers = {"x-api-key": os.getenv("CHANNEL3_API_KEY")}
    for attempt in (1, 2):
        try:
            resp = httpx.post(CHANNEL3_URL, json=body, headers=headers, timeout=30)
        except httpx.HTTPError as e:
            raise CatalogError(f"search failed: {e}") from e
        # One retry only, for the cases Channel3 documents as worth repeating.
        if attempt == 2 or resp.status_code not in RETRY_STATUS:
            break
        time.sleep(_retry_after(resp))
    if resp.status_code >= 400:
        raise CatalogError(f"search failed: HTTP {resp.status_code} {_error_code(resp)}".strip())
    try:
        return resp.json()["products"]
    except (ValueError, KeyError, TypeError) as e:
        raise CatalogError(f"unexpected search response: {e}") from e


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
    """Price in integer cents, or None when the offer has no usable price."""
    price = offer.get("price") or {}
    # The schema documents price.price, but the guide's examples write price.amount. Accept either
    # until a real response settles it (see docs/progress.md).
    value = price.get("price") if price.get("price") is not None else price.get("amount")
    try:
        return to_cents(value)
    except (TypeError, ValueError):
        return None


def _in_stock(offer: dict) -> bool:
    """Channel3 counts an offer with no availability data as in stock, so only known values mean no."""
    value = offer.get("availability")
    if value not in (None, "InStock") and value not in UNAVAILABLE and value not in _seen_availability:
        _seen_availability.add(value)  # warn once per value, so a real response teaches us what exists
        log.warning("unknown Channel3 availability %r; treating it as in stock", value)
    return value not in UNAVAILABLE


def normalize(raw: dict) -> dict:
    """Map one Channel3 result to a Product, choosing the cheapest in-stock USD offer.

    If no USD offer is in stock, the cheapest USD offer is kept with in_stock=False (reason: out of stock).
    If there is no USD offer at all, price_cents and currency are None (reason: no in-stock USD offer).
    """
    usd = [o for o in raw.get("offers") or [] if (o.get("price") or {}).get("currency") == "USD" and _offer_cents(o) is not None]
    in_stock = [o for o in usd if _in_stock(o)]
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
