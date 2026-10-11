"""AnswerAgent (capability ``answer``): hybrid router -> retrieval -> grounded answer with provenance.

Every answer carries the Cypher that ran, the subgraph it touched, the sources (fact ids with who
said it and where) and the router decision, so the UI can render the Why panel.

Evidence for the model (``evidence.py``): every fact it may cite comes with its whole SUPERSEDES chain
(oldest first, each version's value, date, status, speaker or sender, meeting or email thread and the
words it was derived from), later CONFIRMED_BY episodes, PRECEDENT_FOR neighbours and stated-rationale
facts. Raw Episodes are recalled too (vector KNN on Episode plus full-text on Episode.text), fused with
the route's facts by reciprocal-rank fusion, returned as ``episodes[]`` and drawn into the subgraph.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import UTC, datetime
from typing import Any

from ingest.fakes import new_id

from .base import AgentResult, BaseAgent, load_prompt
from .evidence import (
    EvidenceIndex,
    build_dossiers,
    dossier_fact_ids,
    episode_source_item,
    fuse,
    keywords,
    merge_subgraph,
    pretty_object,
    quoted_episode_ids,
    recall_episodes,
    render_dossier,
    render_episodes,
    rrf,
)
from .router import RouterDecision, find_entities, route

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
            episode_id = fact.get("episode_id") or (fact.get("source") or {}).get("episode_id")
            if episode_id:
                add(episode_id, "Episode", {"id": episode_id})
                edges.append({"source": container["id"], "target": episode_id, "type": "HAS_EPISODE", "props": {}})
                edges.append({"source": fid, "target": episode_id, "type": "DERIVED_FROM", "props": {}})
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
        self._qvec_cache: tuple[str, list[float]] | None = None
        self._index = EvidenceIndex(self.hive, self.tenant)
        entities, people = self.hive.list_entities(self.tenant), self.hive.list_persons(self.tenant)
        query = self._resolve_followup(message, session_id, entities, people)
        decision = route(query, entities, people)
        if query != message:
            decision.notes = "Resolved follow-up from this session's last named entity; evidence queried again."
        facts, cypher, subgraph, extra = self._retrieve(query, decision)
        evidence = self._gather_evidence(query, decision, facts, extra)
        index: EvidenceIndex | None = evidence.get("index")
        source_facts = list(facts[:12])
        if index is not None:
            seen = {f.get("id") for f in source_facts}
            widen = decision.route in ("graph", "vector") or decision.intent == "why"
            for fid in dossier_fact_ids(evidence["dossiers"]):
                if widen and fid not in seen and len(source_facts) < 20:
                    fact = index.fact(fid)
                    if fact:
                        source_facts.append(fact)
                        seen.add(fid)
            subgraph = merge_subgraph(subgraph, index, evidence["dossiers"], evidence["episodes"])
            cypher = [*cypher, *evidence["cypher"]]
        sources = [_source_from_fact(f) for f in source_facts]
        answer = self._compose(message, decision, facts, extra, evidence)
        # Every accepted citation must be inspectable, including a dossier's neighbour or old version.
        if index is not None:
            for citation in re.findall(r"\[((?:fact|ep)_[^\]\s]+)\]", answer):
                if citation.startswith("fact_") and not any(s["fact_id"] == citation for s in sources):
                    fact = index.fact(citation)
                    if fact:
                        sources.append(_source_from_fact(fact))
                elif citation.startswith("ep_") and not any(ep["id"] == citation for ep in evidence["episodes"]):
                    episode = index.episode(citation)
                    if episode:
                        evidence["episodes"].append(episode)
        latency = int((time.perf_counter() - started) * 1000)
        response = {
            "answer": answer,
            "session_id": session_id,
            "router": decision.as_dict(),
            "cypher": list(dict.fromkeys(c for c in cypher if c)),
            "subgraph": subgraph,
            "sources": sources,
            "episodes": [episode_source_item(ep, evidence["episode_scores"].get(ep["id"])) for ep in evidence["episodes"]],
            "model": getattr(self.llm, "model", "fake"),
            "latency_ms": latency,
        }
        self.hive.add_turn(self.tenant, session_id, "user", message, {})
        self.hive.add_turn(self.tenant, session_id, "assistant", answer, {"response": response})
        return response

    def _resolve_followup(self, message: str, session_id: str, entities: list[dict[str, Any]], people: list[dict[str, Any]]) -> str:
        """Reuse a single explicit topic, never an old answer as evidence or another tenant's session."""
        found, persons = find_entities(message, entities, people)
        if found or persons or not re.search(r"\b(it|its|that|those|they|them)\b|^\s*and\b", message, re.I):
            return message
        available = {e["name"] for e in entities}
        for turn in reversed(self.hive.get_turns(self.tenant, session_id)):
            if turn.get("role") != "assistant":
                continue
            response = (turn.get("meta") or {}).get("response") or {}
            names = (response.get("router") or {}).get("entities") or []
            if len(names) == 1 and names[0] in available:
                return f"{message} (Context: {names[0]})"
            break  # ambiguous or absent context: do not reach back to an unrelated topic
        return message

    @property
    def index(self) -> EvidenceIndex:
        """Per-answer fact/episode cache (embedding-free projections on FalkorDB)."""
        if getattr(self, "_index", None) is None:
            self._index = EvidenceIndex(self.hive, self.tenant)
        return self._index

    def _qvec(self, message: str) -> list[float]:
        cached = getattr(self, "_qvec_cache", None)
        if cached and cached[0] == message:
            return cached[1]
        vec = self.embedder.embed_one(message, "query")
        self._qvec_cache = (message, vec)
        return vec

    def _fact_fulltext(self, message: str, k: int = 8) -> list[str]:
        words = keywords(message)
        if not words:
            return []
        try:
            if getattr(self.hive, "kind", "") == "falkordb":
                rows = self.hive.fulltext(self.tenant, " ".join(words), label="Fact", k=k)
            else:
                rows = [r for w in words for r in self.hive.fulltext(self.tenant, w, label="Fact", k=k)]
        except Exception as exc:  # noqa: BLE001
            log.warning("fact full-text failed: %s", exc)
            return []
        return list(dict.fromkeys(r.get("id") for r in rows if r.get("id") and r.get("status", "active") == "active"))[:k]

    def _gather_evidence(self, message: str, decision: RouterDecision, facts: list[dict[str, Any]], extra: dict[str, Any]) -> dict[str, Any]:
        """Fact dossiers (history, source, rationale) and raw Episodes fused with the route's facts by RRF."""
        empty: dict[str, Any] = {"index": None, "dossiers": [], "episodes": [], "episode_scores": {}, "cypher": []}
        if extra.get("error") or decision.route == "freeform_ro" or decision.intent in ("ownership", "belief_at"):
            # Historical answers must only use the time-filtered query result. A present-day
            # dossier/episode recall would reintroduce future versions and confirmations.
            return empty
        if not facts and decision.route in ("graph", "template") and decision.intent not in ("why", "who_knows", "contradictions"):
            return empty
        index = self.index
        for fact in facts:
            if fact.get("id"):
                index.add_fact(fact)
        try:
            vec = self._qvec(message)
        except Exception as exc:  # noqa: BLE001
            log.warning("query embedding failed: %s", exc)
            vec = None
        hits = recall_episodes(self.hive, self.tenant, message, vec, k=10)
        route_ids = [f["id"] for f in facts if f.get("id")]
        open_ended = decision.route == "vector" or decision.intent == "why"
        fact_lists = [route_ids]
        if decision.route == "vector":
            fact_lists.append(self._fact_fulltext(message))
        facts_ranked, eps_ranked = fuse(index, fact_lists, hits)
        known = {fid for fid, _ in facts_ranked}
        if open_ended:
            boosted = []
            for fid, score in facts_ranked:
                fact = index.fact(fid) or {}
                if fact.get("kind") == "decision":
                    score *= 1.25
                if fact.get("supersedes") or fact.get("status") == "superseded":
                    score *= 1.5 if decision.intent == "when" else 1.25  # "what slipped" asks for a moved date
                boosted.append((fid, score))
            boosted.sort(key=lambda kv: -kv[1])
            primary_ids = [fid for fid, _ in boosted][:6]
        else:
            # anchored routes keep their order; the episode hop may add two facts the route missed (graph routes only:
            # template rows are already filtered, e.g. by person)
            extra_ids = [fid for fid, _ in facts_ranked if fid not in set(route_ids)][:2] if decision.route == "graph" else []
            primary_ids = route_ids[:8] + extra_ids
        primary = [index.fact(fid, next((f for f in facts if f.get("id") == fid), None)) for fid in primary_ids if fid in known or fid in route_ids]
        if decision.intent in ("contradictions", "who_knows"):
            primary = primary[:6]
        dossiers = build_dossiers(index, [f for f in primary if f], max_blocks=8)
        episodes = []
        for eid, _score in eps_ranked[:8]:
            ep = index.episode(eid)
            if ep:
                episodes.append(ep)
        return {
            "index": index,
            "dossiers": dossiers,
            "episodes": episodes,
            "episode_scores": dict(eps_ranked),
            "cypher": [*hits["cypher"], *index.cypher],
        }

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
            if decision.intent == "ownership":
                result = self.hive.owners(tenant, decision.entities[0]) if decision.entities else {"rows": [], "cypher": ""}
                rows = result["rows"]
                facts = [f for row in rows if (f := self.index.fact(row["fact_id"]))]
                graph = _subgraph_from_facts(facts)
                for row in rows:
                    person = row["person"]
                    if not any(n["id"] == person["id"] for n in graph["nodes"]):
                        graph["nodes"].append({"id": person["id"], "label": "Person", "props": person})
                    fact = self.index.fact(row["fact_id"]) or {}
                    if fact.get("predicate") != "owner":
                        graph["edges"].append({"source": row["fact_id"], "target": person["id"], "type": "OWNED_BY", "props": {}})
                return facts, [result.get("cypher", ""), *self.index.cypher], graph, {"owners": rows}
            if decision.intent == "who_knows":
                result = self.hive.who_knows(tenant, decision.entities[0])
                extra["who_knows"] = result["rows"]
                if decision.entity_ids:
                    facts = self.index.active_about(decision.entity_ids[0])
                else:
                    facts = self.hive.list_facts(tenant, status="active", entity=decision.entities[0])
                return facts, [result.get("cypher", "")], _subgraph_from_facts(facts), extra
            if decision.intent == "open_commitments":
                person = decision.person_ids[0] if decision.person_ids else None
                result = self.hive.open_commitments(tenant, person)
                rows = result["rows"]
                if decision.entity_ids:
                    wanted = set(decision.entity_ids)
                    rows = [r for r in rows if wanted & set(r.get("entity_ids") or [])]
                # the analytics query returns owner + entities only; join speaker and container for the sources
                rows = [{**r, **(self.index.fact(r["id"]) or {})} if r.get("id") else r for r in rows[:20]]
                for row in rows:
                    if not row.get("speaker") and row.get("owner"):
                        row["speaker"] = row["owner"]
                return rows, [result.get("cypher", "")], _subgraph_from_facts(rows), {**extra, "open_commitments": True}
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
                    rows = [r for r in rows if str(r.get("subject", "")).lower() in wanted]
                enriched = []
                for row in rows:
                    full = self.index.fact(row["id"]) or {}
                    historical = dict(row)
                    # The temporal query omits source joins. Fill only provenance:
                    # historical values/times must remain exactly as selected at T.
                    for key in ("speaker", "meeting", "thread", "episode_id", "source", "entity_ids"):
                        if historical.get(key) is None:
                            historical[key] = full.get(key)
                    enriched.append(historical)
                rows = enriched
                return rows, [result.get("cypher", ""), *self.index.cypher], _subgraph_from_facts(rows), extra
            if decision.intent == "why":
                return self._retrieve_why(message, decision)

        if decision.route == "graph":
            facts: list[dict[str, Any]] = []
            cyphers: list[str] = []
            for entity_id in decision.entity_ids[:3]:
                rows = self.index.active_about(entity_id)
                if decision.intent == "decisions":
                    rows = [r for r in rows if r.get("kind") == "decision"]
                if decision.intent == "when":
                    rows = sorted(rows, key=lambda r: (r.get("due_at") is None, -(r.get("valid_from") or 0)))
                facts.extend(r for r in rows if r.get("id") not in {f.get("id") for f in facts})
            cyphers.extend(self.index.cypher)
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

        vec = self._qvec(message)
        recall = self.hive.recall(tenant, vec, k=8)
        facts = [{**(i.get("node") or {}), "entities": i.get("entities") or [], "similarity": i.get("similarity")} for i in recall["items"]]
        enriched = []
        for fact in facts:
            full = self.index.fact(fact.get("id"))
            enriched.append({**fact, **(full or {})})
        return enriched, [recall.get("cypher", "")], recall.get("subgraph") or _subgraph_from_facts(enriched), extra

    def _retrieve_why(self, message: str, decision: RouterDecision) -> tuple[list[dict[str, Any]], list[str], dict[str, Any], dict[str, Any]]:
        """Why questions: RRF over entity-anchored facts, facts whose value names the entity ("we chose the side
        drawer" -> navigation uses side drawer), vector recall and full-text; provenance (32_why_path) for the best."""
        tenant = self.tenant
        vec = self._qvec(message)
        recall = self.hive.recall(tenant, vec, k=8)
        cyphers = [recall.get("cypher", "")]
        full: dict[str, dict[str, Any]] = {}
        knn_ids = [str((i.get("node") or {}).get("id") or i.get("id")) for i in recall["items"] if (i.get("node") or {}).get("id") or i.get("id")]
        anchored_ids: list[str] = []
        object_ids: list[str] = []
        for entity_id in decision.entity_ids[:3]:
            for fact in self.index.active_about(entity_id)[::-1]:
                full.setdefault(fact["id"], fact)
                anchored_ids.append(fact["id"])
        names = [n.lower() for n in decision.entities if len(n) > 2]
        if names:
            for fact in (f for f in self.index.facts.values() if f.get("status") == "active"):
                obj = str(fact.get("object") or "").lower()
                if any(n == obj or n in obj for n in names):
                    full.setdefault(fact["id"], fact)
                    object_ids.append(fact["id"])
        object_ids.sort(key=lambda fid: (full[fid].get("kind") != "decision", -(full[fid].get("valid_from") or 0)))
        scores = rrf(anchored_ids, object_ids, knn_ids, self._fact_fulltext(message), weights=[1.0, 1.5, 1.0, 0.7])
        facts: list[dict[str, Any]] = []
        for fid, _score in sorted(scores.items(), key=lambda kv: -kv[1])[:8]:
            fact = full.get(fid) or self.index.fact(fid) or self.hive.get_fact(tenant, fid)
            if fact:
                facts.append(fact)
        subgraph: dict[str, Any] = {"nodes": [], "edges": []}
        if facts:
            try:
                why = self.hive.why(tenant, facts[0]["id"])
                cyphers.append(why.get("cypher", ""))
                subgraph = why.get("subgraph") or subgraph
            except Exception as exc:  # noqa: BLE001
                log.warning("why(%s) failed: %s", facts[0]["id"], exc)
        return facts, cyphers, subgraph if subgraph["nodes"] else _subgraph_from_facts(facts), {}

    def _compose(self, message: str, decision: RouterDecision, facts: list[dict[str, Any]], extra: dict[str, Any], evidence: dict[str, Any] | None = None) -> str:
        evidence = evidence or {"index": None, "dossiers": [], "episodes": []}
        if extra.get("error"):
            return f"I could not run that query: {extra['error']}"
        if decision.intent == "ownership":
            return render_answer(message, decision, facts, extra)
        if extra.get("open_commitments") and not facts:
            return "No open commitments match the requested person or project in the recorded company knowledge."
        answerable = facts or extra.get("who_knows") or extra.get("rows") or extra.get("contradictions") is not None or evidence.get("episodes")
        if not answerable:
            return "I found nothing in the team memory that answers that. Try naming the project, person or decision."
        if getattr(self.llm, "backend", "") == "fake":
            return render_answer(message, decision, facts, extra, evidence.get("dossiers"))
        user = build_user_prompt(message, decision, facts, extra, evidence)
        try:
            text = self.llm.complete(load_prompt("answer"), user, temperature=0.2, max_tokens=700)
        except Exception as exc:  # noqa: BLE001 - fail loudly in the payload, keep provenance
            log.error("answer composition failed: %s", exc)
            return f"The model failed to compose an answer ({type(exc).__name__}); evidence: " + render_answer(message, decision, facts, extra, evidence.get("dossiers"))
        # Do not let a fabricated reference masquerade as a traceable company fact.
        allowed = {f["id"] for f in facts if f.get("id")}
        allowed.update(dossier_fact_ids(evidence.get("dossiers") or []))
        allowed.update(quoted_episode_ids(evidence.get("dossiers") or []))
        allowed.update(ep["id"] for ep in evidence.get("episodes") or [])
        cited = set(re.findall(r"\[((?:fact|ep)_[^\]\s]+)\]", text))
        if cited - allowed or (allowed and not cited):
            log.warning("answer has missing or unknown evidence citations; returning grounded fallback")
            return render_answer(message, decision, facts, extra, evidence.get("dossiers"))
        return text.strip() or render_answer(message, decision, facts, extra, evidence.get("dossiers"))


def _legacy_fact_line(fact: dict[str, Any]) -> str:
    """One line for rows that have no dossier (free-form Cypher results, analytics rows)."""
    speaker = (fact.get("speaker") or {}).get("name") or fact.get("speaker_id") or "unknown"
    thread = fact.get("thread") or {}
    meeting = fact.get("meeting") or {}
    if thread.get("subject"):
        where = f'written in the email thread "{thread["subject"]}" (email sent by {speaker})'
    elif meeting.get("title"):
        where = f'spoken in the meeting "{meeting["title"]}"'
    else:
        where = "source unknown"
    return (
        f"- [{fact.get('id')}] {fact.get('subject')} {str(fact.get('predicate') or '').replace('_', ' ')} {pretty_object(fact.get('object'))} "
        f"({fact.get('kind')}, {fact.get('status', 'active')}; stated {_iso(fact.get('valid_from'))} by {speaker}, {where}): {fact.get('text')}"
    )


def build_user_prompt(message: str, decision: RouterDecision, facts: list[dict[str, Any]], extra: dict[str, Any], evidence: dict[str, Any]) -> str:
    """The evidence block: one section per fact with its whole history (oldest first), then raw episodes."""
    index: EvidenceIndex | None = evidence.get("index")
    dossiers = evidence.get("dossiers") or []
    parts = [f"Question: {message}", f"Router: intent={decision.intent}, route={decision.route}, entities={decision.entities}"]
    if decision.intent == "belief_at" and decision.at_ms:
        parts.append(f"The question asks what was believed as of {_iso(decision.at_ms)}: use the version that was active on that date; later versions are context only.")
    parts.append("")
    if dossiers and index is not None:
        parts.append(
            "EVIDENCE A: facts from the memory graph. Each FACT lists every version oldest to newest, who stated it, "
            "where (a meeting or an email thread), what they said or wrote, and any stated rationale."
        )
        parts.extend(render_dossier(index, d, i + 1) for i, d in enumerate(dossiers))
    else:
        rows = [f for f in facts[:12] if isinstance(f, dict) and f.get("id")]
        if rows:
            parts.append("EVIDENCE A: facts from the memory graph.")
            parts.extend(_legacy_fact_line(f) for f in rows)
    if extra.get("who_knows"):
        parts.append("WHO KNOWS (mentions across meetings and emails): " + ", ".join(f"{r['person']['name']} ({r['mentions']} mentions)" for r in extra["who_knows"][:6]))
    if extra.get("contradictions") is not None:
        pairs = extra["contradictions"]
        lines = [f"CONTRADICTIONS between active facts: {len(pairs)}"]
        for p in pairs[:5]:
            a, b = p["facts"][0], p["facts"][1]
            lines.append(f"- {p['key']}: [{a.get('id')}] '{a.get('object')}' vs [{b.get('id')}] '{b.get('object')}'")
        parts.append("\n".join(lines))
    if extra.get("rows") and not dossiers:
        parts.append("QUERY ROWS: " + str(extra["rows"][:10])[:3000])
    quoted = quoted_episode_ids(dossiers)
    episodes = [ep for ep in evidence.get("episodes") or [] if ep["id"] not in quoted][:6]
    if episodes:
        shown: dict[str, str] = {}
        for d in dossiers:
            for v in d.get("versions", []):
                if v["source"]["episode"]:
                    shown.setdefault(v["source"]["episode"]["id"], v["fact"]["id"])
        parts.append("")
        parts.append("EVIDENCE B: more raw episodes (verbatim utterances and emails) found by semantic and keyword search, best first.")
        parts.extend(render_episodes(episodes, shown))
    parts.append("")
    parts.append(
        "Answer in at most five sentences. Cite fact ids (or episode ids) in square brackets after each claim. "
        "If a value changed, tell it in time order: first ..., then ..., now ... (and say so if a status fact shows it was completed). "
        "For each version or reason, name who stated it and the meeting title or email subject it came from. "
        "Say 'meeting' only for evidence marked 'spoken in the meeting'; evidence marked 'email thread' is an email."
    )
    return "\n".join(parts)


def _chain_sentence(dossier: dict[str, Any]) -> str:
    words = ["first", *(["then"] * (len(dossier["versions"]) - 2)), "now"]
    bits = []
    for word, version in zip(words, dossier["versions"]):
        src = version["source"]
        where = f'email "{src["container"]}"' if src["kind"] == "email" else f'meeting "{src["container"]}"'
        bits.append(f"{word} {version['fact'].get('object')} ({src['speaker']}, {where}, {src['date']}) [{version['fact'].get('id')}]")
    head = dossier["chain"][-1]
    return f"{head.get('subject')} {str(head.get('predicate') or '').replace('_', ' ')}: " + ", ".join(bits)


def render_answer(message: str, decision: RouterDecision, facts: list[dict[str, Any]], extra: dict[str, Any], dossiers: list[dict[str, Any]] | None = None) -> str:
    """Deterministic, citation-bearing answer used by the fake backend and as the model fallback."""
    if decision.intent == "ownership":
        if not decision.entities:
            return "Name the project or commitment whose owner you want to look up."
        owners = extra.get("owners") or []
        if not owners:
            return f"No commitment owner is recorded for {decision.entities[0]}. Mentions alone do not establish ownership."
        people: dict[str, list[str]] = {}
        for row in owners:
            people.setdefault(row["person"]["name"], []).append(row["fact_id"])
        return f"Recorded owners for {decision.entities[0]}: " + "; ".join(
            f"{name} " + " ".join(f"[{fid}]" for fid in dict.fromkeys(ids)) for name, ids in people.items()
        ) + "."
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
        thread = fact.get("thread") or {}
        meeting = fact.get("meeting") or {}
        where = f'email "{thread["subject"]}"' if thread.get("subject") else meeting.get("title") or "a source"
        lines.append(f"{fact.get('subject')} {str(fact.get('predicate', '')).replace('_', ' ')} {fact.get('object')} ({speaker}, {where}, {_iso(fact.get('valid_from'))}) [{fact.get('id')}]")
    if decision.intent != "belief_at":
        for dossier in dossiers or []:
            if len(dossier.get("versions") or []) > 1:
                lines.append("History: " + _chain_sentence(dossier))
                break
    if decision.intent == "belief_at" and decision.at_ms:
        lines.insert(0, f"Belief as of {_iso(decision.at_ms)}:")
    return "\n".join(lines) if lines else "No matching facts."
