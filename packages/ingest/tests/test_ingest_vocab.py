"""Extraction v2: controlled vocabulary, canonical subjects, post-processing and the v2 user prompt."""

from __future__ import annotations

import json
from datetime import date

from ingest.chunker import Episode
from ingest.eval import main
from ingest.extract import EpisodeContext, LLMExtractor, build_user_prompt_v2, make_extractor, postprocess_v2
from ingest.llm_protocol import FakeLLM
from ingest.models import EpisodeExtraction, ExtractedFact, ExtractionStats
from ingest.vocab import (
    FEWSHOT_SOURCE,
    PREDICATES,
    canonicalize_object,
    canonicalize_predicate,
    canonicalize_subject,
    render_subjects,
    tenant_of,
)

SPEAKERS = [{"id": "spk_aditya", "name": "Aditya", "role": "lead"}, {"id": "spk_priya", "name": "Priya", "role": "backend"}]


def _ctx(text: str, speaker: str = "spk_priya", **kwargs) -> EpisodeContext:
    episode = Episode(id="ep_x_001", seq=1, speaker_id=speaker, text=text, t_start=0, t_end=5000, t_occurred=1_789_000_000_000, segment_indices=[1])
    return EpisodeContext(
        episode=episode,
        container_title="Orbit standup 1",
        container_date=date(2026, 9, 14),
        speakers=SPEAKERS,
        tenant="orbit",
        **kwargs,
    )


def _fact(**kw) -> ExtractedFact:
    base = {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-25", "text": "t", "speaker": "spk_priya"}
    base.update(kw)
    return ExtractedFact.model_validate(base)


def test_closed_predicate_set_and_synonyms():
    assert set(PREDICATES) == {"due", "owner", "scope_includes", "uses_vendor", "uses_pattern", "status", "requires", "customer", "decided", "lesson"}
    assert canonicalize_predicate("Due Date") == "due"
    assert canonicalize_predicate("deadline") == "due"
    assert canonicalize_predicate("uses_vendor") == "uses_vendor"
    assert canonicalize_predicate("blocked_by") is None


def test_subject_canonicalisation_and_tenant():
    assert tenant_of("orbit_thread_002") == "orbit" and tenant_of("mtg_nimbus_001") == "nimbus"
    assert canonicalize_subject("the UPI Flow", "orbit") == "UPI flow"
    assert canonicalize_subject("Payments Service", "orbit") == "payments service"
    assert canonicalize_subject("launch posts", "quill") == "launch post"
    assert canonicalize_subject("brand new thing", "orbit") == "brand new thing"
    assert canonicalize_object("status", "Done.") == "completed"
    assert canonicalize_object("uses_vendor", "the PayU") == "PayU"
    assert "UPI flow" in render_subjects("orbit") and "events pipeline" not in render_subjects("orbit")


def test_postprocess_v2_vocabulary_kinds_and_readbacks():
    items = [
        _fact(predicate="blocked_by", object="keys"),  # outside the vocabulary: dropped
        _fact(subject="the upi flow", predicate="deadline", object="2026-09-25"),  # canonicalised
        _fact(predicate="due", object="soon", subject="cost estimate"),  # due without a date: dropped
        _fact(kind="fact", subject="offline mode spike", predicate="status", object="done"),  # completion -> commitment
        _fact(kind="decision", subject="October release", predicate="scope_includes", object="payments"),  # read-back
    ]
    extraction = EpisodeExtraction(items=items, stats=ExtractionStats(proposed=5, kept=5))
    ctx = _ctx("text", container_items=[{"subject": "October release", "predicate": "scope_includes", "object": "payments"}])
    out = postprocess_v2(extraction, ctx)
    rows = [(i.kind, i.subject, i.predicate, i.object) for i in out.items]
    assert rows == [("commitment", "UPI flow", "due", "2026-09-25"), ("commitment", "offline mode spike", "status", "completed")]
    assert out.stats.dropped == 3 and out.stats.kept == 2
    assert out.items[0].due_at == "2026-09-25"


def test_readbacks_are_kept_in_email():
    extraction = EpisodeExtraction(items=[_fact()], stats=ExtractionStats(proposed=1, kept=1))
    ctx = _ctx("text", container_items=[{"subject": "UPI flow", "predicate": "due", "object": "2026-09-25"}])
    ctx.source_kind = "email"
    assert len(postprocess_v2(extraction, ctx).items) == 1


def test_v2_user_prompt_has_entities_context_and_calendar():
    ctx = _ctx("So I need to move it to Friday.", context_before=[{"speaker": "spk_aditya", "text": "How much will the UPI flow slip?"}])
    prompt = build_user_prompt_v2(ctx)
    assert "Known entities" in prompt and "- UPI flow" in prompt
    assert "Aditya: How much will the UPI flow slip?" in prompt and "do NOT extract" in prompt
    assert "Fri 2026-09-25" in prompt and "Week +3" in prompt
    assert "Speaker: Priya (spk_priya, backend)" in prompt


def test_v2_extractor_uses_v2_prompts():
    llm = FakeLLM([{"entities": [], "items": [{"kind": "commitment", "subject": "upi flow", "predicate": "due", "object": "Friday the 25th", "text": "Priya moves it"}]}])
    extractor = make_extractor(llm, "v2")
    assert isinstance(extractor, LLMExtractor) and extractor.prompt_name == "extract_v2"
    assert make_extractor(llm).prompt_name.startswith("extract_v") and make_extractor(llm).version >= "v5"
    result = extractor.extract(_ctx("So I need to move it to Friday the 25th."))
    assert [(i.subject, i.object) for i in result.items] == [("UPI flow", "2026-09-25")]
    assert "closed set" not in llm.calls[0]["user"] and "Known entities" in llm.calls[0]["user"]
    assert "predicate (exactly one of)" in llm.calls[0]["system"]


def test_eval_cli_files_and_exclude(tmp_path, sample_meeting, sample_gold, capsys):
    meetings, gold_dir = tmp_path / "meetings", tmp_path / "gold"
    meetings.mkdir(), gold_dir.mkdir()
    for slug in ("orbit_001", "orbit_009"):
        (meetings / f"{slug}.json").write_text(json.dumps(sample_meeting), encoding="utf-8")
        (gold_dir / f"{slug}.json").write_text(json.dumps(sample_gold), encoding="utf-8")
    assert main(["--meetings", str(meetings), "--gold", str(gold_dir), "--backend", "fake", "--files", "orbit_009"]) == 0
    out = capsys.readouterr().out
    assert "orbit_009" in out and "orbit_001 " not in out
    assert main(["--meetings", str(meetings), "--gold", str(gold_dir), "--backend", "fake", "--exclude", "orbit_009,orbit_001"]) == 1
    assert FEWSHOT_SOURCE == "orbit_001"


def test_v3_schema_rules_lead_and_commitment_shape():
    items = [
        _fact(kind="decision", subject="nightly events job (run time)", predicate="decided", object="03:00 IST"),  # member decision -> fact
        _fact(kind="commitment", subject="one-time UPI path", predicate="status", object="active"),  # not a completion: dropped
        _fact(kind="commitment", subject="UPI flow", predicate="uses_pattern", object="interface"),  # commitment without date: dropped
        _fact(kind="commitment", subject="PayU sandbox integration", predicate="due", object="2026-10-01"),  # fuzzy subject snap
    ]
    ctx = _ctx("text", speaker="spk_priya")
    ctx.tenant = "orbit"
    out = postprocess_v2(EpisodeExtraction(items=items, stats=ExtractionStats(proposed=4, kept=4)), ctx, "v3")
    rows = [(i.kind, i.subject, i.predicate, i.object) for i in out.items]
    assert rows == [("fact", "nightly events job", "decided", "03:00 IST"), ("commitment", "PayU integration", "due", "2026-10-01")]
    # the lead keeps the decision kind; the read-back filter is kind-aware from v3 on
    lead_ctx = _ctx("text", speaker="spk_aditya", container_items=[{"kind": "fact", "subject": "nightly events job", "predicate": "decided", "object": "03:00 IST"}])
    lead = postprocess_v2(EpisodeExtraction(items=[_fact(kind="decision", subject="nightly events job", predicate="decided", object="03:00 IST")], stats=ExtractionStats(proposed=1, kept=1)), lead_ctx, "v3")
    assert [(i.kind, i.subject) for i in lead.items] == [("decision", "nightly events job")]


def test_trivial_utterances_skip_the_model():
    from ingest.extract import is_trivial_utterance

    assert is_trivial_utterance(_ctx("Got it, already stubbed."))
    assert not is_trivial_utterance(_ctx("Done: the spec."))
    assert not is_trivial_utterance(_ctx("By the 25th."))
    llm = FakeLLM([])
    assert make_extractor(llm).extract(_ctx("Bye.")).items == [] and llm.calls == []


def test_v4_weekday_correction_numbers_and_rationale():
    from ingest.extract import correct_weekday

    ctx = _ctx("I'll have the navigation accessibility review done for Wednesday's design review.")
    ctx.episode.t_occurred = 1_789_363_800_000  # 2026-09-14 04:30 UTC, a Monday
    assert correct_weekday("2026-09-17", ctx) == "2026-09-16"
    ctx.episode.text = "By Friday the 25th."
    assert correct_weekday("2026-09-25", ctx) == "2026-09-25"
    assert canonicalize_object("requires", "audit log retained seven years", numbers=True) == "audit log retained 7 years"
    assert canonicalize_object("status", "sent to finance", numbers=True) == "completed"
    items = [_fact(kind="fact", subject="nightly events job", predicate="decided", object="because of the backup window")]
    out = postprocess_v2(EpisodeExtraction(items=items, stats=ExtractionStats(proposed=1, kept=1)), _ctx("text"), "v4")
    assert out.items == []
    asked = _ctx("text", context_before=[{"speaker": "spk_aditya", "text": "Why did we choose the side drawer again?"}])
    assert len(postprocess_v2(EpisodeExtraction(items=items, stats=ExtractionStats(proposed=1, kept=1)), asked, "v4").items) == 1


def test_v5_readbacks_and_untracked_completions():
    from ingest.extract import is_readback

    assert is_readback(_ctx("Let me read it back. Scope: payments, offline, onboarding."))
    assert not is_readback(_ctx("Decision: the payments service uses PayU."))
    llm = FakeLLM([])
    assert make_extractor(llm, "v5").extract(_ctx("Let me read it back. Dates: UPI flow the 28th, Priya.")).items == []
    assert llm.calls == []
    items = [
        _fact(subject="payment branch", predicate="status", object="completed"),
        _fact(subject="offline mode spike", predicate="status", object="completed"),
    ]
    out = postprocess_v2(EpisodeExtraction(items=items, stats=ExtractionStats(proposed=2, kept=2)), _ctx("text"), "v5")
    assert [i.subject for i in out.items] == ["offline mode spike"]


def test_predicate_names_used_as_kind_are_mapped():
    item = ExtractedFact.model_validate({"kind": "lesson", "subject": "Orbit", "predicate": "lesson", "object": "record the rationale", "text": "t"})
    assert item.kind == "decision"
