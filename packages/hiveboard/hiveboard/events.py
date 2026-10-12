"""Redis pub/sub on the FalkorDB server: one channel per tenant, `team_<slug>:events`, JSON `{event, payload, ts}`.

The substrate is the single publisher of memory events (the ingest pipeline and the API no longer emit their own
variants); the full schema lives in `packages/hiveboard/hiveboard/EVENTS.md`. Summary of the payloads:

episode.ingested      once per `remember_episodes` / `remember_email_episodes` call (one batch, never per episode):
                      {container_id, count, source_kind, first_episode_id, last_episode_id, t_first, t_last, tenant}
fact.created          a fact born ACTIVE (remember_fact, supersede_fact); never for facts born superseded by chain insertion:
                      {id, fact_id, kind, key, subject, predicate, object, text, speaker_id, episode_id, due_at, valid_from, tenant}
commitment.created    same payload plus commitment_id, only when kind == 'commitment'
fact.superseded       something was expired (superset of every earlier variant; consumers read any of the aliases):
                      {new_fact_id, new_id, old_fact_id, old_fact_ids, old_ids, key, subject, predicate, kind,
                       old_object, new_object, object, valid_from, due_at, episode_id, speaker_id, head_changed, tenant}
                      head_changed is True for remember_fact(supersede=True) and supersede_fact (the current belief moved)
                      and False for insert_fact_in_chain (a late import re-wired history; the head is unchanged).
commitment.updated    the fact.superseded payload plus {id, commitment_id, replaces}, only when kind == 'commitment'
task.submitted        {task_id, kind, requires, about, priority}
task.claimed          {task_id, agent_id, version, lease_until}
task.handed_off       {task_id, from, to, version, summary, subgraph_ids}
task.completed        {task_id, agent_id, artifact, version}
task.failed           {task_id, agent_id, reason, version}
task.input_required   {task_id, agent_id, question, version}
task.lease_expired    {task_id, agent_id (former owner), version, at}   (board.reap_expired)
skill.learned         {skill_id, goal, steps, learned_from}
skill.ran             {skill_id, agent_id, ok, task_id, runs, success_rate}
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import orjson
import redis.asyncio as aioredis

from .db import HiveDB
from .temporal import now_ms

EVENT_NAMES = frozenset(
    {
        "episode.ingested",
        "fact.created",
        "fact.superseded",
        "commitment.created",
        "commitment.updated",
        "task.submitted",
        "task.claimed",
        "task.handed_off",
        "task.completed",
        "task.failed",
        "task.input_required",
        "task.lease_expired",
        "skill.learned",
        "skill.ran",
    }
)

# Keys every fact.superseded payload carries (contract test target for consumers such as the Scheduler).
SUPERSEDED_PAYLOAD_KEYS = frozenset(
    {
        "new_fact_id",
        "new_id",
        "old_fact_id",
        "old_fact_ids",
        "old_ids",
        "key",
        "subject",
        "predicate",
        "kind",
        "old_object",
        "new_object",
        "object",
        "valid_from",
        "due_at",
        "episode_id",
        "speaker_id",
        "head_changed",
        "tenant",
    }
)


def channel(tenant: str) -> str:
    """`team_<slug>:events`."""
    return f"team_{tenant}:events"


def publish(db: HiveDB, tenant: str, event: str, payload: dict[str, Any]) -> None:
    """Publish one event; the message is `{"event", "payload", "ts"}` serialised with orjson."""
    message = orjson.dumps({"event": event, "payload": payload, "ts": now_ms()}, default=str)
    db.connection.publish(channel(tenant), message)


def subscribe(db: HiveDB, tenant: str, idle_timeout: float | None = None) -> Iterator[dict[str, Any]]:
    """Blocking iterator of decoded events. The SUBSCRIBE is sent before this returns, so events published
    afterwards are not missed. With `idle_timeout` (seconds) iteration stops after that long without a message."""
    pubsub = db.connection.pubsub(ignore_subscribe_messages=True)
    pubsub.subscribe(channel(tenant))
    pubsub.get_message(timeout=1.0)  # consume the subscribe confirmation: the server has registered us
    return _drain(pubsub, idle_timeout)


def _drain(pubsub, idle_timeout: float | None) -> Iterator[dict[str, Any]]:
    idle = 0.0
    try:
        while True:
            message = pubsub.get_message(timeout=1.0)
            if message is None:
                idle += 1.0
                if idle_timeout is not None and idle >= idle_timeout:
                    return
                continue
            idle = 0.0
            if message.get("type") == "message":
                yield orjson.loads(message["data"])
    finally:
        pubsub.close()


async def asubscribe(db: HiveDB, tenant: str) -> AsyncIterator[dict[str, Any]]:
    """Async generator over the same channel using redis.asyncio (its own connection to the same server)."""
    client = aioredis.Redis(host=db.host, port=db.port, username=db.admin_user, password=db.admin_password)
    pubsub = client.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(channel(tenant))
    try:
        async for message in pubsub.listen():
            if message.get("type") == "message":
                yield orjson.loads(message["data"])
    finally:
        await pubsub.aclose()
        await client.aclose()
