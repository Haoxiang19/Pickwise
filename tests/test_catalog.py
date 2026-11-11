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


class FakeResp:
    def __init__(self, status=200, data=None, headers=None):
        self.status_code, self._data, self.headers = status, data, headers or {}

    def json(self):
        if self._data is None:
            raise ValueError("not json")
        return self._data


def test_channel3_request_shape(monkeypatch):
    monkeypatch.setenv("CHANNEL3_API_KEY", "k")
    sent = {}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers)
        return FakeResp(200, {"products": [{"id": "p1", "offers": [offer(1.5)]}], "next_page_token": None})

    monkeypatch.setattr(catalog.httpx, "post", fake_post)
    [p] = catalog.search("tent", limit=10)
    assert p["price_cents"] == 150
    assert sent["url"] == catalog.CHANNEL3_URL
    assert sent["json"] == {"query": "tent", "limit": 10, "config": {"currency": "USD", "country": "US"}}
    assert sent["headers"] == {"x-api-key": "k"}


def test_mock_search_prefers_title_matches():
    assert catalog.search("water bottle", limit=1)[0]["category"] == "Water Bottles"


# --- Field names and availability values the Channel3 docs leave ambiguous ---

def test_offer_price_accepts_both_documented_field_names():
    """The schema says offers[].price.price; the guide's examples say price.amount."""
    assert catalog.normalize({"id": "a", "offers": [offer("12.34")]})["price_cents"] == 1234
    by_amount = {"price": {"amount": "12.34", "currency": "USD"}, "availability": "InStock", "url": "u"}
    assert catalog.normalize({"id": "b", "offers": [by_amount]})["price_cents"] == 1234
    no_price = {"price": {"currency": "USD"}, "availability": "InStock", "url": "u"}
    assert catalog.normalize({"id": "c", "offers": [no_price]})["price_cents"] is None


@pytest.mark.parametrize("availability,buyable", [
    ("InStock", True), ("LimitedAvailability", True), ("Unheard Of", True),
    ("OutOfStock", False), ("SoldOut", False), ("PreOrder", False), ("BackOrder", False),
])
def test_known_unavailable_values_only(availability, buyable):
    p = catalog.normalize({"id": "a", "offers": [offer(10, availability=availability)]})
    assert p["in_stock"] is buyable


def test_missing_availability_counts_as_in_stock():
    """Channel3 says an offer with no availability data is in stock; rejecting it would drop good products."""
    no_field = {"price": {"price": 10, "currency": "USD"}, "url": "u"}
    assert catalog.normalize({"id": "a", "offers": [no_field]})["in_stock"] is True


def test_unknown_availability_is_logged_once(monkeypatch, caplog):
    monkeypatch.setattr(catalog, "_seen_availability", set())
    with caplog.at_level("WARNING"):
        for _ in range(3):
            catalog.normalize({"id": "a", "offers": [offer(10, availability="Backordered")]})
    assert sum("Backordered" in r.getMessage() for r in caplog.records) == 1


# --- Rate limiting and errors ---

def live(monkeypatch, replies):
    """Real-mode search with fake HTTP: returns the list of recorded sleep durations."""
    monkeypatch.setenv("CHANNEL3_API_KEY", "k")
    waits = []
    monkeypatch.setattr(catalog.time, "sleep", waits.append)
    it = iter(replies)
    monkeypatch.setattr(catalog.httpx, "post", lambda *a, **k: next(it))
    return waits


def test_retries_once_on_rate_limit_and_waits_retry_after(monkeypatch):
    ok = FakeResp(200, {"products": [{"id": "p", "offers": [offer(1.5)]}]})
    waits = live(monkeypatch, [FakeResp(429, headers={"Retry-After": "5"}), ok])
    assert [p["id"] for p in catalog.search("tent")] == ["p"]
    assert waits == [5.0]


@pytest.mark.parametrize("header,wait", [
    ("600", catalog.MAX_RETRY_WAIT),                      # capped, so one slow call cannot stall a request
    ("Wed, 11 Nov 2026 12:00:00 GMT", 1.0),               # Retry-After may be a date; a short wait will do
    (None, 1.0),                                          # no header at all
])
def test_retry_wait_is_capped_and_tolerates_odd_headers(monkeypatch, header, wait):
    headers = {"Retry-After": header} if header else {}
    waits = live(monkeypatch, [FakeResp(503, headers=headers), FakeResp(200, {"products": []})])
    assert catalog.search("tent") == []
    assert waits == [wait]


def test_gives_up_after_one_retry(monkeypatch):
    waits = live(monkeypatch, [FakeResp(503), FakeResp(503)])
    with pytest.raises(catalog.CatalogError, match="HTTP 503"):
        catalog.search("tent")
    assert len(waits) == 1


def test_client_error_is_not_retried_and_reports_the_code(monkeypatch):
    body = {"error": {"code": "insufficient_credits", "message": "No credits left."}}
    waits = live(monkeypatch, [FakeResp(402, body)])
    with pytest.raises(catalog.CatalogError, match="insufficient_credits"):
        catalog.search("tent")
    assert waits == []


def test_network_error_and_unexpected_body_become_catalog_errors(monkeypatch):
    monkeypatch.setenv("CHANNEL3_API_KEY", "k")

    def boom(*a, **k):
        raise catalog.httpx.ConnectError("no route")

    monkeypatch.setattr(catalog.httpx, "post", boom)
    with pytest.raises(catalog.CatalogError, match="search failed"):
        catalog.search("tent")
    live(monkeypatch, [FakeResp(200, {"unexpected": []})])
    with pytest.raises(catalog.CatalogError, match="unexpected search response"):
        catalog.search("tent")
