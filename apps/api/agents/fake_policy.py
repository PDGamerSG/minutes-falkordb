"""Deterministic stand-ins for the model when ``LLM_BACKEND=fake``.

The agents send a machine-readable header (``TASK_KIND: ...``, ``NEW_FACT_ID: ...``) at the top of
every task message; the tool policy reads it and replays the tool sequence a sensible model would
choose, so the board demo (supersede -> Scheduler -> hand-off -> FollowUp -> issue) works offline.
"""

from __future__ import annotations

import re
from typing import Any

from ingest.llm_protocol import LLMFormatError
from pydantic import BaseModel

from ..llm.gemma import ToolSpec

_HEADER = re.compile(r"^([A-Z_]+):\s*(.*)$", re.MULTILINE)


def parse_header(text: str) -> dict[str, str]:
    """``KEY: value`` lines from a task message."""
    return {m.group(1): m.group(2).strip() for m in _HEADER.finditer(text or "")}


def fake_json_policy(system: str, user: str, schema: type[BaseModel]) -> Any:
    name = schema.__name__
    if name == "RawExtraction":
        return {"entities": [], "items": []}
    if name == "SupersessionVerdict":
        return {"verdict": "contradiction", "reason": "fake backend: objects differ"}
    raise LLMFormatError(f"fake backend has no policy for schema {name}")


def fake_text_policy(system: str, user: str) -> str:
    return ""


def _tool_steps(history: list[dict[str, Any]]) -> int:
    return sum(1 for m in history if m.get("role") == "tool")


def fake_tool_policy(system: str, history: list[dict[str, Any]], tools: list[ToolSpec]) -> dict[str, Any] | None:
    """Next protocol message for the current task, based on the header and the steps so far."""
    first_user = next((m.get("content", "") for m in history if m.get("role") == "user"), "")
    header = parse_header(first_user)
    kind = header.get("TASK_KIND", "")
    done = _tool_steps(history)
    names = {t.name for t in tools}
    # The agent identity shows in its toolbox: a handed-off task keeps its kind, so dispatch on tools first.
    if "hand_off" in names and "update_commitment" in names:
        role = "scheduler"
    elif "create_issue" in names:
        role = "followup"
    elif "write_fact" in names:
        role = "fact"
    else:
        role = kind

    if role == "scheduler" or kind in ("reschedule", "schedule") and role not in ("followup", "fact"):
        new_fact = header.get("NEW_FACT_ID", "")
        old_fact = header.get("OLD_FACT_ID", "")
        due = header.get("DUE_AT", "")
        subject = header.get("SUBJECT", "the commitment")
        wants_update = bool(due and due.lower() not in {"none", ""}) and "does not match" in first_user
        if done == 0 and wants_update and "update_commitment" in names:
            return {"tool": "update_commitment", "args": {"fact_id": new_fact, "due_at": due}}
        if "hand_off" in names and not any("hand_off" in str(m.get("content", "")) for m in history if m.get("role") == "assistant"):
            ids = [i for i in (new_fact, old_fact, header.get("EPISODE_ID", "")) if i and i.lower() != "none"]
            summary = f"{subject} moved from {header.get('OLD_OBJECT', '?')} to {header.get('NEW_OBJECT', due or '?')}; nudge the owner and track it."
            return {"tool": "hand_off", "args": {"to_agent": "followup_agent", "summary": summary, "subgraph_ids": ids}}
        return {"final": "rescheduled"}

    if role == "followup" or kind in ("followup", "nudge", "demo"):
        subject = header.get("SUBJECT", "a commitment")
        new_object = header.get("NEW_OBJECT", header.get("DUE_AT", "a new date"))
        if done == 0 and "open_commitments" in names:
            return {"tool": "open_commitments", "args": {}}
        if done == 1 and "create_issue" in names:
            return {
                "tool": "create_issue",
                "args": {
                    "title": f"Follow up: {subject} now due {new_object}",
                    "body": f"The commitment '{subject}' moved to {new_object}. Confirm the new date with the owner and update dependent work.",
                    "labels": ["minutes", "follow-up"],
                },
            }
        if "finish" in names:
            return {"tool": "finish", "args": {"summary": f"Nudge sent: {subject} is now due {new_object}; tracking issue created.", "artifact_kind": "nudge_message", "artifact_text": f"Hi, quick reminder that {subject} now lands on {new_object}. Shout if that slips again."}}
        return {"final": "done"}

    if role == "fact" or kind in ("record_fact", "extract"):
        if done == 0 and "write_fact" in names and header.get("SUBJECT"):
            return {"tool": "write_fact", "args": {"kind": header.get("KIND", "fact"), "subject": header["SUBJECT"], "predicate": header.get("PREDICATE", "status"), "object": header.get("OBJECT", "noted"), "text": header.get("TEXT", f"{header['SUBJECT']} {header.get('PREDICATE', 'status')} {header.get('OBJECT', 'noted')}")}}
        return {"tool": "finish", "args": {"summary": "recorded"}} if "finish" in names else {"final": "recorded"}

    if "finish" in names:
        return {"tool": "finish", "args": {"summary": f"fake backend: no policy for task kind {kind!r}; nothing to do"}}
    return {"final": f"fake backend: no policy for task kind {kind!r}"}
