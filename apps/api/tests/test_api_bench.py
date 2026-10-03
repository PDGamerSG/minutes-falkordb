"""Bench routes: results from the results directory plus an in-process run."""

from __future__ import annotations

import time


def test_bench_results_reads_directory(client):
    rows = client.get("/bench/results").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == "bench_demo" and row["engine"] == "6.0.1" and row["target"] == "local"
    assert row["agents"] == 200 and row["tenants"] == 20 and row["duration_s"] == 300
    assert row["read_p99"] == 9.1 and row["write_p50"] == 2.0 and row["errors"] == 0
    assert row["cas"] == {"attempts": 50, "winners": 1, "losers": 49}
    assert set(row) >= {"run_id", "ts", "engine", "target", "agents", "tenants", "duration_s", "read_p50", "read_p95", "read_p99", "write_p50", "write_p95", "write_p99", "errors", "cas"}


def test_bench_run_in_process(client):
    response = client.post("/bench/run", json={"agents": 4, "tenants": 1, "duration_s": 0.5})
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    deadline = time.time() + 10
    rows = []
    while time.time() < deadline:
        rows = [r for r in client.get("/bench/results").json() if r["run_id"] == run_id]
        if rows:
            break
        time.sleep(0.1)
    assert rows, "in-process bench run did not report"
    row = rows[0]
    assert row["agents"] == 4 and row["tenants"] == 1 and row["engine"] == "fake"
    assert row["reads"] > 0 and row["writes"] > 0 and row["errors"] == 0
    assert row["cas"]["winners"] == 1 and row["cas"]["losers"] == row["cas"]["attempts"] - 1
    assert row["read_p50"] <= row["read_p99"]
