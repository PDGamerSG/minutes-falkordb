import hiveboard as hb
import pytest
from hiveboard.queries import cypher_path, list_queries, load_cypher
from redis.exceptions import ResponseError

REQUIRED = [
    "10_ingest_episode",
    "11_ingest_fact",
    "12_supersede_fact",
    "20_claim_task",
    "21_handoff_task",
    "22_complete_task",
    "30_recall_hybrid",
    "31_belief_at_time",
    "32_why_path",
    "40_skill_retrieve",
    "41_skill_outcome",
    "50_who_knows",
    "51_open_commitments",
    "52_contradictions",
    "60_pagerank_skills",
    "61_wcc_entities",
]


def test_schema_is_idempotent(db, tenant):
    first = hb.ensure_schema(db, tenant)  # the fixture already ran it once
    second = hb.ensure_schema(db, tenant)
    assert first["indexes_created"] == 0 and first["constraints_created"] == 0
    assert second == first
    assert first["indexes_existing"] >= 35 and first["constraints_existing"] == len(
        hb.schema.UNIQUE_ID_LABELS
    )
    indexes = (
        db.graph(tenant)
        .query("CALL db.indexes() YIELD label, properties RETURN label, properties")
        .result_set
    )
    labels = {row[0] for row in indexes}
    assert {"Person", "Episode", "Fact", "Task", "Skill", "EmailThread"} <= labels


def test_unique_constraint_rejects_duplicate_ids(db, tenant):
    g = db.graph(tenant)
    g.query("CREATE (:Person {id: 'dup', name: 'A'})")
    with pytest.raises(ResponseError, match="unique constraint"):
        g.query("CREATE (:Person {id: 'dup', name: 'B'})")
    assert g.query("MATCH (p:Person {id: 'dup'}) RETURN count(p)").result_set[0][0] == 1


def test_udf_loaded_and_scores_as_specified(db):
    assert hb.schema.load_udfs is not None
    g = db.commons()
    row = g.query(
        "RETURN hive.score(0, 0.9, 0.2, 86400000), hive.score($now, 1.0, 0.0, $now), hive.score(0, 0.0, 1.5, 0)",
        {"now": hb.now_ms()},
    ).result_set[0]
    assert row[0] == pytest.approx(2.718281828 ** (-1 / 30) * 0.9 * 0.8, rel=1e-6)
    assert row[1] == pytest.approx(1.0)
    assert row[2] == 0.0  # similarity clamps at 0 for distance > 1


def test_every_required_cypher_file_exists_with_header_comment():
    names = list_queries()
    for required in REQUIRED:
        assert required in names, required
    for name in names:
        text = cypher_path(name).read_text(encoding="utf-8")
        assert text.startswith("//"), f"{name} must start with a comment line"
        if name != "00_schema":
            assert load_cypher(name).strip(), name
