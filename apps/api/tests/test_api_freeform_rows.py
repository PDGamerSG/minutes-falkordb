"""Free-form Cypher (findings 1.3, 2.4, 2.6): rows reach the caller and are tabulated without a model call,
chat history labels are refused, the write-keyword check ignores strings and comments, LIMIT is injected."""

from __future__ import annotations

from apps.api.agents.answer_agent import render_rows_table
from apps.api.agents.router import is_read_only_cypher, names_private_label, route, strip_literals, with_limit


def test_freeform_rows_are_returned_and_tabulated(client):
    body = client.post("/tenants/orbit/chat", json={"message": "cypher: MATCH (f:Fact {status:'active'}) RETURN f LIMIT 3"}).json()
    assert body["router"]["route"] == "freeform_ro" and body["router"]["intent"] == "freeform"
    assert isinstance(body["rows"], list) and body["rows"]
    assert all("embedding" not in r for r in body["rows"] if isinstance(r, dict))
    assert body["answer"].startswith(f"{len(body['rows'])} row(s)") and "|" in body["answer"]
    assert body["model"] == "fake"
    # non-freeform answers carry an empty rows list for a stable shape
    other = client.post("/tenants/orbit/chat", json={"message": "Who knows about the UPI flow?"}).json()
    assert other["rows"] == []


def test_chat_history_labels_are_refused(client):
    for query in ("cypher: MATCH (t:Turn) RETURN t.text", "MATCH (s:ChatSession)-[:HAS_TURN]->(t) RETURN t", "MATCH (n) WHERE n:Turn RETURN n"):
        body = client.post("/tenants/orbit/chat", json={"message": query}).json()
        assert body["router"]["route"] == "freeform_ro" and "could not run" in body["answer"] and "chat history" in body["answer"], query
    assert not names_private_label("MATCH (f:Fact) WHERE f.text CONTAINS 'Turn' RETURN f")


def test_write_keywords_inside_strings_and_comments_are_not_writes():
    assert is_read_only_cypher("MATCH (f:Fact) WHERE f.text CONTAINS 'create' RETURN f")
    assert is_read_only_cypher("MATCH (f:Fact) // SET nothing\nRETURN f")
    assert is_read_only_cypher("MATCH (`set`:Fact) RETURN `set`")
    assert not is_read_only_cypher("MATCH (f) SET f.x = 1")
    assert not is_read_only_cypher("LOAD CSV FROM 'x' AS row RETURN row")
    assert route("LOAD CSV FROM 'file:///etc/passwd' AS r RETURN r", [], []).notes.startswith("rejected")
    assert route("CREATE (n:X) RETURN n", [], []).notes.startswith("rejected")
    assert strip_literals("RETURN 'a // b' // comment") == "RETURN '' "


def test_limit_injection():
    assert with_limit("MATCH (n) RETURN n") == "MATCH (n) RETURN n LIMIT 200"
    assert with_limit("MATCH (n) RETURN n LIMIT 5") == "MATCH (n) RETURN n LIMIT 5"
    assert with_limit("MATCH (n) RETURN n ORDER BY n.id;") == "MATCH (n) RETURN n ORDER BY n.id LIMIT 200"
    assert with_limit("MATCH (f) WHERE f.text = 'LIMIT 3' RETURN f").endswith("LIMIT 200")


def test_render_rows_table_shapes():
    assert render_rows_table([]) == "The query ran and returned no rows."
    text = render_rows_table([{"name": "Priya", "role": "backend"}, {"name": "Rahul", "role": None}])
    assert text.startswith("2 row(s).") and "| name | role |" in text and "| Rahul |  |" in text
    nested = render_rows_table([{"f": {"id": "fact_1", "subject": "UPI flow", "embedding": [0.1] * 768}}])
    assert "id=fact_1" in nested and "0.1" not in nested
    assert "first 50 shown" in render_rows_table([{"v": i} for i in range(60)])
    assert render_rows_table([1, 2]).count("| value |") == 1
