"""Identifier helpers: time-ordered ULID-style ids with a readable prefix, and slugs."""

from __future__ import annotations

import os
import re
import time

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32, lower-case


def _base32(value: int, length: int) -> str:
    chars = []
    for _ in range(length):
        chars.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def ulid() -> str:
    """26-char ULID: 48-bit epoch ms + 80 random bits, lexically sortable by time."""
    return _base32(int(time.time() * 1000), 10) + _base32(int.from_bytes(os.urandom(10), "big"), 16)


def new_id(prefix: str) -> str:
    """`<prefix>_<ulid>`; prefixes used here: per, mtg, thr, ep, ent, fact, task, agt, skl, stp, art, snap."""
    return f"{prefix}_{ulid()}"


def slugify(text: str) -> str:
    """Lower-case `[a-z0-9_]` slug for deterministic ids such as `ent_upi_flow`."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "x"
