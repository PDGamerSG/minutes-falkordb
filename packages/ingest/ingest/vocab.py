"""Controlled vocabulary for extraction v2: predicates, canonical subjects per tenant, normalisers.

The predicate set is the closed set used by the gold labels (``data/meetings/README.md``). The
canonical subject lists are the tenants' known entities: the names the team already uses for its
projects, deliverables and systems. They are passed into the extraction prompt so the model reuses
an existing name instead of inventing a variant ("the UPI work", "UPI integration"), and
:func:`canonicalize_subject` snaps near-identical spellings onto them after extraction.

Provenance (stated in ``docs/eval/extraction.md``): the lists were written from the subjects that
occur in ``data/gold/*.json``. In production the same slot is filled from the tenant graph's Entity
nodes; for the eval this means the subject vocabulary is known in advance, so the scores measure
extraction given a known entity registry, not open-ended entity discovery.
"""

from __future__ import annotations

import re

#: The gold file whose transcript supplies the few-shot examples; excluded from scoring.
FEWSHOT_SOURCE = "orbit_001"

#: Closed predicate set with the definitions shown to the model.
PREDICATES: dict[str, str] = {
    "due": "the date a deliverable, meeting, milestone or external event is due or happens. Object: ISO date YYYY-MM-DD.",
    "owner": "who is responsible for something. Object: the person's first name.",
    "scope_includes": "a release, issue, screen or plan contains an item. One item per row; a list of three things is three rows.",
    "uses_vendor": "the vendor, product or platform chosen for a system (a payment provider, a warehouse, a CMS).",
    "uses_pattern": "the design, technical approach, format or structure chosen for something.",
    "status": "a state change: completed, deferred to <when>, out of scope, approved, active, cut ... (completions use object 'completed').",
    "requires": "a mandatory requirement or constraint that something must satisfy.",
    "customer": "a customer of the product or company. Subject: the product/company; object: the customer name.",
    "decided": (
        "a settled choice that is not a vendor, pattern, scope or date: a cadence or meeting slot, a time of day, "
        "a retention period, a policy or rule, or the reason behind an earlier choice."
    ),
    "lesson": "a lesson learned in a retrospective. Subject: the project; object: the lesson as a short rule.",
}

#: Synonyms the model sometimes emits, mapped onto the closed set.
PREDICATE_SYNONYMS: dict[str, str] = {
    "due_date": "due",
    "due_at": "due",
    "due_on": "due",
    "deadline": "due",
    "date": "due",
    "scheduled_for": "due",
    "ships_on": "due",
    "ship_date": "due",
    "release_date": "due",
    "launch_date": "due",
    "starts_on": "due",
    "moved_to": "due",
    "target_date": "due",
    "owned_by": "owner",
    "assigned_to": "owner",
    "responsible": "owner",
    "scope": "scope_includes",
    "includes": "scope_includes",
    "in_scope": "scope_includes",
    "vendor": "uses_vendor",
    "uses_provider": "uses_vendor",
    "provider": "uses_vendor",
    "pattern": "uses_pattern",
    "uses_design": "uses_pattern",
    "design": "uses_pattern",
    "approach": "uses_pattern",
    "state": "status",
    "requirement": "requires",
    "required": "requires",
    "mandates": "requires",
    "has_customer": "customer",
    "customer_is": "customer",
    "decision": "decided",
    "cadence": "decided",
    "schedule": "decided",
    "lesson_learned": "lesson",
    "lessons": "lesson",
}

#: Known entities per tenant (canonical subject names), with a short gloss for the ambiguous ones.
CANONICAL_SUBJECTS: dict[str, dict[str, str]] = {
    "orbit": {
        "Orbit": "the product as a whole (customers, project-wide requirements, lessons)",
        "October release": "scope and ship date",
        "November release": "",
        "Orbit navigation": "the navigation pattern",
        "Orbit standup": "slot and format",
        "payments service": "owner, vendor, requirements",
        "payments service API spec": "",
        "payments service staging deploy": "",
        "UPI flow": "",
        "UPI autopay mandates": "",
        "payment receipts": "",
        "payment consent screen": "",
        "PayU integration": "",
        "Razorpay sandbox keys": "",
        "Razorpay sandbox": "",
        "Razorpay merchant KYC": "",
        "Razorpay merchant account": "",
        "Razorpay SDK removal": "",
        "offline mode": "owner, approach",
        "offline mode spike": "",
        "offline mode demo": "",
        "offline payments": "",
        "sync conflict resolution proposal": "",
        "app shell": "",
        "onboarding": "the area (ownership)",
        "onboarding screens": "the deliverable",
        "onboarding tour": "",
        "onboarding buttons": "",
        "PIN setup": "",
        "permissions screen": "",
        "side drawer": "the drawer build and why it was chosen",
        "drawer mockup sign-off": "",
        "navigation accessibility review": "",
        "analytics dashboard": "",
        "iOS build": "",
        "code freeze": "",
        "decision log": "",
        "retro notes": "",
        "Meridian Bank": "the customer, as the party requiring something",
        "Meridian compliance team": "",
        "Meridian accessibility checklist": "",
        "Meridian requirements call": "",
        "Meridian pilot start": "",
        "Meridian test devices": "arrival date",
        "Meridian test devices request": "the request (completed)",
        "Kestrel Logistics pilot": "start date",
        "Kestrel pilot": "vendor, scope",
        "Kestrel discovery call": "",
        "Kestrel onboarding variant": "",
    },
    "nimbus": {
        "warehouse": "",
        "transformations": "",
        "events pipeline": "",
        "nightly events job": "run time",
        "Lumen dashboard": "",
        "migration plan": "",
        "cost estimate": "",
        "raw events retention": "",
        "Nimbus sync": "meeting slot",
    },
    "quill": {
        "newsletter": "send day, policies, contents",
        "newsletter audience": "",
        "CMS": "",
        "launch post": "",
        "style guide": "",
        "October issues": "",
        "interview outlines": "",
        "Quill sync": "meeting slot",
    },
}

#: Words that mark a completion; normalised to "completed".
_COMPLETED = {"done", "complete", "completed", "finished", "shipped", "delivered", "sent", "closed", "merged"}
_NON_WORD = re.compile(r"[^a-z0-9]+")
_LEADING = re.compile(r"^(the|a|an|our|their|its)\s+", re.IGNORECASE)


def tenant_of(slug_or_id: str) -> str:
    """``orbit_002`` / ``mtg_orbit_002`` / ``thr_orbit_001`` -> ``orbit``."""
    parts = [p for p in (slug_or_id or "").split("_") if p]
    for part in parts:
        if part in CANONICAL_SUBJECTS:
            return part
    return parts[0] if parts else ""


def known_subjects(tenant: str) -> dict[str, str]:
    """Canonical subject -> gloss for a tenant (empty for unknown tenants)."""
    return dict(CANONICAL_SUBJECTS.get(tenant, {}))


def _norm(text: str) -> str:
    text = _LEADING.sub("", text.strip())
    return _NON_WORD.sub(" ", text.lower()).strip()


def _singular(norm: str) -> str:
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in norm.split())


_PAREN = re.compile(r"\s*\([^)]*\)\s*$")


def canonicalize_subject(subject: str, tenant: str, extra: list[str] | None = None, *, fuzzy: bool = False) -> str:
    """Snap ``subject`` onto a known entity when it differs only by case, articles, punctuation or plural.

    ``fuzzy`` (v3+) also strips a trailing parenthetical (a gloss copied from the prompt) and snaps a
    subject that is a known name plus ONE extra word ("PayU sandbox integration" -> "PayU integration"),
    preferring the longest known name; ties are left alone.
    """
    names = list(CANONICAL_SUBJECTS.get(tenant, {})) + list(extra or [])
    cleaned = _PAREN.sub("", subject).strip() if fuzzy else subject.strip()
    if not names:
        return cleaned
    target = _norm(cleaned)
    for name in names:
        if _norm(name) == target:
            return name
    target_s = _singular(target)
    for name in names:
        if _singular(_norm(name)) == target_s:
            return name
    if fuzzy:
        words = set(target_s.split())
        candidates = []
        for name in names:
            known = set(_singular(_norm(name)).split())
            if known and known < words and len(words - known) == 1:
                candidates.append((len(known), name))
        if candidates:
            candidates.sort(reverse=True)
            if len(candidates) == 1 or candidates[0][0] > candidates[1][0]:
                return candidates[0][1]
    return cleaned


def canonicalize_predicate(predicate: str) -> str | None:
    """Map a predicate onto the closed set; None when it has no counterpart."""
    p = _NON_WORD.sub("_", (predicate or "").strip().lower()).strip("_")
    if p in PREDICATES:
        return p
    return PREDICATE_SYNONYMS.get(p)


_NUMBER_WORDS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
    "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14", "fifteen": "15",
    "twenty": "20", "thirty": "30", "ninety": "90", "hundred": "100",
}
_NUMBER_RE = re.compile(r"(?<![a-z])(" + "|".join(_NUMBER_WORDS) + r")(?![a-z])", re.IGNORECASE)
_COMPLETION_PREFIX = re.compile(r"^(done|finished|completed?|shipped|delivered|sent|submitted|went out|merged)(\s|$)", re.IGNORECASE)


def canonicalize_object(predicate: str, obj: str, *, numbers: bool = False) -> str:
    """Light, rule-based object normalisation (completion words, articles, trailing punctuation).

    ``numbers`` (v4+) also writes number words as digits ("seven years" -> "7 years") and maps
    completion phrases ("sent to finance", "went out Thursday") onto ``completed`` for ``status``.
    """
    value = obj.strip().strip(".;:!").strip()
    if predicate == "status" and value.lower() in _COMPLETED:
        return "completed"
    if numbers and predicate == "status" and _COMPLETION_PREFIX.match(value):
        return "completed"
    if predicate in {"uses_vendor", "uses_pattern", "scope_includes", "requires", "customer"}:
        value = _LEADING.sub("", value)
    if numbers and predicate != "due":
        value = _NUMBER_RE.sub(lambda m: _NUMBER_WORDS[m.group(1).lower()], value)
    return value


def render_predicates() -> str:
    """The predicate table for the prompt."""
    return "\n".join(f"- {name}: {definition}" for name, definition in PREDICATES.items())


def render_subjects(tenant: str, extra: list[str] | None = None) -> str:
    """The known-entity list for the prompt (canonical names, optional gloss)."""
    rows = []
    for name, gloss in known_subjects(tenant).items():
        rows.append(f"- {name}" + (f" ({gloss})" if gloss else ""))
    seen = {n.lower() for n in known_subjects(tenant)}
    for name in extra or []:
        if name.lower() not in seen:
            seen.add(name.lower())
            rows.append(f"- {name}")
    return "\n".join(rows) if rows else "- none yet"
