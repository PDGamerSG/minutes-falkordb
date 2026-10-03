"""Shared builders for the scripted meeting / email corpus.

Dialogue is authored as (speaker_id, text[, gold_items]) tuples. Offsets are
computed from word counts so segments are ordered, non-overlapping and 2-12 s.
Gold items attached to a segment inherit speaker_id and segment_index, so the
labels are consistent with the transcript by construction.
"""
import json
import math
import os
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
# repo root = two levels above data/generator/; override with MINUTES_REPO if running from elsewhere
REPO = os.environ.get("MINUTES_REPO") or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MEET_DIR = os.path.join(REPO, "data", "meetings")
GOLD_DIR = os.path.join(REPO, "data", "gold")

EXTRA_KEYS = ("supersedes", "reverses_meeting", "follows_precedent", "confirms")


def D(s, p, o, **k):
    return dict(kind="decision", subject=s, predicate=p, object=o, **k)


def C(s, p, o, **k):
    return dict(kind="commitment", subject=s, predicate=p, object=o, **k)


def F(s, p, o, **k):
    return dict(kind="fact", subject=s, predicate=p, object=o, **k)


def seg_duration_ms(text):
    words = len(text.split())
    d = 0.9 + 0.34 * words
    if text.rstrip().endswith("?"):
        d += 0.2
    d = max(2.0, min(12.0, d))
    return int(round(d * 10)) * 100


def gap_ms(i):
    # small, deterministic pauses between turns (300..799 ms)
    return 300 + (i * 37) % 500


def mmss(ms):
    s = ms // 1000
    return "%d:%02d" % (s // 60, s % 60)


def _gold_item(it, speaker_id, index_key, index):
    g = {
        "kind": it["kind"],
        "subject": it["subject"],
        "predicate": it["predicate"],
        "object": it["object"],
        "speaker_id": speaker_id,
        index_key: index,
    }
    for k in EXTRA_KEYS:
        if k in it:
            g[k] = it[k]
    return g


def build_meeting(slug, meeting_id, title, started_iso, speakers, segs, planted):
    speaker_ids = {s["id"] for s in speakers}
    started = datetime.fromisoformat(started_iso)
    t = 0
    out_segs = []
    gold = []
    problems = []
    for i, seg in enumerate(segs):
        spk, text = seg[0], seg[1]
        items = seg[2] if len(seg) > 2 else []
        if spk not in speaker_ids:
            problems.append("%s seg %d: unknown speaker %s" % (slug, i, spk))
        words = len(text.split())
        if words > 30:
            problems.append("%s seg %d: %d words (split it)" % (slug, i, words))
        d = seg_duration_ms(text)
        start, end = t, t + d
        out_segs.append({"start_ms": start, "end_ms": end, "speaker_id": spk, "text": text})
        for it in items:
            if it["kind"] != "note":  # notes go to the planted table only, never to gold
                gold.append(_gold_item(it, spk, "segment_index", i))
            if "tag" in it:
                planted.append({
                    "source": slug, "index": i, "at": mmss(start), "speaker": spk,
                    "tag": it["tag"], "kind": it["kind"], "subject": it["subject"],
                    "predicate": it["predicate"], "object": it["object"],
                    "quote": text,
                })
        t = end + gap_ms(i)
    total_ms = out_segs[-1]["end_ms"]
    ended = started + timedelta(seconds=math.ceil(total_ms / 1000.0))
    doc = {
        "version": 1,
        "meeting": {
            "id": meeting_id,
            "title": title,
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "audio_uri": "data/meetings/%s.wav" % slug,
        },
        "speakers": speakers,
        "segments": out_segs,
    }
    gold_doc = {"meeting_id": meeting_id, "items": gold}
    _write(os.path.join(MEET_DIR, slug + ".json"), doc)
    _write(os.path.join(GOLD_DIR, slug + ".json"), gold_doc)
    stats = {
        "slug": slug, "segments": len(out_segs), "duration_s": total_ms / 1000.0,
        "gold": len(gold),
        "decisions": sum(1 for g in gold if g["kind"] == "decision"),
        "commitments": sum(1 for g in gold if g["kind"] == "commitment"),
        "facts": sum(1 for g in gold if g["kind"] == "fact"),
    }
    return stats, problems


def build_thread(slug, thread_id, subject, people, messages, planted):
    """messages: list of dicts with sender (id), to (ids), cc (ids), sent_at (iso),
    reply_to (int index or None), subject (optional override), body, items (gold)."""
    by_id = {p["id"]: p for p in people}
    out = []
    gold = []
    problems = []
    last_sent = None
    for i, m in enumerate(messages):
        sender = by_id[m["sender"]]
        sent = datetime.fromisoformat(m["sent_at"])
        if last_sent is not None and sent <= last_sent:
            problems.append("%s msg %d: sent_at not increasing" % (slug, i))
        last_sent = sent
        mid = "msg_%s_%d" % (thread_id[len("thr_"):], i + 1)
        reply_to = m.get("reply_to")
        out.append({
            "id": mid,
            "sent_at": sent.isoformat(),
            "from": sender["email"],
            "to": [by_id[x]["email"] for x in m["to"]],
            "cc": [by_id[x]["email"] for x in m.get("cc", [])],
            "in_reply_to": None if reply_to is None else out[reply_to]["id"],
            "subject": m.get("subject") or (subject if reply_to is None else "Re: " + subject),
            "body_text": m["body"],
        })
        for it in m.get("items", []):
            gold.append(_gold_item(it, m["sender"], "message_index", i))
            if "tag" in it:
                planted.append({
                    "source": slug, "index": i, "at": sent.strftime("%b %d %H:%M"),
                    "speaker": m["sender"], "tag": it["tag"], "kind": it["kind"],
                    "subject": it["subject"], "predicate": it["predicate"],
                    "object": it["object"], "quote": m["body"].split("\n")[0],
                })
    doc = {
        "version": 1,
        "thread": {"id": thread_id, "subject": subject, "started_at": out[0]["sent_at"]},
        "people": [{"id": p["id"], "name": p["name"], "email": p["email"]} for p in people],
        "messages": out,
    }
    gold_doc = {"thread_id": thread_id, "items": gold}
    _write(os.path.join(MEET_DIR, slug + ".json"), doc)
    _write(os.path.join(GOLD_DIR, slug + ".json"), gold_doc)
    stats = {"slug": slug, "messages": len(out), "gold": len(gold)}
    return stats, problems


def write_roster(slug, roster):
    _write(os.path.join(MEET_DIR, slug), roster)


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
