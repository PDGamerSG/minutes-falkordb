"""Date helpers shared by extraction, the pipeline and the eval."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

from dateutil import parser as _dateparser

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_MONTHS = (
    "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|"
    "august|september|october|november|december"
)
_DATE_LIKE = re.compile(
    rf"(\b\d{{1,2}}(st|nd|rd|th)?\s+({_MONTHS})\b)"
    rf"|(\b({_MONTHS})\.?\s+\d{{1,2}}(st|nd|rd|th)?\b)"
    r"|(\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b)",
    re.IGNORECASE,
)

DATE_PREDICATES = frozenset(
    {
        "due",
        "due_at",
        "due_date",
        "due_on",
        "deadline",
        "date",
        "scheduled_for",
        "scheduled",
        "ships_on",
        "ship_date",
        "release_date",
        "launch_date",
        "starts_on",
        "ends_on",
        "moved_to",
        "target_date",
        "eta",
        "by",
    }
)

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def looks_like_date(text: str | None) -> bool:
    """True when the string is an ISO date/datetime or a human date such as "24 Sep 2026"."""
    if not text:
        return False
    s = text.strip()
    return bool(_ISO_DATE.match(s) or _ISO_DATETIME.match(s) or _DATE_LIKE.search(s))


def normalize_date(text: str | None, reference: date | datetime | None = None) -> str | None:
    """Return an ISO date (YYYY-MM-DD) for a date-like string, or None when it is not one.

    Only strings that look like dates are parsed, which avoids dateutil's eagerness with
    words such as "May" or bare numbers. Missing years resolve against ``reference``.
    """
    if not looks_like_date(text):
        return None
    s = text.strip()
    if _ISO_DATE.match(s):
        return s
    default = None
    if reference is not None:
        ref = reference if isinstance(reference, datetime) else datetime(reference.year, reference.month, reference.day)
        default = ref.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    try:
        parsed = _dateparser.parse(s, default=default, dayfirst=False)
    except (ValueError, OverflowError):
        return None
    return parsed.date().isoformat()


def date_to_ms(iso: str | None) -> int | None:
    """Epoch milliseconds (UTC midnight) for an ISO date, or the instant for an ISO datetime."""
    if not iso:
        return None
    s = iso.strip()
    try:
        if _ISO_DATE.match(s):
            dt = datetime.fromisoformat(s).replace(tzinfo=UTC)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)


def ms_to_date(ms: int) -> date:
    """UTC calendar date for an epoch-millisecond timestamp."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC).date()


def is_date_predicate(predicate: str, obj: str | None = None) -> bool:
    """Whether a (predicate, object) pair carries a date; used to wake the Scheduler."""
    p = (predicate or "").strip().lower()
    if p in DATE_PREDICATES or p.endswith("_date") or p.endswith("_at") or p.startswith("due"):
        return True
    return looks_like_date(obj)


def calendar_table(reference: date | datetime, weeks_after: int = 1) -> str:
    """Markdown-ish table of weekday -> ISO date for the reference week and the next ones.

    Gemma's weekday arithmetic is unreliable, so extraction prompts embed this table and
    instruct the model to copy ISO dates from it instead of computing them.
    """
    ref = reference.date() if isinstance(reference, datetime) else reference
    monday = ref - timedelta(days=ref.weekday())
    lines = [f"Reference date: {ref.isoformat()} ({_WEEKDAYS[ref.weekday()]})"]
    for week in range(weeks_after + 1):
        label = "This week" if week == 0 else ("Next week" if week == 1 else f"Week +{week}")
        start = monday + timedelta(days=7 * week)
        cells = ", ".join(f"{_WEEKDAYS[i][:3]} {(start + timedelta(days=i)).isoformat()}" for i in range(7))
        lines.append(f"{label}: {cells}")
    lines.append(f"Yesterday: {(ref - timedelta(days=1)).isoformat()}; tomorrow: {(ref + timedelta(days=1)).isoformat()}")
    return "\n".join(lines)
