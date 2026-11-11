"""F12: repeated clicks or refreshes never create a second order or capture."""
import threading
import time

from app import checkout, paypal_mock, store


def setup_cart():
    s = store.Session()
    s.products["p1"] = {"id": "p1", "title": "Mat", "price_cents": 2500, "in_stock": True, "currency": "USD"}
    return s, store.create_cart(s, "p1", fetch=s.products.get)


def run_in_threads(fn, n=5):
    results, errors = [], []

    def worker():
        try:
            results.append(fn())
        except Exception as e:  # noqa: BLE001 - collected and asserted below
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, errors


def slow(fn, calls):
    """Wrap a PayPal call so it is slow and counted, to give a race a chance to happen."""
    def wrapper(*args, **kwargs):
        calls.append(args)
        time.sleep(0.05)
        return fn(*args, **kwargs)
    return wrapper


def test_simultaneous_confirms_create_one_order(monkeypatch):
    s, cart = setup_cart()
    calls = []
    monkeypatch.setattr(checkout.paypal, "create_order", slow(checkout.paypal.create_order, calls))
    results, errors = run_in_threads(lambda: checkout.confirm(s, "u1", cart["id"], "http://t"))
    assert errors == [] and len(calls) == 1
    assert len({r["id"] for r in results}) == 1 and len({r["approval_url"] for r in results}) == 1
    assert len(store.list_orders("u1")) == 1 and len(paypal_mock.orders) == 1


def test_simultaneous_returns_capture_once(monkeypatch):
    s, cart = setup_cart()
    order = checkout.confirm(s, "u1", cart["id"], "http://t")
    paypal_mock.approve(order["paypal_order_id"])
    calls = []
    monkeypatch.setattr(checkout.paypal, "capture_order", slow(checkout.paypal.capture_order, calls))
    results, errors = run_in_threads(lambda: checkout.handle_return("u1", order["id"]))
    assert errors == [] and len(calls) == 1
    assert {r["status"] for r in results} == {"COMPLETED"}


def test_repeated_capture_request_id_returns_same_capture():
    """Second guard: even if the local check were bypassed, the same request ID gives the same capture."""
    s, cart = setup_cart()
    order = checkout.confirm(s, "u1", cart["id"], "http://t")
    paypal_mock.approve(order["paypal_order_id"])
    first = paypal_mock.capture_order(order["paypal_order_id"], f"capture-{order['id']}")
    again = paypal_mock.capture_order(order["paypal_order_id"], f"capture-{order['id']}")
    assert first == again


def test_a_slow_paypal_call_on_one_order_does_not_block_another_order(monkeypatch):
    """The lock is per order: while order A waits on PayPal, order B can be captured."""
    s, cart_a = setup_cart()
    order_a = checkout.confirm(s, "u1", cart_a["id"], "http://t")
    cart_b = store.create_cart(s, "p1", fetch=s.products.get)
    order_b = checkout.confirm(s, "u2", cart_b["id"], "http://t")
    for o in (order_a, order_b):
        paypal_mock.approve(o["paypal_order_id"])
    a_waiting, release_a = threading.Event(), threading.Event()
    real = checkout.paypal.capture_order

    def capture(pp_id, request_id):
        if pp_id == order_a["paypal_order_id"]:
            a_waiting.set()
            assert release_a.wait(5)  # order A's capture hangs until the test releases it
        return real(pp_id, request_id)

    monkeypatch.setattr(checkout.paypal, "capture_order", capture)
    thread_a = threading.Thread(target=lambda: checkout.handle_return("u1", order_a["id"]))
    thread_a.start()
    assert a_waiting.wait(5)
    try:
        assert checkout.handle_return("u2", order_b["id"])["status"] == "COMPLETED"  # not blocked by A
    finally:
        release_a.set()
        thread_a.join()
    assert store.get_order(order_a["id"], "u1")["status"] == "COMPLETED"


def test_new_cart_after_cancel_gets_new_order():
    s, cart = setup_cart()
    order = checkout.confirm(s, "u1", cart["id"], "http://t")
    checkout.handle_cancel("u1", order["id"])
    new_cart = store.create_cart(s, "p1", fetch=s.products.get)
    new_order = checkout.confirm(s, "u1", new_cart["id"], "http://t")
    assert new_order["id"] != order["id"] and new_order["status"] == "CREATED"
