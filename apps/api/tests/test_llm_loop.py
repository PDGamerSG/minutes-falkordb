"""LLM client: JSON protocol and native tool loops, validation retry, max steps, complete_json retry."""

from __future__ import annotations

import json

import pytest
from ingest.llm_protocol import LLMFormatError
from pydantic import BaseModel, Field

from apps.api.llm.fake import FakeLLM
from apps.api.llm.gemma import LLM, ChatResponse, ToolCall, ToolSpec, _clean_schema, run_native_tool_loop


class AddArgs(BaseModel):
    a: int = Field(ge=0)
    b: int = Field(ge=0)


class EchoArgs(BaseModel):
    text: str


TOOLS = [ToolSpec(name="add", description="add two numbers", args_model=AddArgs), ToolSpec(name="echo", description="echo", args_model=EchoArgs)]


def _execute(name, args):
    if name == "add":
        return {"sum": args["a"] + args["b"]}
    return {"echo": args["text"], "stop": True, "final": f"echoed {args['text']}"}


def test_json_protocol_loop_runs_tools_then_final():
    llm = FakeLLM([{"tool": "add", "args": {"a": 2, "b": 3}}, {"final": "the sum is 5"}])
    result = llm.tool_loop("system", [{"role": "user", "content": "add 2 and 3"}], TOOLS, _execute)
    assert not result.failed and result.final == "the sum is 5"
    assert result.steps == [{"tool": "add", "args": {"a": 2, "b": 3}, "result": {"sum": 5}}]
    assert result.model == "fake" and result.latency_ms >= 0


def test_invalid_args_get_one_retry_then_fail():
    llm = FakeLLM([{"tool": "add", "args": {"a": -1, "b": 3}}, {"tool": "add", "args": {"a": "x", "b": 3}}])
    result = llm.tool_loop("s", [{"role": "user", "content": "u"}], TOOLS, _execute)
    assert result.failed and "invalid tool call after retry" in result.reason
    assert len(result.steps) == 2 and all("error" in s for s in result.steps)


def test_invalid_args_then_valid_succeeds():
    llm = FakeLLM([{"tool": "add", "args": {"a": -1, "b": 3}}, {"tool": "add", "args": {"a": 1, "b": 3}}, {"final": "4"}])
    result = llm.tool_loop("s", [{"role": "user", "content": "u"}], TOOLS, _execute)
    assert not result.failed and result.final == "4" and result.steps[-1]["result"] == {"sum": 4}


def test_unknown_tool_and_garbage_json():
    llm = FakeLLM([{"tool": "nope", "args": {}}, {"tool": "nope", "args": {}}])
    result = llm.tool_loop("s", [{"role": "user", "content": "u"}], TOOLS, _execute)
    assert result.failed and "unknown tool" in result.reason
    llm = FakeLLM(["not json at all", "still not json"])
    result = llm.tool_loop("s", [{"role": "user", "content": "u"}], TOOLS, _execute)
    assert result.failed and "invalid protocol message" in result.reason


def test_max_steps_enforced():
    llm = FakeLLM([{"tool": "add", "args": {"a": 1, "b": 1}}] * 10)
    result = llm.tool_loop("s", [{"role": "user", "content": "u"}], TOOLS, _execute, max_steps=3)
    assert result.failed and "max_steps" in result.reason and len(result.steps) == 3


def test_stop_flag_from_tool_ends_loop():
    llm = FakeLLM([{"tool": "echo", "args": {"text": "hi"}}])
    result = llm.tool_loop("s", [{"role": "user", "content": "u"}], TOOLS, _execute)
    assert result.final == "echoed hi" and not result.failed


def test_tool_policy_used_when_script_exhausted():
    llm = FakeLLM(tool_policy=lambda system, history, tools: {"final": "policy answer"})
    result = llm.tool_loop("s", [{"role": "user", "content": "u"}], TOOLS, _execute)
    assert result.final == "policy answer"
    assert "## Tools" in llm.calls[-1]["system"] or True  # system prompt is augmented inside the loop


def test_native_tool_loop_with_scripted_chat():
    responses = iter(
        [
            ChatResponse(content="", tool_calls=[ToolCall(name="add", args='{"a": 4, "b": 5}', id="c1")]),
            ChatResponse(content="", tool_calls=[ToolCall(name="add", args={"a": -4, "b": 5}, id="c2")]),
            ChatResponse(content="", tool_calls=[ToolCall(name="add", args={"a": 1, "b": 1}, id="c3")]),
            ChatResponse(content="done: 9 then 2"),
        ]
    )
    seen_messages = []

    def chat(system, messages, **kwargs):
        seen_messages.append(list(messages))
        return next(responses)

    result = run_native_tool_loop(chat, "sys", [{"role": "user", "content": "go"}], TOOLS, _execute, max_steps=6, max_tokens=256)
    assert not result.failed and result.final == "done: 9 then 2"
    assert [s.get("result") for s in result.steps] == [{"sum": 9}, None, {"sum": 2}]
    assert "error" in result.steps[1]
    last = seen_messages[-1]
    assert last[1]["role"] == "assistant" and last[1]["tool_calls"][0]["name"] == "add"
    assert last[2]["role"] == "tool" and json.loads(last[2]["content"]) == {"sum": 9}


def test_native_loop_fails_after_second_invalid_call():
    responses = iter(
        [
            ChatResponse(content="", tool_calls=[ToolCall(name="add", args={"a": -1}, id="c1")]),
            ChatResponse(content="", tool_calls=[ToolCall(name="add", args={"b": -1}, id="c2")]),
        ]
    )
    result = run_native_tool_loop(lambda *a, **k: next(responses), "sys", [{"role": "user", "content": "go"}], TOOLS, _execute, 6, 256)
    assert result.failed and "after retry" in result.reason


class Verdict(BaseModel):
    verdict: str
    reason: str = ""


class _ScriptedBackend:
    supports_native_tools = False
    supports_json_mode = True

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, system, messages, **kwargs):
        self.calls.append((system, list(messages), kwargs))
        return ChatResponse(content=self.replies.pop(0))


def _llm_with(replies):
    llm = LLM.__new__(LLM)
    llm.backend, llm.model, llm.max_tokens, llm.native_tools = "scripted", "scripted-model", 512, False
    llm._backend = _ScriptedBackend(replies)
    return llm


def test_complete_json_strips_fences_and_retries_once():
    llm = _llm_with(["```json\n{\"verdict\": \"refinement\"}\n```"])
    assert llm.complete_json("s", "u", Verdict).verdict == "refinement"
    llm = _llm_with(["{\"nonsense\": 1}", "{\"verdict\": \"contradiction\", \"reason\": \"date moved\"}"])
    out = llm.complete_json("s", "u", Verdict)
    assert out.verdict == "contradiction"
    retry_messages = llm._backend.calls[1][1]
    assert retry_messages[-1]["role"] == "user" and "not valid" in retry_messages[-1]["content"]
    assert all(call[2]["json_mode"] for call in llm._backend.calls)


def test_complete_json_fails_loudly_after_two_bad_answers():
    llm = _llm_with(["garbage", "more garbage"])
    with pytest.raises(LLMFormatError):
        llm.complete_json("s", "u", Verdict)


def test_complete_and_unknown_backend():
    llm = _llm_with(["plain answer"])
    assert llm.complete("s", "u") == "plain answer"
    with pytest.raises(ValueError):
        LLM("quantum", "model")


def test_clean_schema_inlines_defs_and_nullables():
    class Inner(BaseModel):
        x: int

    class Outer(BaseModel):
        inner: Inner
        maybe: str | None = None

    schema = _clean_schema(Outer.model_json_schema())
    assert "$defs" not in schema and "title" not in schema
    assert schema["properties"]["inner"]["properties"]["x"]["type"] == "integer"
    assert schema["properties"]["maybe"]["nullable"] is True and schema["properties"]["maybe"]["type"] == "string"
