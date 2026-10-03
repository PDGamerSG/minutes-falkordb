"""Email thread format (docs/contracts/email-format.md).

Pydantic model of the thread JSON, a parser from ``.eml`` / ``.mbox`` (stdlib ``email``) into
the same model, quoted-reply stripping, and the mapping of messages to Episodes.
"""

from __future__ import annotations

import email
import hashlib
import json
import mailbox
import re
import tempfile
from datetime import UTC, datetime
from email import policy
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .chunker import Episode, episode_id
from .recorder_format import to_ms

_QUOTE_INTRO = re.compile(r"^\s*On\s.+?(wrote|a écrit|schrieb)\s*:\s*$", re.IGNORECASE)
_QUOTE_INTRO_START = re.compile(r"^\s*On\s.+", re.IGNORECASE)
_ORIGINAL_MESSAGE = re.compile(r"^\s*-{2,}\s*(Original Message|Forwarded message)\s*-{2,}\s*$", re.IGNORECASE)
_HEADER_BLOCK = re.compile(r"^(From|Sent|To|Subject)\s*:\s", re.IGNORECASE)
_SIGNATURE = re.compile(r"^--\s*$")
_RE_PREFIX = re.compile(r"^\s*((re|fwd?|aw|wg)\s*:\s*)+", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_NON_WORD = re.compile(r"[^a-z0-9]+")


class EmailFormatError(ValueError):
    """Raised when a thread does not satisfy the contract."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)


def _tz_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("timestamps must carry a timezone offset")
    return value


class ThreadMeta(_Strict):
    id: str = Field(min_length=1)
    subject: str = Field(min_length=1)
    started_at: datetime

    @field_validator("started_at")
    @classmethod
    def _started(cls, value: datetime) -> datetime:
        return _tz_aware(value)


class ThreadPerson(_Strict):
    """A participant; ``id`` reuses the meeting speaker ids via the tenant roster."""

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    email: str = Field(min_length=3)
    role: str | None = None

    @field_validator("email")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.lower()


class EmailMessageModel(_Strict):
    """One message of the thread. ``from`` is exposed as ``from_`` in Python."""

    id: str = Field(min_length=1)
    sent_at: datetime
    from_: str = Field(alias="from", min_length=3)
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    in_reply_to: str | None = None
    subject: str | None = None
    body_text: str = ""

    @field_validator("sent_at")
    @classmethod
    def _sent(cls, value: datetime) -> datetime:
        return _tz_aware(value)

    @field_validator("from_")
    @classmethod
    def _from(cls, value: str) -> str:
        return value.lower()

    @field_validator("to", "cc")
    @classmethod
    def _addresses(cls, value: list[str]) -> list[str]:
        return [v.strip().lower() for v in value if v and v.strip()]


class EmailThread(_Strict):
    """Root of the thread JSON."""

    version: Literal[1]
    thread: ThreadMeta
    people: list[ThreadPerson] = Field(default_factory=list)
    messages: list[EmailMessageModel] = Field(min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> EmailThread:
        ids = [m.id for m in self.messages]
        if len(set(ids)) != len(ids):
            raise ValueError("message ids must be unique")
        person_ids = [p.id for p in self.people]
        if len(set(person_ids)) != len(person_ids):
            raise ValueError("people ids must be unique")
        seen: set[str] = set()
        prev: datetime | None = None
        for index, msg in enumerate(self.messages):
            if prev is not None and msg.sent_at < prev:
                raise ValueError(f"message {index} is out of sent_at order")
            if msg.in_reply_to is not None and msg.in_reply_to not in seen:
                raise ValueError(f"message {index} replies to unknown or later message {msg.in_reply_to!r}")
            seen.add(msg.id)
            prev = msg.sent_at
        return self

    @property
    def started_at_ms(self) -> int:
        return to_ms(self.thread.started_at)

    def resolve_people(self, roster: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
        """People keyed by id: roster entries win, then ``people``, then synthesized from addresses."""
        by_email: dict[str, dict[str, Any]] = {}
        for entry in roster or []:
            mail = str(entry.get("email") or "").lower()
            if mail and entry.get("id"):
                by_email[mail] = {"id": entry["id"], "name": entry.get("name") or mail, "email": mail, "role": entry.get("role")}
        for person in self.people:
            by_email.setdefault(person.email, {"id": person.id, "name": person.name, "email": person.email, "role": person.role})
        for msg in self.messages:
            for addr in [msg.from_, *msg.to, *msg.cc]:
                by_email.setdefault(addr, synthesize_person(addr))
        people: dict[str, dict[str, Any]] = {}
        for person in by_email.values():
            people.setdefault(person["id"], person)
        return people


def synthesize_person(address: str) -> dict[str, Any]:
    """Fallback identity for an address that is in no roster: ``spk_<local-part>``."""
    local = address.split("@", 1)[0].lower()
    slug = _NON_WORD.sub("_", local).strip("_") or "unknown"
    name = " ".join(part.capitalize() for part in re.split(r"[._-]+", local) if part) or address
    return {"id": f"spk_{slug}", "name": name, "email": address.lower(), "role": None}


def strip_quoted(body: str) -> str:
    """Drop quoted replies: lines starting with ``>`` and everything after an ``On ... wrote:`` line."""
    kept: list[str] = []
    lines = body.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        if _QUOTE_INTRO.match(line) or _ORIGINAL_MESSAGE.match(line):
            break
        if _QUOTE_INTRO_START.match(line) and i + 1 < len(lines) and lines[i + 1].strip().lower().startswith("wrote:"):
            break
        if _HEADER_BLOCK.match(line) and i + 1 < len(lines) and _HEADER_BLOCK.match(lines[i + 1]):
            break
        if _SIGNATURE.match(line):
            break
        if line.lstrip().startswith(">"):
            i += 1
            continue
        kept.append(line.rstrip())
        i += 1
    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_thread(data: dict[str, Any] | str | bytes | EmailThread) -> EmailThread:
    """Validate raw JSON into an :class:`EmailThread`."""
    if isinstance(data, EmailThread):
        return data
    try:
        if isinstance(data, (str, bytes)):
            data = json.loads(data)
        return EmailThread.model_validate(data)
    except (ValidationError, json.JSONDecodeError) as exc:
        raise EmailFormatError(str(exc)) from exc


def load_thread(path: str | Path) -> EmailThread:
    """Read and validate a thread JSON file."""
    return parse_thread(Path(path).read_text(encoding="utf-8"))


def _clean_subject(subject: str | None) -> str:
    return _RE_PREFIX.sub("", subject or "").strip() or "(no subject)"


def _message_body(msg: EmailMessage) -> str:
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is None:
        return ""
    try:
        content = body.get_content()
    except (LookupError, KeyError):
        payload = body.get_payload(decode=True) or b""
        content = payload.decode("utf-8", errors="replace")
    if body.get_content_type() == "text/html":
        content = _TAG.sub(" ", content)
        content = re.sub(r"[ \t]+", " ", content)
    return content.strip()


def _addresses(msg: EmailMessage, header: str) -> list[str]:
    values = msg.get_all(header, [])
    return [addr.lower() for _, addr in getaddresses(values) if addr]


def _strip_angle(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().strip("<>").strip() or None


def thread_from_messages(messages: list[EmailMessage], *, thread_id: str | None = None) -> EmailThread:
    """Build an :class:`EmailThread` from parsed stdlib messages (one ``.eml`` or a whole ``.mbox``)."""
    if not messages:
        raise EmailFormatError("no messages found")
    rows: list[dict[str, Any]] = []
    people: dict[str, dict[str, Any]] = {}
    for index, msg in enumerate(messages):
        try:
            sent_at = parsedate_to_datetime(msg.get("Date", ""))
        except (TypeError, ValueError) as exc:
            raise EmailFormatError(f"message {index} has no parseable Date header") from exc
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=UTC)
        senders = getaddresses(msg.get_all("From", []))
        if not senders or not senders[0][1]:
            raise EmailFormatError(f"message {index} has no From address")
        sender_name, sender = senders[0][0], senders[0][1].lower()
        for name, addr in getaddresses(msg.get_all("From", []) + msg.get_all("To", []) + msg.get_all("Cc", [])):
            if addr:
                person = synthesize_person(addr)
                if name:
                    person["name"] = name
                people.setdefault(addr.lower(), person)
        rows.append(
            {
                "id": _strip_angle(msg.get("Message-ID")) or f"msg_{index + 1}",
                "sent_at": sent_at,
                "from": sender,
                "to": _addresses(msg, "To"),
                "cc": _addresses(msg, "Cc"),
                "in_reply_to": _strip_angle(msg.get("In-Reply-To")),
                "subject": msg.get("Subject"),
                "body_text": _message_body(msg),
                "_sender_name": sender_name,
            }
        )
    rows.sort(key=lambda r: r["sent_at"])
    known = {r["id"] for r in rows}
    for row in rows:
        row.pop("_sender_name", None)
        if row["in_reply_to"] not in known:
            row["in_reply_to"] = None
    first = rows[0]
    digest = hashlib.sha1(first["id"].encode("utf-8")).hexdigest()[:10]
    data = {
        "version": 1,
        "thread": {
            "id": thread_id or f"thr_{digest}",
            "subject": _clean_subject(first["subject"]),
            "started_at": first["sent_at"],
        },
        "people": list(people.values()),
        "messages": rows,
    }
    try:
        return EmailThread.model_validate(data)
    except ValidationError as exc:
        raise EmailFormatError(str(exc)) from exc


def thread_from_eml(raw: bytes | str, *, thread_id: str | None = None) -> EmailThread:
    """Parse one RFC 822 message into a single-message thread."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    msg = email.message_from_bytes(raw, policy=policy.default)
    return thread_from_messages([msg], thread_id=thread_id)


def thread_from_mbox(raw: bytes | str, *, thread_id: str | None = None) -> EmailThread:
    """Parse an mbox file (bytes) into one thread ordered by Date."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    with tempfile.NamedTemporaryFile(suffix=".mbox", delete=False) as handle:
        handle.write(raw)
        path = handle.name
    try:
        box = mailbox.mbox(path, factory=lambda f: email.message_from_binary_file(f, policy=policy.default))
        messages = [m for m in box]
        box.close()
    finally:
        Path(path).unlink(missing_ok=True)
    return thread_from_messages(messages, thread_id=thread_id)


def thread_episodes(thread: EmailThread, people: dict[str, dict[str, Any]]) -> list[Episode]:
    """One Episode per message with ``source_kind="email"`` and reply links resolved to episode ids."""
    by_email = {p["email"]: p["id"] for p in people.values() if p.get("email")}
    message_to_episode: dict[str, str] = {}
    episodes: list[Episode] = []
    for seq, msg in enumerate(thread.messages):
        eid = episode_id(thread.thread.id, seq)
        message_to_episode[msg.id] = eid
        text = strip_quoted(msg.body_text) or msg.body_text.strip() or "(empty message)"
        episodes.append(
            Episode(
                id=eid,
                seq=seq,
                speaker_id=by_email.get(msg.from_) or synthesize_person(msg.from_)["id"],
                text=text,
                t_start=None,
                t_end=None,
                t_occurred=to_ms(msg.sent_at),
                segment_indices=[seq],
                source_kind="email",
                container_id=thread.thread.id,
                to_ids=[by_email.get(a) or synthesize_person(a)["id"] for a in msg.to],
                cc_ids=[by_email.get(a) or synthesize_person(a)["id"] for a in msg.cc],
                in_reply_to_episode_id=message_to_episode.get(msg.in_reply_to) if msg.in_reply_to else None,
                message_id=msg.id,
            )
        )
    return episodes
