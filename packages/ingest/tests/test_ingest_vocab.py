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
    known_spelling,
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


def test_fuzzy_snapping_needs_a_qualifier_word_or_a_two_word_name():
    # a one-word known name plus a content word is a different subject
    assert canonicalize_subject("Orbit launch", "orbit", fuzzy=True) == "Orbit launch"
    assert canonicalize_subject("Orbit retro", "orbit", fuzzy=True) == "Orbit retro"
    assert canonicalize_subject("the Orbit roadmap", "orbit", fuzzy=True) == "Orbit roadmap"
    # qualifier words never make a new subject
    assert canonicalize_subject("the UPI flow work", "orbit", fuzzy=True) == "UPI flow"
    assert canonicalize_subject("new onboarding", "orbit", fuzzy=True) == "onboarding"
    # a known name of two or more words absorbs one extra word
    assert canonicalize_subject("PayU sandbox integration", "orbit", fuzzy=True) == "PayU integration"
    assert canonicalize_subject("payments service spec", "orbit", fuzzy=True) == "payments service"
    # known spelling is kept for display; unknown names are left to the caller
    assert known_spelling("Payments Service", "orbit") == "payments service"
    assert known_spelling("upi flow", "orbit") == "UPI flow"
    assert known_spelling("Zephyr Portal", "orbit", ["Zephyr portal"]) == "Zephyr portal"
    assert known_spelling("brand new thing", "orbit") is None


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
    # per item: only the item whose own text names the weekday is corrected
    two = _ctx("Review done for Wednesday's design review, and the spec goes to finance on the 18th.")
    two.episode.t_occurred = 1_789_363_800_000
    items = [
        _fact(subject="navigation accessibility review", predicate="due", object="2026-09-17", text="Sana finishes the review for Wednesday's design review."),
        _fact(subject="payments service API spec", predicate="due", object="2026-09-18", text="Priya sends the spec to finance on the 18th."),
    ]
    out = postprocess_v2(EpisodeExtraction(items=items, stats=ExtractionStats(proposed=2, kept=2)), two, "v4")
    assert [(i.subject, i.object) for i in out.items] == [("navigation accessibility review", "2026-09-16"), ("payments service API spec", "2026-09-18")]
    assert canonicalize_object("requires", "audit log retained seven years", numbers=True) == "audit log retained 7 years"
    assert canonicalize_object("status", "sent to finance", numbers=True) == "completed"
    items = [_fact(kind="fact", subject="nightly events job", predicate="decided", object="because of the backup window")]
    out = postprocess_v2(EpisodeExtraction(items=items, stats=ExtractionStats(proposed=1, kept=1)), _ctx("text"), "v4")
    assert out.items == []
    asked = _ctx("text", context_before=[{"speaker": "spk_aditya", "text": "Why did we choose the side drawer again?"}])
    assert len(postprocess_v2(EpisodeExtraction(items=items, stats=ExtractionStats(proposed=1, kept=1)), asked, "v4").items) == 1


def test_v5_readbacks_are_filtered_per_item_and_untracked_completions_dropped():
    from ingest.extract import is_readback

    assert is_readback(_ctx("Let me read it back. Scope: payments, offline, onboarding."))
    assert not is_readback(_ctx("Decision: the payments service uses PayU."))
    assert not is_readback(_ctx("Decisions since last standup: the vendor moves to PayU."))  # standup routine, not a cue
    recap = _ctx(
        "To recap: UPI flow the 25th, Priya. And one new thing: Rahul, the offline mode demo is due Monday the 28th.",
        speaker="spk_aditya",
        container_items=[{"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24"}],
    )
    recap.episode.t_occurred = 1_789_363_800_000  # Monday 2026-09-14
    llm = FakeLLM([
        {"items": [
            {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-25", "text": "Priya has the UPI flow by the 25th."},
            {"kind": "commitment", "subject": "offline mode demo", "predicate": "due", "object": "2026-09-28", "text": "Rahul demos offline mode Monday the 28th."},
        ]}
    ])
    result = make_extractor(llm, "v5").extract(recap)
    assert len(llm.calls) == 1  # the model is still called for a read-back episode
    assert [(i.subject, i.object) for i in result.items] == [("offline mode demo", "2026-09-28")]
    assert any("read-back" in e for e in result.stats.errors)
    items = [
        _fact(subject="payment branch", predicate="status", object="completed"),
        _fact(subject="offline mode spike", predicate="status", object="completed"),
    ]
    out = postprocess_v2(EpisodeExtraction(items=items, stats=ExtractionStats(proposed=2, kept=2)), _ctx("text"), "v5")
    assert [i.subject for i in out.items] == ["offline mode spike"]


def test_dayfirst_policy_flows_through_the_context():
    from ingest.dates import date_to_ms, normalize_date

    assert normalize_date("12/09/2026") == "2026-09-12" and normalize_date("12/09/2026", dayfirst=False) == "2026-12-09"
    assert date_to_ms("2026-09-24") == 1790208000000 and date_to_ms("2026-09-24", "+05:30") == 1790208000000 - 19_800_000
    from ingest.extract import coerce_extraction
    from ingest.models import RawExtraction

    raw = RawExtraction(items=[{"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "12/09/2026", "text": "t"}])
    assert coerce_extraction(raw, _ctx("text")).items[0].object == "2026-09-12"
    us = _ctx("text")
    us.dayfirst = False
    assert coerce_extraction(raw, us).items[0].object == "2026-12-09"
    assert postprocess_v2(coerce_extraction(raw, us), us, "v3").items[0].object == "2026-12-09"


def test_gold_hints_use_the_live_format():
    from ingest.gold import GoldFile, supersedes_hint_for

    gold = GoldFile.model_validate(
        {
            "meeting_id": "mtg_x",
            "items": [
                {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "speaker_id": "spk_priya", "segment_index": 1},
                {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-25", "speaker_id": "spk_priya", "segment_index": 6, "supersedes": {"subject": "UPI flow", "predicate": "due"}},
                {"kind": "decision", "subject": "newsletter", "predicate": "decided", "object": "weekly on Tuesdays", "speaker_id": "spk_aditya", "segment_index": 9, "supersedes": {"subject": "newsletter", "predicate": "decided"}},
            ],
        }
    )
    assert supersedes_hint_for(gold, gold.items[0]) is None
    assert supersedes_hint_for(gold, gold.items[1]) == "replaces: UPI flow due 2026-09-24"
    # the replaced statement lives in another file: the hint names only the key
    assert supersedes_hint_for(gold, gold.items[2]) == "replaces: newsletter decided"


def test_window_planning_and_prompt():
    from ingest.extract import build_window_prompt, plan_windows

    def ep(seq, speaker, start, end, text="words " * 8):
        return Episode(id=f"ep_m_{seq:03d}", seq=seq, speaker_id=speaker, text=text, t_start=start, t_end=end, t_occurred=1_789_000_000_000 + start, segment_indices=[seq], container_id="m")

    episodes = [ep(0, "spk_aditya", 0, 7000), ep(1, "spk_priya", 7000, 15000), ep(2, "spk_aditya", 15000, 22000), ep(3, "spk_priya", 22000, 70000), ep(4, "spk_aditya", 70000, 75000)]
    windows = plan_windows(episodes, 3)
    assert [[e.seq for e in w] for w in windows] == [[0, 1, 2], [3], [4]]  # 3 max, and 22-70 s would exceed 60 s
    assert [[e.seq for e in w] for w in plan_windows(episodes, 1)] == [[0], [1], [2], [3], [4]]
    ctxs = [EpisodeContext(episode=e, container_title="Orbit standup 1", container_date=date(2026, 9, 14), speakers=SPEAKERS, tenant="orbit", prior_facts=[{"id": "f_upi", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "speaker_id": "spk_priya"}]) for e in windows[0]]
    prompt = build_window_prompt(ctxs)
    assert "[1] Aditya (spk_aditya, lead):" in prompt and "[2] Priya (spk_priya, backend):" in prompt and "[3] Aditya" in prompt
    assert prompt.count("UPI flow | due | 2026-09-24") == 1 and "Known entities" in prompt
    assert prompt.index("## Episodes to extract from") > prompt.index("Facts already recorded")


def test_predicate_names_used_as_kind_are_mapped():
    item = ExtractedFact.model_validate({"kind": "lesson", "subject": "Orbit", "predicate": "lesson", "object": "record the rationale", "text": "t"})
    assert item.kind == "decision"
