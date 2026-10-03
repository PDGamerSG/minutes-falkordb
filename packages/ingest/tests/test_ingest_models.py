"""Extraction models: normalisation and leniency where the model output is messy."""

from __future__ import annotations

import pytest
from ingest.dates import calendar_table, date_to_ms, is_date_predicate, looks_like_date, normalize_date
from ingest.llm_protocol import FakeLLM, LLMFormatError, parse_json_object, strip_code_fences
from ingest.models import (
    ExtractedCommitment,
    ExtractedFact,
    RawExtraction,
    SupersessionVerdict,
    canonical_entity_name,
    entity_id_for,
    fact_key,
    normalize_predicate,
)
from pydantic import ValidationError


def test_predicate_and_kind_normalisation():
    item = ExtractedFact(kind="Commitment", subject="UPI flow", predicate="Due Date", object="2026-09-24", text="t")
    assert item.kind == "commitment"
    assert item.predicate == "due_date"
    assert item.key == "upi flow|due_date"
    assert item.due_at == "2026-09-24"


def test_kind_synonyms_and_unknown():
    assert ExtractedFact(kind="action item", subject="s", predicate="p", object="o", text="t").kind == "commitment"
    with pytest.raises(ValidationError):
        ExtractedFact(kind="rumour", subject="s", predicate="p", object="o", text="t")


def test_dates_in_objects_are_normalised():
    item = ExtractedFact(kind="commitment", subject="UPI flow", predicate="due", object="24 Sep 2026", text="t")
    assert item.object == "2026-09-24" and item.due_at == "2026-09-24"
    item = ExtractedFact(kind="fact", subject="x", predicate="status", object="done", text="t", due_at="n/a")
    assert item.due_at is None


def test_object_coercion_and_confidence():
    item = ExtractedFact(subject="x", predicate="p", object=["a", "b"], text="t", confidence="0.7")
    assert item.object == "a, b" and item.confidence == 0.7
    with pytest.raises(ValidationError):
        ExtractedFact(subject="x", predicate="p", object="o", text="t", confidence=1.5)


def test_subclass_kinds():
    assert ExtractedCommitment(subject="s", predicate="p", object="o", text="t").kind == "commitment"


def test_raw_extraction_is_lenient():
    raw = RawExtraction.model_validate({"items": {"subject": "x"}, "entities": None, "noise": 1})
    assert raw.items == [{"subject": "x"}] and raw.entities == []


def test_verdict_synonyms():
    assert SupersessionVerdict(verdict="Contradicts").verdict == "contradiction"
    assert SupersessionVerdict(verdict="refines").verdict == "refinement"
    assert SupersessionVerdict(verdict="unrelated").verdict == "unrelated"
    with pytest.raises(ValidationError):
        SupersessionVerdict(verdict="maybe")


def test_entity_helpers():
    assert canonical_entity_name("  upi   flow ") == "Upi Flow"
    assert canonical_entity_name("UPI flow") == "UPI Flow"
    assert entity_id_for("UPI Flow") == "ent_upi_flow"
    assert fact_key("UPI Flow", "Due Date") == "upi flow|due_date"
    assert normalize_predicate("scope-includes!") == "scope_includes"


def test_date_helpers():
    assert looks_like_date("2026-09-24") and looks_like_date("Sep 24") and not looks_like_date("payments")
    assert normalize_date("the 24th") is None
    assert normalize_date("24 Sep 2026") == "2026-09-24"
    assert normalize_date("Sept 24", reference=__import__("datetime").date(2026, 9, 7)) == "2026-09-24"
    assert date_to_ms("2026-09-24") == 1790208000000
    assert date_to_ms("not a date") is None
    assert is_date_predicate("due") and is_date_predicate("ship_date") and is_date_predicate("status", "2026-10-01")
    assert not is_date_predicate("owner", "Priya")


def test_calendar_table_lists_the_week():
    table = calendar_table(__import__("datetime").date(2026, 9, 9))
    assert "Reference date: 2026-09-09 (Wednesday)" in table
    assert "Mon 2026-09-07" in table and "Fri 2026-09-11" in table and "Next week" in table


def test_json_helpers():
    assert strip_code_fences("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert parse_json_object("Sure! {\"a\": [1, 2]} hope this helps") == {"a": [1, 2]}
    with pytest.raises(LLMFormatError):
        parse_json_object("no json here")


def test_fake_llm_scripting_and_policy():
    llm = FakeLLM([{"verdict": "refinement"}, "plain text"])
    assert llm.complete_json("s", "u", SupersessionVerdict).verdict == "refinement"
    assert llm.complete("s", "u") == "plain text"
    with pytest.raises(LLMFormatError):
        llm.complete_json("s", "u", SupersessionVerdict)
    policy = FakeLLM(json_policy=lambda s, u, schema: {"verdict": "contradiction", "reason": u})
    assert policy.complete_json("s", "hello", SupersessionVerdict).reason == "hello"
    assert len(policy.calls) == 1
