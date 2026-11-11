import pytest

from app import paypal, paypal_mock, store


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Every test gets keyless mode, a fresh SQLite file and an empty PayPal mock."""
    for var in ("LLM_API_KEY", "CHANNEL3_API_KEY", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "APP_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "test.db"))
    store.sessions.clear()
    for d in (paypal_mock.orders, paypal_mock.urls, paypal_mock.responses):
        d.clear()
    paypal._token.update(value=None, expires_at=0.0)
