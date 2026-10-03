"""In-process import jobs: ``POST .../import`` returns a job id; the pipeline runs in a worker thread."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from ingest.fakes import new_id

log = logging.getLogger(__name__)

JobFn = Callable[[Callable[[str, float], None]], dict[str, Any]]


class JobStore:
    """Thread-safe registry of import jobs and their progress."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

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
        return job_id

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
        self.update(job_id, status="done", stage="done", progress=1.0, stats=stats)
        return stats

    async def run_async(self, job_id: str, fn: JobFn) -> None:
        """Schedule the job on a thread without blocking the event loop."""
        try:
            await asyncio.to_thread(self.run_sync, job_id, fn)
        except Exception:  # noqa: BLE001 - already recorded on the job
            return
