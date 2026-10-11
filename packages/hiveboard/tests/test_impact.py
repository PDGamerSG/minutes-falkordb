"""Explicit work dependencies must determine which decision changes need follow-up."""

import hiveboard as hb
import pytest
from hiveboard import impact


def manifest(seeded, **overrides):
    item = {"id": "work_release", "title": "Prepare release checklist", "status": "open",
            "owner_id": seeded["aditya"], "baseline_fact_id": seeded["fact"],
            "rationale": "The release checklist was planned against the Thursday UPI delivery."}
    item.update(overrides)
    return {"document": {"id": "doc_release_v1", "title": "Release plan", "uri": "synthetic://release-plan",
                         "content": "Synthetic delivery plan explicitly linking the release checklist to the UPI date.",
                         "synthetic": True}, "items": [item]}


def test_impact_tracks_only_explicit_work_and_preserves_source(db, tenant, seeded):
    data = manifest(seeded)
    assert impact.import_manifest(db, tenant, data) == 1
    assert impact.import_manifest(db, tenant, data) == 1
    original = impact.work_impacts(db, tenant)[0]
    assert original["baseline"]["id"] == seeded["fact"]
    assert original["candidates"][0]["fact"]["id"] == seeded["fact"]
    assert original["document"]["content"] == data["document"]["content"]
    # Same subject with a different predicate is not a superseding dependency.
    hb.remember_fact(db, tenant, {"subject": "UPI flow", "predicate": "owner", "object": "Priya"})
    newer = hb.supersede_fact(db, tenant, seeded["fact"], {
        "subject": "UPI flow", "predicate": "due", "object": "Friday", "kind": "commitment",
        "speaker_id": seeded["priya"], "episode_id": "ep2", "valid_from": 9999999999999,
    })
    rows = impact.work_impacts(db, tenant)
    assert len(rows) == 1
    assert rows[0]["owner"]["id"] == seeded["aditya"]
    assert rows[0]["candidates"][0]["fact"]["id"] == newer["id"]
    assert rows[0]["candidates"][0]["via"] == [newer["id"], seeded["fact"]]


def test_import_is_atomic_on_missing_reference_and_tenant_scoped(db, tenant, other_tenant, seeded):
    data = manifest(seeded)
    data["items"].append({**data["items"][0], "id": "bad", "owner_id": "person_missing"})
    with pytest.raises(ValueError, match="reference"):
        impact.import_manifest(db, tenant, data)
    assert impact.work_impacts(db, tenant) == []
    with pytest.raises(ValueError, match="reference"):
        impact.import_manifest(db, other_tenant, manifest(seeded))
    assert impact.work_impacts(db, other_tenant) == []


def test_reimport_updates_owner_and_status_without_duplicate_edges(db, tenant, seeded):
    impact.import_manifest(db, tenant, manifest(seeded))
    impact.import_manifest(db, tenant, manifest(seeded, owner_id=seeded["priya"], status="completed"))
    rows = impact.work_impacts(db, tenant)
    assert len(rows) == 1 and rows[0]["item"]["status"] == "completed"
    assert rows[0]["owner"]["id"] == seeded["priya"]



def _draft(db, tenant, seeded):
    impact.import_manifest(db, tenant, manifest(seeded))
    newer = hb.supersede_fact(db, tenant, seeded["fact"], {
        "subject": "UPI flow", "predicate": "due", "object": "Friday", "kind": "commitment",
        "speaker_id": seeded["priya"], "episode_id": "ep2", "valid_from": 9999999999999,
    })
    draft = {"id": "draft_test", "work_item_id": "work_release", "baseline_fact_id": seeded["fact"],
             "current_fact_id": newer["id"], "owner_id": seeded["aditya"], "document_id": "doc_release_v1",
             "created_at": 123, "status": "draft", "title": "Review release checklist", "body": "Local draft."}
    assert impact.save_draft(db, tenant, draft) == draft
    return newer, draft


def test_draft_persists_once_and_write_rechecks_current_graph(db, tenant, seeded):
    newer, draft = _draft(db, tenant, seeded)
    assert impact.save_draft(db, tenant, {**draft, "created_at": 456}) == draft
    assert len(impact.list_drafts(db, tenant)) == 1
    hb.supersede_fact(db, tenant, newer["id"], {
        "subject": "UPI flow", "predicate": "due", "object": "Monday", "kind": "commitment",
        "speaker_id": seeded["priya"], "episode_id": "ep3", "valid_from": 99999999999999,
    })
    assert impact.save_draft(db, tenant, draft) is None
    assert len(impact.list_drafts(db, tenant)) == 1
    candidates = impact.work_impacts(db, tenant)[0]["candidates"]
    assert len(candidates) == 1 and len(candidates[0]["via"]) == 3


def test_conflicting_current_fact_rejects_draft_even_when_one_has_a_path(db, tenant, seeded):
    _, draft = _draft(db, tenant, seeded)
    hb.remember_fact(db, tenant, {"subject": "UPI flow", "predicate": "due", "object": "Tuesday"})
    candidates = impact.work_impacts(db, tenant)[0]["candidates"]
    assert len(candidates) == 2
    assert impact.save_draft(db, tenant, draft) is None


def test_closed_work_and_changed_owner_reject_inflight_draft(db, tenant, seeded):
    _, draft = _draft(db, tenant, seeded)
    impact.import_manifest(db, tenant, manifest(seeded, status="completed"))
    assert impact.save_draft(db, tenant, draft) is None
    impact.import_manifest(db, tenant, manifest(seeded, owner_id=seeded["priya"]))
    assert impact.save_draft(db, tenant, draft) is None
