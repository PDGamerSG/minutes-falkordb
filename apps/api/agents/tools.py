"""Tools the agents can call. Every tool validates its arguments with a Pydantic model
(``ToolSpec.args_model``) before touching the graph; handlers run parameterised Cypher through
the hive adapter, never free-form Cypher from the model.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
from ingest.dates import date_to_ms
from ingest.fakes import new_id, now_ms
from pydantic import BaseModel, Field

from ..llm.gemma import ToolSpec

log = logging.getLogger(__name__)

Handler = Callable[[BaseModel], dict[str, Any]]


@dataclass
class Tool:
    spec: ToolSpec
    handler: Handler


@dataclass
class ToolSet:
    """Dispatch table for one agent run; records artifacts and hand-offs produced by tools."""

    tools: list[Tool]
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    handed_off: bool = False
    used_skill_id: str | None = None
    submitted_tasks: list[str] = field(default_factory=list)

    PRIMARY_KINDS = ("github_issue", "standup_summary", "extraction", "skill", "answer")

    @property
    def specs(self) -> list[ToolSpec]:
        return [t.spec for t in self.tools]

    @property
    def artifact(self) -> dict[str, Any] | None:
        """The artifact to attach to the task: a ticket or summary first, otherwise the last one produced.
        Other artifacts (e.g. the nudge text) are folded into its JSON text under ``also``."""
        if not self.artifacts:
            return None
        primary = next((a for kind in self.PRIMARY_KINDS for a in self.artifacts if a.get("kind") == kind), self.artifacts[-1])
        others = [a for a in self.artifacts if a is not primary]
        if not others:
            return primary
        text = primary.get("text")
        try:
            payload = json.loads(text) if isinstance(text, str) and text.strip().startswith("{") else {"text": text}
        except json.JSONDecodeError:
            payload = {"text": text}
        if not isinstance(payload, dict):
            payload = {"text": text}
        payload["also"] = [{"kind": a.get("kind"), "text": a.get("text")} for a in others]
        return {**primary, "text": json.dumps(payload, default=str)}

    def execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        tool = next((t for t in self.tools if t.spec.name == name), None)
        if tool is None:
            return {"error": f"unknown tool {name!r}"}
        try:
            result = tool.handler(tool.spec.args_model.model_validate(args))
        except Exception as exc:  # noqa: BLE001 - the model sees the error and can retry or finish
            log.warning("tool %s failed: %s", name, exc)
            return {"error": f"{type(exc).__name__}: {exc}"[:500]}
        if result.get("artifact"):
            self.artifacts.append(result["artifact"])
        if result.get("handed_off"):
            self.handed_off = True
        if result.get("used_skill_id"):
            self.used_skill_id = result["used_skill_id"]
        if result.get("submitted_task_id"):
            self.submitted_tasks.append(result["submitted_task_id"])
        return result


# --------------------------------------------------------------------------- arg models
class RecallArgs(BaseModel):
    query: str = Field(description="natural-language query to search the memory for")
    k: int = Field(default=5, ge=1, le=20)


class ActiveFactsArgs(BaseModel):
    entity: str | None = Field(default=None, description="entity id or name to filter on")
    kind: str | None = Field(default=None, description="fact | decision | commitment")


class OpenCommitmentsArgs(BaseModel):
    person_id: str | None = Field(default=None, description="owner id such as spk_priya; omit for everyone")


class WhyArgs(BaseModel):
    node_id: str = Field(description="id of a fact, decision or commitment")


class CreateIssueArgs(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(default="", max_length=8000)
    labels: list[str] = Field(default_factory=list)


class UpdateCommitmentArgs(BaseModel):
    fact_id: str = Field(description="id of the commitment")
    due_at: str = Field(description="new due date, ISO YYYY-MM-DD")


class SubmitTaskArgs(BaseModel):
    kind: str = Field(min_length=2)
    payload: dict[str, Any] = Field(default_factory=dict)
    requires: list[str] = Field(default_factory=list, description="capabilities the task needs, e.g. ['followup']")
    about_ids: list[str] = Field(default_factory=list)
    priority: int = Field(default=5, ge=1, le=10)


class HandOffArgs(BaseModel):
    to_agent: str = Field(description="agent id, e.g. followup_agent")
    summary: str = Field(min_length=3, max_length=2000)
    subgraph_ids: list[str] = Field(default_factory=list, description="ids of the nodes the receiver should read")


class StepArgs(BaseModel):
    order: int = Field(ge=0)
    tool: str
    args_template: str = Field(default="{}", description="JSON string of the tool args; {{goal}} and {{tenant}} are substituted")
    guard: str | None = None


class LearnSkillArgs(BaseModel):
    goal: str = Field(min_length=3)
    steps: list[StepArgs] = Field(min_length=1)
    learned_from: list[str] = Field(default_factory=list)


class RetrieveSkillArgs(BaseModel):
    goal: str = Field(min_length=3)


class RecordOutcomeArgs(BaseModel):
    skill_id: str
    ok: bool


class WriteFactArgs(BaseModel):
    kind: str = Field(default="fact", pattern="^(fact|decision|commitment)$")
    subject: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object: str = Field(min_length=1)
    text: str = Field(min_length=1)
    due_at: str | None = None
    confidence: float = Field(default=0.7, ge=0, le=1)


class StaleDecisionsArgs(BaseModel):
    older_than_days: int = Field(default=14, ge=1, le=365)


class FinishArgs(BaseModel):
    summary: str = Field(min_length=1, max_length=8000)
    artifact_kind: str | None = Field(default=None, description="e.g. nudge_message, standup_summary")
    artifact_text: str | None = None


# --------------------------------------------------------------------------- helpers
def _fact_brief(fact: dict[str, Any]) -> dict[str, Any]:
    speaker = fact.get("speaker") or {}
    return {
        "id": fact.get("id"),
        "kind": fact.get("kind"),
        "subject": fact.get("subject"),
        "predicate": fact.get("predicate"),
        "object": fact.get("object"),
        "text": fact.get("text"),
        "status": fact.get("status"),
        "valid_from": fact.get("valid_from"),
        "due_at": fact.get("due_at"),
        "speaker": speaker.get("name") or fact.get("speaker_id"),
        "speaker_id": speaker.get("id") or fact.get("speaker_id"),
    }


def create_github_issue(title: str, body: str, labels: list[str], *, token: str, repo: str) -> dict[str, Any]:
    """Create a real issue through the GitHub REST API; returns ``{uri, number}``."""
    response = httpx.post(
        f"https://api.github.com/repos/{repo}/issues",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"},
        json={"title": title, "body": body, "labels": labels},
        timeout=20.0,
    )
    response.raise_for_status()
    data = response.json()
    return {"uri": data.get("html_url"), "number": data.get("number")}


# --------------------------------------------------------------------------- factory
def build_tools(agent: Any, task: dict[str, Any], names: list[str]) -> ToolSet:
    """Instantiate the named tools bound to ``agent`` (tenant, hive, llm, embedder, settings) and ``task``."""
    hive, tenant, embedder, settings = agent.hive, agent.tenant, agent.embedder, agent.settings
    registry: dict[str, Tool] = {}

    def add(name: str, description: str, model: type[BaseModel], handler: Handler) -> None:
        registry[name] = Tool(ToolSpec(name=name, description=description, args_model=model), handler)

    def recall(args: RecallArgs) -> dict[str, Any]:
        vec = embedder.embed_one(args.query, "query")
        result = hive.recall(tenant, vec, k=args.k)
        items = [{**_fact_brief(i.get("node") or {}), "similarity": i.get("similarity"), "rank": i.get("rank")} for i in result["items"]]
        return {"items": items, "cypher": result.get("cypher")}

    def active_facts(args: ActiveFactsArgs) -> dict[str, Any]:
        rows = hive.list_facts(tenant, status="active", entity=args.entity, kind=args.kind)
        return {"facts": [_fact_brief(f) for f in rows[:40]]}

    def open_commitments(args: OpenCommitmentsArgs) -> dict[str, Any]:
        result = hive.open_commitments(tenant, args.person_id)
        rows = [{**_fact_brief(r), "owner": (r.get("owner") or {}).get("name")} for r in result["rows"]]
        return {"commitments": rows[:40], "cypher": result.get("cypher")}

    def why(args: WhyArgs) -> dict[str, Any]:
        info = hive.why(tenant, args.node_id)
        episode = info.get("episode") or {}
        node = _fact_brief(info.get("node") or {})
        # the substrate returns the chain newest first (and the fake omits the node itself): normalise to oldest first
        history = [_fact_brief(h) for h in info.get("history") or []]
        if node.get("id") and all(h.get("id") != node["id"] for h in history):
            history.append(node)
        history.sort(key=lambda h: h.get("valid_from") or 0)
        source_kind = (info.get("source") or {}).get("kind") or ("email" if info.get("thread") else "utterance")
        return {
            "node": node,
            "speaker": (info.get("speaker") or {}).get("name"),
            "source_kind": source_kind,
            "meeting": (info.get("meeting") or {}).get("title") if source_kind != "email" else None,
            "thread": (info.get("thread") or {}).get("subject"),
            "said" if source_kind != "email" else "wrote": episode.get("text"),
            "t_start": episode.get("t_start"),
            "source": info.get("source"),
            "history_order": "oldest first; the last active version is the current value",
            "history": history,
        }

    def create_issue(args: CreateIssueArgs) -> dict[str, Any]:
        artifact: dict[str, Any] = {"id": new_id("art"), "kind": "github_issue", "title": args.title, "body": args.body, "simulated": True}
        if settings.github_token and settings.github_demo_repo:
            try:
                created = create_github_issue(args.title, args.body, args.labels, token=settings.github_token, repo=settings.github_demo_repo)
                artifact.update({"uri": created["uri"], "number": created["number"], "simulated": False})
            except Exception as exc:  # noqa: BLE001 - keep the demo moving, record the failure
                log.warning("GitHub issue creation failed: %s", exc)
                artifact["github_error"] = str(exc)[:300]
        if artifact.get("uri") is None:
            # Simulated tickets never point at a real GitHub namespace (finding 2.9).
            artifact["uri"] = f"minutes://simulated/issue/{new_id('sim')[-8:]}"
        artifact["text"] = json.dumps({"title": args.title, "body": args.body, "labels": args.labels, "simulated": artifact["simulated"]})
        return {"artifact": artifact, "issue_url": artifact["uri"], "simulated": artifact["simulated"]}

    def update_commitment(args: UpdateCommitmentArgs) -> dict[str, Any]:
        due_ms = date_to_ms(args.due_at)
        if due_ms is None:
            return {"error": f"due_at {args.due_at!r} is not an ISO date"}
        fact = hive.update_fact_due(tenant, args.fact_id, due_ms)
        hive.publish(tenant, "commitment.updated", {"commitment_id": args.fact_id, "due_at": due_ms, "by": agent.agent_id, "task_id": task.get("id")})
        return {"updated": _fact_brief(fact), "due_at": due_ms}

    def submit_task(args: SubmitTaskArgs) -> dict[str, Any]:
        task_id = hive.submit_task(tenant, args.kind, args.payload, args.requires, args.about_ids, args.priority)
        return {"submitted_task_id": task_id, "kind": args.kind}

    def hand_off(args: HandOffArgs) -> dict[str, Any]:
        version = hive.handoff(tenant, task["id"], agent.agent_id, args.to_agent, task["version"], args.summary, args.subgraph_ids)
        if version is None:
            return {"error": "handoff rejected (stale version, not the owner, or unknown agent)"}
        task["version"] = version
        return {"handed_off": True, "to_agent": args.to_agent, "version": version, "stop": True, "final": f"handed off to {args.to_agent}: {args.summary}"}

    def learn_skill(args: LearnSkillArgs) -> dict[str, Any]:
        vec = embedder.embed_one(args.goal, "document")
        skill_id = hive.learn_skill(tenant, args.goal, [s.model_dump() for s in args.steps], args.learned_from, vec)
        return {"skill_id": skill_id, "goal": args.goal, "steps": len(args.steps)}

    def retrieve_skill(args: RetrieveSkillArgs) -> dict[str, Any]:
        vec = embedder.embed_one(args.goal, "query")
        skills = hive.retrieve_skill(tenant, vec, k=3)
        if not skills:
            return {"skills": [], "note": "no active skill matches; learn one or finish"}
        best = skills[0]
        return {"skills": [{"id": s["id"], "goal": s["goal"], "success_rate": s.get("success_rate"), "runs": s.get("runs"), "steps": s.get("steps")} for s in skills], "used_skill_id": best["id"]}

    def record_outcome(args: RecordOutcomeArgs) -> dict[str, Any]:
        skill = hive.record_outcome(tenant, args.skill_id, agent.agent_id, args.ok, task.get("id"))
        return {"skill_id": args.skill_id, "runs": skill.get("runs"), "success_rate": skill.get("success_rate")}

    def write_fact(args: WriteFactArgs) -> dict[str, Any]:
        vec = embedder.embed_one(args.text, "document")
        fact = {
            "kind": args.kind,
            "subject": args.subject,
            "predicate": args.predicate,
            "object": args.object,
            "text": args.text,
            "confidence": args.confidence,
            "speaker_id": None,
            "episode_id": None,
            "entity_ids": [],
            "valid_from": now_ms(),
            "embedding": vec,
        }
        due_ms = date_to_ms(args.due_at) if args.due_at else None
        if due_ms is not None:
            fact["due_at"] = due_ms
        result = hive.remember_fact(tenant, fact)
        return {"fact_id": result["id"], "superseded": result.get("superseded", [])}

    def stale_decisions(args: StaleDecisionsArgs) -> dict[str, Any]:
        result = hive.stale_decisions(tenant, args.older_than_days * 86_400_000)
        return {"decisions": [_fact_brief(r) for r in result["rows"][:20]], "cypher": result.get("cypher")}

    def finish(args: FinishArgs) -> dict[str, Any]:
        out: dict[str, Any] = {"stop": True, "final": args.summary}
        if args.artifact_kind:
            out["artifact"] = {"id": new_id("art"), "kind": args.artifact_kind, "text": args.artifact_text or args.summary}
        return out

    add("recall", "Semantic search over the team memory (facts, decisions, commitments). Returns the best matches with ids.", RecallArgs, recall)
    add("active_facts", "List currently active facts, optionally for one entity and/or kind.", ActiveFactsArgs, active_facts)
    add("open_commitments", "Open commitments (who promised what by when), optionally for one person.", OpenCommitmentsArgs, open_commitments)
    add("why", "Provenance of a fact: who said it, in which meeting or email, when, and what it replaced.", WhyArgs, why)
    add("create_issue", "Create a tracking issue (GitHub when configured, otherwise simulated) and record it as the task artifact.", CreateIssueArgs, create_issue)
    add("update_commitment", "Set a new due date on a commitment and announce commitment.updated.", UpdateCommitmentArgs, update_commitment)
    add("submit_task", "Submit a new task to the board for agents with the given capabilities.", SubmitTaskArgs, submit_task)
    add("hand_off", "Hand the current task to another agent with a summary and the ids of the nodes they should read. Ends your turn.", HandOffArgs, hand_off)
    add("learn_skill", "Store a reusable routine (ordered tool steps) as a Skill.", LearnSkillArgs, learn_skill)
    add("retrieve_skill", "Find the best stored Skill for a goal.", RetrieveSkillArgs, retrieve_skill)
    add("record_outcome", "Record whether a Skill run succeeded.", RecordOutcomeArgs, record_outcome)
    add("write_fact", "Store a new fact, decision or commitment in the memory.", WriteFactArgs, write_fact)
    add("stale_decisions", "Active decisions older than N days.", StaleDecisionsArgs, stale_decisions)
    add("finish", "Finish the task with a summary (and optionally an artifact). Call this when you are done.", FinishArgs, finish)

    missing = [n for n in names if n not in registry]
    if missing:
        raise KeyError(f"unknown tools {missing}")
    return ToolSet([registry[n] for n in names])
