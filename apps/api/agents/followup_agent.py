"""FollowUpAgent (capability ``followup``): turns a changed or stale commitment into a nudge and a ticket."""

from __future__ import annotations

from typing import Any

from .base import BaseAgent
from .tools import _fact_brief


class FollowUpAgent(BaseAgent):
    agent_id = "followup_agent"
    name = "FollowUpAgent"
    capabilities = ["followup"]
    handles = ("followup", "nudge", "demo")  # reschedule reaches it only by hand-off from the Scheduler
    tool_names = ["recall", "why", "open_commitments", "active_facts", "create_issue", "finish"]
    prompt_name = "followup"

    def context_for(self, task: dict[str, Any]) -> str:
        """Pre-load the provenance of the nodes the task is about so the model starts informed."""
        lines = []
        payload = task.get("payload") or {}
        ids = list(task.get("about") or [])
        for key in ("new_fact_id", "fact_id", "commitment_id"):
            if payload.get(key) and payload[key] not in ids:
                ids.append(payload[key])
        for node_id in ids[:3]:
            try:
                info = self.hive.why(self.tenant, node_id)
            except Exception:  # noqa: BLE001 - the model can still look things up itself
                continue
            node = _fact_brief(info.get("node") or {})
            speaker = (info.get("speaker") or {}).get("name") or node.get("speaker")
            where = (info.get("meeting") or {}).get("title") or (info.get("thread") or {}).get("subject")
            lines.append(f"- {node['kind']} {node['id']}: {node['subject']} {node['predicate']} {node['object']} (said by {speaker} in {where!r})")
            for older in info.get("history") or []:
                if older.get("id") != node["id"]:
                    lines.append(f"    previously: {older.get('subject')} {older.get('predicate')} {older.get('object')} ({older.get('status')})")
        handoff = payload.get("handoff_summary") or payload.get("summary")
        if handoff:
            lines.append(f"Hand-off summary: {handoff}")
        if payload.get("old_object") and payload.get("new_object"):
            lines.append(f"Date change: {payload.get('subject')} moved from {payload['old_object']} to {payload['new_object']}.")
        return ("Context from the memory graph:\n" + "\n".join(lines)) if lines else ""

    def task_instructions(self, task: dict[str, Any]) -> str:
        return (
            "Decide who must be nudged and about what. Use why/open_commitments if the context is thin. "
            "Then create_issue with a short title and a body that names the owner, the old and new dates "
            "and the source meeting or email. Finally call finish with a one-paragraph nudge message "
            "(artifact_kind='nudge_message')."
        )
