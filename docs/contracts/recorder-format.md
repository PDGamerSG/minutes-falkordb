# Contract: recorder export format (input to ingestion)

Produced by the team's on-device recorder (speech-to-text plus speaker diarization) or hand-written for scripted meetings. One JSON file per meeting under `data/meetings/<slug>.json`. Audio, when present, sits next to it as `<slug>.wav` or `.m4a` and is referenced by `audio_uri`.

```json
{
  "version": 1,
  "meeting": {
    "id": "mtg_orbit_001",
    "title": "Orbit kickoff",
    "started_at": "2026-09-07T10:00:00+05:30",
    "ended_at": "2026-09-07T10:08:30+05:30",
    "audio_uri": "data/meetings/orbit_001.wav"
  },
  "speakers": [
    {"id": "spk_aditya", "name": "Aditya", "role": "lead"},
    {"id": "spk_priya", "name": "Priya", "role": "backend"}
  ],
  "segments": [
    {"start_ms": 0, "end_ms": 6400, "speaker_id": "spk_aditya", "text": "Alright, let's lock the scope for the October release."},
    {"start_ms": 6400, "end_ms": 15200, "speaker_id": "spk_priya", "text": "Payments go first. I can have the UPI flow done by the 24th."}
  ]
}
```

Rules
- `start_ms` and `end_ms` are offsets from `started_at`. `t_occurred` of an episode = `started_at + start_ms`.
- Segments are in time order and non-overlapping. Consecutive same-speaker segments are merged by the chunker into episodes of 30 to 60 seconds.
- Speaker ids are stable across meetings for the same tenant (the recorder's voice profiles, or our hand-assigned ids).

## Gold labels (for the extraction eval), `data/gold/<slug>.json`

```json
{
  "meeting_id": "mtg_orbit_001",
  "items": [
    {"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "speaker_id": "spk_priya", "segment_index": 1},
    {"kind": "decision", "subject": "October release", "predicate": "scope_includes", "object": "payments", "speaker_id": "spk_aditya", "segment_index": 0}
  ]
}
```

Matching rule for the eval: an extracted item matches a gold item when `kind` equals, speaker equals, and normalized `subject` and `predicate` match (case-insensitive, punctuation stripped) and `object` matches after date normalization.
