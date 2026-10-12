"""GeminiBackend retry, key rotation and retry_after with a stubbed client (finding 4.1). No network, no real calls."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from google.genai import errors

from apps.api.llm.gemma import GeminiBackend, LLMRateLimited, TokenBucket


class StubModels:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def generate_content(self, **_: Any) -> Any:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return SimpleNamespace(text=outcome)


def _backend(monkeypatch: pytest.MonkeyPatch, *clients: StubModels) -> GeminiBackend:
    backend = GeminiBackend.__new__(GeminiBackend)
    backend.model = "stub"
    backend.think = False
    backend._clients = [SimpleNamespace(models=c) for c in clients]
    backend._active = 0
    backend._system_ok = backend._json_ok = backend._minimal_ok = None
    backend.bucket = TokenBucket(1_000_000)
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    return backend


def _quota(message: str = "quota exceeded") -> errors.APIError:
    return errors.APIError(429, {"error": {"message": message, "status": "RESOURCE_EXHAUSTED"}})


def _chat(backend: GeminiBackend) -> Any:
    return backend.chat("system", [{"role": "user", "content": "hello"}], temperature=0.0, max_tokens=64, json_mode=False, tools=None)


def test_429_rotates_to_the_second_key_and_succeeds(monkeypatch):
    first, second = StubModels([_quota()]), StubModels(["answer"])
    backend = _backend(monkeypatch, first, second)
    assert _chat(backend).content == "answer"
    assert (first.calls, second.calls) == (1, 1) and backend._active == 1


def test_persistent_429_raises_rate_limited_with_the_servers_retry_hint(monkeypatch):
    stub = StubModels([_quota("Please retry in 17s")] * 10)
    backend = _backend(monkeypatch, stub)
    with pytest.raises(LLMRateLimited) as exc:
        _chat(backend)
    assert exc.value.retry_after == 17.0
    assert stub.calls == GeminiBackend.MAX_TRANSIENT_RETRIES + 1  # bounded, never an endless loop


def test_a_429_without_a_hint_defaults_retry_after_to_thirty_seconds(monkeypatch):
    backend = _backend(monkeypatch, StubModels([_quota()] * 10))
    with pytest.raises(LLMRateLimited) as exc:
        _chat(backend)
    assert exc.value.retry_after == 30.0


def test_an_exhausted_token_budget_refuses_before_any_call(monkeypatch):
    stub = StubModels(["never reached"])
    backend = _backend(monkeypatch, stub)
    backend.bucket = TokenBucket(60, clock=lambda: 0.0, sleep=lambda _s: None)  # 1 token per second, empty after the first call
    backend.bucket.acquire(60)
    with pytest.raises(LLMRateLimited) as exc:
        backend.chat("s" * 4000, [{"role": "user", "content": "x" * 400}], temperature=0.0, max_tokens=64, json_mode=False, tools=None)
    assert exc.value.retry_after > 20 and stub.calls == 0
