"""Messages API contract and failure handling; no credentials or paid calls in tests."""

import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from apps.api.config import Settings
from apps.api.llm import LLM, LLMError, LLMRateLimited, ToolSpec, make_llm

MODEL = "claude-haiku-4-5-20251001"


def client(handler):
    llm = LLM("anthropic", MODEL, api_key="test-key", max_tokens=128)
    llm._backend._client.close()
    llm._backend._client = httpx.Client(transport=httpx.MockTransport(handler))
    return llm


def message(text="ok", **kwargs):
    return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn", **kwargs}


def test_settings_default_to_haiku_for_both_roles_and_wire_the_key():
    settings = Settings(_env_file=None, llm_backend="anthropic", anthropic_api_key="test-key")
    assert settings.llm_model == settings.llm_model_small == MODEL
    llm = make_llm(settings)
    assert llm.native_tools and llm._backend._headers["x-api-key"] == "test-key"
    llm._backend._client.close()


@pytest.mark.parametrize("field", ["llm_model", "llm_model_small"])
def test_non_haiku_is_rejected(field):
    with pytest.raises(ValidationError, match="require Haiku"):
        Settings(_env_file=None, llm_backend="anthropic", **{field: "claude-sonnet-test"})
    with pytest.raises(LLMError, match="Only Claude Haiku"):
        LLM("anthropic", "claude-sonnet-test", api_key="test-key")


def test_missing_key_fails_without_a_fallback():
    with pytest.raises(LLMError, match="ANTHROPIC_API_KEY"):
        LLM("anthropic", MODEL)


def test_text_request_and_token_cap():
    def handler(request):
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "test-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        body = json.loads(request.content)
        assert body["model"] == MODEL and body["max_tokens"] == 128
        assert body["system"] == "Be concise"
        assert body["messages"] == [{"role": "user", "content": "Hello"}]
        assert "thinking" not in body and "tools" not in body
        return httpx.Response(200, json=message("Hello back"))

    assert client(handler).complete("Be concise", "Hello") == "Hello back"


def test_probe_checks_the_specific_model_without_generating_tokens():
    def handler(request):
        assert request.method == "GET" and request.url.path == f"/v1/models/{MODEL}"
        return httpx.Response(200, json={"id": MODEL})

    assert client(handler).probe()


def test_json_validation_retries_with_the_original_history():
    class Answer(BaseModel):
        count: int

    requests = []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert "valid JSON object" in body["system"]
        return httpx.Response(200, json=message('{"count":"invalid"}' if len(requests) == 1 else '{"count":3}'))

    assert client(handler).complete_json("Return a count", "Count three", Answer).count == 3
    assert [m["role"] for m in requests[1]["messages"]] == ["user", "assistant", "user"]


def test_native_tools_preserve_nullable_schema_and_group_parallel_results():
    class Lookup(BaseModel):
        query: str
        limit: int | None = None

    requests, executions = [], []

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        schema = body["tools"][0]["input_schema"]
        assert schema["properties"]["limit"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
        if len(requests) == 1:
            return httpx.Response(200, json=message(content=[
                {"type": "text", "text": "Looking up both records"},
                {"type": "tool_use", "id": "tool_1", "name": "lookup", "input": {"query": "first"}},
                {"type": "tool_use", "id": "tool_2", "name": "lookup", "input": {"query": "second", "limit": None}},
            ], stop_reason="tool_use"))
        history = body["messages"]
        assert [m["role"] for m in history] == ["user", "assistant", "user"]
        assert history[1]["content"][1]["id"] == "tool_1"
        assert [b["tool_use_id"] for b in history[2]["content"]] == ["tool_1", "tool_2"]
        assert json.loads(history[2]["content"][0]["content"]) == {"found": "first"}
        return httpx.Response(200, json=message("Both found"))

    def execute(name, args):
        executions.append((name, args))
        return {"found": args["query"]}

    result = client(handler).tool_loop("Use lookup", [{"role": "user", "content": "Find both"}],
                                      [ToolSpec(name="lookup", description="Find a record", args_model=Lookup)], execute)
    assert result.final == "Both found" and not result.failed
    assert len(executions) == 2 and executions[0][1] == {"query": "first", "limit": None}


@pytest.mark.parametrize("hint", ["17", "nonsense", "NaN", format_datetime(datetime.now(UTC) + timedelta(seconds=60))])
def test_rate_limit_headers_are_robust(hint):
    llm = client(lambda _: httpx.Response(429, headers={"retry-after": hint}, json={"error": {"message": "private text"}}))
    with pytest.raises(LLMRateLimited) as exc:
        llm.complete("", "hi")
    assert 0 <= exc.value.retry_after <= 61
    assert "private text" not in str(exc.value)
    if hint == "17":
        assert exc.value.retry_after == 17


@pytest.mark.parametrize("status", [400, 401, 403, 404, 500, 529])
def test_provider_error_bodies_are_not_exposed(status):
    llm = client(lambda _: httpx.Response(status, json={"error": {"message": "private key and document text"}}))
    with pytest.raises(LLMError) as exc:
        llm.complete("", "hi")
    assert str(status) in str(exc.value) and "private" not in str(exc.value)


@pytest.mark.parametrize("payload", [message(stop_reason="max_tokens"), message(stop_reason="refusal"), message(content=[]), {}, []])
def test_incomplete_or_malformed_messages_fail(payload):
    with pytest.raises(LLMError):
        client(lambda _: httpx.Response(200, json=payload)).complete("", "hi")


def test_invalid_json_and_connection_errors_fail():
    with pytest.raises(LLMError, match="invalid JSON"):
        client(lambda _: httpx.Response(200, text="not json")).complete("", "hi")

    def timeout(request):
        raise httpx.ReadTimeout("private text", request=request)

    with pytest.raises(LLMError, match="timed out"):
        client(timeout).complete("", "hi")
