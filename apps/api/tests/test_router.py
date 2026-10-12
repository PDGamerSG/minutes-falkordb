"""Router unit tests: entity counting, intent classification, route selection."""

from __future__ import annotations

from apps.api.agents.router import find_entities, is_read_only_cypher, route

ENTITIES = [
    {"id": "ent_upi_flow", "name": "UPI Flow", "type": "feature"},
    {"id": "ent_payu_integration", "name": "PayU Integration", "type": "system"},
    {"id": "ent_payment_gateway", "name": "Payment Gateway", "type": "system"},
]
PERSONS = [{"id": "spk_priya", "name": "Priya"}, {"id": "spk_aditya", "name": "Aditya"}]


def test_find_entities_prefers_longest_match():
    hits, people = find_entities("What about the PayU integration and Priya?", ENTITIES, PERSONS)
    assert [h["id"] for h in hits] == ["ent_payu_integration"]
    assert [p["id"] for p in people] == ["spk_priya"]


def test_why_routes_to_template():
    decision = route("Why did we choose the side drawer?", ENTITIES, PERSONS)
    assert decision.intent == "why" and decision.route == "template" and decision.template == "32_why_path"


def test_entity_status_routes_to_graph():
    decision = route("What is the status of the UPI flow?", ENTITIES, PERSONS)
    assert decision.route == "graph" and decision.entity_ids == ["ent_upi_flow"] and decision.intent == "status"
    decision = route("What did we decide about the payment gateway?", ENTITIES, PERSONS)
    assert decision.route == "graph" and decision.intent == "decisions"


def test_who_knows_and_commitments():
    assert route("Who knows about the UPI flow?", ENTITIES, PERSONS).template == "50_who_knows"
    who = route("Who knows the most here?", ENTITIES, PERSONS)
    assert who.route == "vector"  # no entity to anchor the template
    decision = route("What is Priya working on?", ENTITIES, PERSONS)
    assert decision.template == "51_open_commitments" and decision.person_ids == ["spk_priya"]
    assert route("show open commitments", ENTITIES, PERSONS).template == "51_open_commitments"


def test_contradictions_stale_and_belief():
    assert route("Any contradictions in our facts?", ENTITIES, PERSONS).template == "52_contradictions"
    assert route("Which decisions are stale?", ENTITIES, PERSONS).template == "53_stale_decisions"
    belief = route("What did we believe about the UPI flow on 15 Sep 2026?", ENTITIES, PERSONS)
    assert belief.template == "31_belief_at_time" and belief.at_ms == 1789516799000
    assert route("What did we believe about the UPI flow back then?", ENTITIES, PERSONS).route == "graph"


def test_vector_fallback_and_freeform():
    assert route("tell me something interesting", ENTITIES, PERSONS).route == "vector"
    ok = route("cypher: MATCH (n) RETURN count(n)", ENTITIES, PERSONS)
    assert ok.route == "freeform_ro" and ok.cypher == "MATCH (n) RETURN count(n) LIMIT 200" and ok.notes == "LIMIT 200 added"
    capped = route("cypher: MATCH (n) RETURN n LIMIT 5", ENTITIES, PERSONS)
    assert capped.cypher == "MATCH (n) RETURN n LIMIT 5" and not capped.notes
    bad = route("MATCH (n) DETACH DELETE n", ENTITIES, PERSONS)
    assert bad.route == "freeform_ro" and bad.notes.startswith("rejected")


def test_read_only_guard():
    assert is_read_only_cypher("MATCH (f:Fact) RETURN f")
    assert not is_read_only_cypher("MATCH (f) SET f.x = 1")
    assert not is_read_only_cypher("MERGE (n:X)")
    assert not is_read_only_cypher("CALL db.idx.create('x')")
