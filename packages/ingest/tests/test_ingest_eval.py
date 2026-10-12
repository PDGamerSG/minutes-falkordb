"""Eval matching rule (strict and partial), precision/recall, rescoring and the CLI table."""

from __future__ import annotations

import json
from datetime import date

from ingest.eval import (
    EvalResult,
    discover,
    evaluate,
    evaluate_partial,
    format_partial_table,
    format_table,
    items_match,
    main,
    normalize_object,
    normalize_text,
    partial_match,
    predicates_equivalent,
    rescore_saved,
    run_meeting_eval,
    token_f1,
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
    # the pipeline's object canonicalisation applies to the gold side too
    assert normalize_object("three cards", predicate="uses_pattern") == "3 cards"
    assert normalize_object("the SQLite cache", predicate="uses_pattern") == "sqlite cache"
    assert normalize_object("done", predicate="status") == "completed"
    assert normalize_object("12/09/2026", predicate="due") == "2026-09-12"


def test_items_match_rule():
    extracted = {"kind": "commitment", "subject": "upi flow", "predicate": "Due", "object": "24 Sep 2026", "speaker_id": "spk_priya"}
    assert items_match(extracted, _gold())
    assert not items_match({**extracted, "speaker_id": "spk_aditya"}, _gold())
    assert not items_match({**extracted, "kind": "fact"}, _gold())
    assert not items_match({**extracted, "object": "2026-09-26"}, _gold())
    assert not items_match({**extracted, "predicate": "deadline"}, _gold())
    cards = {"kind": "decision", "subject": "onboarding tour", "predicate": "uses_pattern", "object": "3 cards", "speaker_id": "spk_aditya"}
    assert items_match(cards, _gold(kind="decision", subject="onboarding tour", predicate="uses_pattern", object="three cards", speaker_id="spk_aditya"))


def test_partial_match_rules():
    gold = _gold(kind="decision", subject="payments service", predicate="requires", object="audit log retained 7 years", speaker_id="spk_aditya")
    item = {"kind": "fact", "subject": "payments service", "predicate": "requires", "object": "audit log retained for seven years", "speaker_id": "spk_farah", "episode_id": "ep_1"}
    assert partial_match(item, gold, "ep_1", "orbit")  # kind and speaker may differ; object token-F1 >= 0.5
    assert not partial_match(item, gold, "ep_2", "orbit")  # another episode
    assert partial_match({**item, "predicate": "uses_pattern"}, gold, "ep_1", "orbit")  # same predicate group
    assert not partial_match({**item, "predicate": "due"}, gold, "ep_1", "orbit")
    assert not partial_match({**item, "subject": "Orbit"}, gold, "ep_1", "orbit")  # umbrella subject is not the deliverable
    assert partial_match({**item, "subject": "the payments service work"}, gold, "ep_1", "orbit")  # qualifier word snaps
    assert not partial_match({**item, "object": "no retention at all"}, gold, "ep_1", "orbit")
    # dates never get partial credit
    assert not partial_match({"subject": "UPI flow", "predicate": "due", "object": "2026-09-25", "episode_id": "ep_1"}, _gold(), "ep_1", "orbit")
    assert predicates_equivalent("decided", "status") and not predicates_equivalent("decided", "requires")
    assert token_f1("audit log retained 7 years", "audit log retained for 7 years") > 0.8 and token_f1("a", "b") == 0.0


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


def test_evaluate_partial_and_slots():
    gold = [
        _gold(segment_index=0),
        _gold(kind="decision", subject="Payment gateway", predicate="decided", object="Razorpay chosen", speaker_id="spk_aditya", segment_index=3),
    ]
    extracted = [
        {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "speaker_id": "spk_priya", "episode_id": "ep_0"},
        {"kind": "fact", "subject": "payment gateway", "predicate": "status", "object": "Razorpay", "speaker_id": "spk_rahul", "episode_id": "ep_2"},
    ]
    result = evaluate(extracted, gold, slug="t")
    assert (result.tp, result.fp, result.fn) == (1, 1, 1)
    evaluate_partial(result, extracted, gold, ["ep_0", "ep_2"], "orbit")
    assert (result.partial_tp, result.partial_fp, result.partial_fn) == (2, 0, 0)
    assert result.partial_precision == 1.0 and result.partial_recall == 1.0
    slots = result.as_dict()["partial"]["slots"]
    assert slots["subject"]["hits"] == 2 and slots["predicate"]["hits"] == 1 and slots["kind"]["hits"] == 1 and slots["speaker_id"]["hits"] == 1
    table = format_partial_table([result])
    assert "Partial credit" in table and "speaker_id" in table


def test_run_meeting_eval_with_gold_extractor(tmp_path, sample_meeting, sample_gold):
    path = tmp_path / "orbit_001.json"
    path.write_text(json.dumps(sample_meeting), encoding="utf-8")
    gold = GoldFile.model_validate(sample_gold)
    result = run_meeting_eval(path, gold, GoldExtractor(gold), partial=True)
    assert result.precision == 1.0 and result.recall == 1.0 and result.tp == 3
    assert result.partial_tp == 3 and result.calls == 3
    table = format_table([result])
    assert "orbit_001" in table and "TOTAL" in table and "1.00" in table


def test_rescore_saved_run_offline(tmp_path, sample_meeting, sample_gold):
    meetings, gold_dir = tmp_path / "meetings", tmp_path / "gold"
    meetings.mkdir(), gold_dir.mkdir()
    (meetings / "orbit_001.json").write_text(json.dumps(sample_meeting), encoding="utf-8")
    (gold_dir / "orbit_001.json").write_text(json.dumps(sample_gold), encoding="utf-8")
    saved = {
        "backend": "gemini",
        "results": [
            {
                "slug": "orbit_001",
                "matched": [{"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "speaker_id": "spk_priya", "episode_id": "ep_mtg_orbit_001_001"}],
                "spurious": [
                    # strict miss (predicate), partial hit: same episode, same subject, {decided, status}, same object
                    {"kind": "fact", "subject": "Payment gateway", "predicate": "status", "object": "Razorpay", "speaker_id": "spk_aditya", "episode_id": "ep_mtg_orbit_001_002"},
                    # was spurious under the old matcher ("three cards" vs "3 cards"); strict hit now
                    {"kind": "decision", "subject": "October release", "predicate": "scope_includes", "object": "the payments", "speaker_id": "spk_aditya", "episode_id": "ep_mtg_orbit_001_000"},
                ],
                "missed": [],
                "proposed": 3,
            }
        ],
    }
    results = rescore_saved(saved, meetings, gold_dir)
    assert len(results) == 1
    r = results[0]
    assert (r.tp, r.fp, r.fn) == (2, 1, 1)
    assert (r.partial_tp, r.partial_fp, r.partial_fn) == (3, 0, 0)
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert main(["--meetings", str(meetings), "--gold", str(gold_dir), "--rescore", str(path)]) == 0


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
    assert main(["--meetings", str(meetings), "--gold", str(gold_dir), "--backend", "fake", "--partial"]) == 0
    out = capsys.readouterr().out
    assert "TOTAL" in out and "backend=fake" in out and "Partial credit" in out
    assert main(["--meetings", str(tmp_path / "nothing"), "--gold", str(gold_dir)]) == 1


def test_eval_result_zero_division():
    empty = EvalResult(slug="x")
    assert empty.precision == 0.0 and empty.recall == 0.0 and empty.f1 == 0.0
    assert empty.partial_precision == 0.0 and empty.partial_f1 == 0.0
