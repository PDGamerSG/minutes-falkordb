# Contract: email thread format (second source, priority 2 after meetings)

Scope: upload-only ingestion of `.json` (this shape), `.eml` or `.mbox` files parsed with Python's standard `email` module into this shape. No mailbox connectors (no Gmail OAuth, no IMAP): rule 6 bans personal data and it costs a day of auth work. Corpus is synthetic and follows the same people and story as the scripted meetings.

```json
{
  "version": 1,
  "thread": {
    "id": "thr_orbit_001",
    "subject": "UPI flow timeline",
    "started_at": "2026-09-16T14:02:00+05:30"
  },
  "people": [
    {"id": "spk_priya", "name": "Priya", "email": "priya@orbit.example"},
    {"id": "spk_aditya", "name": "Aditya", "email": "aditya@orbit.example"}
  ],
  "messages": [
    {
      "id": "msg_orbit_001_1",
      "sent_at": "2026-09-16T14:02:00+05:30",
      "from": "priya@orbit.example",
      "to": ["aditya@orbit.example"],
      "cc": ["rahul@orbit.example"],
      "in_reply_to": null,
      "subject": "UPI flow timeline",
      "body_text": "Aditya, quick heads-up on the UPI flow ..."
    }
  ]
}
```

Rules
- `people[].id` reuses the meeting speaker ids (`spk_*`). The roster `data/meetings/<tenant>_roster.json` (`[{id, name, role, email}]`) is the join key between sources. It is a seed file, never inferred.
- One Episode per message (`source_kind = "email"`), `t_occurred = sent_at`, `t_start`/`t_end` null, `text = body_text` with quoted replies stripped (lines starting with `>` and everything after a `On ... wrote:` line).
- Messages are in `sent_at` order. `in_reply_to` references a message id in the same thread or null.

## Graph model delta (applies to `docs/06-implementation-plan.md` section 3 and `hiveboard-api.md`)

- `Episode.source_kind`: `utterance | email | doc_chunk`. Existing utterance episodes get `utterance`.
- New node `EmailThread {id, subject, started_at}` with `(EmailThread)-[:HAS_EPISODE]->(Episode)`. `Meeting` stays as is.
- New edges: `(Episode)-[:SENT_BY]->(Person)`, `(Episode)-[:SENT_TO {cc: bool}]->(Person)`, `(Episode)-[:REPLIES_TO]->(Episode)`. `SPOKEN_BY` stays for meetings.
- `Person.email` property; `Person.id` is still the key.
- Everything downstream is unchanged: Facts, Decisions, Commitments hang off the Episode through `DERIVED_FROM`; supersession, `belief_at`, recall and the vector index do not change. A commitment made in a meeting and moved in an email produces a `SUPERSEDES` edge that crosses sources.
- `why()` returns `source: {kind, container: {id, title|subject}, t_start?|sent_at, message_id?}` so the UI shows "play at timestamp" for utterances and "open email" for emails.
- `who_knows` counts `SPOKEN_BY`, `SENT_BY` and `SENT_TO` mentions.

## hiveboard additions

```python
def remember_thread(db, tenant, thread: dict) -> str                       # {id?, subject, started_at}
def remember_email_episodes(db, tenant, thread_id: str, episodes: list[dict]) -> int
    # episode: {id?, seq, sender_id, to_ids: [str], cc_ids: [str], in_reply_to_episode_id?: str, text, t_occurred, embedding?}
    # creates HAS_EPISODE, SENT_BY, SENT_TO{cc}, REPLIES_TO, NEXT (by seq), source_kind='email'
```

## HTTP additions

- `POST /tenants/{tenant}/email/import` body = thread JSON, or multipart with an `.eml`/`.mbox` file → `{thread_id, job_id}` (same job polling as meetings)
- `GET /tenants/{tenant}/threads` → `[{id, subject, started_at, messages, facts, status}]`
- `GET /tenants/{tenant}/threads/{id}/messages` → `[{id, seq, sender: {id,name,email}, to: [...], cc: [...], sent_at, text, in_reply_to}]`
- `GET /tenants/{tenant}/why/{node_id}` response gains `source` as described above; `sources[]` in chat answers gain `kind` and `thread`/`sent_at` fields.

## Gold labels

Same shape as meetings (`data/gold/<thread slug>.json`) with `message_index` instead of `segment_index`. Supersessions that cross sources carry `"supersedes": {"subject", "predicate"}` as before.

## UI

The meetings page becomes "Sources" with two tabs: Meetings and Email threads. Sources lists use a microphone icon for utterances and an envelope icon for emails (lucide icons, not emoji). Why panel: "play at timestamp" for utterances, "open email" (drawer with the message) for emails.
