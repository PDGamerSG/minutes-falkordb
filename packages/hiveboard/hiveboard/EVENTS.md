# hiveboard events

The substrate is the single publisher of memory and board events. Consumers (the API workers, the SSE stream, the
agents) subscribe; the ingest pipeline and the API routes do not publish their own variants of these events.

Transport: Redis pub/sub on the FalkorDB server, one channel per tenant, `team_<slug>:events`.
Message: JSON `{"event": <name>, "payload": {...}, "ts": <epoch ms>}`.
Helpers: `hiveboard.subscribe(db, tenant, idle_timeout=None)` (blocking iterator), `hiveboard.asubscribe(db, tenant)`
(async generator), `hiveboard.publish(db, tenant, event, payload)`. Delivery is fire-and-forget (pub/sub): a subscriber
that is down misses events, so consumers also poll the board.

Every memory payload carries `tenant`. Timestamps are epoch milliseconds. Absent values are `null`, never omitted.

## Memory

### `episode.ingested`

Published once per `remember_episodes` / `remember_email_episodes` call (one batch, never per episode).

| key | meaning |
| --- | --- |
| `container_id` | Meeting or EmailThread id |
| `count` | episodes written |
| `source_kind` | `utterance` or `email` |
| `first_episode_id`, `last_episode_id` | the batch ends (by `seq`) |
| `t_first`, `t_last` | `t_occurred` of those two episodes |
| `tenant` | slug |

### `fact.created`

A fact born ACTIVE: `remember_fact` (when something was written) and `supersede_fact` (the replacement).
Never published for a fact born superseded by `insert_fact_in_chain`, and not for an `existing` duplicate.

`{id, fact_id, kind, key, subject, predicate, object, text, speaker_id, episode_id, due_at, valid_from, tenant}`

### `commitment.created`

Same payload as `fact.created` plus `commitment_id`; only when `kind == "commitment"`.

### `fact.superseded`

Something was expired. One schema for every producer; consumers may read any alias.

| key | meaning |
| --- | --- |
| `new_fact_id`, `new_id` | the fact that now holds the key (alias pair) |
| `old_fact_id` | first expired fact (null when none) |
| `old_fact_ids`, `old_ids` | every expired fact id (alias pair) |
| `key` | `subject\|predicate`, lower-cased |
| `subject`, `predicate`, `kind` | of the new fact |
| `old_object` | object of the first expired fact |
| `new_object`, `object` | object of the new fact (alias pair) |
| `valid_from` | when the new statement became true (valid time) |
| `due_at` | the new fact's due date, or null |
| `episode_id`, `speaker_id` | provenance of the new fact |
| `head_changed` | true when the current belief moved (`remember_fact(supersede=True)`, `supersede_fact`); false for `insert_fact_in_chain`, where a late import re-wired history and the head is unchanged |
| `tenant` | slug |

Consumers that react to "the plan changed" (the Scheduler) should ignore events with `head_changed == false`.

### `commitment.updated`

The `fact.superseded` payload plus `id`, `commitment_id` and `replaces` (the expired ids); only when `kind == "commitment"`.

## Board

| event | payload |
| --- | --- |
| `task.submitted` | `{task_id, kind, requires, about, priority}` |
| `task.claimed` | `{task_id, agent_id, version, lease_until}` |
| `task.handed_off` | `{task_id, from, to, version, summary, subgraph_ids}` |
| `task.completed` | `{task_id, agent_id, artifact, version}` |
| `task.failed` | `{task_id, agent_id, reason, version}` |
| `task.input_required` | `{task_id, agent_id, question, version}` |
| `task.lease_expired` | `{task_id, agent_id (former owner), version, at}`, from `board.reap_expired` |

## Skills

| event | payload |
| --- | --- |
| `skill.learned` | `{skill_id, goal, steps, learned_from}` |
| `skill.ran` | `{skill_id, agent_id, ok, task_id, runs, success_rate}` |

## Contract tests

`hiveboard.events.SUPERSEDED_PAYLOAD_KEYS` is the exact key set of `fact.superseded`; the substrate tests assert it and
consumer tests (Scheduler) can import it.
