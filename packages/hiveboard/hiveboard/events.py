"""Redis pub/sub on the FalkorDB server: one channel per tenant, `team_<slug>:events`, JSON `{event, payload, ts}`."""

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
        "skill.learned",
        "skill.ran",
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
