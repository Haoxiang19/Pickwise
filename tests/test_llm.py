import httpx
import pytest

from app import llm
from app.money import to_cents, to_dollars


class FakeResponse:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad", request=None, response=None)

    def json(self):
        return self.data


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.invalid/v1/")
    monkeypatch.setenv("LLM_MODEL", "m")
    llm.reset_usage()


def test_mock_used_without_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    msg = llm.chat([{"role": "user", "content": "hi"}], mock=lambda m: {"role": "assistant", "content": "mocked"})
    assert msg["content"] == "mocked"


def test_extra_body_merged_and_message_returned_unchanged(keyed, monkeypatch):
    monkeypatch.setenv("LLM_EXTRA_BODY", '{"thinking": {"type": "disabled"}}')
    sent = {}
    message = {"role": "assistant", "content": "ok", "reasoning_content": "kept"}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, body=json)
        return FakeResponse({"choices": [{"message": message}], "usage": {"prompt_tokens": 5, "completion_tokens": 2}})

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    assert llm.chat([{"role": "user", "content": "x"}]) == message
    assert sent["url"] == "https://example.invalid/v1/chat/completions"
    assert sent["body"]["thinking"] == {"type": "disabled"}
    assert llm.usage == {"calls": 1, "prompt_tokens": 5, "completion_tokens": 2}


def test_missing_usage_counts_zero(keyed, monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: FakeResponse({"choices": [{"message": {"content": "x"}}]}))
    llm.chat([])
    assert llm.usage["prompt_tokens"] == 0 and llm.usage["completion_tokens"] == 0


def test_http_error_becomes_llm_error(keyed, monkeypatch):
    monkeypatch.setattr(llm.httpx, "post", lambda *a, **k: FakeResponse({}, status=500))
    with pytest.raises(llm.LLMError):
        llm.chat([])


def test_ask_retries_once_then_falls_back(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    replies = iter(["   ", "good"])

    def parse(msg):
        if not msg["content"].strip():
            raise ValueError("blank")
        return msg["content"]

    mock = lambda m: {"role": "assistant", "content": next(replies)}
    assert llm.ask([], parse, fallback="fb", mock=mock) == "good"
    always_blank = lambda m: {"role": "assistant", "content": ""}
    assert llm.ask([], parse, fallback="fb", mock=always_blank) == "fb"


def test_money_conversion():
    assert to_cents("12.34") == 1234
    assert to_cents(19.99) == 1999
    assert to_cents("5") == 500
    assert to_dollars(1234) == "12.34" and to_dollars(5) == "0.05"
    for bad in ("12.345", "abc", "NaN"):
        with pytest.raises(ValueError):
            to_cents(bad)
