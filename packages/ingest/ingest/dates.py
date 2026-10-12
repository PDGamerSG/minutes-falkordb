"""Date helpers shared by extraction, the pipeline and the eval."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, timezone

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


#: Default calendar convention for numeric dates: the demo tenants are Indian teams, so
#: ``12/09/2026`` is 12 September (``dayfirst=True``). Pipelines pass their tenant's policy.
DEFAULT_DAYFIRST = True

#: Default tenant timezone offset for calendar dates (IST). Pipelines pass their tenant's zone.
DEFAULT_TZ = "+05:30"

_OFFSET = re.compile(r"^([+-])(\d{2}):?(\d{2})$")


def tz_from_offset(offset: str | None) -> timezone:
    """``"+05:30"`` -> a fixed-offset timezone; ``None``, ``""`` or ``"UTC"`` -> UTC."""
    if not offset or offset.strip().upper() in {"UTC", "Z"}:
        return UTC
    match = _OFFSET.match(offset.strip())
    if not match:
        raise ValueError(f"timezone offset must look like +05:30, got {offset!r}")
    sign = 1 if match.group(1) == "+" else -1
    return timezone(sign * timedelta(hours=int(match.group(2)), minutes=int(match.group(3))))


def normalize_date(
    text: str | None,
    reference: date | datetime | None = None,
    *,
    dayfirst: bool = DEFAULT_DAYFIRST,
) -> str | None:
    """Return an ISO date (YYYY-MM-DD) for a date-like string, or None when it is not one.

    Only strings that look like dates are parsed, which avoids dateutil's eagerness with
    words such as "May" or bare numbers. Missing years resolve against ``reference``.
    ``dayfirst`` decides ambiguous numeric dates (``12/09/2026``): the tenant's convention.
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
        parsed = _dateparser.parse(s, default=default, dayfirst=dayfirst)
    except (ValueError, OverflowError):
        return None
    return parsed.date().isoformat()


def date_to_ms(iso: str | None, tz: str | timezone | None = None) -> int | None:
    """Epoch milliseconds for an ISO date (local midnight in ``tz``, UTC by default) or ISO datetime.

    Ingestion passes the tenant timezone (``"+05:30"``) so a due date of 2026-09-24 means midnight
    in Mumbai, not 05:30 IST; API callers that pass nothing keep the UTC-midnight behaviour.
    """
    if not iso:
        return None
    zone = tz if isinstance(tz, timezone) else tz_from_offset(tz)
    s = iso.strip()
    try:
        if _ISO_DATE.match(s):
            dt = datetime.fromisoformat(s).replace(tzinfo=zone)
        else:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=zone)
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


_DAY_ONLY = re.compile(r"(?<![0-9])([0-9]{1,2})(st|nd|rd|th)(?![a-z])", re.IGNORECASE)


def resolve_day_of_month(text: str | None, reference: date | datetime) -> str | None:
    """Resolve "the 25th" / "Friday the 25th" -> ISO date in the reference month (next month if already past).

    A fallback for objects the model left relative; full dates go through :func:`normalize_date`.
    """
    if not text:
        return None
    match = _DAY_ONLY.search(text)
    if not match:
        return None
    ref = reference.date() if isinstance(reference, datetime) else reference
    day = int(match.group(1))
    year, month = ref.year, ref.month
    for _ in range(2):
        try:
            candidate = date(year, month, day)
        except ValueError:
            candidate = None
        if candidate is not None and candidate >= ref - timedelta(days=7):
            return candidate.isoformat()
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return None
