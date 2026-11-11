import pytest

from app import checkout, paypal, paypal_mock, store

BASE = "http://test"


def session_with_cart(price=2500, quantity=1):
    s = store.Session()
    s.products["p1"] = {"id": "p1", "title": "Mat", "price_cents": price, "in_stock": True, "currency": "USD"}
    return s, store.create_cart(s, "p1", quantity, fetch=s.products.get)


# --- F9, F10 Confirm ---

def test_confirm_creates_row_then_paypal_order():
    s, cart = session_with_cart(price=1999, quantity=2)
    order = checkout.confirm(s, "u1", cart["id"], BASE)
    assert order["status"] == "CREATED" and order["amount_cents"] == 3998 and order["currency"] == "USD"
    assert order["items"] == cart["items"] and order["cart_id"] == cart["id"]
    pp = paypal_mock.orders[order["paypal_order_id"]]
    assert pp["purchase_units"][0]["amount"] == {"currency_code": "USD", "value": "39.98",
                                                 "breakdown": {"item_total": {"currency_code": "USD", "value": "39.98"}}}
    # F21: PayPal receives the order row's items as line items.
    assert pp["purchase_units"][0]["items"] == [
        {"name": "Mat", "quantity": "2", "unit_amount": {"currency_code": "USD", "value": "19.99"}}]
    assert paypal_mock.urls[pp["id"]] == {"return_url": f"{BASE}/paypal/return?order_id={order['id']}",
                                         "cancel_url": f"{BASE}/paypal/cancel?order_id={order['id']}"}
    assert f"create-{cart['id']}" in paypal_mock.responses
    assert order["approval_url"].startswith("/mock-paypal/checkout?token=")


def test_confirm_sends_the_order_rows_items_for_a_two_item_cart(monkeypatch):
    s = store.Session()
    for pid, price in (("a", 1500), ("b", 250)):
        s.products[pid] = {"id": pid, "title": pid.upper(), "price_cents": price, "in_stock": True, "currency": "USD"}
    cart = store.create_cart_items(s, [("a", 1), ("b", 4)], fetch=s.products.get)
    sent = []
    real = checkout.paypal.create_order
    monkeypatch.setattr(checkout.paypal, "create_order", lambda *a, **kw: sent.append(kw) or real(*a, **kw))
    order = checkout.confirm(s, "u1", cart["id"], BASE)
    assert sent[0]["items"] == order["items"] and order["amount_cents"] == 2500
    pp = paypal_mock.orders[order["paypal_order_id"]]["purchase_units"][0]
    assert [(i["name"], i["quantity"]) for i in pp["items"]] == [("A", "1"), ("B", "4")]


def test_second_confirm_returns_same_order_and_link():
    s, cart = session_with_cart()
    first = checkout.confirm(s, "u1", cart["id"], BASE)
    second = checkout.confirm(s, "u1", cart["id"], BASE)
    assert second["id"] == first["id"] and second["approval_url"] == first["approval_url"]
    assert len(paypal_mock.orders) == 1 and len(store.list_orders("u1")) == 1


def test_expired_or_foreign_cart_is_refused():
    s, cart = session_with_cart()
    cart["expires_at"] = 0
    with pytest.raises(store.CartError, match="expired"):
        checkout.confirm(s, "u1", cart["id"], BASE)
    with pytest.raises(store.CartError, match="Unknown cart"):
        checkout.confirm(store.Session(), "u2", cart["id"], BASE)
    assert store.list_orders("u1") == []


def test_paypal_create_failure_keeps_row_and_retry_uses_same_request_id(monkeypatch):
    s, cart = session_with_cart()
    seen = []

    def failing(*args, request_id, **kwargs):
        seen.append(request_id)
        raise paypal.PayPalError("NETWORK_ERROR")

    monkeypatch.setattr(checkout.paypal, "create_order", failing)
    for _ in range(2):
        with pytest.raises(checkout.CheckoutError, match="Nothing was charged"):
            checkout.confirm(s, "u1", cart["id"], BASE)
    [row] = store.list_orders("u1")
    assert row["status"] == "CREATED" and row["paypal_order_id"] is None
    assert seen == [f"create-{cart['id']}"] * 2


def test_confirm_refused_when_order_no_longer_created():
    s, cart = session_with_cart()
    order = checkout.confirm(s, "u1", cart["id"], BASE)
    store.update_order(order["id"], status="CANCELLED")
    with pytest.raises(checkout.CheckoutError, match="choose the product again"):
        checkout.confirm(s, "u1", cart["id"], BASE)


def test_orders_are_private_to_their_user():
    s, cart = session_with_cart()
    order = checkout.confirm(s, "u1", cart["id"], BASE)
    assert store.get_order(order["id"], "u2") is None
    assert store.get_order_by_cart(cart["id"], "u2") is None


# --- F11 Verify then capture, F13 cancel and failure, F14 result ---

def approved_order(price=2500):
    s, cart = session_with_cart(price=price)
    order = checkout.confirm(s, "u1", cart["id"], BASE)
    paypal_mock.approve(order["paypal_order_id"])
    return order


def fail_if_called(*args, **kwargs):
    raise AssertionError("PayPal must not be called")


def test_return_after_approval_captures_once():
    order = approved_order()
    done = checkout.handle_return("u1", order["id"])
    assert done["status"] == "COMPLETED" and done["capture_id"].startswith("MOCKCAP-")
    assert f"capture-{order['id']}" in paypal_mock.responses
    assert checkout.order_view(done)["message"] == "Payment successful."


def test_refresh_after_result_does_not_call_paypal(monkeypatch):
    order = approved_order()
    checkout.handle_return("u1", order["id"])
    monkeypatch.setattr(checkout.paypal, "get_order", fail_if_called)
    monkeypatch.setattr(checkout.paypal, "capture_order", fail_if_called)
    assert checkout.handle_return("u1", order["id"])["status"] == "COMPLETED"


def test_not_approved_is_cancelled_and_not_captured(monkeypatch):
    s, cart = session_with_cart()
    order = checkout.confirm(s, "u1", cart["id"], BASE)  # buyer never approved
    monkeypatch.setattr(checkout.paypal, "capture_order", fail_if_called)
    out = checkout.handle_return("u1", order["id"])
    assert out["status"] == "CANCELLED" and "Nothing was charged" in checkout.order_view(out)["message"]


@pytest.mark.parametrize("field,value", [("value", "24.99"), ("value", "250.00"), ("currency_code", "EUR"), ("value", "abc")])
def test_amount_or_currency_mismatch_is_not_captured(monkeypatch, field, value):
    order = approved_order(price=2500)
    paypal_mock.orders[order["paypal_order_id"]]["purchase_units"][0]["amount"][field] = value
    monkeypatch.setattr(checkout.paypal, "capture_order", fail_if_called)
    assert checkout.handle_return("u1", order["id"])["status"] == "AMOUNT_MISMATCH"


@pytest.mark.parametrize("issue,status,text", [
    ("INSTRUMENT_DECLINED", "CAPTURE_FAILED", "declined"),
    ("ORDER_NOT_APPROVED", "CANCELLED", "not approved"),
    ("SOMETHING_ELSE", "CAPTURE_FAILED", "SOMETHING_ELSE"),
])
def test_capture_errors_map_to_status(monkeypatch, issue, status, text):
    order = approved_order()

    def failing(*args):
        raise paypal.PayPalError(issue)

    monkeypatch.setattr(checkout.paypal, "capture_order", failing)
    out = checkout.handle_return("u1", order["id"])
    assert out["status"] == status and text in out["note"]
    assert out["capture_id"] is None


def test_capture_status_other_than_completed_is_not_paid(monkeypatch):
    order = approved_order()
    pending = {"purchase_units": [{"payments": {"captures": [{"id": "C1", "status": "PENDING"}]}}], "status": "COMPLETED"}
    monkeypatch.setattr(checkout.paypal, "capture_order", lambda *a: pending)
    out = checkout.handle_return("u1", order["id"])
    assert out["status"] == "CAPTURE_FAILED" and "PENDING" in out["note"]


def test_already_captured_reads_back_real_state(monkeypatch):
    order = approved_order()
    pp_id = order["paypal_order_id"]
    stale = paypal_mock.get_order(pp_id)  # APPROVED, as read before the lost capture
    paypal_mock.capture_order(pp_id, "earlier-attempt")  # captured at PayPal, result never stored locally
    reads = iter([stale, paypal_mock.get_order(pp_id)])
    monkeypatch.setattr(checkout.paypal, "get_order", lambda _id: next(reads))
    monkeypatch.setattr(checkout.paypal, "capture_order", lambda *a: paypal_mock.capture_order(pp_id, "new-request"))
    out = checkout.handle_return("u1", order["id"])  # capture raises ORDER_ALREADY_CAPTURED, then reads back
    assert out["status"] == "COMPLETED" and out["capture_id"].startswith("MOCKCAP-")


def test_completed_on_readback_is_recorded_without_capture(monkeypatch):
    order = approved_order()
    paypal_mock.capture_order(order["paypal_order_id"], "earlier-attempt")
    monkeypatch.setattr(checkout.paypal, "capture_order", fail_if_called)
    assert checkout.handle_return("u1", order["id"])["status"] == "COMPLETED"


def test_network_error_keeps_order_open_then_retry_succeeds(monkeypatch):
    order = approved_order()
    network = {"down": True}
    real_capture = checkout.paypal.capture_order

    def flaky(*args):
        if network["down"]:
            raise paypal.PayPalError("NETWORK_ERROR")
        return real_capture(*args)

    monkeypatch.setattr(checkout.paypal, "capture_order", flaky)
    out = checkout.handle_return("u1", order["id"])
    assert out["status"] == "CREATED" and "Could not reach PayPal" in out["note"]
    network["down"] = False
    assert checkout.handle_return("u1", order["id"])["status"] == "COMPLETED"


def test_capture_window_of_three_hours(monkeypatch):
    order = approved_order()
    monkeypatch.setattr(checkout.time, "time", lambda: order["created_at"] + 3 * 3600 + 1)
    monkeypatch.setattr(checkout.paypal, "get_order", fail_if_called)
    out = checkout.handle_return("u1", order["id"])
    assert out["status"] == "CAPTURE_FAILED" and "3 hours" in out["note"]


def test_cancel_marks_cancelled_only_from_created():
    s, cart = session_with_cart()
    order = checkout.confirm(s, "u1", cart["id"], BASE)
    assert checkout.handle_cancel("u1", order["id"])["status"] == "CANCELLED"
    paid = approved_order()
    checkout.handle_return("u1", paid["id"])
    assert checkout.handle_cancel("u1", paid["id"])["status"] == "COMPLETED"


def test_other_user_cannot_return_or_cancel():
    order = approved_order()
    for fn in (checkout.handle_return, checkout.handle_cancel):
        with pytest.raises(checkout.CheckoutError):
            fn("intruder", order["id"])
    assert store.get_order(order["id"], "u1")["status"] == "CREATED"


# --- F16 refund ---

def paid(price=2500):
    order = approved_order(price)
    return checkout.handle_return("u1", order["id"])


def test_refund_after_confirm_marks_refunded_once(monkeypatch):
    order = paid()
    draft = checkout.refund_draft("u1", order["id"])
    assert draft["amount_cents"] == 2500 and store.get_order(order["id"], "u1")["status"] == "COMPLETED"
    done = checkout.refund("u1", order["id"])
    # F23: a single-item order is one line, refunded by one call for the full amount.
    assert done["status"] == "REFUNDED" and done["items"][0]["refund_id"].startswith("MOCKREF-")
    assert paypal_mock.responses[f"refund-{order['id']}-1"]["amount"] == {"value": "25.00", "currency_code": "USD"}
    monkeypatch.setattr(checkout.paypal, "refund_capture", fail_if_called)
    with pytest.raises(checkout.CheckoutError, match="already refunded"):
        checkout.refund("u1", order["id"])
    with pytest.raises(checkout.CheckoutError, match="already refunded"):
        checkout.refund_draft("u1", order["id"])


def test_refund_only_for_own_paid_orders(monkeypatch):
    monkeypatch.setattr(checkout.paypal, "refund_capture", fail_if_called)
    s, cart = session_with_cart()
    unpaid = checkout.confirm(s, "u1", cart["id"], BASE)
    with pytest.raises(checkout.CheckoutError, match="Only paid orders"):
        checkout.refund("u1", unpaid["id"])
    order = paid()
    with pytest.raises(checkout.CheckoutError, match="not found"):
        checkout.refund("intruder", order["id"])


def test_refund_failure_or_pending_leaves_order_paid(monkeypatch):
    order = paid()

    def failing(*args):
        raise paypal.PayPalError("REFUND_FAILED_INSUFFICIENT_FUNDS")

    monkeypatch.setattr(checkout.paypal, "refund_capture", failing)
    # F23: the failure is reported on the order (a multi-line refund may have refunded earlier lines).
    out = checkout.refund("u1", order["id"])
    assert out["status"] == "COMPLETED" and "Line 1 (Mat) was not refunded (REFUND_FAILED_INSUFFICIENT_FUNDS)" in out["note"]
    monkeypatch.setattr(checkout.paypal, "refund_capture", lambda *a: {"id": "R1", "status": "PENDING"})
    out = checkout.refund("u1", order["id"])
    assert out["status"] == "COMPLETED" and "PENDING" in out["note"] and "refund_id" not in out["items"][0]


def test_simultaneous_refund_clicks_call_paypal_once(monkeypatch):
    import threading
    import time as _time
    order = paid()
    calls = []
    real = checkout.paypal.refund_capture

    def slow(*args):
        calls.append(args)
        _time.sleep(0.05)
        return real(*args)

    monkeypatch.setattr(checkout.paypal, "refund_capture", slow)
    threads = [threading.Thread(target=lambda: _try_refund(order["id"])) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and store.get_order(order["id"], "u1")["status"] == "REFUNDED"


# --- F23 refund by line ---

def paid_two_lines(prices=(1500, 250), quantities=(1, 4)):
    """A paid order with two lines: 1 x A at $15.00 and 4 x B at $2.50 (total $25.00)."""
    s = store.Session()
    for pid, price in zip("ab", prices):
        s.products[pid] = {"id": pid, "title": pid.upper(), "price_cents": price, "in_stock": True, "currency": "USD"}
    cart = store.create_cart_items(s, list(zip("ab", quantities)), fetch=s.products.get)
    order = checkout.confirm(s, "u1", cart["id"], BASE)
    paypal_mock.approve(order["paypal_order_id"])
    return checkout.handle_return("u1", order["id"])


def recording(monkeypatch):
    calls = []
    real = checkout.paypal.refund_capture
    monkeypatch.setattr(checkout.paypal, "refund_capture", lambda *a: calls.append(a) or real(*a))
    return calls


def test_one_line_then_the_other(monkeypatch):
    order = paid_two_lines()
    calls = recording(monkeypatch)
    first = checkout.refund("u1", order["id"], [2])
    assert first["status"] == "PARTIALLY_REFUNDED"
    assert calls == [(order["capture_id"], f"refund-{order['id']}-2", 1000, "USD")]
    assert "refund_id" in first["items"][1] and "refund_id" not in first["items"][0]
    view = checkout.order_view(first)
    assert view["refunded_cents"] == 1000 and [i["refunded"] for i in view["items"]] == [False, True]
    second = checkout.refund("u1", order["id"], [1])
    assert second["status"] == "REFUNDED" and calls[1][1:] == (f"refund-{order['id']}-1", 1500, "USD")


def test_same_line_twice_is_refused_without_calling_paypal(monkeypatch):
    order = paid_two_lines()
    checkout.refund("u1", order["id"], [1])
    monkeypatch.setattr(checkout.paypal, "refund_capture", fail_if_called)
    with pytest.raises(checkout.CheckoutError, match="Line 1 of order .* already refunded"):
        checkout.refund("u1", order["id"], [1])
    with pytest.raises(checkout.CheckoutError, match="no line 3"):
        checkout.refund_draft("u1", order["id"], [3])
    with pytest.raises(checkout.CheckoutError, match="at least one line"):
        checkout.refund_draft("u1", order["id"], [])


def test_all_remaining_lines_make_one_call_per_line(monkeypatch):
    order = paid_two_lines()
    draft = checkout.refund_draft("u1", order["id"])
    assert [(l["line"], l["amount_cents"]) for l in draft["lines"]] == [(1, 1500), (2, 1000)] and draft["amount_cents"] == 2500
    calls = recording(monkeypatch)
    done = checkout.refund("u1", order["id"])
    assert done["status"] == "REFUNDED" and [c[1] for c in calls] == [f"refund-{order['id']}-1", f"refund-{order['id']}-2"]
    # The refunded lines add up to the order amount, and the mock agrees nothing is left to refund.
    assert sum(c[2] for c in calls) == order["amount_cents"]
    with pytest.raises(paypal.PayPalError, match="CAPTURE_FULLY_REFUNDED"):
        paypal.refund_capture(order["capture_id"], "refund-extra", 1, "USD")


def test_failure_on_the_second_line_keeps_the_first_and_retry_reuses_the_request_id(monkeypatch):
    order = paid_two_lines()
    real = checkout.paypal.refund_capture
    seen = []

    def second_fails_once(capture_id, request_id, amount, currency):
        seen.append(request_id)
        if request_id.endswith("-2") and seen.count(request_id) == 1:
            raise paypal.PayPalError("NETWORK_ERROR")
        return real(capture_id, request_id, amount, currency)

    monkeypatch.setattr(checkout.paypal, "refund_capture", second_fails_once)
    out = checkout.refund("u1", order["id"])
    assert out["status"] == "PARTIALLY_REFUNDED" and "Line 2 (B) was not refunded (NETWORK_ERROR)" in out["note"]
    retry = checkout.refund("u1", order["id"])
    assert retry["status"] == "REFUNDED" and retry["note"] == ""
    assert seen == [f"refund-{order['id']}-1", f"refund-{order['id']}-2", f"refund-{order['id']}-2"]


def test_simultaneous_clicks_on_a_two_line_order_make_one_call_per_line(monkeypatch):
    import threading
    order = paid_two_lines()
    calls = recording(monkeypatch)
    threads = [threading.Thread(target=lambda: _try_refund(order["id"])) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(c[1] for c in calls) == [f"refund-{order['id']}-1", f"refund-{order['id']}-2"]
    assert store.get_order(order["id"], "u1")["status"] == "REFUNDED"


def test_mock_refuses_a_refund_larger_than_what_is_left():
    order = paid_two_lines()
    paypal.refund_capture(order["capture_id"], "r-a", 2000, "USD")
    with pytest.raises(paypal.PayPalError, match="REFUND_AMOUNT_EXCEEDED"):
        paypal.refund_capture(order["capture_id"], "r-b", 501, "USD")


def test_refund_by_line_only_for_own_orders(monkeypatch):
    order = paid_two_lines()
    monkeypatch.setattr(checkout.paypal, "refund_capture", fail_if_called)
    with pytest.raises(checkout.CheckoutError, match="not found"):
        checkout.refund("intruder", order["id"], [1])


def _try_refund(order_id):
    try:
        checkout.refund("u1", order_id)
    except checkout.CheckoutError:
        pass
