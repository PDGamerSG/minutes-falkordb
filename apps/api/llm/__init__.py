"""LLM client factory. ``make_llm(settings)`` returns the real client or the demo fake."""

from __future__ import annotations

from typing import Any

from ingest.llm_protocol import LLMFormatError

from ..config import Settings, get_settings
from .fake import FakeLLM
from .gemma import LLM, LLMError, LLMRateLimited, ToolLoopResult, ToolSpec

__all__ = ["LLM", "FakeLLM", "LLMError", "LLMFormatError", "LLMRateLimited", "ToolLoopResult", "ToolSpec", "llm_from_env", "make_llm"]


def make_llm(settings: Settings | None = None) -> Any:
    """Build the client selected by ``LLM_BACKEND``; ``fake`` wires the deterministic demo policies."""
    settings = settings or get_settings()
    backend = settings.llm_backend.lower()
    if backend == "fake":
        from ..agents.fake_policy import fake_json_policy, fake_text_policy, fake_tool_policy

        return FakeLLM(json_policy=fake_json_policy, text_policy=fake_text_policy, tool_policy=fake_tool_policy)
    return LLM(
        backend,
        settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        max_tokens=settings.llm_max_tokens,
        timeout_s=settings.llm_timeout_s,
        think=False,
        tpm_budget=getattr(settings, "gemini_tpm_budget", None),
    )


def llm_from_env() -> Any:
    """Entry point used by ``python -m ingest.eval --llm-factory apps.api.llm:llm_from_env``."""
    get_settings.cache_clear()
    return make_llm(get_settings())
