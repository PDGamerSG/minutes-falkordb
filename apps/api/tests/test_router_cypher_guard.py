"""Free-form Cypher guard for the FalkorDB 6.0.1 bug: MATCH ... WHERE ... MATCH drops the first WHERE."""

from __future__ import annotations

from apps.api.agents.router import guard_match_where_match, route


def test_where_followed_by_match_gets_with_star():
    query = "MATCH (f:Fact) WHERE f.status = 'active' MATCH (f)-[:ABOUT]->(e:Entity) RETURN f.id, e.name"
    guarded, rewritten = guard_match_where_match(query)
    assert rewritten
    assert guarded == "MATCH (f:Fact) WHERE f.status = 'active' WITH * MATCH (f)-[:ABOUT]->(e:Entity) RETURN f.id, e.name"


def test_every_offending_match_is_guarded_and_case_is_ignored():
    query = "match (a:Person) where a.name = 'Priya' match (a)<-[:SPOKEN_BY]-(ep) where ep.seq > 2 match (ep)<-[:DERIVED_FROM]-(f) return f"
    guarded, rewritten = guard_match_where_match(query)
    assert rewritten and guarded.count("WITH * match") == 2


def test_safe_queries_are_untouched():
    safe = [
        "MATCH (n) RETURN count(n)",
        "MATCH (f:Fact) WHERE f.status = 'active' OPTIONAL MATCH (f)-[:ABOUT]->(e) RETURN f, e",
        "MATCH (f:Fact) WHERE f.status = 'active' WITH f MATCH (f)-[:ABOUT]->(e) RETURN f, e",
        "MATCH (f:Fact) MATCH (f)-[:ABOUT]->(e) WHERE e.name = 'UPI Flow' RETURN f",
        "MATCH (f:Fact) WHERE f.text = 'where we MATCH things' RETURN f",
        "MATCH (f:Fact) WHERE size([x IN f.tags WHERE x = 'a']) > 0 RETURN f.match",
        "MATCH (f:Fact) WHERE exists { MATCH (f)-[:ABOUT]->(:Entity) } RETURN f",
    ]
    for query in safe:
        assert guard_match_where_match(query) == (query, False), query


def test_router_applies_the_guard_to_free_form_cypher():
    decision = route("cypher: MATCH (f:Fact) WHERE f.status = 'active' MATCH (f)-[:STATED_BY]->(p) RETURN p.name", [], [])
    assert decision.route == "freeform_ro"
    assert "WITH * MATCH (f)-[:STATED_BY]" in decision.cypher and decision.notes.startswith("rewritten")
    plain = route("cypher: MATCH (n) RETURN count(n)", [], [])
    assert plain.cypher == "MATCH (n) RETURN count(n)" and not plain.notes
