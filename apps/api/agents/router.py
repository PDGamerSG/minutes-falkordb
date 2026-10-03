"""Hybrid router for the AnswerAgent (plan section 5): count entities, classify intent, pick a route.

Routes: ``template`` (one of the numbered Cypher files, parameterised), ``graph`` (entity-anchored
traversal through active facts and provenance), ``vector`` (hybrid recall), ``freeform_ro``
(a read-only Cypher query the caller typed, run as the tenant's ro user with a 3 s timeout).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ingest.dates import normalize_date

_WRITE_KEYWORDS = re.compile(r"\b(CREATE|MERGE|SET|DELETE|REMOVE|DROP|DETACH|CALL\s+db\.idx\.(create|drop)|LOAD\s+CSV|FOREACH)\b", re.IGNORECASE)
_CYPHER_HINT = re.compile(r"^\s*(cypher\s*:|MATCH\b|OPTIONAL\s+MATCH\b|CALL\b|RETURN\b|WITH\b|UNWIND\b)", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")

TEMPLATES = {
    "why": "32_why_path",
    "who_knows": "50_who_knows",
    "open_commitments": "51_open_commitments",
    "contradictions": "52_contradictions",
    "stale_decisions": "53_stale_decisions",
    "belief_at": "31_belief_at_time",
    "clusters": "61_wcc_entities",
}

_INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("contradictions", re.compile(r"\b(contradict\w*|conflict\w*|disagree\w*|inconsisten\w*)\b", re.IGNORECASE)),
    ("who_knows", re.compile(r"\b(who (knows|talked|spoke|is familiar|has context|owns|worked)|who should i ask|who can tell|expert on)\b", re.IGNORECASE)),
    ("open_commitments", re.compile(r"\b(open commitments?|outstanding|what (is|are) \w+ (working on|owed?|promised)|what did \w+ (promise|commit)|what does \w+ owe|commitments? (for|of|by)|action items?|to-?dos?)\b", re.IGNORECASE)),
    ("stale_decisions", re.compile(r"\b(stale|outdated|old decisions?|decisions? (we|that) (never|have not|haven't))\b", re.IGNORECASE)),
    ("belief_at", re.compile(r"\b(what did we (believe|think|know)|as of|at the time|back (on|in)|before the|on \d{1,2}(st|nd|rd|th)? \w+|on \w+ \d{1,2})\b", re.IGNORECASE)),
    ("why", re.compile(r"\b(why|rationale|reason(ing)?|who (said|decided)|where did .* come from|how do we know)\b", re.IGNORECASE)),
    ("decisions", re.compile(r"\b(decid\w*|decision|agreed|chose|choice|went with|go with)\b", re.IGNORECASE)),
    ("when", re.compile(r"\b(when|due|deadline|by when|what date|which day|slip\w*|moved to)\b", re.IGNORECASE)),
    ("status", re.compile(r"\b(status|where are we|progress|update on|state of|what do we know|tell me about|what about)\b", re.IGNORECASE)),
]


@dataclass
class RouterDecision:
    intent: str
    entities: list[str]
    route: str
    template: str | None = None
    entity_ids: list[str] = field(default_factory=list)
    person_ids: list[str] = field(default_factory=list)
    at_ms: int | None = None
    cypher: str | None = None
    notes: str = ""

    def as_dict(self) -> dict[str, Any]:
        out = {"intent": self.intent, "entities": self.entities, "route": self.route, "template": self.template}
        if self.at_ms is not None:
            out["t"] = self.at_ms
        if self.notes:
            out["notes"] = self.notes
        return out


def is_read_only_cypher(query: str) -> bool:
    """True when the statement contains no write clauses (defence in depth; the ro user is the real guard)."""
    return not _WRITE_KEYWORDS.search(query)


def find_entities(message: str, entities: list[dict[str, Any]], persons: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Entities and persons whose names occur in the message (longest names first, whole words)."""
    text = f" {message.lower()} "
    hits: list[dict[str, Any]] = []
    for entity in sorted(entities, key=lambda e: -len(str(e.get("name") or ""))):
        name = str(entity.get("name") or "").lower().strip()
        if len(name) < 3:
            continue
        if re.search(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", text):
            if not any(name in h["name"].lower() for h in hits):
                hits.append(entity)
    people = [p for p in persons if p.get("name") and re.search(r"(?<![a-z0-9])" + re.escape(str(p["name"]).lower()) + r"(?![a-z0-9])", text)]
    return hits, people


def _date_in(message: str, reference: datetime | None = None) -> int | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})|(\b\d{1,2}(st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b(\s+\d{4})?)|(\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(st|nd|rd|th)?\b(,?\s+\d{4})?)", message, re.IGNORECASE)
    if not match:
        return None
    iso = normalize_date(match.group(0), reference or datetime.now(tz=UTC))
    if not iso:
        return None
    # end of that day, so "what did we believe on Sep 14" includes that day's meeting
    return int(datetime.fromisoformat(iso).replace(hour=23, minute=59, second=59, tzinfo=UTC).timestamp() * 1000)


def route(message: str, entities: list[dict[str, Any]], persons: list[dict[str, Any]], *, reference: datetime | None = None) -> RouterDecision:
    """Classify a question. Pure function: no model call, no graph access beyond the name lists."""
    text = message.strip()
    if _CYPHER_HINT.match(text):
        query = re.sub(r"^\s*cypher\s*:\s*", "", text, flags=re.IGNORECASE)
        if not is_read_only_cypher(query):
            return RouterDecision("freeform", [], "freeform_ro", cypher=query, notes="rejected: write clause in free-form Cypher")
        return RouterDecision("freeform", [], "freeform_ro", cypher=query)

    found, people = find_entities(text, entities, persons)
    names = [str(e["name"]) for e in found]
    entity_ids = [str(e["id"]) for e in found if e.get("id")]
    person_ids = [str(p["id"]) for p in people if p.get("id")]
    intent = "lookup"
    for name, pattern in _INTENT_PATTERNS:
        if pattern.search(text):
            intent = name
            break
    at_ms = _date_in(text, reference) if intent == "belief_at" else None
    if intent == "belief_at" and at_ms is None:
        intent = "status"

    if intent in ("contradictions", "stale_decisions"):
        return RouterDecision(intent, names, "template", TEMPLATES[intent], entity_ids, person_ids)
    if intent == "who_knows" and names:
        return RouterDecision(intent, names, "template", TEMPLATES[intent], entity_ids, person_ids)
    if intent == "open_commitments":
        return RouterDecision(intent, names, "template", TEMPLATES[intent], entity_ids, person_ids)
    if intent == "belief_at":
        return RouterDecision(intent, names, "template", TEMPLATES[intent], entity_ids, person_ids, at_ms=at_ms)
    if intent == "why":
        return RouterDecision(intent, names, "template", TEMPLATES[intent], entity_ids, person_ids)
    if names and intent in ("decisions", "when", "status", "lookup", "who_knows"):
        return RouterDecision(intent, names, "graph", None, entity_ids, person_ids)
    if people and intent in ("when", "status", "lookup"):
        return RouterDecision("open_commitments", names, "template", TEMPLATES["open_commitments"], entity_ids, person_ids)
    return RouterDecision(intent, names, "vector", None, entity_ids, person_ids)
