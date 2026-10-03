"""Eval matching rule, precision/recall and the CLI table."""

from __future__ import annotations

import json
from datetime import date

from ingest.eval import (
    EvalResult,
    discover,
    evaluate,
    format_table,
    items_match,
    main,
    normalize_object,
    normalize_text,
    run_meeting_eval,
)
from ingest.extract import GoldExtractor
from ingest.gold import GoldFile, GoldItem


def _gold(**over):
    base = {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "speaker_id": "spk_priya", "segment_index": 1}
    return GoldItem.model_validate({**base, **over})


def test_normalisation_helpers():
    assert normalize_text("UPI-Flow!!") == "upi flow"
    assert normalize_text("scope_includes") == "scope includes"
    assert normalize_object("24 Sep 2026") == "2026-09-24"
    assert normalize_object("Sept 24", date(2026, 9, 7)) == "2026-09-24"
    assert normalize_object("Payments.") == "payments"


def test_items_match_rule():
    extracted = {"kind": "commitment", "subject": "upi flow", "predicate": "Due", "object": "24 Sep 2026", "speaker_id": "spk_priya"}
    assert items_match(extracted, _gold())
    assert not items_match({**extracted, "speaker_id": "spk_aditya"}, _gold())
    assert not items_match({**extracted, "kind": "fact"}, _gold())
    assert not items_match({**extracted, "object": "2026-09-26"}, _gold())
    assert not items_match({**extracted, "predicate": "deadline"}, _gold())


def test_evaluate_counts():
    gold = [_gold(), _gold(kind="decision", subject="Payment gateway", predicate="decided", object="Razorpay", speaker_id="spk_aditya")]
    extracted = [
        {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "speaker_id": "spk_priya"},
        {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "speaker_id": "spk_priya"},
        {"kind": "fact", "subject": "Budget", "predicate": "is", "object": "10k", "speaker_id": "spk_priya"},
    ]
    result = evaluate(extracted, gold, slug="t")
    assert (result.tp, result.fp, result.fn) == (1, 2, 1)
    assert result.precision == 1 / 3 and result.recall == 0.5
    assert result.missed[0]["subject"] == "Payment gateway"
    assert result.as_dict()["f1"] == 0.4


def test_run_meeting_eval_with_gold_extractor(tmp_path, sample_meeting, sample_gold):
    path = tmp_path / "orbit_001.json"
    path.write_text(json.dumps(sample_meeting), encoding="utf-8")
    gold = GoldFile.model_validate(sample_gold)
    result = run_meeting_eval(path, gold, GoldExtractor(gold))
    assert result.precision == 1.0 and result.recall == 1.0 and result.tp == 3
    table = format_table([result])
    assert "orbit_001" in table and "TOTAL" in table and "1.00" in table


def test_discover_pairs_by_slug_and_id(tmp_path, sample_meeting, sample_gold):
    meetings, gold_dir = tmp_path / "meetings", tmp_path / "gold"
    meetings.mkdir(), gold_dir.mkdir()
    (meetings / "orbit_001.json").write_text(json.dumps(sample_meeting), encoding="utf-8")
    (meetings / "orbit_roster.json").write_text("[]", encoding="utf-8")
    (gold_dir / "different_name.json").write_text(json.dumps(sample_gold), encoding="utf-8")
    pairs = discover(meetings, gold_dir)
    assert len(pairs) == 1 and pairs[0][0].stem == "orbit_001" and pairs[0][2] == "meeting"


def test_cli_fake_backend(tmp_path, sample_meeting, sample_gold, capsys):
    meetings, gold_dir = tmp_path / "meetings", tmp_path / "gold"
    meetings.mkdir(), gold_dir.mkdir()
    (meetings / "orbit_001.json").write_text(json.dumps(sample_meeting), encoding="utf-8")
    (gold_dir / "orbit_001.json").write_text(json.dumps(sample_gold), encoding="utf-8")
    assert main(["--meetings", str(meetings), "--gold", str(gold_dir), "--backend", "fake"]) == 0
    out = capsys.readouterr().out
    assert "TOTAL" in out and "backend=fake" in out
    assert main(["--meetings", str(tmp_path / "nothing"), "--gold", str(gold_dir)]) == 1


def test_eval_result_zero_division():
    empty = EvalResult(slug="x")
    assert empty.precision == 0.0 and empty.recall == 0.0 and empty.f1 == 0.0
