"""The only file that calls the model.

Uses the OpenAI-compatible /chat/completions format over plain HTTP, so switching
provider is a config change: LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_EXTRA_BODY.
With no key, callers supply a rule-based `mock` that returns a message of the same shape.
"""
import json
import logging
import os
import threading

import httpx

log = logging.getLogger(__name__)

DEFAULT_TEMPERATURE = 0.0  # used by every call in this app; the eval records it

# Token counts for cost reporting in the eval. Shared by the process; the eval runs one request at a time.
usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
_usage_lock = threading.Lock()  # multi-shuffle ranking (F17) calls the model from several threads


class LLMError(Exception):
    """The model call failed or returned something unusable."""


def enabled() -> bool:
    return bool(os.getenv("LLM_API_KEY"))


def reset_usage() -> None:
    usage.update(calls=0, prompt_tokens=0, completion_tokens=0)


def _extra_body() -> dict:
    raw = os.getenv("LLM_EXTRA_BODY", "").strip()
    if not raw:
        return {}
    try:
        extra = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("LLM_EXTRA_BODY is not valid JSON; ignored")
        return {}
    return extra if isinstance(extra, dict) else {}


def chat(messages: list[dict], tools: list[dict] | None = None, temperature: float = DEFAULT_TEMPERATURE, mock=None) -> dict:
    """Send one chat request and return the assistant message dict unchanged.

    `mock(messages)` is used when no key is configured. Raises LLMError on any failure.
    """
    with _usage_lock:
        usage["calls"] += 1
    if not enabled():
        if mock is None:
            raise LLMError("no LLM_API_KEY and no mock given")
        return mock(messages)

    body = {"model": os.getenv("LLM_MODEL", ""), "messages": messages, "temperature": temperature}
    if tools:
        body["tools"] = tools
    body.update(_extra_body())
    base = os.getenv("LLM_BASE_URL", "").rstrip("/")
    headers = {"Authorization": f"Bearer {os.getenv('LLM_API_KEY')}"}
    try:
        resp = httpx.post(f"{base}/chat/completions", json=body, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        message = data["choices"][0]["message"]
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        raise LLMError(f"model call failed: {e}") from e

    # A missing usage field is recorded as 0 instead of failing the request.
    u = data.get("usage") or {}
    with _usage_lock:
        usage["prompt_tokens"] += u.get("prompt_tokens") or 0
        usage["completion_tokens"] += u.get("completion_tokens") or 0
    return message


def ask(messages: list[dict], parse, fallback, tools=None, temperature: float = DEFAULT_TEMPERATURE, mock=None):
    """Call the model and validate the reply with `parse`, which raises ValueError on a format error.

    One retry, then `fallback` is returned, so bad model output never crashes a request.
    """
    for attempt in (1, 2):
        try:
            return parse(chat(messages, tools, temperature, mock))
        except (LLMError, ValueError) as e:
            log.warning("model reply rejected (attempt %d): %s", attempt, e)
    return fallback
