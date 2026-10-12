"""AnswerAgent evidence: full supersession history oldest first, meeting vs email wording, rationale,
episode recall fused with fact recall, and the Why panel subgraph."""

from __future__ import annotations

import re
from typing import Any

from apps.api.agents.answer_agent import AnswerAgent
from apps.api.agents.evidence import EvidenceIndex, build_dossiers, pretty_object, rrf
from apps.api.agents.tools import build_tools


class SpyLLM:
    """Records the prompt the AnswerAgent would send to the model."""

    backend = "spy"
    model = "spy"

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, temperature: float = 0.1, max_tokens: int = 2048) -> str:
        self.calls.append((system, user))
        citation = re.search(r"\[(fact_[^\]]+)\]", user)
        return f"spy answer [{citation.group(1)}]" if citation else "No recorded evidence."


def _agent(seeded, llm: Any = None) -> AnswerAgent:
    return AnswerAgent("orbit", seeded.hive, llm or seeded.llm, seeded.embedder, seeded.settings)


def test_prompt_carries_full_history_oldest_first_with_sources(seeded):
    spy = SpyLLM()
    response = _agent(seeded, spy).answer("When is the UPI flow due?")
    assert response["answer"].startswith("spy answer [fact_")
    system, user = spy.calls[0]
    assert "Never call an email or an email thread a meeting" in system

    block = user.split("FACT 1:")[1].split("FACT 2:")[0]
    versions = re.findall(r"v(\d)\. \[(fact_[^\]]+)\] UPI [Ff]low due = (\d{4}-\d{2}-\d{2})", block)
    assert [v[2] for v in versions] == ["2026-09-24", "2026-09-25", "2026-09-28"]
    lines = {v[2]: next(line for line in block.splitlines() if v[1] in line and line.strip().startswith(f"v{v[0]}.")) for v in versions}
    assert 'spoken in the meeting "Orbit kickoff"' in lines["2026-09-24"] and "superseded" in lines["2026-09-24"]
    assert 'spoken in the meeting "Orbit standup 1"' in lines["2026-09-25"]
    email = lines["2026-09-28"]
    assert 'written in the email thread "UPI flow timeline" (email sent by Priya)' in email and "ACTIVE, current value" in email
    assert "meeting" not in email
    assert "chronology: first 2026-09-24" in block and "then 2026-09-25" in block and "now 2026-09-28" in block
    assert "previously" not in user
    # the confirmation in standup 2 and the source words are in the evidence
    assert "later confirmed" in block and "Orbit standup 2" in block
    assert 'Priya said: "I can have the UPI flow done by Thursday the 24th.' in block
    assert 'Priya said: "The UPI flow slips by a day. Move it to Friday the 25th."' in block


def test_fake_answer_tells_the_history_in_time_order(client):
    body = client.post("/tenants/orbit/chat", json={"message": "When is the UPI flow due?"}).json()
    history = next(line for line in body["answer"].splitlines() if line.startswith("History:"))
    assert history.index("first 2026-09-24") < history.index("then 2026-09-25") < history.index("now 2026-09-28")
    assert 'email "UPI flow timeline"' in history and 'meeting "UPI flow timeline"' not in history
    # sources now include every version of the chain, with who said it and where
    by_id = {s["fact_id"]: s for s in body["sources"]}
    kinds = {(s["kind"], s.get("meeting") or s.get("thread")) for s in by_id.values()}
    assert ("utterance", "Orbit kickoff") in kinds and ("email", "UPI flow timeline") in kinds


def test_episode_recall_is_fused_and_reaches_the_why_panel(client):
    body = client.post("/tenants/orbit/chat", json={"message": "what slips by a day?"}).json()
    assert body["router"]["route"] == "vector"
    episodes = body["episodes"]
    hit = next(e for e in episodes if "slips by a day" in e["text"])
    assert hit["speaker"] == "Priya" and hit["kind"] == "utterance" and hit["meeting"] == "Orbit standup 1"
    # the episode hop pulls in the commitment derived from that utterance, with its history
    assert any(s["meeting"] == "Orbit standup 1" and s["speaker"] == "Priya" for s in body["sources"] if s["kind"] == "utterance")
    nodes = {n["id"]: n for n in body["subgraph"]["nodes"]}
    assert nodes[hit["episode_id"]]["label"] == "Episode"
    edges = {(e["source"], e["target"], e["type"]) for e in body["subgraph"]["edges"]}
    assert (hit["episode_id"], "spk_priya", "SPOKEN_BY") in edges
    assert ("mtg_orbit_002", hit["episode_id"], "HAS_EPISODE") in edges
    assert any(t == "DERIVED_FROM" and target == hit["episode_id"] for _, target, t in edges)


def test_email_episodes_are_labelled_as_email(seeded):
    spy = SpyLLM()
    response = _agent(seeded, spy).answer("KYC lead time")
    _, user = spy.calls[0]
    email_eps = [e for e in response["episodes"] if e["kind"] == "email"]
    assert email_eps and all(e["thread"] == "UPI flow timeline" and "sent_at" in e for e in email_eps)
    for line in user.splitlines():
        if "UPI flow timeline" in line:
            assert 'meeting "UPI flow timeline"' not in line


def test_dossier_rationale_and_dedup(seeded):
    index = EvidenceIndex(seeded.hive, "orbit")
    gateway = next(f for f in index.facts.values() if f.get("object") == "Razorpay")
    dossiers = build_dossiers(index, [gateway])
    assert dossiers[0]["chain"][-1]["id"] == gateway["id"]
    shown = [f["id"] for d in dossiers for f in d["chain"]] + [f["id"] for d in dossiers for f in d["rationale"]]
    assert len(shown) == len(set(shown))


def test_rrf_and_pretty_dates():
    scores = rrf(["a", "b", "c"], ["c", "a"], weights=[1.0, 0.5])
    assert max(scores, key=scores.get) == "a" and scores["c"] > scores["b"]
    assert pretty_object("2026-09-25") == "2026-09-25 (Friday)" and pretty_object("PayU") == "PayU"


def test_why_tool_history_is_oldest_first(seeded):
    agent = _agent(seeded)
    toolset = build_tools(agent, {"id": "task_x", "version": 0}, ["why"])
    head = next(f for f in seeded.hive.list_facts("orbit", status="active") if f.get("object") == "2026-09-28" and f.get("subject", "").lower() == "upi flow")
    result = toolset.execute("why", {"node_id": head["id"]})
    assert [h["object"] for h in result["history"]][:3] == ["2026-09-24", "2026-09-25", "2026-09-28"]
    assert result["source_kind"] == "email" and result["meeting"] is None and "wrote" in result


def test_unknown_model_citation_is_replaced_with_grounded_fallback(seeded):
    class InventedCitation(SpyLLM):
        def complete(self, *args, **kwargs):
            return "A made-up owner approved this [fact_not_in_this_tenant]."

    response = _agent(seeded, InventedCitation()).answer("When is the UPI flow due?")
    assert "made-up" not in response["answer"]
    assert "2026-09-28" in response["answer"]
    cited = set(re.findall(r"\[(fact_[^\]]+)\]", response["answer"]))
    assert cited <= {s["fact_id"] for s in response["sources"]}


def test_explanation_uses_real_provenance_edges(client):
    response = client.post("/tenants/orbit/chat", json={"message": "When is the UPI flow due?"}).json()
    types = {edge["type"] for edge in response["subgraph"]["edges"]}
    assert "CONTAINS" not in types
    assert {"HAS_EPISODE", "DERIVED_FROM", "SUPERSEDES"} <= types


def test_uncited_model_claim_is_replaced_with_grounded_evidence(seeded):
    class UncitedAnswer(SpyLLM):
        def complete(self, *args, **kwargs):
            return "The project was cancelled by the CEO."

    response = _agent(seeded, UncitedAnswer()).answer("When is the UPI flow due?")
    assert "cancelled" not in response["answer"]
    assert "2026-09-28" in response["answer"]
    assert "[fact_" in response["answer"]


def test_historical_question_does_not_send_future_evidence_to_model(seeded):
    spy = SpyLLM()
    response = _agent(seeded, spy).answer("What did we believe about the UPI flow as of 2026-09-10?")
    assert response["router"]["intent"] == "belief_at"
    _, prompt = spy.calls[0]
    assert "2026-09-24" in prompt
    assert "2026-09-25" not in prompt
    assert "2026-09-28" not in prompt
    assert response["sources"] and all(s["container_id"] == "mtg_orbit_001" for s in response["sources"])
    assert all(e["meeting"] == "Orbit kickoff" for e in response["episodes"])


def test_historical_rows_with_missing_provenance_keep_the_original_source(seeded, monkeypatch):
    original = seeded.hive.belief_at_result

    def without_container(*args, **kwargs):
        result = original(*args, **kwargs)
        # The real belief query supplies facts and speakers, but not joined containers.
        result["rows"] = [{**row, "meeting": None, "thread": None, "episode_id": None}
                          for row in result["rows"]]
        return result

    monkeypatch.setattr(seeded.hive, "belief_at_result", without_container)
    spy = SpyLLM()
    response = _agent(seeded, spy).answer("What did we believe about the UPI flow as of 2026-09-10?")
    assert "Orbit kickoff" in spy.calls[0][1]
    assert "2026-09-28" not in spy.calls[0][1]
    assert any(n["id"] == "mtg_orbit_001" for n in response["subgraph"]["nodes"])
    assert all(s["container_id"] == "mtg_orbit_001" for s in response["sources"])
