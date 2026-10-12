"""Fixtures: a tiny Orbit corpus on disk, a FakeHive + FakeLLM + FakeEmbedder context, a TestClient.

No FalkorDB, no models. The corpus reproduces the demo story: the UPI flow moves Sep 24 -> Sep 25
(standup 1) -> Sep 28 (email), is confirmed in standup 2, and the PayU integration (due Oct 1) is
the target of the "move it to Friday" demo button.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient
from ingest.embed import Embedder

from apps.api.agents.fake_policy import fake_json_policy, fake_text_policy, fake_tool_policy
from apps.api.config import Settings
from apps.api.hive_adapter import FakeHive, register_default_agents
from apps.api.ingest_service import import_file
from apps.api.llm.fake import FakeLLM
from apps.api.main import create_app
from apps.api.state import AppContext

SPEAKERS = [
    {"id": "spk_aditya", "name": "Aditya", "role": "lead"},
    {"id": "spk_priya", "name": "Priya", "role": "backend"},
    {"id": "spk_rahul", "name": "Rahul", "role": "mobile"},
]
ROSTER = [{**s, "email": f"{s['name'].lower()}@orbit.example"} for s in SPEAKERS]


def _seg(start_s: int, end_s: int, speaker: str, text: str) -> dict[str, Any]:
    return {"start_ms": start_s * 1000, "end_ms": end_s * 1000, "speaker_id": speaker, "text": text}


MEETING_001 = {
    "version": 1,
    "meeting": {"id": "mtg_orbit_001", "title": "Orbit kickoff", "started_at": "2026-09-07T10:00:00+05:30", "ended_at": "2026-09-07T10:08:30+05:30", "audio_uri": "data/meetings/orbit_001.wav"},
    "speakers": SPEAKERS,
    "segments": [
        _seg(0, 8, "spk_aditya", "Alright, let's lock the scope for the October release. Payments go first."),
        _seg(8, 15, "spk_priya", "I can have the UPI flow done by Thursday the 24th."),
        _seg(15, 22, "spk_priya", "The PayU integration lands on October the 1st."),
        _seg(22, 28, "spk_aditya", "Decision: we go with Razorpay for the payment gateway."),
        _seg(28, 34, "spk_rahul", "Offline mode spike is mine, done by the 11th."),
    ],
}
GOLD_001 = {
    "meeting_id": "mtg_orbit_001",
    "items": [
        {"kind": "decision", "subject": "October release", "predicate": "scope_includes", "object": "payments", "speaker_id": "spk_aditya", "segment_index": 0},
        {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "speaker_id": "spk_priya", "segment_index": 1},
        {"kind": "commitment", "subject": "PayU integration", "predicate": "due", "object": "2026-10-01", "speaker_id": "spk_priya", "segment_index": 2},
        {"kind": "decision", "subject": "payment gateway", "predicate": "decided", "object": "Razorpay", "speaker_id": "spk_aditya", "segment_index": 3},
        {"kind": "commitment", "subject": "offline mode spike", "predicate": "due", "object": "2026-09-11", "speaker_id": "spk_rahul", "segment_index": 4},
    ],
}
MEETING_002 = {
    "version": 1,
    "meeting": {"id": "mtg_orbit_002", "title": "Orbit standup 1", "started_at": "2026-09-14T10:00:00+05:30", "ended_at": "2026-09-14T10:04:33+05:30", "audio_uri": "data/meetings/orbit_002.wav"},
    "speakers": SPEAKERS,
    "segments": [
        _seg(0, 8, "spk_aditya", "Morning. Standup, same shape as always: done, next, blockers."),
        _seg(8, 16, "spk_priya", "The UPI flow slips by a day. Move it to Friday the 25th."),
        _seg(16, 22, "spk_rahul", "Offline mode spike is done."),
    ],
}
GOLD_002 = {
    "meeting_id": "mtg_orbit_002",
    "items": [
        {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-25", "speaker_id": "spk_priya", "segment_index": 1, "supersedes": {"subject": "UPI flow", "predicate": "due"}},
        {"kind": "commitment", "subject": "offline mode spike", "predicate": "status", "object": "completed", "speaker_id": "spk_rahul", "segment_index": 2},
    ],
}
THREAD_001 = {
    "version": 1,
    "thread": {"id": "thr_orbit_001", "subject": "UPI flow timeline", "started_at": "2026-09-17T14:02:00+05:30"},
    "people": [{"id": "spk_priya", "name": "Priya", "email": "priya@orbit.example"}, {"id": "spk_aditya", "name": "Aditya", "email": "aditya@orbit.example"}],
    "messages": [
        {"id": "msg_orbit_001_1", "sent_at": "2026-09-17T14:02:00+05:30", "from": "priya@orbit.example", "to": ["aditya@orbit.example"], "cc": ["rahul@orbit.example"], "in_reply_to": None, "subject": "UPI flow timeline", "body_text": "Aditya, KYC lead time bit us: the UPI flow now lands on Monday the 28th."},
        {"id": "msg_orbit_001_2", "sent_at": "2026-09-17T15:10:00+05:30", "from": "aditya@orbit.example", "to": ["priya@orbit.example"], "cc": [], "in_reply_to": "msg_orbit_001_1", "subject": "Re: UPI flow timeline", "body_text": "Understood, Monday it is.\n\nOn Thu, Sep 17, 2026 at 2:02 PM Priya wrote:\n> the UPI flow now lands on Monday the 28th."},
    ],
}
GOLD_THREAD_001 = {
    "thread_id": "thr_orbit_001",
    "items": [
        {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-28", "speaker_id": "spk_priya", "message_index": 0, "supersedes": {"subject": "UPI flow", "predicate": "due"}},
    ],
}
MEETING_003 = {
    "version": 1,
    "meeting": {"id": "mtg_orbit_003", "title": "Orbit standup 2", "started_at": "2026-09-21T10:00:00+05:30", "ended_at": "2026-09-21T10:03:00+05:30", "audio_uri": "data/meetings/orbit_003.wav"},
    "speakers": SPEAKERS,
    "segments": [
        _seg(0, 6, "spk_aditya", "Standup. Same shape."),
        _seg(6, 12, "spk_priya", "UPI flow is on track for Monday the 28th."),
        _seg(12, 18, "spk_aditya", "Decision: code freeze is Friday October the 9th."),
    ],
}
GOLD_003 = {
    "meeting_id": "mtg_orbit_003",
    "items": [
        {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-28", "speaker_id": "spk_priya", "segment_index": 1, "confirms": {"subject": "UPI flow", "predicate": "due"}},
        {"kind": "decision", "subject": "code freeze", "predicate": "scheduled_for", "object": "2026-10-09", "speaker_id": "spk_aditya", "segment_index": 2},
    ],
}

IMPORT_ORDER = ["orbit_001.json", "orbit_002.json", "orbit_thread_001.json", "orbit_003.json"]


def cf(value: Any) -> str:
    """Casefold for assertions: entity display casing follows the source text and may change with the pipeline."""
    return str(value or "").casefold()


def cfs(values: Any) -> set[str]:
    return {cf(v) for v in values}


@pytest.fixture(scope="session")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("data")
    meetings, gold = root / "meetings", root / "gold"
    meetings.mkdir(), gold.mkdir()
    (root / "bench").mkdir()
    files = {
        "orbit_001.json": MEETING_001,
        "orbit_002.json": MEETING_002,
        "orbit_003.json": MEETING_003,
        "orbit_thread_001.json": THREAD_001,
        "orbit_roster.json": ROSTER,
    }
    for name, payload in files.items():
        (meetings / name).write_text(json.dumps(payload), encoding="utf-8")
    for name, payload in {"orbit_001.json": GOLD_001, "orbit_002.json": GOLD_002, "orbit_003.json": GOLD_003, "orbit_thread_001.json": GOLD_THREAD_001}.items():
        (gold / name).write_text(json.dumps(payload), encoding="utf-8")
    (root / "bench" / "run_2026-10-03.json").write_text(
        json.dumps({"run_id": "bench_demo", "ts": 1790000000000, "engine": "6.0.1", "target": "local", "agents": 200, "tenants": 20, "duration_s": 300, "read_p50": 1.2, "read_p95": 4.5, "read_p99": 9.1, "write_p50": 2.0, "write_p95": 6.3, "write_p99": 12.4, "errors": 0, "cas": {"attempts": 50, "winners": 1, "losers": 49}}),
        encoding="utf-8",
    )
    return root


def make_settings(data_dir: Path, **overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "llm_backend": "fake",
        "embed_backend": "fake",
        "data_dir": str(data_dir),
        "bench_results_dir": str(data_dir / "bench"),
        "seed_tenants": "orbit",
        "auto_create_tenants": True,
        "workers_enabled": False,
        "worker_poll_s": 0.05,
        "github_token": None,
        "github_demo_repo": None,
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def make_ctx(data_dir: Path, **overrides: Any) -> AppContext:
    settings = make_settings(data_dir, **overrides)
    hive = FakeHive()
    llm = FakeLLM(json_policy=fake_json_policy, text_policy=fake_text_policy, tool_policy=fake_tool_policy)
    ctx = AppContext(settings=settings, hive=hive, llm=llm, embedder=Embedder(backend="fake"))
    hive.create_tenant("orbit", "Orbit")
    hive.create_tenant("nimbus", "Nimbus")
    register_default_agents(hive, "orbit", "fake")
    register_default_agents(hive, "nimbus", "fake")
    return ctx


def seed(ctx: AppContext, data_dir: Path, *, skip: set[str] | None = None) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for name in IMPORT_ORDER:
        if skip and Path(name).stem in skip:
            continue
        result = import_file(data_dir / "meetings" / name, "orbit", ctx)
        assert result is not None, name
        stats[name] = result
    return stats


@pytest.fixture
def ctx(data_dir: Path) -> AppContext:
    return make_ctx(data_dir)


@pytest.fixture
def seeded(ctx: AppContext, data_dir: Path) -> AppContext:
    seed(ctx, data_dir)
    return ctx


@pytest.fixture
def client(seeded: AppContext):
    app = create_app(seeded, start_workers=False)
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_meeting() -> dict[str, Any]:
    return copy.deepcopy(MEETING_001)


@pytest.fixture
def sample_thread() -> dict[str, Any]:
    return copy.deepcopy(THREAD_001)
