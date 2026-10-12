"""Process-wide Gemini token budget (finding 4.1) and the per-task agent deadline (4.3)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from apps.api.agents.base import BaseAgent
from apps.api.llm.gemma import LLMError, LLMRateLimited, TokenBucket, estimate_tokens, shared_token_bucket


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def test_bucket_queues_then_refuses_with_retry_after():
    clock = Clock()
    bucket = TokenBucket(600, clock=clock, sleep=clock.sleep)  # 10 tokens per second
    assert bucket.acquire(600) == 0.0
    assert bucket.available == 0.0
    waited = bucket.acquire(50, max_wait=20.0)  # 5 s of refill: queued, not refused
    assert 4.9 <= waited <= 5.5
    with pytest.raises(LLMRateLimited) as exc:
        bucket.acquire(600, max_wait=20.0)  # 60 s needed, over the 20 s ceiling
    assert 55.0 <= exc.value.retry_after <= 60.0
    assert isinstance(exc.value, LLMError)
    assert bucket.acquire(5000, max_wait=120.0) == pytest.approx(60.0, abs=1.0)  # requests above the capacity are capped at it


def test_estimate_and_shared_bucket():
    assert estimate_tokens("a" * 400, "b" * 400) == 200 and estimate_tokens("") == 1
    assert shared_token_bucket(14000) is shared_token_bucket(14000)
    assert shared_token_bucket(14000) is not shared_token_bucket(7000)
    assert bucket_wait_is_zero_when_full()


def bucket_wait_is_zero_when_full() -> bool:
    return TokenBucket(100).wait_for(50) == 0.0


class SleepyLLM:
    backend = "sleepy"
    model = "sleepy"

    def tool_loop(self, system: str, messages: list[dict[str, Any]], tools: Any, execute: Any, max_steps: int = 6):
        time.sleep(1.0)
        raise AssertionError("the loop should have been abandoned")


class Settings:
    agent_task_deadline_s = 0.2
    github_token = None
    github_demo_repo = None


def test_agent_run_fails_fast_when_the_task_deadline_passes(seeded):
    agent = BaseAgent("orbit", seeded.hive, SleepyLLM(), seeded.embedder, Settings())
    agent.tool_names = ["finish"]
    agent.prompt_name = "followup"
    started = time.perf_counter()
    result = agent.run({"id": "task_x", "kind": "followup", "payload": {}})
    assert time.perf_counter() - started < 0.9
    assert result.failed and "deadline" in result.reason and result.model == "sleepy"
