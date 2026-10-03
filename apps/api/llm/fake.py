"""Scripted LLM for tests and model-free demos: the ingest fake plus a JSON-protocol tool loop."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable
from typing import Any

from ingest.llm_protocol import _MISSING
from ingest.llm_protocol import FakeLLM as _BaseFakeLLM
from pydantic import BaseModel

from .gemma import ExecuteFn, ToolLoopResult, ToolSpec, run_json_protocol_loop

ToolPolicy = Callable[[str, list[dict[str, Any]], list[ToolSpec]], dict[str, Any] | None]


class FakeLLM(_BaseFakeLLM):
    """``responses`` feed ``complete``/``complete_json`` and the tool loop in order.

    Tool-loop responses are ``{"tool": name, "args": {...}}`` or ``{"final": "..."}`` dicts. When the
    script is exhausted, ``tool_policy`` (if any) decides the next protocol message from the
    conversation so far; otherwise the loop ends with an empty final answer.
    """

    def __init__(
        self,
        responses: Iterable[Any] | None = None,
        *,
        json_policy: Callable[[str, str, type[BaseModel]], Any] | None = None,
        text_policy: Callable[[str, str], str] | None = None,
        tool_policy: ToolPolicy | None = None,
        max_tokens: int = 1024,
    ) -> None:
        super().__init__(responses, json_policy=json_policy, text_policy=text_policy)
        self.tool_policy = tool_policy
        self.max_tokens = max_tokens
        self.native_tools = False

    def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        execute: ExecuteFn,
        max_steps: int = 6,
    ) -> ToolLoopResult:
        started = time.perf_counter()
        self.calls.append({"kind": "tool_loop", "system": system, "user": messages[-1]["content"] if messages else ""})

        def ask(sys_prompt: str, history: list[dict[str, Any]]) -> str:
            resp = self._next()
            if resp is _MISSING:
                decision = self.tool_policy(sys_prompt, history, tools) if self.tool_policy else None
                resp = decision if decision is not None else {"final": ""}
            if isinstance(resp, BaseModel):
                return resp.model_dump_json()
            if isinstance(resp, (dict, list)):
                return json.dumps(resp)
            return str(resp)

        result = run_json_protocol_loop(ask, system, messages, tools, execute, max_steps)
        result.model = self.model
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        return result
