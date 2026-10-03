"""Self-contained Gemma 4 clients for the eval CLI (``gemini`` and ``ollama``), no ``apps`` import.

Mirrors ``apps/api/llm/gemma.py`` for the parts extraction needs (``complete``/``complete_json``,
system instruction, JSON mode, ``thinking_level="minimal"``, key rotation on 429/5xx) and adds
client-side pacing so a long eval run stays under a shared free-tier quota:

* ``rpm`` is the per-key request budget; calls rotate across keys round-robin and each key waits
  until ``60 / rpm`` seconds have passed since its previous call.
* ``tpm`` is the per-key input-token budget per minute (the free tier's binding limit for Gemma is
  input tokens per minute); calls are delayed until the estimated prompt fits in the 60 s window.
* a 429 puts the key on cooldown (the server's ``retryDelay`` when given, else 20 s) and the call
  moves to the next key; after ``max_retries`` the call raises :class:`LLMUnavailable`.

``stats`` counts calls, 429s, retries and tokens so the eval can report the observed rate limit.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .llm_protocol import LLMFormatError, parse_json_object, strip_code_fences

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
_RETRY_DELAY = re.compile(r"retry(?:Delay|_delay)?['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", re.IGNORECASE)


class LLMUnavailable(RuntimeError):
    """The backend did not answer (quota, network, server error) after the retries."""


@dataclass
class ClientStats:
    calls: int = 0
    ok: int = 0
    rate_limited: int = 0
    server_errors: int = 0
    format_retries: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    started: float = field(default_factory=time.monotonic)
    latencies: list[float] = field(default_factory=list)
    quota: dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        minutes = max((time.monotonic() - self.started) / 60.0, 1e-9)
        avg = sum(self.latencies) / len(self.latencies) if self.latencies else 0.0
        return (
            f"calls={self.calls} ok={self.ok} http429={self.rate_limited} 5xx={self.server_errors} "
            f"json_retries={self.format_retries} prompt_tokens={self.prompt_tokens} output_tokens={self.output_tokens} "
            f"wall={minutes:.1f} min, {self.ok / minutes:.1f} ok calls/min, avg latency {avg:.2f} s"
            + (f", quotas hit: {self.quota}" if self.quota else "")
        )


class _BaseClient:
    backend = "base"

    def __init__(self, model: str, *, max_tokens: int = 1536) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.stats = ClientStats()

    def _chat(self, system: str, messages: list[dict[str, str]], *, temperature: float, max_tokens: int, json_mode: bool) -> str:
        raise NotImplementedError

    def complete(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 2048) -> str:
        return self._chat(system, [{"role": "user", "content": user}], temperature=temperature, max_tokens=min(max_tokens, self.max_tokens), json_mode=False)

    def complete_json(self, system: str, user: str, schema: type[T], temperature: float = 0.1) -> T:
        messages = [{"role": "user", "content": user}]
        last_error = ""
        for attempt in range(2):
            content = self._chat(system, messages, temperature=temperature, max_tokens=self.max_tokens, json_mode=True)
            try:
                return schema.model_validate(parse_json_object(strip_code_fences(content)))
            except (LLMFormatError, ValidationError) as exc:
                last_error = str(exc).splitlines()[0][:400]
                self.stats.format_retries += 1
                log.warning("complete_json attempt %d invalid for %s: %s", attempt + 1, schema.__name__, last_error)
                messages = [
                    {"role": "user", "content": user},
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"Your previous answer was not valid: {last_error}\nReturn ONE JSON object and nothing else."},
                ]
        raise LLMFormatError(f"{self.model} returned invalid {schema.__name__} twice: {last_error}")


def _flatten(messages: list[dict[str, str]]) -> str:
    if len(messages) == 1:
        return messages[0]["content"]
    parts = []
    for msg in messages:
        prefix = "ASSISTANT" if msg["role"] == "assistant" else "USER"
        parts.append(f"{prefix}:\n{msg['content']}")
    return "\n\n".join(parts)


class GeminiClient(_BaseClient):
    """google-genai against the Gemini API (Gemma 4 served there), paced and key-rotating."""

    backend = "gemini"

    def __init__(
        self,
        model: str,
        api_keys: list[str],
        *,
        rpm: float = 15.0,
        tpm: float = 0.0,
        max_retries: int = 10,
        timeout_s: float = 120.0,
        max_tokens: int = 1536,
    ) -> None:
        super().__init__(model, max_tokens=max_tokens)
        from google import genai

        if not api_keys:
            raise LLMUnavailable("LLM_BACKEND=gemini requires GEMINI_API_KEY (and optionally GEMINI_API_KEY_2)")
        self._clients = [genai.Client(api_key=k, http_options={"timeout": int(timeout_s * 1000)}) for k in api_keys]
        self._interval = 60.0 / rpm if rpm > 0 else 0.0
        self._next_ok = [0.0] * len(self._clients)
        self._tpm = tpm
        self._spent: list[list[tuple[float, int]]] = [[] for _ in self._clients]
        self._turn = 0
        self._lock = threading.Lock()
        self.max_retries = max_retries
        self._minimal_ok: bool | None = None

    def _token_wait(self, index: int, estimate: int, now: float) -> float:
        """Seconds until key ``index`` has room for ``estimate`` input tokens in its 60 s window."""
        if self._tpm <= 0:
            return 0.0
        window = [(t, n) for t, n in self._spent[index] if now - t < 60.0]
        self._spent[index] = window
        budget = self._tpm * 0.9
        used = sum(n for _, n in window)
        if used + estimate <= budget or not window:
            return 0.0
        for t, n in window:  # oldest first: wait until enough old calls leave the window
            used -= n
            if used + estimate <= budget:
                return max(0.0, 60.0 - (now - t))
        return 60.0

    def _acquire(self, estimate: int = 0) -> int:
        """Pick the key that becomes available first (request and token budget), wait, reserve it."""
        with self._lock:
            now = time.monotonic()
            order = [(self._turn + i) % len(self._clients) for i in range(len(self._clients))]
            ready = {i: max(self._next_ok[i] - now, self._token_wait(i, estimate, now)) for i in order}
            index = min(order, key=lambda i: ready[i])
            self._turn = (index + 1) % len(self._clients)
            wait = max(ready[index], 0.0)
            self._next_ok[index] = now + wait + self._interval
            self._spent[index].append((now + wait, estimate))
        if wait > 0:
            time.sleep(wait)
        return index

    def _chat(self, system: str, messages: list[dict[str, str]], *, temperature: float, max_tokens: int, json_mode: bool) -> str:
        from google.genai import errors, types

        contents = _flatten(messages)
        estimate = int((len(system) + len(contents)) / 3.6) + 50
        attempts = 0
        while True:
            index = self._acquire(estimate)
            use_minimal = self._minimal_ok is not False
            kwargs: dict[str, Any] = {"temperature": temperature, "max_output_tokens": max_tokens if use_minimal else max_tokens + 4096, "system_instruction": system}
            if json_mode:
                kwargs["response_mime_type"] = "application/json"
            if use_minimal:
                kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="minimal")
            self.stats.calls += 1
            started = time.monotonic()
            try:
                response = self._clients[index].models.generate_content(model=self.model, contents=contents, config=types.GenerateContentConfig(**kwargs))
            except errors.APIError as exc:
                code = getattr(exc, "code", None)
                text = str(exc)
                if use_minimal and "thinking" in text.lower() and code == 400:
                    self._minimal_ok = False
                    continue
                if code == 429 or (isinstance(code, int) and code >= 500):
                    attempts += 1
                    if code == 429:
                        self.stats.rate_limited += 1
                        match = _RETRY_DELAY.search(text)
                        cooldown = float(match.group(1)) + 1.0 if match else 20.0
                    else:
                        self.stats.server_errors += 1
                        cooldown = min(5.0 * attempts, 30.0)
                    with self._lock:
                        self._next_ok[index] = max(self._next_ok[index], time.monotonic() + cooldown)
                    quota = re.search(r"quotaId['\"]?\s*:\s*['\"]([^'\"]+)", text)
                    limit = re.search(r"quotaValue['\"]?\s*:\s*['\"]?(\d+)", text)
                    if limit and quota:
                        self.stats.quota[quota.group(1)] = int(limit.group(1))
                    log.warning(
                        "gemini %s on key %d (attempt %d/%d), cooling %.0f s%s",
                        code, index + 1, attempts, self.max_retries, cooldown, f" [{quota.group(1)}={limit.group(1) if limit else '?'}]" if quota else "",
                    )
                    if attempts >= self.max_retries:
                        raise LLMUnavailable(f"gemini gave up after {attempts} transient errors: {text[:200]}") from exc
                    continue
                raise LLMUnavailable(f"gemini request failed: {text[:300]}") from exc
            except Exception as exc:  # network errors from httpx inside google-genai
                attempts += 1
                self.stats.server_errors += 1
                log.warning("gemini transport error on key %d: %s", index + 1, str(exc)[:200])
                if attempts >= self.max_retries:
                    raise LLMUnavailable(f"gemini transport failed: {exc}") from exc
                time.sleep(min(5.0 * attempts, 30.0))
                continue
            self.stats.ok += 1
            self.stats.latencies.append(time.monotonic() - started)
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                self.stats.prompt_tokens += int(getattr(usage, "prompt_token_count", 0) or 0)
                self.stats.output_tokens += int(getattr(usage, "candidates_token_count", 0) or 0)
            if use_minimal:
                self._minimal_ok = True
            return response.text or ""


class OllamaClient(_BaseClient):
    """Ollama native ``/api/chat`` with ``think`` off (local fallback)."""

    backend = "ollama"

    def __init__(self, model: str, base_url: str = "http://localhost:11434", *, timeout_s: float = 300.0, max_tokens: int = 1536) -> None:
        super().__init__(model, max_tokens=max_tokens)
        self.root = base_url.rstrip("/").removesuffix("/v1")
        self.timeout_s = timeout_s

    def _chat(self, system: str, messages: list[dict[str, str]], *, temperature: float, max_tokens: int, json_mode: bool) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "think": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if json_mode:
            body["format"] = "json"
        request = urllib.request.Request(f"{self.root}/api/chat", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        self.stats.calls += 1
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                data = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError) as exc:
            self.stats.server_errors += 1
            raise LLMUnavailable(f"ollama request failed: {exc}") from exc
        self.stats.ok += 1
        self.stats.latencies.append(time.monotonic() - started)
        self.stats.prompt_tokens += int(data.get("prompt_eval_count") or 0)
        self.stats.output_tokens += int(data.get("eval_count") or 0)
        return (data.get("message") or {}).get("content") or ""


def make_llm(backend: str, model: str | None = None, *, rpm: float | None = None, tpm: float | None = None) -> _BaseClient:
    """Build a client from the environment (``GEMINI_API_KEY[_2]``, ``OLLAMA_BASE_URL``, ``LLM_RPM``, ``LLM_TPM``)."""
    backend = backend.lower()
    if backend == "gemini":
        keys = [os.environ.get(name, "").strip() for name in ("GEMINI_API_KEY", "GEMINI_API_KEY_2")]
        rate = rpm if rpm is not None else float(os.environ.get("LLM_RPM", "15"))
        tokens = tpm if tpm is not None else float(os.environ.get("LLM_TPM", "15000"))
        return GeminiClient(model or os.environ.get("LLM_MODEL") or "gemma-4-26b-a4b-it", [k for k in keys if k], rpm=rate, tpm=tokens)
    if backend == "ollama":
        return OllamaClient(model or "gemma4:e4b", os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434")
    raise ValueError(f"backend {backend!r} has no built-in client (use gemini | ollama, or --llm-factory)")
