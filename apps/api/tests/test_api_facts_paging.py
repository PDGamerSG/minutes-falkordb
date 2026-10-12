"""GET /facts paging (finding 1.2): limit + opaque cursor, X-Next-Cursor / X-Truncated headers, array body kept;
internal list_facts pages through everything (RealHive loop tested with a stubbed _fact_rows)."""

from __future__ import annotations

from typing import Any

from apps.api.hive_adapter import FACT_PAGE, RealHive, decode_cursor, encode_cursor


def _page(client, **params):
    response = client.get("/tenants/orbit/facts", params={"status": "all", **params})
    assert response.status_code == 200
    return response.json(), response.headers.get("x-next-cursor"), response.headers.get("x-truncated")


def test_pages_cover_every_fact_in_order(client):
    full, cursor, truncated = _page(client, limit=1000)
    assert cursor is None and truncated == "false" and len(full) >= 9
    assert [f["id"] for f in full] == [f["id"] for f in sorted(full, key=lambda f: (f["valid_from"] or 0, f["id"]))]
    seen: list[str] = []
    cursor = None
    pages = 0
    while True:
        rows, cursor, truncated = _page(client, limit=4, **({"cursor": cursor} if cursor else {}))
        pages += 1
        seen.extend(f["id"] for f in rows)
        assert len(rows) <= 4
        if truncated == "false":
            assert cursor is None
            break
        assert cursor and len(rows) == 4
    assert pages >= 3 and seen == [f["id"] for f in full]


def test_default_limit_and_bad_cursor(client):
    rows, cursor, truncated = _page(client)
    assert len(rows) <= 200 and truncated == "false"
    bad = client.get("/tenants/orbit/facts", params={"cursor": "!!not-a-cursor"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "bad_cursor"
    assert client.get("/tenants/orbit/facts", params={"limit": 5000}).status_code == 422


def test_cursor_round_trip():
    cursor = encode_cursor(1790000000000, "fact_abc|weird")
    assert "=" not in cursor and decode_cursor(cursor) == (1790000000000, "fact_abc|weird")
    assert decode_cursor(None) is None and decode_cursor(encode_cursor(None, "x")) == (0, "x")


def test_realhive_list_facts_loops_over_pages():
    """1,234 synthetic facts behind a paging _fact_rows: list_facts returns all, page_facts honours the cursor."""
    universe = [{"id": f"fact_{i:05d}", "valid_from": 1_000 + (i // 3), "status": "active"} for i in range(1234)]
    calls: list[dict[str, Any]] = []

    def fake_rows(self, tenant, **params):
        calls.append(params)
        after = (params.get("cursor_vf"), params.get("cursor_id"))
        rows = sorted(universe, key=lambda f: (f["valid_from"], f["id"]))
        if after[0] is not None:
            rows = [f for f in rows if (f["valid_from"], f["id"]) > after]
        return rows[: params["limit"]]

    hive = RealHive.__new__(RealHive)
    hive._fact_rows = fake_rows.__get__(hive, RealHive)  # type: ignore[attr-defined]
    everything = hive.list_facts("orbit", status="all")
    assert [f["id"] for f in everything] == [f["id"] for f in sorted(universe, key=lambda f: (f["valid_from"], f["id"]))]
    assert len(calls) == 3 and calls[0]["limit"] == FACT_PAGE + 1
    page, cursor = hive.page_facts("orbit", status="all", limit=10)
    assert len(page) == 10 and cursor is not None
    page2, _ = hive.page_facts("orbit", status="all", limit=10, cursor=cursor)
    assert page2[0]["id"] == everything[10]["id"]
