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
_CYPHER_HINT = re.compile(r"^\s*(cypher\s*:|MATCH\b|OPTIONAL\s+MATCH\b|CALL\b|RETURN\b|WITH\b|UNWIND\b|LOAD\s+CSV\b|CREATE\b|MERGE\b)", re.IGNORECASE)
_WORD = re.compile(r"[a-z0-9]+")
# Conversation history is private to the caller (finding 2.4): free-form Cypher may not name these labels.
PRIVATE_LABELS = ("Turn", "ChatSession")
_PRIVATE_LABEL = re.compile(r"(?::\s*`?(" + "|".join(PRIVATE_LABELS) + r")`?\b)|(\b(" + "|".join(PRIVATE_LABELS) + r")\b)")
FREEFORM_LIMIT = 200
_TOP_LIMIT = re.compile(r"\bLIMIT\s+\d+\s*$", re.IGNORECASE)


def strip_literals(query: str) -> str:
    """The query with string literals, backtick names and ``//`` comments blanked (keeps offsets' order, not length)."""
    out: list[str] = []
    i, n = 0, len(query)
    while i < n:
        ch = query[i]
        if ch in "'\"`":
            j = i + 1
            while j < n and query[j] != ch:
                j += 2 if query[j] == "\\" else 1
            out.append(ch + ch)
            i = j + 1
            continue
        if query.startswith("//", i):
            j = query.find("\n", i)
            i = n if j < 0 else j + 1
            if not out or not out[-1].isspace():
                out.append(" ")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def names_private_label(query: str) -> bool:
    """True when the (literal-stripped) query mentions a label that holds chat history."""
    return bool(_PRIVATE_LABEL.search(strip_literals(query)))


def with_limit(query: str, limit: int = FREEFORM_LIMIT) -> str:
    """Append ``LIMIT <n>`` when the query has no top-level LIMIT (the ro user still enforces read-only)."""
    clauses = [kw for _, kw in _top_level_clauses(query)]
    if "LIMIT" in clauses:
        return query
    return query.rstrip().rstrip(";") + f" LIMIT {int(limit)}"

TEMPLATES = {
    "why": "32_why_path",
    "who_knows": "50_who_knows",
    "ownership": "54_owners",
    "open_commitments": "51_open_commitments",
    "contradictions": "52_contradictions",
    "stale_decisions": "53_stale_decisions",
    "belief_at": "31_belief_at_time",
    "clusters": "61_wcc_entities",
}

_INTENT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ownership", re.compile(r"\b(who owns|who is (responsible|accountable)|owner of|who.*assigned to)\b", re.IGNORECASE)),
    ("contradictions", re.compile(r"\b(contradict\w*|conflict\w*|disagree\w*|inconsisten\w*)\b", re.IGNORECASE)),
    ("who_knows", re.compile(r"\b(who (knows|talked|spoke|is familiar|has context|worked)|who should i ask|who can tell|expert on)\b", re.IGNORECASE)),
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
    """True when the statement contains no write clauses outside strings and comments (defence in depth;
    the ro user is the real guard). ``CONTAINS 'create'`` is a string, not a write."""
    return not _WRITE_KEYWORDS.search(strip_literals(query))


_CLAUSE = re.compile(r"\b(OPTIONAL\s+MATCH|MATCH|WHERE|WITH|UNWIND|CALL|RETURN|UNION|ORDER\s+BY|SKIP|LIMIT)\b", re.IGNORECASE)


def _top_level_clauses(query: str) -> list[tuple[int, str]]:
    """``(offset, KEYWORD)`` for clause keywords outside strings, backticks, comments and (), [], {} nesting."""
    out: list[tuple[int, str]] = []
    depth = 0
    i, n = 0, len(query)
    while i < n:
        ch = query[i]
        if ch in "'\"`":
            j = i + 1
            while j < n and query[j] != ch:
                j += 2 if query[j] == "\\" else 1
            i = j + 1
            continue
        if query.startswith("//", i):
            j = query.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif depth == 0 and (ch.isalpha()) and (i == 0 or not (query[i - 1].isalnum() or query[i - 1] in "_.$")):
            m = _CLAUSE.match(query, i)
            if m:
                out.append((i, re.sub(r"\s+", " ", m.group(1).upper())))
                i = m.end()
                continue
        i += 1
    return out


def guard_match_where_match(query: str) -> tuple[str, bool]:
    """Work around a FalkorDB 6.0.1 planner bug: ``MATCH ... WHERE ...`` followed directly by another (non-optional)
    ``MATCH`` silently drops the first WHERE (no Filter in the plan, wrong rows). Inserting ``WITH *`` before the
    second MATCH forces the filter to apply first and does not change the query's meaning. Returns (query, rewritten)."""
    inserts: list[int] = []
    in_match = False
    filtered = False
    for offset, keyword in _top_level_clauses(query):
        if keyword == "MATCH":
            if in_match and filtered:
                inserts.append(offset)
            in_match, filtered = True, False
        elif keyword == "OPTIONAL MATCH":
            in_match, filtered = True, False
        elif keyword == "WHERE":
            filtered = filtered or in_match
        else:  # WITH, UNWIND, CALL, RETURN, UNION, ORDER BY ... end the MATCH...WHERE run
            in_match, filtered = False, False
    for offset in reversed(inserts):
        query = query[:offset] + "WITH * " + query[offset:]
    return query, bool(inserts)


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
        if names_private_label(query):
            return RouterDecision("freeform", [], "freeform_ro", cypher=query, notes="rejected: chat history (Turn, ChatSession) is not queryable")
        guarded, rewritten = guard_match_where_match(query)
        limited = with_limit(guarded)
        notes = []
        if rewritten:
            notes.append("rewritten: WITH * inserted before a MATCH that follows MATCH ... WHERE (FalkorDB 6.0.1 drops that WHERE)")
        if limited != guarded:
            notes.append(f"LIMIT {FREEFORM_LIMIT} added")
        return RouterDecision("freeform", [], "freeform_ro", cypher=limited, notes="; ".join(notes))

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
    if intent == "ownership":
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
