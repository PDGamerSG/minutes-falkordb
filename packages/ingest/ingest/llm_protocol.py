"""The LLM surface the ingestion code depends on, plus a scripted fake for tests.

The production client lives in ``apps/api/llm/gemma.py`` and satisfies :class:`LLMProtocol`.
Keeping the protocol and the error type here avoids a dependency from ``ingest`` on the API.
"""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n(.*?)\n```\s*$", re.DOTALL)


class LLMFormatError(RuntimeError):
    """The model did not return valid JSON matching the schema after one retry."""


@runtime_checkable
class LLMProtocol(Protocol):
    """Minimal text and JSON completion interface."""

    model: str

    def complete(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 2048) -> str: ...

    def complete_json(self, system: str, user: str, schema: type[T], temperature: float = 0.1) -> T: ...


def strip_code_fences(text: str) -> str:
    """Remove a surrounding Markdown code fence, if any."""
    stripped = text.strip()
    match = _FENCE.match(stripped)
    return match.group(1).strip() if match else stripped


def parse_json_object(text: str) -> Any:
    """Parse the first JSON object or array in ``text`` (tolerates prose around it)."""
    cleaned = strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (cleaned.find("{"), cleaned.find("[")) if i >= 0]
    if not starts:
        raise LLMFormatError(f"no JSON found in model output: {cleaned[:200]!r}")
    start = min(starts)
    closer = "}" if cleaned[start] == "{" else "]"
    end = cleaned.rfind(closer)
    if end <= start:
        raise LLMFormatError(f"unterminated JSON in model output: {cleaned[:200]!r}")
    try:
        return json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMFormatError(f"invalid JSON in model output: {exc}") from exc


def validate_payload(payload: Any, schema: type[T]) -> T:
    """Validate a parsed payload (or a model instance) against ``schema``."""
    if isinstance(payload, schema):
        return payload
    if isinstance(payload, BaseModel):
        payload = payload.model_dump()
    if isinstance(payload, (str, bytes)):
        payload = parse_json_object(payload if isinstance(payload, str) else payload.decode())
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        raise LLMFormatError(str(exc)) from exc


_MISSING = object()

JsonPolicy = Callable[[str, str, type[BaseModel]], Any]
TextPolicy = Callable[[str, str], str]


class FakeLLM:
    """Scripted LLM for tests and for model-free demos.

    ``responses`` are consumed in order by :meth:`complete` and :meth:`complete_json`.
    When the script runs out, ``json_policy`` / ``text_policy`` (if given) produce an
    answer from the prompt; otherwise :meth:`complete_json` raises :class:`LLMFormatError`.
    """

    model = "fake"
    backend = "fake"

    def __init__(
        self,
        responses: Iterable[Any] | None = None,
        *,
        json_policy: JsonPolicy | None = None,
        text_policy: TextPolicy | None = None,
    ) -> None:
        self._responses: deque[Any] = deque(responses or [])
        self.json_policy = json_policy
        self.text_policy = text_policy
        self.calls: list[dict[str, Any]] = []

    def push(self, *responses: Any) -> None:
        """Append scripted responses."""
        self._responses.extend(responses)

    def _next(self) -> Any:
        return self._responses.popleft() if self._responses else _MISSING

    def complete(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 2048) -> str:
        self.calls.append({"kind": "complete", "system": system, "user": user})
        resp = self._next()
        if resp is _MISSING:
            return self.text_policy(system, user) if self.text_policy else ""
        if isinstance(resp, BaseModel):
            return resp.model_dump_json()
        if isinstance(resp, (dict, list)):
            return json.dumps(resp)
        return str(resp)

    def complete_json(self, system: str, user: str, schema: type[T], temperature: float = 0.1) -> T:
        self.calls.append({"kind": "complete_json", "system": system, "user": user, "schema": schema.__name__})
        resp = self._next()
        if resp is _MISSING:
            if self.json_policy is None:
                raise LLMFormatError(f"FakeLLM has no scripted response for {schema.__name__}")
            resp = self.json_policy(system, user, schema)
        return validate_payload(resp, schema)
