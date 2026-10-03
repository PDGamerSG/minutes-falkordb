# Corpus generator

The JSON files in `data/meetings/` and `data/gold/` are the source of truth; this generator is how they were produced and is kept so a date or wording change can be made once and regenerated consistently. The whole corpus is synthetic: fictional teams, people and companies (`*.example` addresses), written by us for the demo and the extraction eval.

Dialogue lives in `orbit_meetings.py`, `other_meetings.py` and `threads.py` as `(speaker_id, text[, gold_items])` tuples (meetings) or message dicts (threads). `gen_lib.py` computes segment offsets from word counts (2 to 12 s, ordered, non-overlapping), inherits `speaker_id` and `segment_index` / `message_index` into the gold items, and writes both files.

Regenerate from the repo root with `python data/generator/build.py` (Python 3.9+, standard library only). It overwrites every meeting, thread, roster and gold JSON, then prints per-file stats, a planted-events table with indices and timestamps (paste into `data/meetings/README.md` if they moved), and validates ordering, durations and index ranges. Set `MINUTES_REPO` to write into a different checkout.

Rules the generator enforces: a segment is at most 30 words, meeting lengths stay within the brief (orbit 4 to 8 minutes, others 2 to 4), speaker ids match the roster, thread messages are in `sent_at` order. Items with `kind: "note"` appear in the planted table but never in gold.
