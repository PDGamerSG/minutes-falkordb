import json
import threading

import hiveboard as hb
import pytest
from hiveboard.embed import fake_embedding
from hiveboard.mcp_server import build_server


def test_publish_subscribe_roundtrip(db, tenant):
    received: list[dict] = []
    ready = threading.Event()

    def listener():
        gen = hb.subscribe(db, tenant, idle_timeout=5)
        ready.set()
        for event in gen:
            received.append(event)
            if event["event"] == "task.submitted":
                break

    thread = threading.Thread(target=listener, daemon=True)
    thread.start()
    assert ready.wait(5)
    hb.publish(db, tenant, "fact.created", {"id": "f1"})
    hb.register_agent(db, tenant, "agt", "A", ["x"], "m")
    task_id = hb.submit_task(db, tenant, "x", {"k": "v"}, ["x"])
    thread.join(10)
    assert not thread.is_alive()
    assert [e["event"] for e in received] == ["fact.created", "task.submitted"]
    assert received[1]["payload"]["task_id"] == task_id and received[1]["ts"] > 0
    assert hb.events.channel(tenant) == f"team_{tenant}:events"


async def test_asubscribe_receives_events(db, tenant):
    import asyncio

    async def consume():
        async for event in hb.asubscribe(db, tenant):
            return event

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.3)
    hb.publish(db, tenant, "skill.learned", {"skill_id": "s1"})
    event = await asyncio.wait_for(task, 5)
    assert event["event"] == "skill.learned" and event["payload"] == {"skill_id": "s1"}


def _tool_payload(result) -> dict:
    """mcp 1.x returns (content, structured) tuples; mcp 2.x returns CallToolResult with JSON text content."""
    if isinstance(result, tuple):
        payload = result[1]
        return payload.get("result", payload) if isinstance(payload, dict) else payload
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if structured:
        return structured.get("result", structured)
    assert not result.is_error, result.content
    return json.loads(result.content[0].text)


async def test_mcp_server_exposes_tools_and_runs_recall(db, tenant, seeded):
    server = build_server(db, embedder=fake_embedding)
    names = {t.name for t in await server.list_tools()}
    assert names == {"recall", "why", "belief_at", "list_tasks", "claim", "handoff", "open_commitments"}
    recalled = _tool_payload(
        await server.call_tool("recall", {"tenant": tenant, "query_text": "when is the UPI flow due", "k": 2})
    )
    assert recalled["items"][0]["id"] == seeded["fact"] and "hive.score" in recalled["cypher"]
    belief = _tool_payload(await server.call_tool("belief_at", {"tenant": tenant, "t_ms": hb.now_ms()}))
    assert [f["object"] for f in belief["facts"]] == ["Thursday"]
    hb.register_agent(db, tenant, "agt_mcp", "MCP", ["followup"], "assistant")
    task_id = hb.submit_task(db, tenant, "followup", {}, ["followup"])
    won = _tool_payload(
        await server.call_tool(
            "claim", {"tenant": tenant, "task_id": task_id, "agent_id": "agt_mcp", "expected_version": 0}
        )
    )
    lost = _tool_payload(
        await server.call_tool(
            "claim", {"tenant": tenant, "task_id": task_id, "agent_id": "agt_mcp", "expected_version": 0}
        )
    )
    assert won["won"] and won["version"] == 1 and not lost["won"] and lost["version"] is None
    listed = _tool_payload(await server.call_tool("list_tasks", {"tenant": tenant, "status": "working"}))
    assert [t["id"] for t in listed["tasks"]] == [task_id]


def test_temporal_helpers_roundtrip():
    ms = hb.iso_to_ms("2026-09-16T14:02:00+05:30")
    assert ms == hb.iso_to_ms("2026-09-16T08:32:00Z")
    assert hb.ms_to_iso(ms) == "2026-09-16T08:32:00.000Z"
    assert hb.iso_to_ms("2026-09-16") == hb.iso_to_ms("2026-09-16T00:00:00Z")
    assert hb.to_ms(None) is None and hb.to_ms(5) == 5 and hb.to_ms("1970-01-01T00:00:01Z") == 1000
    assert abs(hb.now_ms() - hb.iso_to_ms(hb.ms_to_iso(hb.now_ms()))) < 1000
    with pytest.raises(TypeError):
        hb.to_ms(True)
