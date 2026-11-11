import json

import pytest

from app import paypal


class Resp:
    def __init__(self, status, data):
        self.status_code, self.data = status, data
        self.content = json.dumps(data).encode() if data is not None else b""

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


@pytest.fixture
def live(monkeypatch):
    """Real-mode code path with fake HTTP: records requests instead of calling PayPal."""
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "secret")
    calls = {"token": 0, "requests": [], "replies": []}

    def fake_post(url, data, auth, timeout):
        calls["token"] += 1
        assert url == "https://api-m.sandbox.paypal.com/v1/oauth2/token"
        assert data == {"grant_type": "client_credentials"} and auth == ("id", "secret")
        return Resp(200, {"access_token": "tok", "expires_in": 32400})

    def fake_request(method, url, headers, json, timeout):
        calls["requests"].append({"method": method, "url": url, "headers": headers, "json": json})
        return calls["replies"].pop(0)

    monkeypatch.setattr(paypal.httpx, "post", fake_post)
    monkeypatch.setattr(paypal.httpx, "request", fake_request)
    return calls


def test_base_url_is_sandbox_constant():
    assert paypal.BASE_URL == "https://api-m.sandbox.paypal.com"
    source = open(paypal.__file__, encoding="utf-8").read()
    assert 'BASE_URL = "https://api-m.sandbox.paypal.com"' in source


def test_create_order_request_and_payer_action_link(live):
    live["replies"].append(Resp(200, {"id": "PP1", "status": "PAYER_ACTION_REQUIRED",
                                      "links": [{"rel": "self", "href": "x"}, {"rel": "payer-action", "href": "https://pay"}]}))
    out = paypal.create_order(1234, "USD", [item(1234)], "create-cart_1", "https://app/r", "https://app/c")
    assert out == {"id": "PP1", "approve_url": "https://pay"}
    req = live["requests"][0]
    assert req["url"] == "https://api-m.sandbox.paypal.com/v2/checkout/orders"
    assert req["headers"]["PayPal-Request-Id"] == "create-cart_1" and req["headers"]["Authorization"] == "Bearer tok"
    assert req["json"]["purchase_units"][0]["amount"] == {
        "currency_code": "USD", "value": "12.34", "breakdown": {"item_total": {"currency_code": "USD", "value": "12.34"}}}
    ctx = req["json"]["payment_source"]["paypal"]["experience_context"]
    assert ctx == {"return_url": "https://app/r", "cancel_url": "https://app/c",
                   "user_action": "PAY_NOW", "shipping_preference": "NO_SHIPPING"}


def test_token_is_cached(live):
    live["replies"] += [Resp(200, {"id": "A"}), Resp(200, {"id": "A"})]
    paypal.get_order("A")
    paypal.get_order("A")
    assert live["token"] == 1


def test_capture_and_refund_send_empty_body_and_request_id(live):
    live["replies"] += [Resp(201, {"id": "PP1"}), Resp(201, {"id": "R1", "status": "COMPLETED"})]
    paypal.capture_order("PP1", "capture-7")
    paypal.refund_capture("CAP1", "refund-7")
    cap, ref = live["requests"]
    assert cap["url"].endswith("/v2/checkout/orders/PP1/capture") and cap["json"] == {}
    assert cap["headers"]["PayPal-Request-Id"] == "capture-7"
    assert ref["url"].endswith("/v2/payments/captures/CAP1/refund") and ref["json"] == {}
    assert ref["headers"]["PayPal-Request-Id"] == "refund-7"


def test_errors_carry_paypal_issue(live):
    live["replies"] += [
        Resp(422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "INSTRUMENT_DECLINED"}]}),
        Resp(404, {"name": "RESOURCE_NOT_FOUND"}),
        Resp(503, None),
    ]
    for expected in ("INSTRUMENT_DECLINED", "RESOURCE_NOT_FOUND", "NETWORK_ERROR"):
        with pytest.raises(paypal.PayPalError) as e:
            paypal.capture_order("PP1", "capture-1")
        assert e.value.issue == expected


def test_missing_payer_action_link_is_an_error(live):
    live["replies"].append(Resp(200, {"id": "PP1", "links": [{"rel": "approve", "href": "x"}]}))
    with pytest.raises(paypal.PayPalError, match="NO_APPROVAL_LINK"):
        paypal.create_order(100, "USD", [item(100)], "r", "a", "b")


# --- F21 line items in the create body ---

def item(unit_cents, quantity=1, title="Mat"):
    return {"product_id": "p", "title": title, "unit_price_cents": unit_cents, "quantity": quantity}


def ok_reply():
    return Resp(200, {"id": "PP1", "links": [{"rel": "payer-action", "href": "https://pay"}]})


def test_create_body_for_a_two_item_order(live):
    live["replies"].append(ok_reply())
    paypal.create_order(5997, "USD", [item(1999, 2, "Tent"), item(1999, 1, "Lamp")], "r", "a", "b")
    unit = live["requests"][0]["json"]["purchase_units"][0]
    assert unit["amount"]["value"] == "59.97" and unit["amount"]["breakdown"]["item_total"]["value"] == "59.97"
    assert unit["items"] == [
        {"name": "Tent", "quantity": "2", "unit_amount": {"currency_code": "USD", "value": "19.99"}},
        {"name": "Lamp", "quantity": "1", "unit_amount": {"currency_code": "USD", "value": "19.99"}},
    ]
    assert all(isinstance(i["quantity"], str) for i in unit["items"])


def test_long_title_is_cut_to_paypal_limit(live):
    live["replies"].append(ok_reply())
    paypal.create_order(100, "USD", [item(100, title="x" * 300)], "r", "a", "b")
    assert len(live["requests"][0]["json"]["purchase_units"][0]["items"][0]["name"]) == paypal.ITEM_NAME_MAX == 127


@pytest.mark.parametrize("items", [[item(1000, 3)], [item(1000), item(999)], []])
def test_sum_mismatch_sends_nothing(live, items):
    with pytest.raises(paypal.PayPalError) as e:
        paypal.create_order(2000, "USD", items, "r", "a", "b")
    assert e.value.issue == "ITEM_TOTAL_MISMATCH" and live["requests"] == []


def test_mock_rejects_bodies_that_break_the_sum_rules():
    from app import paypal_mock
    ctx = {"paypal": {"experience_context": {"return_url": "r", "cancel_url": "c"}}}
    usd = lambda v: {"currency_code": "USD", "value": v}
    line = {"name": "Mat", "quantity": "2", "unit_amount": usd("5.00")}
    cases = {
        "ITEM_TOTAL_REQUIRED": {"amount": usd("10.00"), "items": [line]},
        "ITEM_TOTAL_MISMATCH": {"amount": {**usd("9.00"), "breakdown": {"item_total": usd("9.00")}}, "items": [line]},
        "AMOUNT_MISMATCH": {"amount": {**usd("12.00"), "breakdown": {"item_total": usd("10.00")}}, "items": [line]},
    }
    for issue, unit in cases.items():
        with pytest.raises(paypal.PayPalError) as e:
            paypal_mock.create_order({"purchase_units": [unit], "payment_source": ctx}, "req-" + issue)
        assert e.value.issue == issue
    assert paypal_mock.orders == {}
