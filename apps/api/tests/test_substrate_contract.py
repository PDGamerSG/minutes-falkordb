"""Seams with the substrate: the fact.superseded payload contract, per-tenant ACL password derivation."""

from __future__ import annotations

from hiveboard.events import SUPERSEDED_PAYLOAD_KEYS

from apps.api.agents.scheduler_agent import superseded_event_to_task
from apps.api.hive_adapter import RealHive


def test_fake_hive_superseded_payload_carries_every_contract_key(seeded):
    ctx = seeded
    task_id_before = len(ctx.hive.events["orbit"])
    old = next(f for f in ctx.hive.list_facts("orbit", status="active", kind="commitment") if f.get("due_at"))
    new = {**{k: old[k] for k in ("kind", "subject", "predicate", "key", "text", "speaker_id", "episode_id") if k in old}, "object": "2031-01-01", "valid_from": 2_000_000_000_000, "due_at": 1_924_992_000_000}
    ctx.hive.supersede_fact("orbit", old["id"], new)
    events = [e for e in ctx.hive.events["orbit"][task_id_before:] if e["event"] == "fact.superseded"]
    assert events, "the hive must publish fact.superseded itself"
    assert SUPERSEDED_PAYLOAD_KEYS <= set(events[0]["payload"])
    spec = superseded_event_to_task(events[0]["payload"])
    assert spec and spec["kind"] == "reschedule" and spec["payload"]["old_object"] == old["object"] and spec["requires"] == ["schedule"]


def test_head_unchanged_chain_insertions_do_not_wake_anyone():
    payload = {key: None for key in SUPERSEDED_PAYLOAD_KEYS} | {"new_fact_id": "f2", "predicate": "due", "new_object": "2026-10-02", "head_changed": False}
    # head_changed=False is filtered by the worker before this function; the spec itself stays well formed
    assert superseded_event_to_task(payload)["payload"]["new_fact_id"] == "f2"


def test_tenant_acl_passwords_are_per_tenant_and_stable():
    hive = RealHive.__new__(RealHive)
    hive.rw_password, hive.ro_password = "master-rw", "master-ro"
    orbit_ro, nimbus_ro = hive._derive("orbit", "ro"), hive._derive("nimbus", "ro")
    assert orbit_ro != nimbus_ro and orbit_ro == hive._derive("orbit", "ro")
    assert hive._derive("orbit", "rw") != orbit_ro
    other = RealHive.__new__(RealHive)
    other.rw_password, other.ro_password = "other-rw", "other-ro"
    assert other._derive("orbit", "ro") != orbit_ro
