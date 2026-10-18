"""Model client with Anthropic Haiku, Gemini, OpenRouter and Ollama backends (docs/contracts/llm.md).

* ``complete``       plain text
* ``complete_json``  JSON mode where the backend has one, fences stripped, Pydantic-validated,
                     one retry with the validation error appended, then ``LLMFormatError``
* ``tool_loop``      native function calling on Anthropic (Messages API), ollama (native /api/chat)
                     and openrouter (OpenAI tools); the JSON protocol everywhere else. Tool args are validated
                     against ``ToolSpec.args_model`` before ``execute``; one retry, then fail loudly.

Gemma 4 thinks by default; ``think=False`` is sent to Ollama (``think`` field) and OpenRouter
(``reasoning.enabled``) so a 300-token answer does not cost 1,200 reasoning tokens.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import httpx
from ingest.llm_protocol import LLMFormatError, parse_json_object, strip_code_fences
from pydantic import BaseModel, ConfigDict, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
ExecuteFn = Callable[[str, dict[str, Any]], dict[str, Any]]

NATIVE_TOOL_BACKENDS = frozenset({"anthropic", "ollama", "openrouter"})
DEFAULT_TPM_BUDGET = 14_000  # input tokens per minute (chars / 4) shared by every Gemini call in this process
TOKEN_BUCKET_MAX_WAIT_S = 20.0


class LLMError(RuntimeError):
    """Transport or backend failure (the model never answered)."""


class LLMRateLimited(LLMError):
    """The shared per-minute budget (or the provider's quota) is exhausted; ``retry_after`` is in seconds."""

    def __init__(self, message: str, retry_after: float) -> None:
        super().__init__(message)
        self.retry_after = max(0.0, float(retry_after))


def estimate_tokens(*texts: str) -> int:
    """Input-token estimate: characters / 4 (the free tier counts input tokens per minute)."""
    return max(1, sum(len(t or "") for t in texts) // 4)


class TokenBucket:
    """Process-wide budget of input tokens per minute (finding 4.1).

    ``acquire(n)`` blocks until ``n`` tokens are available, at most ``max_wait`` seconds, then raises
    :class:`LLMRateLimited` with the time until enough tokens have refilled. Requests therefore queue
    instead of burning the provider's retry budget. The clock is injectable for tests.
    """

    def __init__(self, tokens_per_minute: int, *, clock: Callable[[], float] | None = None, sleep: Callable[[float], None] | None = None) -> None:
        self.capacity = max(1.0, float(tokens_per_minute))
        self.rate = self.capacity / 60.0  # tokens per second
        self._tokens = self.capacity
        self._clock = clock or time.monotonic
        self._sleep = sleep or time.sleep
        self._updated = self._clock()
        self._lock = threading.Lock()

    def _refill_locked(self) -> None:
        now = self._clock()
        self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
        self._updated = now

    @property
    def available(self) -> float:
        with self._lock:
            self._refill_locked()
            return self._tokens

    def wait_for(self, tokens: int) -> float:
        """Seconds until ``tokens`` are available (0 when they already are)."""
        with self._lock:
            self._refill_locked()
            need = min(float(tokens), self.capacity) - self._tokens
            return 0.0 if need <= 0 else need / self.rate

    def acquire(self, tokens: int, max_wait: float = TOKEN_BUCKET_MAX_WAIT_S) -> float:
        """Take ``tokens`` (capped at the capacity); returns the seconds waited."""
        wanted = min(float(tokens), self.capacity)
        waited = 0.0
        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= wanted:
                    self._tokens -= wanted
                    return waited
                delay = (wanted - self._tokens) / self.rate
            if waited + delay > max_wait:
                raise LLMRateLimited(f"token budget exhausted: {int(wanted)} tokens needed, {delay:.1f}s until available", retry_after=delay)
            step = min(delay, 0.5)
            self._sleep(step)
            waited += step


_BUCKETS: dict[int, TokenBucket] = {}
_BUCKETS_LOCK = threading.Lock()


def shared_token_bucket(tokens_per_minute: int) -> TokenBucket:
    """One bucket per budget size for the whole process (every GeminiBackend shares it)."""
    with _BUCKETS_LOCK:
        bucket = _BUCKETS.get(int(tokens_per_minute))
        if bucket is None:
            bucket = _BUCKETS[int(tokens_per_minute)] = TokenBucket(tokens_per_minute)
        return bucket


class ToolSpec(BaseModel):
    """A callable tool: name, description and the Pydantic model of its arguments."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    args_model: type[BaseModel]

    def openai_schema(self, *, clean: bool = True) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": _clean_schema(self.args_model.model_json_schema()) if clean else self.args_model.model_json_schema(),
            },
        }


class ToolLoopResult(BaseModel):
    """Outcome of :meth:`LLM.tool_loop`."""

    final: str | None = None
    steps: list[dict[str, Any]] = []
    failed: bool = False
    reason: str | None = None
    model: str = ""
    latency_ms: int = 0


@dataclass(slots=True)
class ToolCall:
    name: str
    args: Any
    id: str = ""


@dataclass(slots=True)
class ChatResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: Any = None


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline ``$defs`` references and drop titles (Ollama's and Gemini's schema parsers are picky)."""
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref = node["$ref"].rsplit("/", 1)[-1]
                return walk(defs.get(ref, {}))
            out = {}
            for key, value in node.items():
                if key in {"title", "$defs"}:
                    continue
                if key == "anyOf" and isinstance(value, list):
                    non_null = [v for v in value if v.get("type") != "null"]
                    if len(non_null) == 1:
                        merged = walk(non_null[0])
                        merged.setdefault("nullable", True)
                        out.update(merged)
                        continue
                out[key] = walk(value)
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    cleaned = walk(schema)
    cleaned.setdefault("type", "object")
    return cleaned


# --------------------------------------------------------------------------- backends
class AnthropicBackend:
    """Anthropic Messages API backend with native tool use and Haiku-only deployments."""

    name = "anthropic"
    supports_native_tools = True
    supports_json_mode = False

    def __init__(self, model: str, api_key: str | None, base_url: str | None, *, timeout_s: float, think: bool) -> None:
        if not api_key:
            raise LLMError("LLM_BACKEND=anthropic requires ANTHROPIC_API_KEY")
        if not model.startswith("claude-haiku-"):
            raise LLMError("Only Claude Haiku models are enabled for Anthropic")
        self.model = model
        self.think = think
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self._client = httpx.Client(timeout=httpx.Timeout(timeout_s, connect=10.0))
        self._headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def probe(self) -> bool:
        """Check credentials and model access without generating tokens."""
        try:
            response = self._client.get(f"{self.base_url}/v1/models/{self.model}", headers=self._headers, timeout=5.0)
            self._check_status(response)
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMError("Anthropic model probe failed") from exc
        if not isinstance(data, dict) or not str(data.get("id", "")).startswith("claude-haiku-"):
            raise LLMError("Anthropic did not confirm access to a Haiku model")
        return True

    @staticmethod
    def _check_status(response: httpx.Response) -> None:
        # Do not log provider bodies: errors can echo credentials or source documents.
        if response.status_code == 429:
            hint = response.headers.get("retry-after", "30")
            try:
                delay = float(hint)
            except ValueError:
                try:
                    delay = (parsedate_to_datetime(hint) - datetime.now(UTC)).total_seconds()
                except (TypeError, ValueError, OverflowError):
                    delay = 30.0
            raise LLMRateLimited("Anthropic rate limit exceeded", retry_after=delay if math.isfinite(delay) else 30.0)
        if not response.is_success:
            raise LLMError(f"Anthropic request failed (HTTP {response.status_code})")

    def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        tools: list[dict[str, Any]] | None,
    ) -> ChatResponse:
        if json_mode:
            system = (
                f"{system}\n\nReturn exactly one valid JSON object and no markdown, commentary, or code fences."
            )
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": _to_anthropic_messages(messages),
        }
        if tools:
            body["tools"] = [
                {
                    "name": item["function"]["name"],
                    "description": item["function"].get("description", ""),
                    "input_schema": item["function"].get("parameters") or {"type": "object"},
                }
                for item in tools
            ]
        try:
            response = self._client.post(f"{self.base_url}/v1/messages", headers=self._headers, json=body)
            self._check_status(response)
        except httpx.HTTPError as exc:
            raise LLMError("Anthropic connection failed or timed out") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("Anthropic returned invalid JSON") from exc
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            raise LLMError("Anthropic returned an invalid message")
        if data.get("stop_reason") not in {"end_turn", "tool_use", "stop_sequence"}:
            raise LLMError("Anthropic did not complete the response (truncated, refused or paused)")
        blocks = data.get("content") or []
        text = "".join(str(block.get("text") or "") for block in blocks if block.get("type") == "text")
        calls = [
            ToolCall(name=str(block.get("name") or ""), args=block.get("input") or {}, id=str(block.get("id") or ""))
            for block in blocks
            if block.get("type") == "tool_use"
        ]
        if not text.strip() and not calls:
            raise LLMError("Anthropic returned an empty response")
        if any(not c.id or not c.name or not isinstance(c.args, dict) for c in calls):
            raise LLMError("Anthropic returned an invalid tool call")
        return ChatResponse(content=text, tool_calls=calls, raw=data)


def _to_anthropic_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the shared internal tool-loop history to Anthropic's content-block format."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            if msg.get("content"):
                blocks.append({"type": "text", "text": str(msg["content"])})
            for call in msg["tool_calls"]:
                args = call.get("args") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError as exc:
                        raise LLMError("Invalid JSON in tool history") from exc
                blocks.append({"type": "tool_use", "id": call.get("id") or "call_0", "name": call.get("name", ""), "input": args})
            out.append({"role": "assistant", "content": blocks})
        elif role == "tool":
            result = {"type": "tool_result", "tool_use_id": msg.get("tool_call_id") or "call_0", "content": str(msg.get("content") or "")}
            if out and out[-1].get("role") == "user" and isinstance(out[-1].get("content"), list) and all(b.get("type") == "tool_result" for b in out[-1]["content"]):
                out[-1]["content"].append(result)
            else:
                out.append({"role": "user", "content": [result]})
        else:
            content = msg.get("content") or ""
            if isinstance(content, list):
                out.append({"role": role or "user", "content": content})
            else:
                out.append({"role": role or "user", "content": str(content)})
    return out


class OllamaBackend:
    """Ollama native ``/api/chat`` (so ``think`` can be switched off and ``format`` can be set)."""

    name = "ollama"
    supports_native_tools = True
    supports_json_mode = True

    def __init__(self, model: str, base_url: str, *, timeout_s: float, think: bool) -> None:
        self.model = model
        root = base_url.rstrip("/")
        root = root.removesuffix("/v1")
        self.root = root
        self.think = think
        self._client = httpx.Client(timeout=httpx.Timeout(timeout_s, connect=10.0))

    def probe(self) -> bool:
        """Cheap liveness check (no generation): ``GET /api/tags``."""
        response = self._client.get(f"{self.root}/api/tags", timeout=5.0)
        response.raise_for_status()
        return True

    def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        tools: list[dict[str, Any]] | None,
    ) -> ChatResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *_to_ollama_messages(messages)],
            "stream": False,
            "think": self.think,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            body["format"] = "json"
        if tools:
            body["tools"] = tools
        try:
            response = self._client.post(f"{self.root}/api/chat", json=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise LLMError(f"ollama request failed: {exc}") from exc
        data = response.json()
        message = data.get("message") or {}
        calls = []
        for index, call in enumerate(message.get("tool_calls") or []):
            fn = call.get("function") or {}
            calls.append(ToolCall(name=fn.get("name", ""), args=fn.get("arguments", {}), id=call.get("id") or f"call_{index}"))
        return ChatResponse(content=message.get("content") or "", tool_calls=calls, raw=data)


def _to_ollama_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        if role == "assistant" and msg.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": msg.get("content") or "",
                    "tool_calls": [
                        {"function": {"name": c["name"], "arguments": c["args"] if isinstance(c["args"], dict) else {}}}
                        for c in msg["tool_calls"]
                    ],
                }
            )
        elif role == "tool":
            out.append({"role": "tool", "content": msg["content"], "tool_name": msg.get("name", "")})
        else:
            out.append({"role": role, "content": msg.get("content") or ""})
    return out


class OpenAICompatBackend:
    """OpenAI SDK against OpenRouter (or any OpenAI-compatible server)."""

    name = "openrouter"
    supports_native_tools = True
    supports_json_mode = True

    def __init__(self, model: str, api_key: str | None, base_url: str | None, *, timeout_s: float, think: bool) -> None:
        from openai import OpenAI

        self.model = model
        self.think = think
        self._client = OpenAI(api_key=api_key or "none", base_url=base_url, timeout=timeout_s, max_retries=1)

    def probe(self) -> bool:
        """Cheap liveness check (no generation): list models."""
        self._client.with_options(timeout=5.0).models.list()
        return True

    def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        tools: list[dict[str, Any]] | None,
    ) -> ChatResponse:
        from openai import OpenAIError

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *_to_openai_messages(messages)],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if not self.think:
            kwargs["extra_body"] = {"reasoning": {"enabled": False}}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        try:
            completion = self._client.chat.completions.create(**kwargs)
        except OpenAIError as exc:
            if json_mode and "response_format" in str(exc).lower():
                kwargs.pop("response_format", None)
                try:
                    completion = self._client.chat.completions.create(**kwargs)
                except OpenAIError as exc2:
                    raise LLMError(f"openai-compatible request failed: {exc2}") from exc2
            else:
                raise LLMError(f"openai-compatible request failed: {exc}") from exc
        choice = completion.choices[0].message
        calls = []
        for call in choice.tool_calls or []:
            calls.append(ToolCall(name=call.function.name, args=call.function.arguments, id=call.id))
        return ChatResponse(content=choice.content or "", tool_calls=calls, raw=completion)


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        if role == "assistant" and msg.get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": msg.get("content") or None,
                    "tool_calls": [
                        {
                            "id": c.get("id") or f"call_{i}",
                            "type": "function",
                            "function": {"name": c["name"], "arguments": json.dumps(c["args"]) if not isinstance(c["args"], str) else c["args"]},
                        }
                        for i, c in enumerate(msg["tool_calls"])
                    ],
                }
            )
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": msg.get("tool_call_id") or "call_0", "content": msg["content"]})
        else:
            out.append({"role": role, "content": msg.get("content") or ""})
    return out


_RETRY_HINT = re.compile(r"(?:retry in|retryDelay['\"]?\s*:\s*['\"])\s*([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)


class GeminiBackend:
    """google-genai. Verified against gemma-4-26b-a4b-it on 2026-10-03: system instructions and JSON mode
    are accepted; `thinking_budget` is rejected but `thinking_level="minimal"` turns thinking off (2 s
    instead of 13 s per call). Each feature is still tried once and disabled for the session when the API
    refuses it. Transient 429/500/503 answers are retried with backoff, rotating across the configured
    keys (``api_key`` may be a comma-separated list)."""

    name = "gemini"
    supports_native_tools = False
    supports_json_mode = True
    THINKING_HEADROOM = 4096  # extra output tokens when thinking cannot be switched off
    MAX_TRANSIENT_RETRIES = 4
    MAX_RETRY_WAIT_S = 25.0

    def __init__(self, model: str, api_key: str | None, *, timeout_s: float, think: bool, tpm_budget: int | None = None) -> None:
        from google import genai

        keys = [k.strip() for k in (api_key or "").split(",") if k.strip()]
        if not keys:
            raise LLMError("LLM_BACKEND=gemini requires GEMINI_API_KEY")
        self.model = model
        self.think = think
        self._clients = [genai.Client(api_key=k, http_options={"timeout": int(timeout_s * 1000)}) for k in keys]
        self._active = 0
        self._system_ok: bool | None = None
        self._json_ok: bool | None = None
        self._minimal_ok: bool | None = None
        budget = tpm_budget if tpm_budget is not None else int(os.environ.get("GEMINI_TPM_BUDGET", DEFAULT_TPM_BUDGET) or DEFAULT_TPM_BUDGET)
        self.bucket = shared_token_bucket(budget)

    def probe(self) -> bool:
        """Cheap liveness check (no generation): fetch the model's metadata."""
        self._clients[self._active].models.get(model=self.model)
        return True

    def chat(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        tools: list[dict[str, Any]] | None,
    ) -> ChatResponse:
        import time

        from google.genai import errors, types

        transcript = _flatten_transcript(messages)
        waited = self.bucket.acquire(estimate_tokens(system, transcript))
        if waited:
            log.info("gemini call queued %.1fs on the shared token budget", waited)
        feature_attempts = 0
        transient_attempts = 0
        while True:
            use_system = self._system_ok is not False
            use_json = json_mode and self._json_ok is not False
            use_minimal = not self.think and self._minimal_ok is not False
            budget = max_tokens if use_minimal else max_tokens + self.THINKING_HEADROOM
            config_kwargs: dict[str, Any] = {"temperature": temperature, "max_output_tokens": budget}
            if use_system:
                config_kwargs["system_instruction"] = system
            if use_json:
                config_kwargs["response_mime_type"] = "application/json"
            if use_minimal:
                config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="minimal")
            contents = transcript if use_system else f"{system}\n\n{transcript}"
            try:
                response = self._clients[self._active].models.generate_content(
                    model=self.model, contents=contents, config=types.GenerateContentConfig(**config_kwargs)
                )
                if use_system:
                    self._system_ok = True
                if use_json:
                    self._json_ok = True
                if use_minimal:
                    self._minimal_ok = True
                return ChatResponse(content=response.text or "", raw=response)
            except errors.APIError as exc:
                message = str(exc).lower()
                code = getattr(exc, "code", None)
                if code in (429, 500, 503) and transient_attempts < self.MAX_TRANSIENT_RETRIES:
                    transient_attempts += 1
                    self._active = (self._active + 1) % len(self._clients)
                    delay = min(2.0 * transient_attempts, 8.0)
                    # Once every key has been tried, honour the server's retry hint (free-tier per-minute
                    # quotas say "retry in 20s"); fixed short backoffs would give up before the window resets.
                    if code == 429 and transient_attempts >= len(self._clients):
                        hint = _RETRY_HINT.search(str(exc))
                        if hint:
                            delay = max(delay, min(float(hint.group(1)) + 0.5, self.MAX_RETRY_WAIT_S))
                    time.sleep(delay)
                    continue
                if code == 429:
                    hint = _RETRY_HINT.search(str(exc))
                    raise LLMRateLimited(f"gemini rate limited after {transient_attempts} retries: {exc}", retry_after=float(hint.group(1)) if hint else 30.0) from exc
                feature_attempts += 1
                if use_minimal and "thinking" in message:
                    self._minimal_ok = False
                elif use_system and ("system" in message or "developer instruction" in message):
                    self._system_ok = False
                elif use_json and ("mime" in message or "json" in message):
                    self._json_ok = False
                else:
                    raise LLMError(f"gemini request failed: {exc}") from exc
                if feature_attempts >= 4:
                    raise LLMError(f"gemini request failed: {exc}") from exc


def _flatten_transcript(messages: list[dict[str, Any]]) -> str:
    """Single-string transcript for backends driven through the JSON protocol."""
    parts = []
    for msg in messages:
        role = msg["role"]
        if role == "tool":
            parts.append(f"TOOL RESULT ({msg.get('name', '')}):\n{msg['content']}")
        elif role == "assistant":
            parts.append(f"ASSISTANT:\n{msg.get('content') or ''}")
        else:
            parts.append(f"USER:\n{msg.get('content') or ''}")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- the client
JSON_PROTOCOL = (
    "\n\n## Tools\nYou can call tools. Respond with exactly ONE JSON object per turn and nothing else:\n"
    '- to call a tool: {"tool": "<name>", "args": {<arguments matching the schema>}}\n'
    '- when you are done: {"final": "<your answer for the user>"}\n'
    "Never invent tool names. Available tools:\n"
)


class LLM:
    """One interface, three backends chosen by ``LLM_BACKEND``; see the module docstring."""

    def __init__(
        self,
        backend: str,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        max_tokens: int = 1024,
        timeout_s: float = 180.0,
        think: bool = False,
        native_tools: bool | None = None,
        tpm_budget: int | None = None,
    ) -> None:
        backend = backend.lower()
        self.backend = backend
        self.model = model
        self.max_tokens = max_tokens
        if backend == "ollama":
            self._backend: Any = OllamaBackend(model, base_url or "http://localhost:11434/v1", timeout_s=timeout_s, think=think)
        elif backend == "openrouter":
            self._backend = OpenAICompatBackend(
                model, api_key, base_url or "https://openrouter.ai/api/v1", timeout_s=timeout_s, think=think
            )
        elif backend == "gemini":
            self._backend = GeminiBackend(model, api_key, timeout_s=timeout_s, think=think, tpm_budget=tpm_budget)
        elif backend == "anthropic":
            self._backend = AnthropicBackend(model, api_key, base_url, timeout_s=timeout_s, think=think)
        else:
            raise ValueError(f"unknown LLM_BACKEND {backend!r} (expected anthropic | gemini | openrouter | ollama | fake)")
        self.native_tools = self._backend.supports_native_tools if native_tools is None else native_tools

    def probe(self) -> bool:
        """Liveness without a generation (used by ``/health``); raises on failure."""
        probe = getattr(self._backend, "probe", None)
        if probe is None:
            raise LLMError(f"backend {self.backend} has no probe")
        return bool(probe())

    # -- text ---------------------------------------------------------------------------------
    def complete(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 2048) -> str:
        response = self._backend.chat(
            system,
            [{"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=min(max_tokens, self.max_tokens) if self.max_tokens else max_tokens,
            json_mode=False,
            tools=None,
        )
        return response.content

    # -- JSON ---------------------------------------------------------------------------------
    def complete_json(self, system: str, user: str, schema: type[T], temperature: float = 0.1) -> T:
        messages = [{"role": "user", "content": user}]
        last_error = ""
        for attempt in range(2):
            response = self._backend.chat(
                system, messages, temperature=temperature, max_tokens=self.max_tokens, json_mode=True, tools=None
            )
            text = strip_code_fences(response.content)
            try:
                payload = parse_json_object(text)
                return schema.model_validate(payload)
            except (LLMFormatError, ValidationError) as exc:
                last_error = str(exc).splitlines()[0][:400]
                log.warning("complete_json attempt %d invalid for %s: %s", attempt + 1, schema.__name__, last_error)
                messages = [
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": response.content},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous answer was not valid: {last_error}\n"
                            f"Return ONE JSON object matching this schema and nothing else:\n"
                            f"{json.dumps(_clean_schema(schema.model_json_schema()))}"
                        ),
                    },
                ]
        raise LLMFormatError(f"{self.model} returned invalid {schema.__name__} twice: {last_error}")

    # -- tools --------------------------------------------------------------------------------
    def tool_loop(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        execute: ExecuteFn,
        max_steps: int = 6,
    ) -> ToolLoopResult:
        started = time.perf_counter()
        if self.native_tools:
            result = run_native_tool_loop(self._backend.chat, system, messages, tools, execute, max_steps, self.max_tokens, clean_schemas=self.backend != "anthropic")
        else:
            result = run_json_protocol_loop(
                lambda sys_prompt, msgs: self._backend.chat(
                    sys_prompt, msgs, temperature=0.1, max_tokens=self.max_tokens, json_mode=True, tools=None
                ).content,
                system,
                messages,
                tools,
                execute,
                max_steps,
            )
        result.model = self.model
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        return result


# --------------------------------------------------------------------------- loops
def _validate_args(spec: ToolSpec, raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = parse_json_object(raw) if isinstance(raw, str) else (raw or {})
        model = spec.args_model.model_validate(payload)
        return model.model_dump(), None
    except (LLMFormatError, ValidationError) as exc:
        return None, str(exc).splitlines()[0][:300]


def run_native_tool_loop(
    chat: Callable[..., ChatResponse],
    system: str,
    messages: list[dict[str, Any]],
    tools: list[ToolSpec],
    execute: ExecuteFn,
    max_steps: int,
    max_tokens: int,
    *,
    clean_schemas: bool = True,
) -> ToolLoopResult:
    """OpenAI/Ollama-style function calling with per-call Pydantic validation (one retry)."""
    specs = {t.name: t for t in tools}
    schemas = [t.openai_schema(clean=clean_schemas) for t in tools]
    history = list(messages)
    steps: list[dict[str, Any]] = []
    retried = False
    for _ in range(max_steps + 1):
        if len(steps) >= max_steps:
            return ToolLoopResult(steps=steps, failed=True, reason=f"max_steps ({max_steps}) reached without a final answer")
        response = chat(system, history, temperature=0.1, max_tokens=max_tokens, json_mode=False, tools=schemas)
        if not response.tool_calls:
            return ToolLoopResult(final=response.content.strip(), steps=steps)
        history.append(
            {"role": "assistant", "content": response.content, "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in response.tool_calls]}
        )
        for call in response.tool_calls:
            spec = specs.get(call.name)
            if spec is None:
                error = f"unknown tool {call.name!r}; available: {sorted(specs)}"
                args, err = None, error
            else:
                args, err = _validate_args(spec, call.args)
            if err is not None:
                steps.append({"tool": call.name, "args": call.args, "error": err})
                if retried:
                    return ToolLoopResult(steps=steps, failed=True, reason=f"invalid tool call after retry: {err}")
                retried = True
                history.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": json.dumps({"error": err, "hint": "fix the arguments and call again"})})
                continue
            result = execute(call.name, args or {})
            steps.append({"tool": call.name, "args": args, "result": result})
            history.append({"role": "tool", "tool_call_id": call.id, "name": call.name, "content": json.dumps(result, default=str)[:6000]})
            if result.get("stop"):
                return ToolLoopResult(final=str(result.get("final") or result.get("summary") or ""), steps=steps)
    return ToolLoopResult(steps=steps, failed=True, reason="loop exhausted")


def run_json_protocol_loop(
    ask: Callable[[str, list[dict[str, Any]]], str],
    system: str,
    messages: list[dict[str, Any]],
    tools: list[ToolSpec],
    execute: ExecuteFn,
    max_steps: int,
) -> ToolLoopResult:
    """Tool calling for models without native tools: ``{"tool", "args"}`` or ``{"final"}`` per turn."""
    specs = {t.name: t for t in tools}
    tool_doc = "\n".join(
        f"- {t.name}: {t.description}\n  args schema: {json.dumps(_clean_schema(t.args_model.model_json_schema()))}" for t in tools
    )
    full_system = system + JSON_PROTOCOL + tool_doc
    history = list(messages)
    steps: list[dict[str, Any]] = []
    retried = False
    for _ in range(max_steps * 2 + 2):
        if len(steps) >= max_steps:
            return ToolLoopResult(steps=steps, failed=True, reason=f"max_steps ({max_steps}) reached without a final answer")
        text = ask(full_system, history)
        try:
            payload = parse_json_object(text)
            if not isinstance(payload, dict):
                raise LLMFormatError("expected a JSON object")
        except LLMFormatError as exc:
            if retried:
                return ToolLoopResult(steps=steps, failed=True, reason=f"invalid protocol message after retry: {exc}")
            retried = True
            history += [
                {"role": "assistant", "content": text},
                {"role": "user", "content": f"Invalid: {exc}. Reply with ONE JSON object: {{\"tool\": ..., \"args\": ...}} or {{\"final\": ...}}."},
            ]
            continue
        if "final" in payload and "tool" not in payload:
            return ToolLoopResult(final=str(payload.get("final") or ""), steps=steps)
        name = str(payload.get("tool") or "")
        spec = specs.get(name)
        history.append({"role": "assistant", "content": json.dumps(payload)})
        if spec is None:
            err = f"unknown tool {name!r}; available: {sorted(specs)}"
            args = None
        else:
            args, err = _validate_args(spec, payload.get("args") or {})
        if err is not None:
            steps.append({"tool": name, "args": payload.get("args"), "error": err})
            if retried:
                return ToolLoopResult(steps=steps, failed=True, reason=f"invalid tool call after retry: {err}")
            retried = True
            history.append({"role": "user", "content": f"Tool call rejected: {err}. Fix the arguments and try again."})
            continue
        result = execute(name, args or {})
        steps.append({"tool": name, "args": args, "result": result})
        history.append({"role": "tool", "name": name, "content": json.dumps(result, default=str)[:6000]})
        if result.get("stop"):
            return ToolLoopResult(final=str(result.get("final") or result.get("summary") or ""), steps=steps)
    return ToolLoopResult(steps=steps, failed=True, reason="loop exhausted")
