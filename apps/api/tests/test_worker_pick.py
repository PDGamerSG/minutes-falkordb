"""A task handed off to an agent is claimable even when it still requires a capability the agent lacks.

The substrate's next_open_task applies the capability filter to addressed tasks too, so the Scheduler's
`requires: ["schedule"]` reschedule task was invisible to the FollowUp agent after the hand-off; the worker's backlog scan
(addressed-to-me) is what delivers it."""

from __future__ import annotations

from apps.api.agents.base import BaseAgent
from apps.api.workers import AgentWorker


def test_handed_off_task_with_a_foreign_capability_requirement_is_picked(seeded):
    hive = seeded.hive
    original = hive.next_open_task

    def strict_next_open_task(tenant, agent_id):  # the substrate's behaviour: capabilities always checked
        task = original(tenant, agent_id)
        agent = next(a for a in hive.list_agents(tenant) if a["id"] == agent_id)
        return task if task and set(task["requires"]) <= set(agent["capabilities"]) else None

    hive.next_open_task = strict_next_open_task
    task_id = hive.submit_task("orbit", "reschedule", {}, ["schedule"], [], 3, owner_agent="scheduler_agent")
    version = hive.claim("orbit", task_id, "scheduler_agent", 0)
    assert hive.handoff("orbit", task_id, "scheduler_agent", "followup_agent", version, "moved", []) is not None
    assert hive.next_open_task("orbit", "followup_agent") is None  # invisible to the capability-filtered query

    from apps.api.agents.followup_agent import FollowUpAgent

    worker = AgentWorker("orbit", FollowUpAgent("orbit", hive, seeded.llm, seeded.embedder, seeded.settings), seeded)
    picked = worker._pick_task()
    assert picked and picked["id"] == task_id
