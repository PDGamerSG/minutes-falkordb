"""Skills: learned after two meetings with the same title prefix; list, outcome, run."""

from __future__ import annotations

from apps.api.agents.standup_agent import StandupAgent, meetings_by_prefix, render_standup, title_prefix


def test_title_prefix_grouping():
    assert title_prefix("Orbit standup 2") == "orbit standup"
    assert title_prefix("Nimbus sync #3") == "nimbus sync"
    assert title_prefix("Retro") == "retro"
    groups = meetings_by_prefix([{"title": "Orbit standup 1"}, {"title": "Orbit standup 2"}, {"title": "Orbit kickoff"}])
    assert len(groups["orbit standup"]) == 2 and len(groups["orbit kickoff"]) == 1


def test_skill_learned_after_second_standup(client):
    skills = client.get("/tenants/orbit/skills").json()
    assert len(skills) == 1
    skill = skills[0]
    assert skill["goal"].startswith("Run the orbit standup routine")
    assert skill["status"] == "active" and skill["runs"] == 0 and skill["success_rate"] == 0.0 and skill["version"] == 1
    assert [s["tool"] for s in skill["steps"]] == ["open_commitments", "active_facts", "stale_decisions", "recall"]
    assert skill["learned_from"] == ["ep_mtg_orbit_002_000", "ep_mtg_orbit_003_000"]
    assert "pagerank" in skill
    assert client.get(f"/tenants/orbit/skills/{skill['id']}").json()["id"] == skill["id"]
    assert client.get("/tenants/orbit/skills/skl_missing").status_code == 404


def test_no_skill_before_second_meeting(ctx, data_dir):
    from apps.api.tests.conftest import seed

    seed(ctx, data_dir, skip={"orbit_003"})
    assert ctx.hive.list_skills("orbit") == []


def test_record_outcome_updates_success_rate(client):
    skill = client.get("/tenants/orbit/skills").json()[0]
    updated = client.post(f"/tenants/orbit/skills/{skill['id']}/outcome", json={"ok": True}).json()
    assert updated["runs"] == 1 and updated["success_rate"] == 1.0
    updated = client.post(f"/tenants/orbit/skills/{skill['id']}/outcome", json={"ok": False, "agent_id": "standup_agent"}).json()
    assert updated["runs"] == 2 and updated["success_rate"] == 0.5
    assert client.post("/tenants/orbit/skills/skl_missing/outcome", json={"ok": True}).status_code == 404


def test_run_skill_submits_task_and_agent_executes_it(client, seeded):
    response = client.post("/tenants/orbit/skills/run", json={"goal": "orbit standup"})
    assert response.status_code == 202
    task_id = response.json()["task_id"]
    task = client.get(f"/tenants/orbit/tasks/{task_id}").json()
    assert task["kind"] == "run_skill" and task["requires"] == ["standup"] and task["status"] == "submitted"

    agent = StandupAgent("orbit", seeded.hive, seeded.llm, seeded.embedder, seeded.settings)
    assert seeded.hive.claim("orbit", task_id, "standup_agent", 0) == 1
    task["version"] = 1
    result = agent.run(task)
    assert not result.failed and result.artifact["kind"] == "standup_summary"
    assert "Open commitments" in result.final and "PayU Integration" in result.final
    assert result.used_skill_id == client.get("/tenants/orbit/skills").json()[0]["id"]
    assert [s["tool"] for s in result.steps][:2] == ["retrieve_skill", "open_commitments"]
    assert any(e["event"] == "skill.ran" for e in seeded.hive.events["orbit"])
    seeded.hive.complete("orbit", task_id, "standup_agent", result.artifact)
    skill_id = result.used_skill_id
    client.post(f"/tenants/orbit/skills/{skill_id}/outcome", json={"ok": True, "task_id": task_id})
    trace = client.get(f"/tenants/orbit/tasks/{task_id}/trace").json()
    assert any(e["type"] == "skill_used" for e in trace["events"])


def test_render_standup_handles_empty():
    text = render_standup("x", {})
    assert text.startswith("Standup summary (x)") and "Open commitments (0)" in text
