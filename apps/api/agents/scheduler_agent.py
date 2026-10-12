"""SchedulerAgent (capability ``schedule``): wakes on ``fact.superseded`` for date-like predicates,
aligns the commitment's due date and hands the follow-up to the FollowUpAgent with a subgraph reference.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from ingest.dates import date_to_ms, is_date_predicate, normalize_date
from ingest.models import canonical_entity_name

from .base import BaseAgent
from .tools import _fact_brief

log = logging.getLogger(__name__)

DAY_MS = 86_400_000


def superseded_event_to_task(payload: dict[str, Any], *, max_age_days: int | None = None, now_ms: int | None = None) -> dict[str, Any] | None:
    """Normalise a ``fact.superseded`` payload (hiveboard or pipeline shape) into a reschedule task spec.

    Returns None when the predicate does not carry a date (the Scheduler only cares about dates), and
    None for historical supersessions: when ``max_age_days`` is given and the payload's ``valid_from``
    is older than that, the event comes from a late import or a re-seed, not from something that just
    happened, unless the payload says ``live: true`` (the demo button does). Skips are logged at debug.

    The task requires the ``schedule`` capability so only the Scheduler can claim it (finding 3.3).
    """
    new_id = payload.get("new_fact_id") or payload.get("new_id")
    old_ids = payload.get("old_ids") or payload.get("old_fact_ids") or ([payload.get("old_fact_id")] if payload.get("old_fact_id") else [])
    key = str(payload.get("key") or "")
    predicate = payload.get("predicate") or (key.split("|", 1)[1] if "|" in key else "")
    subject = payload.get("subject") or canonical_entity_name(key.split("|", 1)[0] if "|" in key else "")
    new_object = payload.get("new_object") or payload.get("object")
    if not new_id or not is_date_predicate(str(predicate), str(new_object or "")):
        return None
    valid_from = payload.get("valid_from")
    if max_age_days is not None and valid_from is not None and not payload.get("live"):
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        try:
            age_days = (now - int(valid_from)) / DAY_MS
        except (TypeError, ValueError):
            age_days = 0.0
        if age_days > max_age_days:
            log.debug("skipping historical fact.superseded for %s (%s -> %s, valid_from %.0f days ago > %d)", key or new_id, payload.get("old_object"), new_object, age_days, max_age_days)
            return None
    due_iso = normalize_date(str(new_object)) if new_object else None
    return {
        "kind": "reschedule",
        "payload": {
            "new_fact_id": new_id,
            "old_fact_id": old_ids[0] if old_ids else None,
            "subject": subject,
            "predicate": predicate,
            "new_object": new_object,
            "old_object": payload.get("old_object"),
            "due_at": due_iso,
            "episode_id": payload.get("episode_id"),
            "trigger": "fact.superseded",
        },
        "requires": ["schedule"],
        "about_ids": [i for i in [new_id, *old_ids] if i],
        "priority": 3,
    }


class SchedulerAgent(BaseAgent):
    agent_id = "scheduler_agent"
    name = "SchedulerAgent"
    capabilities = ["schedule"]
    handles = ("reschedule", "schedule")
    tool_names = ["why", "active_facts", "open_commitments", "update_commitment", "submit_task", "hand_off", "finish"]
    prompt_name = "scheduler"
    wake_on = ("fact.superseded",)

    def context_for(self, task: dict[str, Any]) -> str:
        payload = task.get("payload") or {}
        lines = []
        new_fact = self.hive.get_fact(self.tenant, payload.get("new_fact_id") or "") if payload.get("new_fact_id") else None
        old_fact = self.hive.get_fact(self.tenant, payload.get("old_fact_id") or "") if payload.get("old_fact_id") else None
        if new_fact:
            brief = _fact_brief(new_fact)
            due = new_fact.get("due_at")
            due_iso = datetime.fromtimestamp(due / 1000, tz=UTC).date().isoformat() if due else None
            lines.append(f"New fact {brief['id']}: {brief['subject']} {brief['predicate']} {brief['object']} (kind={brief['kind']}, due_at={due_iso}, owner={brief['speaker']} / {brief['speaker_id']})")
        if old_fact:
            brief = _fact_brief(old_fact)
            lines.append(f"Replaced fact {brief['id']}: {brief['subject']} {brief['predicate']} {brief['object']} (status={brief['status']})")
        elif payload.get("old_object"):
            lines.append(f"Previous value: {payload['old_object']}")
        expected = payload.get("due_at")
        if expected and new_fact:
            current = new_fact.get("due_at")
            if current != date_to_ms(expected):
                lines.append(f"The commitment's due_at ({current}) does not match the new date {expected}: call update_commitment first.")
            else:
                lines.append(f"The commitment's due_at already matches {expected}; no update_commitment needed.")
        return ("Context from the memory graph:\n" + "\n".join(lines)) if lines else ""

    def task_instructions(self, task: dict[str, Any]) -> str:
        payload = task.get("payload") or {}
        ids = [i for i in (payload.get("new_fact_id"), payload.get("old_fact_id"), payload.get("episode_id")) if i]
        return (
            "A dated statement was superseded. If the commitment's due_at differs from the new date, call "
            "update_commitment(fact_id=NEW_FACT_ID, due_at=DUE_AT). Then hand_off to 'followup_agent' with a "
            f"one-sentence summary of what moved and subgraph_ids={ids}. Do not create issues yourself."
        )
