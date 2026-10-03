"""Shared fixtures: a session HiveDB, a fresh tenant graph per test (deleted at teardown) and a small seeded graph."""

from __future__ import annotations

import os
import uuid

import hiveboard as hb
import pytest
from hiveboard.embed import fake_embedding

BASE = hb.iso_to_ms("2026-09-15T10:00:00+05:30")
DAY = 86_400_000


@pytest.fixture(scope="session")
def db():
    database = hb.HiveDB(os.environ.get("FALKORDB_URL", "falkor://localhost:6379"))
    if not database.ping():
        pytest.skip("FalkorDB is not reachable")
    hb.load_udfs(database)
    yield database
    database.close()


def cleanup_tenant(db: hb.HiveDB, slug: str) -> None:
    hb.delete_tenant(db, slug)
    if db.graph_exists("commons"):
        db.commons().query(
            "MATCH (s:Skill {origin_tenant: $t}) OPTIONAL MATCH (s)-[:STEP]->(st) DETACH DELETE s, st",
            {"t": slug},
        )


@pytest.fixture
def tenant(db):
    slug = f"test_{uuid.uuid4().hex[:12]}"
    hb.ensure_schema(db, slug)
    yield slug
    cleanup_tenant(db, slug)


@pytest.fixture
def other_tenant(db):
    slug = f"test_{uuid.uuid4().hex[:12]}"
    hb.ensure_schema(db, slug)
    yield slug
    cleanup_tenant(db, slug)


@pytest.fixture
def seeded(db, tenant) -> dict:
    """Two people, one meeting with three utterance episodes, two entities and a UPI-flow commitment."""
    priya = hb.remember_person(
        db, tenant, {"id": "spk_priya", "name": "Priya", "role": "PM", "email": "priya@orbit.example"}
    )
    aditya = hb.remember_person(
        db, tenant, {"id": "spk_aditya", "name": "Aditya", "role": "Eng", "email": "aditya@orbit.example"}
    )
    meeting = hb.remember_meeting(
        db,
        tenant,
        {
            "id": "mtg_kickoff",
            "title": "Kickoff",
            "started_at": BASE,
            "source_uri": "data/meetings/kickoff.wav",
        },
    )
    hb.remember_episodes(
        db,
        tenant,
        meeting,
        [
            {
                "id": "ep1",
                "seq": 1,
                "speaker_id": priya,
                "text": "We will ship the UPI flow by Thursday",
                "t_start": 0,
                "t_end": 5000,
                "t_occurred": BASE,
                "embedding": fake_embedding("ship the UPI flow by Thursday"),
            },
            {
                "id": "ep2",
                "seq": 2,
                "speaker_id": aditya,
                "text": "The payments gateway needs the UPI flow first",
                "t_start": 5000,
                "t_end": 9000,
                "t_occurred": BASE + 5000,
                "embedding": fake_embedding("payments gateway needs UPI flow"),
            },
            {
                "id": "ep3",
                "seq": 3,
                "speaker_id": priya,
                "text": "Agreed, onboarding waits for payments",
                "t_start": 9000,
                "t_end": 12000,
                "t_occurred": BASE + 9000,
                "embedding": fake_embedding("onboarding waits for payments"),
            },
        ],
    )
    ids = hb.upsert_entities(
        db,
        tenant,
        [
            {"name": "UPI flow", "type": "project", "embedding": fake_embedding("UPI flow")},
            {"name": "payments gateway", "type": "system", "embedding": fake_embedding("payments gateway")},
            {"name": "onboarding", "type": "project"},
        ],
    )
    hb.link_mentions(db, tenant, "ep1", [ids["UPI flow"]])
    hb.link_mentions(db, tenant, "ep2", [ids["UPI flow"], ids["payments gateway"]])
    hb.link_mentions(db, tenant, "ep3", [ids["onboarding"], ids["payments gateway"]])
    fact = hb.remember_fact(
        db,
        tenant,
        {
            "subject": "UPI flow",
            "predicate": "due",
            "object": "Thursday",
            "text": "UPI flow is due Thursday",
            "confidence": 0.9,
            "speaker_id": priya,
            "episode_id": "ep1",
            "entity_ids": [ids["UPI flow"]],
            "kind": "commitment",
            "due_at": BASE + 3 * DAY,
            "embedding": fake_embedding("UPI flow is due Thursday"),
        },
    )
    return {"priya": priya, "aditya": aditya, "meeting": meeting, "entities": ids, "fact": fact["id"]}
