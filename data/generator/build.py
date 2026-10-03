import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from gen_lib import build_meeting, build_thread, write_roster, MEET_DIR, GOLD_DIR  # noqa: E402
import orbit_meetings  # noqa: E402
import other_meetings  # noqa: E402
import threads  # noqa: E402

planted = []
problems = []
stats = []

for slug, mid, title, started, segs in orbit_meetings.MEETINGS:
    st, pr = build_meeting(slug, mid, title, started, orbit_meetings.SPEAKERS, segs, planted)
    stats.append(st); problems += pr
    if not (240 <= st["duration_s"] <= 480):
        problems.append("%s: duration %.0fs outside 4-8 min" % (slug, st["duration_s"]))
    if not (40 <= st["segments"] <= 90):
        problems.append("%s: %d segments outside 40-90" % (slug, st["segments"]))

for tenant, speakers, slug, mid, title, started, segs in other_meetings.MEETINGS:
    st, pr = build_meeting(slug, mid, title, started, speakers, segs, planted)
    stats.append(st); problems += pr
    if not (120 <= st["duration_s"] <= 240):
        problems.append("%s: duration %.0fs outside 2-4 min" % (slug, st["duration_s"]))

for slug, tid, subject, ppl, msgs in threads.THREADS:
    st, pr = build_thread(slug, tid, subject, ppl, msgs, planted)
    stats.append(st); problems += pr

for fname, roster in threads.ROSTERS:
    write_roster(fname, roster)

print("== files ==")
for st in stats:
    if "segments" in st:
        print("%-20s %3d segments  %5.0f s  gold=%2d (D=%d C=%d F=%d)" % (
            st["slug"], st["segments"], st["duration_s"], st["gold"], st["decisions"], st["commitments"], st["facts"]))
    else:
        print("%-20s %3d messages          gold=%2d" % (st["slug"], st["messages"], st["gold"]))

print("\n== problems ==")
for p in problems:
    print(p)
if not problems:
    print("none")

print("\n== planted events ==")
for e in planted:
    print("| %s | %s | %s | %s | %s | %s %s %s |" % (
        e["source"], e["index"], e["at"], e["speaker"], e["tag"], e["subject"], e["predicate"], e["object"]))

# validate everything we wrote as JSON and check ordering/durations
print("\n== validation ==")
bad = 0
for d in (MEET_DIR, GOLD_DIR):
    for f in sorted(os.listdir(d)):
        if not f.endswith(".json"):
            continue
        path = os.path.join(d, f)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        if d == MEET_DIR and "segments" in doc:
            prev_end = -1
            for i, s in enumerate(doc["segments"]):
                dur = s["end_ms"] - s["start_ms"]
                if s["start_ms"] < prev_end or not (2000 <= dur <= 12000):
                    print("BAD", f, i, s["start_ms"], s["end_ms"]); bad += 1
                prev_end = s["end_ms"]
        if d == GOLD_DIR:
            src = os.path.join(MEET_DIR, f)
            with open(src, encoding="utf-8") as fh:
                sdoc = json.load(fh)
            n = len(sdoc.get("segments") or sdoc.get("messages"))
            key = "segment_index" if "segments" in sdoc else "message_index"
            for it in doc["items"]:
                if not (0 <= it[key] < n):
                    print("BAD index", f, it); bad += 1
print("ok" if not bad else "%d problems" % bad)
