"""Import failures must not appear as successfully ingested company knowledge."""

from apps.api.jobs import JobStore


def test_extraction_failure_preserves_stats_and_marks_import_failed():
    jobs = JobStore()
    job_id = jobs.create("orbit", "meeting", "mtg_partial")
    stats = {"episodes": 3, "facts": 1, "failed_episodes": ["ep_failed"]}
    jobs.run_sync(job_id, lambda progress: stats)
    job = jobs.get(job_id)
    assert job["status"] == "failed"
    assert job["stats"] == stats
    assert "1" in job["error"] and "extract" in job["error"].lower()


def test_validation_drops_do_not_count_as_extraction_outages():
    jobs = JobStore()
    job_id = jobs.create("orbit", "meeting", "mtg_valid")
    jobs.run_sync(job_id, lambda progress: {"episodes": 2, "dropped": 1, "failed_episodes": []})
    assert jobs.get(job_id)["status"] == "done"
