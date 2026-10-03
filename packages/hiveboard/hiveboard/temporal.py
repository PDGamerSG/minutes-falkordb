"""Time helpers. Every timestamp in the graph is epoch milliseconds (int); FalkorDB has no timezone type."""

from __future__ import annotations

import time
from datetime import UTC, datetime


def now_ms() -> int:
    """Current wall-clock time in epoch milliseconds."""
    return int(time.time() * 1000)


def iso_to_ms(s: str) -> int:
    """ISO-8601 string (with offset, `Z`, or naive = UTC; date-only allowed) to epoch ms."""
    dt = datetime.fromisoformat(s.strip())  # Python 3.11+ accepts the `Z` suffix
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp() * 1000)


def ms_to_iso(ms: int) -> str:
    """Epoch ms to an ISO-8601 UTC string with millisecond precision and a `Z` suffix."""
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_ms(value: float | str | None) -> int | None:
    """Accept epoch ms (int/float), an ISO string, or None; return epoch ms or None."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError("booleans are not timestamps")
    if isinstance(value, (int, float)):
        return int(value)
    return iso_to_ms(value)
