import pytest

from app import catalog


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("CHANNEL3_API_KEY", raising=False)


def offer(price, currency="USD", availability="InStock", url="u"):
    return {"price": {"price": price, "currency": currency}, "availability": availability, "url": url}


def test_normalize_picks_cheapest_in_stock_usd_offer():
    raw = {
        "id": 7, "title": "T", "description": "D",
        "brands": [{"name": "B"}],
        "images": [{"url": "a"}, {"url": "main", "is_main_image": True}],
        "category": {"title": "C"},
        "offers": [offer(10.00, availability="OutOfStock"), offer("30.50", url="x"), offer(20.25, url="y"), offer(5, "EUR")],
    }
    p = catalog.normalize(raw)
    assert p == {"id": "7", "title": "T", "brand": "B", "price_cents": 2025, "currency": "USD", "in_stock": True,
                 "url": "y", "image": "main", "description": "D", "category": "C"}


def test_normalize_out_of_stock_and_no_usd_offer():
    oos = catalog.normalize({"id": "a", "offers": [offer("9.99", availability="OutOfStock")]})
    assert oos["in_stock"] is False and oos["price_cents"] == 999
    eur = catalog.normalize({"id": "b", "offers": [offer("9.99", "EUR")]})
    assert eur["price_cents"] is None and eur["currency"] is None and eur["in_stock"] is False
    empty = catalog.normalize({"id": "c"})
    assert empty["price_cents"] is None and empty["image"] == "" and empty["brand"] == ""


def test_mock_search_matches_words_and_respects_limit():
    results = catalog.search("noise cancelling headphones", limit=3)
    assert len(results) == 3
    assert all("Headphones" in p["title"] for p in results)
    assert catalog.search("zzzz nothing matches") == []


def test_channel3_request_shape(monkeypatch):
    monkeypatch.setenv("CHANNEL3_API_KEY", "k")
    sent = {}

    class R:
        def raise_for_status(self): pass
        def json(self): return {"products": [{"id": "p1", "offers": [offer(1.5)]}], "next_page_token": None}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers)
        return R()

    monkeypatch.setattr(catalog.httpx, "post", fake_post)
    [p] = catalog.search("tent", limit=10)
    assert p["price_cents"] == 150
    assert sent["json"] == {"query": "tent", "limit": 10, "config": {"currency": "USD"}}
    assert sent["headers"] == {"x-api-key": "k"}


def test_mock_search_prefers_title_matches():
    assert catalog.search("water bottle", limit=1)[0]["category"] == "Water Bottles"
