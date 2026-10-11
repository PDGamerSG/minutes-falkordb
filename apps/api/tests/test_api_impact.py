"""Decision impact is explicit, tenant scoped, and drafts never send externally."""


def test_owner_choices_use_the_selected_team_roster(client, seeded):
    seeded.hive.remember_person("nimbus", {"id": "spk_nimbus", "name": "Nora"})
    response = client.get("/tenants/orbit/people")
    assert response.status_code == 200
    people = response.json()
    assert {p["id"] for p in people} == {"spk_aditya", "spk_priya", "spk_rahul"}
    assert all(set(p) <= {"id", "name", "email", "role"} for p in people)
    assert [p["name"] for p in people] == ["Aditya", "Priya", "Rahul"]
    assert client.get("/tenants/nimbus/people").json() == [{"id": "spk_nimbus", "name": "Nora"}]
    assert client.get("/tenants/missing/people").status_code == 404


def test_review_can_adopt_current_evidence_and_preserve_the_old_draft(client, seeded):
    people = client.get("/tenants/orbit/people")
    assert people.status_code == 200
    data = work_manifest(seeded)
    data["items"][0]["owner_id"] = next(p["id"] for p in people.json() if p["name"] == "Rahul")
    assert client.post("/tenants/orbit/work-items/import", json=data).status_code == 200
    original = client.get("/tenants/orbit/impact").json()["items"][0]
    draft = client.post("/tenants/orbit/impact/work_release/draft", json={"current_fact_id": original["current"]["id"]})
    assert draft.status_code == 200
    data["items"][0]["baseline_fact_id"] = original["current"]["id"]
    data["document"]["content"] = "Reviewed the email: the release checklist now uses September 28."
    assert client.post("/tenants/orbit/work-items/import", json=data).status_code == 200
    reviewed = client.get("/tenants/orbit/impact").json()["items"][0]
    assert reviewed["assessment"] == "aligned" and reviewed["draft"] is None
    assert reviewed["document"]["id"] != original["document"]["id"]
    assert reviewed["owner"]["name"] == "Rahul"
    assert client.get("/tenants/orbit/impact/drafts").json()[0]["id"] == draft.json()["id"]
    assert client.get("/tenants/nimbus/impact").json()["items"] == []


def work_manifest(seeded, *, status="open", baseline="2026-09-24"):
    fact = next(f for f in seeded.hive.list_facts("orbit", status="all")
                if f["subject"].lower() == "upi flow" and f["object"] == baseline)
    return {"document": {"title": "October release plan", "uri": "synthetic://orbit/release-plan",
                         "content": "The release checklist depends on the UPI delivery date.", "synthetic": True},
            "items": [{"id": "work_release", "title": "Update release checklist", "status": status,
                       "owner_id": "spk_rahul", "baseline_fact_id": fact["id"],
                       "rationale": "The release checklist depends on the UPI delivery date."}]}


def test_explicit_impact_and_local_draft_are_grounded_and_persistent(client, seeded):
    data = work_manifest(seeded)
    assert client.post("/tenants/orbit/work-items/import", json=data).status_code == 200
    response = client.get("/tenants/orbit/impact").json()
    assert response["summary"] == {"tracked": 1, "needs_review": 1, "aligned": 0, "closed": 0, "unresolved": 0}
    item = response["items"][0]
    assert item["owner"]["name"] == "Rahul" and item["current"]["object"] == "2026-09-28"
    assert item["baseline"]["object"] == "2026-09-24" and item["document"]["content"] == data["document"]["content"]
    assert {e["type"] for e in item["path"]["edges"]} >= {"SUPERSEDES", "DEPENDS_ON", "OWNED_BY", "DOCUMENTED_IN"}
    request = {"current_fact_id": item["current"]["id"]}
    draft = client.post("/tenants/orbit/impact/work_release/draft", json=request)
    assert draft.status_code == 200, draft.text
    draft = draft.json()
    assert draft["status"] == "draft" and "Rahul" in draft["body"]
    assert item["current"]["id"] in draft["body"] and item["document"]["id"] in draft["body"]
    assert client.post("/tenants/orbit/impact/work_release/draft", json=request).json()["id"] == draft["id"]
    assert len(client.get("/tenants/orbit/impact/drafts").json()) == 1
    assert client.get("/tenants/orbit/impact").json()["items"][0]["draft"]["id"] == draft["id"]
    assert client.get("/tenants/nimbus/impact").json()["items"] == []
    assert client.post("/tenants/nimbus/impact/work_release/draft", json=request).status_code == 404
    assert not seeded.hive.list_tasks("orbit")  # No external-side-effect worker is enqueued.


def test_closed_aligned_and_stale_items_cannot_be_drafted(client, seeded):
    for status, baseline, assessment in [("completed", "2026-09-24", "closed"), ("open", "2026-09-28", "aligned")]:
        client.post("/tenants/orbit/work-items/import", json=work_manifest(seeded, status=status, baseline=baseline))
        item = client.get("/tenants/orbit/impact").json()["items"][0]
        assert item["assessment"] == assessment
        assert client.post("/tenants/orbit/impact/work_release/draft", json={"current_fact_id": item["current"]["id"]}).status_code == 409
    client.post("/tenants/orbit/work-items/import", json=work_manifest(seeded))
    assert client.post("/tenants/orbit/impact/work_release/draft", json={"current_fact_id": "fact_stale"}).status_code == 409


def test_manifest_validates_references_and_duplicate_ids_before_writing(client, seeded):
    data = work_manifest(seeded)
    data["items"].append({**data["items"][0], "id": "bad", "owner_id": "unknown"})
    assert client.post("/tenants/orbit/work-items/import", json=data).status_code == 422
    assert client.get("/tenants/orbit/impact").json()["items"] == []
    data = work_manifest(seeded)
    data["items"].append(data["items"][0])
    assert client.post("/tenants/orbit/work-items/import", json=data).status_code == 422
    assert client.post("/tenants/missing/work-items/import", json=work_manifest(seeded)).status_code == 404


def test_closed_work_with_unrelated_current_fact_does_not_claim_a_dependency(client, seeded):
    data = work_manifest(seeded, status="completed", baseline="2026-09-28")
    assert client.post("/tenants/orbit/work-items/import", json=data).status_code == 200
    seeded.hive.retract_fact("orbit", data["items"][0]["baseline_fact_id"], "source corrected")
    seeded.hive.remember_fact("orbit", {"subject": "UPI flow", "predicate": "due", "object": "2026-10-05"})
    result = client.get("/tenants/orbit/impact")
    assert result.status_code == 200
    item = result.json()["items"][0]
    assert item["assessment"] == "closed" and item["current"] is None
    assert data["items"][0]["baseline_fact_id"] in [n["id"] for n in item["path"]["nodes"]]
