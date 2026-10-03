"""StandupAgent (capability ``standup``): procedural memory.

After two meetings share a title prefix (e.g. "Orbit standup 1", "Orbit standup 2") the agent
distils the routine into a Skill (ordered tool steps). ``run_skill`` tasks retrieve the best Skill
for a goal, execute its steps as tool calls and produce a standup-summary Artifact; the human
accepts or rejects it in the UI, which records the outcome.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from ingest.fakes import new_id

from .base import AgentResult, BaseAgent, load_prompt
from .tools import build_tools

log = logging.getLogger(__name__)

_TRAILING_NUMBER = re.compile(r"[\s\-:#]*\d+\s*$")
_SPACES = re.compile(r"\s+")

ROUTINE_STEPS: list[dict[str, Any]] = [
    {"order": 0, "tool": "open_commitments", "args_template": "{}", "guard": "always"},
    {"order": 1, "tool": "active_facts", "args_template": "{\"kind\": \"decision\"}", "guard": "always"},
    {"order": 2, "tool": "stale_decisions", "args_template": "{\"older_than_days\": 14}", "guard": "always"},
    {"order": 3, "tool": "recall", "args_template": "{\"query\": \"blockers and open questions for {{goal}}\", \"k\": 5}", "guard": "always"},
]


def title_prefix(title: str) -> str:
    """"Orbit standup 2" -> "orbit standup"; "Nimbus sync #3" -> "nimbus sync"."""
    return _SPACES.sub(" ", _TRAILING_NUMBER.sub("", title or "").strip().lower())


def meetings_by_prefix(meetings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for meeting in meetings:
        prefix = title_prefix(str(meeting.get("title") or ""))
        if prefix:
            groups.setdefault(prefix, []).append(meeting)
    return groups


def render_template(template: str, variables: dict[str, Any]) -> dict[str, Any]:
    """Substitute ``{{name}}`` placeholders in an ``args_template`` JSON string."""
    text = template
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", str(value))
    try:
        parsed = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class StandupAgent(BaseAgent):
    agent_id = "standup_agent"
    name = "StandupAgent"
    capabilities = ["standup"]
    handles = ("learn_standup", "run_skill", "standup")
    tool_names = ["open_commitments", "active_facts", "stale_decisions", "recall", "retrieve_skill", "learn_skill", "finish"]
    prompt_name = "standup"

    # -- learning ------------------------------------------------------------------------------
    def skill_goal(self, prefix: str) -> str:
        return f"Run the {prefix} routine: done, next, blockers, decisions since last time, stale commitments"

    def has_skill_for(self, prefix: str) -> bool:
        goal = self.skill_goal(prefix).lower()
        return any(str(s.get("goal", "")).lower() == goal and s.get("status") == "active" for s in self.hive.list_skills(self.tenant))

    def maybe_learn(self, prefix: str, meetings: list[dict[str, Any]]) -> str | None:
        """Learn the routine once the prefix has reached the configured number of meetings."""
        if len(meetings) < int(getattr(self.settings, "standup_min_meetings", 2)) or self.has_skill_for(prefix):
            return None
        learned_from: list[str] = []
        for meeting in meetings:
            episodes = self.hive.meeting_episodes(self.tenant, meeting["id"])
            if episodes:
                learned_from.append(episodes[0]["id"])
        goal = self.skill_goal(prefix)
        vec = self.embedder.embed_one(goal, "document")
        skill_id = self.hive.learn_skill(self.tenant, goal, ROUTINE_STEPS, learned_from, vec)
        log.info("learned skill %s for %r from %d meetings", skill_id, prefix, len(meetings))
        return skill_id

    # -- running ---------------------------------------------------------------------------------
    def run(self, task: dict[str, Any]) -> AgentResult:
        kind = task.get("kind")
        if kind == "learn_standup":
            return self._learn(task)
        if kind == "run_skill":
            return self._run_skill(task)
        return super().run(task)

    def _learn(self, task: dict[str, Any]) -> AgentResult:
        payload = task.get("payload") or {}
        prefix = title_prefix(str(payload.get("prefix") or payload.get("title") or ""))
        meetings = [m for m in self.hive.list_meetings(self.tenant) if title_prefix(str(m.get("title") or "")) == prefix]
        if not prefix or not meetings:
            return AgentResult(failed=True, reason=f"no meetings with prefix {prefix!r}")
        if self.has_skill_for(prefix):
            return AgentResult(final=f"skill for {prefix!r} already learned", steps=[])
        skill_id = self.maybe_learn(prefix, meetings)
        if skill_id is None:
            return AgentResult(failed=True, reason=f"prefix {prefix!r} has only {len(meetings)} meeting(s)")
        return AgentResult(
            final=f"learned skill {skill_id} for {prefix!r}",
            steps=[{"tool": "learn_skill", "args": {"goal": self.skill_goal(prefix)}, "result": {"skill_id": skill_id}}],
            artifact={"id": new_id("art"), "kind": "skill", "text": json.dumps({"skill_id": skill_id, "prefix": prefix})},
            used_skill_id=skill_id,
            model=getattr(self.llm, "model", ""),
        )

    def _run_skill(self, task: dict[str, Any]) -> AgentResult:
        payload = task.get("payload") or {}
        goal = str(payload.get("goal") or "standup")
        skills = self.hive.retrieve_skill(self.tenant, self.embedder.embed_one(goal, "query"), k=3)
        steps: list[dict[str, Any]] = [{"tool": "retrieve_skill", "args": {"goal": goal}, "result": {"candidates": [s.get("id") for s in skills]}}]
        if not skills:
            return AgentResult(failed=True, reason=f"no active skill matches goal {goal!r}; import two meetings with the same title first", steps=steps)
        skill = skills[0]
        toolset = build_tools(self, task, ["open_commitments", "active_facts", "stale_decisions", "recall", "why"])
        gathered: dict[str, Any] = {}
        for step in sorted(skill.get("steps") or [], key=lambda s: s.get("order", 0)):
            args = render_template(str(step.get("args_template") or "{}"), {"goal": goal, "tenant": self.tenant})
            result = toolset.execute(str(step.get("tool")), args)
            steps.append({"tool": step.get("tool"), "args": args, "result": result, "skill_step": step.get("order")})
            gathered[f"{step.get('order')}_{step.get('tool')}"] = result
        summary = self._summarise(goal, gathered)
        self.hive.publish(self.tenant, "skill.ran", {"skill_id": skill["id"], "agent_id": self.agent_id, "task_id": task.get("id"), "goal": goal, "pending_outcome": True})
        return AgentResult(
            final=summary,
            steps=steps,
            artifact={"id": new_id("art"), "kind": "standup_summary", "text": summary, "title": f"Standup summary: {goal}", "skill_id": skill["id"]},
            used_skill_id=skill["id"],
            model=getattr(self.llm, "model", ""),
        )

    def _summarise(self, goal: str, gathered: dict[str, Any]) -> str:
        if getattr(self.llm, "backend", "") != "fake":
            try:
                text = self.llm.complete(load_prompt("standup"), f"Goal: {goal}\n\nTool results (JSON):\n{json.dumps(gathered, default=str)[:12000]}\n\nWrite the standup summary now.", temperature=0.2, max_tokens=800)
                if text.strip():
                    return text.strip()
            except Exception as exc:  # noqa: BLE001 - fall through to the deterministic summary
                log.warning("standup summary via model failed: %s", exc)
        return render_standup(goal, gathered)


def _fmt_date(ms: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).date().isoformat()
    except (TypeError, ValueError, OSError):
        return "no date"


def render_standup(goal: str, gathered: dict[str, Any]) -> str:
    """Deterministic standup summary used by the fake backend (and as the model fallback)."""
    lines = [f"Standup summary ({goal})", ""]
    commitments = next((v.get("commitments") for k, v in gathered.items() if k.endswith("open_commitments") and isinstance(v, dict)), None) or []
    lines.append(f"Open commitments ({len(commitments)}):")
    for c in commitments[:8]:
        lines.append(f"- {c.get('owner') or c.get('speaker')}: {c.get('subject')} {c.get('predicate')} {c.get('object')} (due {_fmt_date(c.get('due_at'))})")
    decisions = next((v.get("facts") for k, v in gathered.items() if k.endswith("active_facts") and isinstance(v, dict)), None) or []
    lines.append("")
    lines.append(f"Decisions in force ({len(decisions)}):")
    for d in decisions[:8]:
        lines.append(f"- {d.get('subject')}: {d.get('object')} ({d.get('speaker')})")
    stale = next((v.get("decisions") for k, v in gathered.items() if k.endswith("stale_decisions") and isinstance(v, dict)), None) or []
    lines.append("")
    lines.append(f"Stale decisions older than two weeks: {len(stale)}")
    blockers = next((v.get("items") for k, v in gathered.items() if k.endswith("recall") and isinstance(v, dict)), None) or []
    lines.append("")
    lines.append("Blockers and open questions:")
    for b in blockers[:5]:
        lines.append(f"- {b.get('text')}")
    return "\n".join(lines)
