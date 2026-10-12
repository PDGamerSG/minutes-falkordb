"""In-process import jobs: ``POST .../import`` returns a job id; the pipeline runs in a worker thread.

The store is bounded (``max_jobs``, default 500): once full, the oldest finished job is evicted;
running jobs are never evicted.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from ingest.fakes import new_id

log = logging.getLogger(__name__)

JobFn = Callable[[Callable[[str, float], None]], dict[str, Any]]
_FINISHED = ("done", "failed")


class JobStore:
    """Thread-safe registry of import jobs and their progress."""

    def __init__(self, max_jobs: int = 500) -> None:
        self._jobs: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.max_jobs = max_jobs

    def _evict_locked(self) -> None:
        while len(self._jobs) > self.max_jobs:
            victim = next((jid for jid, j in self._jobs.items() if j["status"] in _FINISHED), None)
            if victim is None:
                return
            del self._jobs[victim]

    def create(self, tenant: str, kind: str, container_id: str) -> str:
        job_id = new_id("job")
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "tenant": tenant,
                "kind": kind,
                "container_id": container_id,
                "status": "queued",
                "stage": "queued",
                "progress": 0.0,
                "stats": {},
                "error": None,
                "created_at": int(time.time() * 1000),
                "updated_at": int(time.time() * 1000),
            }
            self._evict_locked()
        return job_id

    def __len__(self) -> int:
        with self._lock:
            return len(self._jobs)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def for_container(self, tenant: str, container_id: str) -> dict[str, Any] | None:
        with self._lock:
            jobs = [j for j in self._jobs.values() if j["tenant"] == tenant and j["container_id"] == container_id]
        if not jobs:
            return None
        return dict(max(jobs, key=lambda j: j["created_at"]))

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.update(fields)
                job["updated_at"] = int(time.time() * 1000)

    def run_sync(self, job_id: str, fn: JobFn) -> dict[str, Any]:
        """Execute ``fn`` now (the worker thread body), recording progress and the outcome."""
        self.update(job_id, status="running", stage="starting", progress=0.0)

        def progress(stage: str, fraction: float) -> None:
            self.update(job_id, stage=stage, progress=round(max(0.0, min(1.0, fraction)), 3))

        try:
            stats = fn(progress)
        except Exception as exc:
            log.exception("job %s failed", job_id)
            self.update(job_id, status="failed", stage="failed", error=f"{type(exc).__name__}: {exc}"[:2000])
            raise
        failed = stats.get("failed_episodes") or []
        if failed:
            self.update(
                job_id, status="failed", stage="extraction incomplete", progress=1.0, stats=stats,
                error=f"Extraction failed for {len(failed)} episode(s). Sources and successful facts were saved; retry the import to finish.",
            )
        else:
            self.update(job_id, status="done", stage="done", progress=1.0, stats=stats)
        return stats

    async def run_async(self, job_id: str, fn: JobFn) -> None:
        """Schedule the job on a thread without blocking the event loop."""
        try:
            await asyncio.to_thread(self.run_sync, job_id, fn)
        except Exception:  # noqa: BLE001 - already recorded on the job
            return
