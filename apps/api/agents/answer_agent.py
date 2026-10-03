"""AnswerAgent (capability ``answer``): hybrid router -> retrieval -> grounded answer with provenance.

Every answer carries the Cypher that ran, the subgraph it touched, the sources (fact ids with who
said it and where) and the router decision, so the UI can render the Why panel.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any

from ingest.fakes import new_id

from .base import AgentResult, BaseAgent, load_prompt
from .router import RouterDecision, route

log = logging.getLogger(__name__)


def _iso(ms: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC).date().isoformat()
    except (TypeError, ValueError, OSError):
        return "?"


def _source_from_fact(fact: dict[str, Any]) -> dict[str, Any]:
    """Chat ``sources[]`` item: display strings plus the ids the UI needs to jump to the source."""
    src = fact.get("source") or {}
    kind = src.get("kind") or ("email" if fact.get("thread") else "utterance")
    speaker = fact.get("speaker") or {}
    meeting = fact.get("meeting") or {}
    thread = fact.get("thread") or {}
    container = src.get("container") or {}
    item: dict[str, Any] = {
        "fact_id": fact.get("id"),
        "kind": kind,
        "speaker": speaker.get("name") or fact.get("speaker_id") or "unknown",
        "container_id": container.get("id") or meeting.get("id") or thread.get("id"),
        "valid_from": fact.get("valid_from"),
        "text": fact.get("text"),
    }
    if kind == "email":
        item["thread"] = thread.get("subject") or container.get("subject")
        item["sent_at"] = src.get("sent_at") or fact.get("valid_from")
        item["message_id"] = src.get("message_id")
    else:
        item["meeting"] = meeting.get("title") or container.get("title")
        item["t_start"] = src.get("t_start")
    return item


def _subgraph_from_facts(facts: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    def add(nid: str | None, label: str, props: dict[str, Any]) -> None:
        if nid and nid not in nodes:
            nodes[nid] = {"id": nid, "label": label, "props": {k: v for k, v in props.items() if k not in {"embedding", "entities", "speaker", "meeting", "thread", "source"}}}

    for fact in facts:
        fid = fact.get("id")
        label = {"decision": "Decision", "commitment": "Commitment"}.get(str(fact.get("kind")), "Fact")
        add(fid, label, fact)
        speaker = fact.get("speaker") or {}
        if speaker.get("id"):
            add(speaker["id"], "Person", speaker)
            edges.append({"source": fid, "target": speaker["id"], "type": "STATED_BY", "props": {}})
        for entity in fact.get("entities") or []:
            if entity and entity.get("id"):
                add(entity["id"], "Entity", entity)
                edges.append({"source": fid, "target": entity["id"], "type": "ABOUT", "props": {}})
        container = fact.get("meeting") or fact.get("thread")
        if container and container.get("id"):
            add(container["id"], "Meeting" if fact.get("meeting") else "EmailThread", container)
            edges.append({"source": container["id"], "target": fid, "type": "CONTAINS", "props": {}})
        for old in fact.get("supersedes") or []:
            edges.append({"source": fid, "target": old, "type": "SUPERSEDES", "props": {}})
    return {"nodes": list(nodes.values()), "edges": edges}


class AnswerAgent(BaseAgent):
    agent_id = "answer_agent"
    name = "AnswerAgent"
    capabilities = ["answer"]
    handles = ("question", "answer")
    tool_names = ["recall", "active_facts", "why", "finish"]
    prompt_name = "answer"

    # -- worker path ------------------------------------------------------------------------------
    def run(self, task: dict[str, Any]) -> AgentResult:
        payload = task.get("payload") or {}
        question = str(payload.get("message") or payload.get("question") or "")
        if not question:
            return AgentResult(failed=True, reason="question task needs payload.message")
        response = self.answer(question, payload.get("session_id"))
        return AgentResult(
            final=response["answer"],
            steps=[{"tool": "answer", "args": {"message": question}, "result": {"route": response["router"]["route"], "sources": len(response["sources"])}}],
            artifact={"id": new_id("art"), "kind": "answer", "text": response["answer"]},
            model=response["model"],
            latency_ms=response["latency_ms"],
        )

    # -- chat path --------------------------------------------------------------------------------
    def answer(self, message: str, session_id: str | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        session_id = session_id or new_id("sess")
        decision = route(message, self.hive.list_entities(self.tenant), self.hive.list_persons(self.tenant))
        facts, cypher, subgraph, extra = self._retrieve(message, decision)
        sources = [_source_from_fact(f) for f in facts[:12]]
        answer = self._compose(message, decision, facts, extra)
        latency = int((time.perf_counter() - started) * 1000)
        response = {
            "answer": answer,
            "session_id": session_id,
            "router": decision.as_dict(),
            "cypher": [c for c in cypher if c],
            "subgraph": subgraph,
            "sources": sources,
            "model": getattr(self.llm, "model", "fake"),
            "latency_ms": latency,
        }
        self.hive.add_turn(self.tenant, session_id, "user", message, {})
        self.hive.add_turn(self.tenant, session_id, "assistant", answer, {"response": response})
        return response

    def _retrieve(self, message: str, decision: RouterDecision) -> tuple[list[dict[str, Any]], list[str], dict[str, Any], dict[str, Any]]:
        """Run the route; returns (facts, cypher list, subgraph, extra rows for templating)."""
        tenant = self.tenant
        extra: dict[str, Any] = {}
        if decision.route == "freeform_ro":
            if decision.notes.startswith("rejected"):
                return [], [decision.cypher or ""], {"nodes": [], "edges": []}, {"error": decision.notes}
            try:
                result = self.hive.run_ro_cypher(tenant, decision.cypher or "", {}, timeout_ms=3000)
            except Exception as exc:  # noqa: BLE001 - surface the engine's error to the user
                return [], [decision.cypher or ""], {"nodes": [], "edges": []}, {"error": str(exc)[:500]}
            rows = result.get("rows", [])
            facts = [r for r in rows if isinstance(r, dict) and r.get("id") and r.get("subject")]
            return facts, [result.get("cypher", "")], _subgraph_from_facts(facts), {"rows": rows[:20]}

        if decision.route == "template":
            if decision.intent == "who_knows":
                result = self.hive.who_knows(tenant, decision.entities[0])
                extra["who_knows"] = result["rows"]
                facts = self.hive.list_facts(tenant, status="active", entity=decision.entity_ids[0] if decision.entity_ids else decision.entities[0])
                return facts, [result.get("cypher", "")], _subgraph_from_facts(facts), extra
            if decision.intent == "open_commitments":
                person = decision.person_ids[0] if decision.person_ids else None
                result = self.hive.open_commitments(tenant, person)
                rows = result["rows"]
                if decision.entity_ids:
                    wanted = set(decision.entity_ids)
                    rows = [r for r in rows if wanted & set(r.get("entity_ids") or [])] or rows
                # the analytics query returns owner + entities only; join speaker and container for the sources
                rows = [{**r, **(self.hive.get_fact(tenant, r["id"]) or {})} if r.get("id") else r for r in rows[:20]]
                for row in rows:
                    if not row.get("speaker") and row.get("owner"):
                        row["speaker"] = row["owner"]
                return rows, [result.get("cypher", "")], _subgraph_from_facts(rows), extra
            if decision.intent == "contradictions":
                result = self.hive.contradictions(tenant)
                extra["contradictions"] = result["rows"]
                facts = [f for pair in result["rows"] for f in pair.get("facts", []) if f]
                return facts, [result.get("cypher", "")], _subgraph_from_facts(facts), extra
            if decision.intent == "stale_decisions":
                result = self.hive.stale_decisions(tenant, 14 * 86_400_000)
                return result["rows"], [result.get("cypher", "")], _subgraph_from_facts(result["rows"]), extra
            if decision.intent == "belief_at":
                entity = decision.entity_ids[0] if decision.entity_ids else None
                result = self.hive.belief_at_result(tenant, int(decision.at_ms or 0), entity)
                rows = result["rows"]
                if entity is None and decision.entities:
                    wanted = {e.lower() for e in decision.entities}
                    rows = [r for r in rows if str(r.get("subject", "")).lower() in wanted] or rows
                return rows, [result.get("cypher", "")], _subgraph_from_facts(rows), extra
            if decision.intent == "why":
                vec = self.embedder.embed_one(message, "query")
                recall = self.hive.recall(tenant, vec, k=5)
                cyphers = [recall.get("cypher", "")]
                candidates = [i.get("node") or {} for i in recall["items"]]
                if decision.entity_ids:
                    anchored = self.hive.list_facts(tenant, status="active", entity=decision.entity_ids[0])
                    candidates = anchored[::-1] + candidates
                facts: list[dict[str, Any]] = []
                subgraph = {"nodes": [], "edges": []}
                for candidate in candidates[:3]:
                    if not candidate.get("id"):
                        continue
                    try:
                        why = self.hive.why(tenant, candidate["id"])
                    except Exception:  # noqa: BLE001
                        continue
                    cyphers.append(why.get("cypher", ""))
                    full = self.hive.get_fact(tenant, candidate["id"]) or candidate
                    facts.append(full)
                    extra.setdefault("why", []).append({"id": candidate["id"], "episode": why.get("episode"), "history": why.get("history"), "speaker": why.get("speaker"), "meeting": why.get("meeting"), "thread": why.get("thread")})
                    if not subgraph["nodes"]:
                        subgraph = why.get("subgraph") or subgraph
                return facts, cyphers, subgraph if subgraph["nodes"] else _subgraph_from_facts(facts), extra

        if decision.route == "graph":
            facts: list[dict[str, Any]] = []
            cyphers: list[str] = []
            for entity_id in decision.entity_ids[:3]:
                rows = self.hive.list_facts(tenant, status="active", entity=entity_id)
                if decision.intent == "decisions":
                    rows = [r for r in rows if r.get("kind") == "decision"] or rows
                if decision.intent == "when":
                    rows = sorted(rows, key=lambda r: (r.get("due_at") is None, -(r.get("valid_from") or 0)))
                facts.extend(r for r in rows if r.get("id") not in {f.get("id") for f in facts})
            cyphers.append("MATCH (f:Fact {status:'active'})-[:ABOUT]->(e:Entity {id:$entity}) OPTIONAL MATCH (f)-[:STATED_BY]->(p) OPTIONAL MATCH (f)-[:DERIVED_FROM]->(ep)<-[:HAS_EPISODE]-(c) RETURN f, p, ep, c ORDER BY f.valid_from")
            if facts:
                try:
                    why = self.hive.why(tenant, facts[-1]["id"])
                    cyphers.append(why.get("cypher", ""))
                    extra["why"] = [{"id": facts[-1]["id"], "episode": why.get("episode"), "history": why.get("history")}]
                    merged = _subgraph_from_facts(facts)
                    for node in (why.get("subgraph") or {}).get("nodes", []):
                        if not any(n["id"] == node["id"] for n in merged["nodes"]):
                            merged["nodes"].append(node)
                    merged["edges"].extend((why.get("subgraph") or {}).get("edges", []))
                    return facts, cyphers, merged, extra
                except Exception:  # noqa: BLE001
                    pass
            return facts, cyphers, _subgraph_from_facts(facts), extra

        vec = self.embedder.embed_one(message, "query")
        recall = self.hive.recall(tenant, vec, k=8)
        facts = [{**(i.get("node") or {}), "entities": i.get("entities") or [], "similarity": i.get("similarity")} for i in recall["items"]]
        enriched = []
        for fact in facts:
            full = self.hive.get_fact(tenant, fact["id"]) if fact.get("id") else None
            enriched.append({**fact, **(full or {})})
        return enriched, [recall.get("cypher", "")], recall.get("subgraph") or _subgraph_from_facts(enriched), extra

    def _compose(self, message: str, decision: RouterDecision, facts: list[dict[str, Any]], extra: dict[str, Any]) -> str:
        if extra.get("error"):
            return f"I could not run that query: {extra['error']}"
        answerable = facts or extra.get("who_knows") or extra.get("rows") or extra.get("contradictions") is not None
        if not answerable:
            return "I found nothing in the team memory that answers that. Try naming the project, person or decision."
        if getattr(self.llm, "backend", "") == "fake":
            return render_answer(message, decision, facts, extra)
        context_lines = []
        for fact in facts[:12]:
            speaker = (fact.get("speaker") or {}).get("name") or fact.get("speaker_id")
            where = (fact.get("meeting") or {}).get("title") or (fact.get("thread") or {}).get("subject") or "?"
            status = fact.get("status", "active")
            context_lines.append(
                f"- [{fact.get('id')}] ({fact.get('kind')}, {status}, said {_iso(fact.get('valid_from'))} by {speaker} in {where!r}) "
                f"{fact.get('subject')} {fact.get('predicate')} {fact.get('object')}: {fact.get('text')}"
            )
        for item in extra.get("why", []) or []:
            older = [f"{h.get('object')} ({_iso(h.get('valid_from'))})" for h in item.get("history") or [] if h.get("id") != item.get("id")]
            if older:
                context_lines.append(f"- history of {item['id']}: previously {' <- '.join(older)}")
        if extra.get("who_knows"):
            context_lines.append("- who knows: " + ", ".join(f"{r['person']['name']} ({r['mentions']} mentions)" for r in extra["who_knows"][:6]))
        user = f"Question: {message}\nRouter: {decision.as_dict()}\n\nEvidence from the memory graph:\n" + "\n".join(context_lines) + "\n\nAnswer in at most five sentences, citing fact ids in square brackets."
        try:
            text = self.llm.complete(load_prompt("answer"), user, temperature=0.2, max_tokens=600)
        except Exception as exc:  # noqa: BLE001 - fail loudly in the payload, keep provenance
            log.error("answer composition failed: %s", exc)
            return f"The model failed to compose an answer ({type(exc).__name__}); evidence: " + render_answer(message, decision, facts, extra)
        return text.strip() or render_answer(message, decision, facts, extra)


def render_answer(message: str, decision: RouterDecision, facts: list[dict[str, Any]], extra: dict[str, Any]) -> str:
    """Deterministic, citation-bearing answer used by the fake backend and as the model fallback."""
    if extra.get("who_knows"):
        people = ", ".join(f"{r['person']['name']} ({r['mentions']})" for r in extra["who_knows"][:5])
        return f"People with context on {decision.entities[0] if decision.entities else 'that'}: {people}."
    if extra.get("contradictions") is not None and decision.intent == "contradictions":
        pairs = extra["contradictions"]
        if not pairs:
            return "No contradictions: every active key has a single object."
        parts = [f"{p['key']}: '{p['facts'][0].get('object')}' vs '{p['facts'][1].get('object')}'" for p in pairs[:5]]
        return f"{len(pairs)} contradiction(s) between active facts: " + "; ".join(parts) + "."
    lines = []
    for fact in facts[:6]:
        speaker = (fact.get("speaker") or {}).get("name") or fact.get("speaker_id") or "someone"
        where = (fact.get("meeting") or {}).get("title") or (fact.get("thread") or {}).get("subject") or "a source"
        lines.append(f"{fact.get('subject')} {str(fact.get('predicate', '')).replace('_', ' ')} {fact.get('object')} ({speaker}, {where}, {_iso(fact.get('valid_from'))}) [{fact.get('id')}]")
    if decision.intent == "why" and extra.get("why"):
        history = extra["why"][0].get("history") or []
        prior = [h for h in history if h.get("id") != extra["why"][0].get("id")]
        if prior:
            lines.append("Earlier: " + "; ".join(f"{h.get('object')} ({h.get('status')}, {_iso(h.get('valid_from'))})" for h in prior[:3]))
    if decision.intent == "belief_at" and decision.at_ms:
        lines.insert(0, f"Belief as of {_iso(decision.at_ms)}:")
    return "\n".join(lines) if lines else "No matching facts."
