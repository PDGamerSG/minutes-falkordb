"""Load harness: N simulated agents across M tenant graphs, 80 % reads (recall / active_facts / list_tasks) and
20 % writes (remember_fact / claim / complete), latency percentiles per class, plus a CAS contention test where
K agents race for one task per tenant and exactly one must win. Writes `docs/bench/<run_id>.json`.

    uv run --package hiveboard python -m bench.harness --agents 20 --tenants 4 --duration 20 --target local
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import platform
import random
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import hiveboard as hb
from hiveboard.embed import fake_embedding
from hiveboard.queries import _PKG_DIR

READ_OPS = ("recall", "active_facts", "list_tasks")
WRITE_OPS = ("remember_fact", "claim", "complete")
QUERIES = (
    "when is the UPI flow due",
    "who owns the payments gateway",
    "what did we decide about onboarding",
    "status of the android release",
    "customer escalation from Acme",
    "standup summary",
)
SUBJECTS = ("UPI flow", "payments gateway", "onboarding", "android release", "Acme escalation", "standup")
PREDICATES = ("due", "owner", "status", "priority")
OBJECTS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Priya",
    "Aditya",
    "Rahul",
    "high",
    "blocked",
)


def percentile(values: list[float], p: float) -> float | None:
    """Nearest-rank percentile in ms, rounded to 3 decimals; None when there are no samples."""
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(p / 100 * len(ordered)) - 1))
    return round(ordered[idx], 3)


@dataclass
class Stats:
    reads: list[float] = field(default_factory=list)
    writes: list[float] = field(default_factory=list)
    by_op: dict[str, list[float]] = field(default_factory=dict)
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, op: str, is_read: bool, ms: float) -> None:
        with self.lock:
            (self.reads if is_read else self.writes).append(ms)
            self.by_op.setdefault(op, []).append(ms)

    def error(self, exc: Exception) -> None:
        with self.lock:
            self.errors += 1
            if len(self.error_samples) < 10:
                self.error_samples.append(f"{type(exc).__name__}: {str(exc)[:160]}")


@dataclass
class TenantSeed:
    tenant: str
    people: list[str]
    entities: list[str]
    agents: list[str]
    submitted: deque = field(default_factory=deque)
    working: deque = field(default_factory=deque)
    lock: threading.Lock = field(default_factory=threading.Lock)


def seed_tenant(db: hb.HiveDB, tenant: str, rng: random.Random) -> TenantSeed:
    """Schema + a small realistic graph: people, one meeting with episodes, entities, facts, agents and open tasks."""
    hb.ensure_schema(db, tenant)
    people = hb.remember_people(
        db, tenant, [{"name": n, "role": "eng"} for n in ("Priya", "Aditya", "Rahul", "Meera")]
    )
    meeting = hb.remember_meeting(db, tenant, {"title": "Kickoff", "started_at": hb.now_ms() - 7 * 86400000})
    base = hb.now_ms() - 7 * 86400000
    episodes = [
        {
            "id": f"ep_{tenant}_{i}",
            "seq": i,
            "speaker_id": people[i % 4],
            "text": f"{SUBJECTS[i % 6]} {PREDICATES[i % 4]} {OBJECTS[i % 10]}",
            "t_start": i * 30000,
            "t_end": i * 30000 + 25000,
            "t_occurred": base + i * 30000,
            "embedding": fake_embedding(f"{SUBJECTS[i % 6]} {PREDICATES[i % 4]} {OBJECTS[i % 10]}"),
        }
        for i in range(12)
    ]
    hb.remember_episodes(db, tenant, meeting, episodes)
    ids = hb.upsert_entities(
        db, tenant, [{"name": s, "type": "topic", "embedding": fake_embedding(s)} for s in SUBJECTS]
    )
    entities = list(ids.values())
    for i, ep in enumerate(episodes):
        hb.link_mentions(db, tenant, ep["id"], [entities[i % 6], entities[(i + 1) % 6]])
    for i in range(30):
        subject, predicate = SUBJECTS[i % 6], PREDICATES[(i // 6) % 4]
        hb.remember_fact(
            db,
            tenant,
            {
                "subject": subject,
                "predicate": predicate,
                "object": OBJECTS[rng.randrange(10)],
                "text": f"{subject} {predicate} {OBJECTS[i % 10]}",
                "confidence": 0.6 + 0.4 * rng.random(),
                "speaker_id": people[i % 4],
                "episode_id": episodes[i % 12]["id"],
                "entity_ids": [ids[subject]],
                "kind": ("fact", "decision", "commitment")[i % 3],
                "embedding": fake_embedding(f"{subject} {predicate}"),
            },
            supersede=True,
        )
    agents = [f"agt_{tenant}_{i}" for i in range(3)]
    for i, agent in enumerate(agents):
        hb.register_agent(db, tenant, agent, f"Agent {i}", ["followup", "schedule", "answer"], "bench")
    seed = TenantSeed(tenant, people, entities, agents)
    for _ in range(10):
        seed.submitted.append(hb.submit_task(db, tenant, "followup", {"n": 1}, ["followup"]))
    return seed


def run_op(db: hb.HiveDB, seed: TenantSeed, op: str, agent: str, rng: random.Random) -> None:
    """One operation of the mix; each branch is exactly one hiveboard call."""
    tenant = seed.tenant
    if op == "recall":
        hb.recall(db, tenant, fake_embedding(rng.choice(QUERIES)), k=8)
    elif op == "active_facts":
        hb.active_facts(db, tenant, entity_id=rng.choice(seed.entities))
    elif op == "list_tasks":
        hb.list_tasks(db, tenant, status="submitted", limit=20)
    elif op == "remember_fact":
        subject = rng.choice(SUBJECTS)
        hb.remember_fact(
            db,
            tenant,
            {
                "subject": subject,
                "predicate": rng.choice(PREDICATES),
                "object": rng.choice(OBJECTS),
                "text": f"{subject} update by {agent}",
                "confidence": 0.9,
                "speaker_id": rng.choice(seed.people),
                "episode_id": f"ep_{tenant}_{rng.randrange(12)}",
                "entity_ids": [rng.choice(seed.entities)],
                "kind": "fact",
                "embedding": fake_embedding(f"{subject} update"),
            },
            supersede=True,
        )
    elif op == "claim":
        with seed.lock:
            task_id = seed.submitted.popleft() if seed.submitted else None
        if task_id is None:
            seed.submitted.append(hb.submit_task(db, tenant, "followup", {"n": 2}, ["followup"]))
            return
        if hb.claim(db, tenant, task_id, agent, 0) is not None:
            with seed.lock:
                seed.working.append((task_id, agent))
    elif op == "complete":
        with seed.lock:
            item = seed.working.popleft() if seed.working else None
        if item is None:
            seed.submitted.append(hb.submit_task(db, tenant, "followup", {"n": 3}, ["followup"]))
            return
        hb.complete(db, tenant, item[0], item[1], {"kind": "note", "text": "done"})
    else:
        raise ValueError(op)


async def agent_loop(
    db: hb.HiveDB,
    index: int,
    seeds: list[TenantSeed],
    stats: Stats,
    deadline: float,
    read_ratio: float,
    seed_value: int,
) -> int:
    """One simulated agent: pick a tenant, pick an op by the read ratio, time it, until the deadline."""
    rng = random.Random(seed_value)
    agent = f"agt_{seeds[index % len(seeds)].tenant}_{index % 3}"
    ops = 0
    while time.perf_counter() < deadline:
        seed = seeds[rng.randrange(len(seeds))]
        is_read = rng.random() < read_ratio
        op = rng.choice(READ_OPS if is_read else WRITE_OPS)
        t0 = time.perf_counter()
        try:
            await asyncio.to_thread(run_op, db, seed, op, agent, rng)
            stats.record(op, is_read, (time.perf_counter() - t0) * 1000)
            ops += 1
        except Exception as exc:  # noqa: BLE001 - the harness keeps going and reports the error count
            stats.error(exc)
    return ops


async def cas_contention(db: hb.HiveDB, seeds: list[TenantSeed], racers: int) -> dict:
    """K agents race for one fresh task per tenant; exactly one claim must return a version."""
    attempts = winners = 0
    per_tenant = []
    for seed in seeds:
        task_id = hb.submit_task(db, seed.tenant, "race", {}, ["followup"])
        results = await asyncio.gather(
            *[
                asyncio.to_thread(hb.claim, db, seed.tenant, task_id, seed.agents[i % 3], 0)
                for i in range(racers)
            ]
        )
        won = sum(1 for r in results if r is not None)
        attempts += racers
        winners += won
        per_tenant.append({"tenant": seed.tenant, "task_id": task_id, "attempts": racers, "winners": won})
        if won != 1:
            raise AssertionError(f"CAS violated on {seed.tenant}: {won} winners out of {racers}")
    return {"attempts": attempts, "winners": winners, "losers": attempts - winners, "per_tenant": per_tenant}


def repo_root() -> Path:
    return _PKG_DIR.parents[2]


async def run(args: argparse.Namespace) -> dict:
    """Seed, run the mixed load, run the CAS test, clean up, return the result document."""
    db = hb.HiveDB(args.url)
    if not db.ping():
        raise SystemExit(f"FalkorDB not reachable at {args.url}")
    hb.load_udfs(db)
    engine = args.engine or db.server_version()
    run_id = f"{engine}-{args.target}-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}"
    asyncio.get_running_loop().set_default_executor(
        ThreadPoolExecutor(max_workers=args.agents + args.cas_agents + 4)
    )
    rng = random.Random(args.seed)
    tenants = [f"bench{i}" for i in range(args.tenants)]
    for tenant in tenants:
        if db.graph_exists(db.graph_name(tenant)):
            db.graph(tenant).delete()
    t_seed = time.perf_counter()
    seeds = [await asyncio.to_thread(seed_tenant, db, tenant, rng) for tenant in tenants]
    seed_s = time.perf_counter() - t_seed

    stats = Stats()
    deadline = time.perf_counter() + args.duration
    t_load = time.perf_counter()
    ops = await asyncio.gather(
        *[
            agent_loop(db, i, seeds, stats, deadline, args.read_ratio, args.seed + i)
            for i in range(args.agents)
        ]
    )
    elapsed = time.perf_counter() - t_load
    cas = await cas_contention(db, seeds, args.cas_agents)
    usage = {s.tenant: db.usage(s.tenant)["total_mb"] for s in seeds}

    result = {
        "run_id": run_id,
        "ts": hb.now_ms(),
        "engine": engine,
        "target": args.target,
        "agents": args.agents,
        "tenants": args.tenants,
        "duration_s": round(elapsed, 2),
        "read_p50": percentile(stats.reads, 50),
        "read_p95": percentile(stats.reads, 95),
        "read_p99": percentile(stats.reads, 99),
        "write_p50": percentile(stats.writes, 50),
        "write_p95": percentile(stats.writes, 95),
        "write_p99": percentile(stats.writes, 99),
        "errors": stats.errors,
        "cas": {k: cas[k] for k in ("attempts", "winners", "losers")},
        "cas_per_tenant": cas["per_tenant"],
        "ops": {
            "total": int(sum(ops)),
            "reads": len(stats.reads),
            "writes": len(stats.writes),
            "per_second": round(sum(ops) / elapsed, 1) if elapsed else None,
            "read_ratio": args.read_ratio,
        },
        "per_op": {
            op: {"n": len(v), "p50": percentile(v, 50), "p95": percentile(v, 95), "p99": percentile(v, 99)}
            for op, v in sorted(stats.by_op.items())
        },
        "error_samples": stats.error_samples,
        "usage_mb": usage,
        "seed_s": round(seed_s, 2),
        "latency_unit": "ms",
        "client": {
            "python": platform.python_version(),
            "os": platform.platform(),
            "mode": "asyncio.to_thread over falkordb-py sync client",
        },
    }
    if not args.keep:
        for seed in seeds:
            db.graph(seed.tenant).delete()
    db.close()
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--agents", type=int, default=20, help="simulated agents (concurrent loops)")
    parser.add_argument("--tenants", type=int, default=4, help="tenant graphs team_bench0..N-1")
    parser.add_argument("--duration", type=float, default=20.0, help="seconds of mixed load")
    parser.add_argument("--engine", default=None, help="engine label, default: detected FalkorDB version")
    parser.add_argument("--target", default="local", help="target label: local | railway | ...")
    parser.add_argument("--url", default=None, help="falkor://host:port (default $FALKORDB_URL or localhost)")
    parser.add_argument(
        "--cas-agents", type=int, default=25, help="racers per tenant in the CAS contention test"
    )
    parser.add_argument("--read-ratio", type=float, default=0.8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--keep", action="store_true", help="keep the bench graphs after the run")
    parser.add_argument("--out", default=None, help="output JSON path (default docs/bench/<run_id>.json)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = asyncio.run(run(args))
    out = Path(args.out) if args.out else repo_root() / "docs" / "bench" / f"{result['run_id']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    summary = {
        k: result[k]
        for k in (
            "run_id",
            "engine",
            "agents",
            "tenants",
            "duration_s",
            "read_p50",
            "read_p95",
            "read_p99",
            "write_p50",
            "write_p95",
            "write_p99",
            "errors",
            "cas",
        )
    }
    summary["ops"] = result["ops"]
    print(json.dumps(summary, indent=2))
    print(f"written {out}")


if __name__ == "__main__":
    main()
