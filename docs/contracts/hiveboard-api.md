# Contract: `hiveboard` Python package (the substrate)

Everyone codes against these signatures. Stream A implements them; Stream B consumes them. All timestamps are epoch milliseconds (`int`). All ids are strings (ULIDs or `<prefix>_<slug>`). Every function takes a `tenant: str` (team slug) unless noted. Embeddings are `list[float]` of length 768 or `None`.

```python
# hiveboard/db.py
class HiveDB:
    def __init__(self, url: str = "falkor://localhost:6379", admin_user: str | None = None, admin_password: str | None = None): ...
    def graph(self, tenant: str):            # rw graph handle: falkordb Graph for f"team_{tenant}"
    def ro(self, tenant: str):               # read-only handle (the tenant's ro ACL user once configure_ro/create_tenant ran;
                                             # otherwise ONE warning per tenant and the admin connection)
    def configure_ro(self, tenant: str, password: str | None) -> None
    def commons(self):                       # shared graph "commons"
    def list_tenants(self) -> list[str]      # valid slugs only; snapshot copies excluded
    def usage(self, tenant: str) -> dict     # GRAPH.MEMORY USAGE -> {"total_mb": float, ...}
    def ping(self) -> bool                   # False (never raises) when the server is down
    @staticmethod
    def graph_name(tenant: str) -> str       # "team_<slug>"; ValueError unless slug matches ^[a-z0-9][a-z0-9-]{1,40}$
                                             # and does not contain "__snap_" (also rw_user / ro_user)
# The connection is lazy. Timeouts: connect 2 s, socket 10 s, health check 30 s.
# hiveboard.validate_slug(slug) -> slug | ValueError

# hiveboard/schema.py
def ensure_schema(db: HiveDB, tenant: str) -> dict        # runs cypher/00_schema.cypher + constraints, idempotent; returns counts.
                                                          # Raises hiveboard.schema.ConstraintFailed(.duplicates) when duplicate ids block a
                                                          # unique constraint (the FAILED constraint is dropped so a repaired graph can retry)
def ensure_commons_schema(db: HiveDB, force: bool = False) -> dict   # once per process per HiveDB
def load_udfs(db: HiveDB) -> None                         # GRAPH.UDF LOAD REPLACE hive <score.js>

# hiveboard/tenancy.py
def create_tenant(db: HiveDB, tenant: str, display_name: str, password_rw: str | None = None,
                  password_ro: str | None = None, rotate: bool = False) -> dict
    # creates graph team_<tenant>, runs ensure_schema, creates ACL users team_<tenant>_rw / team_<tenant>_ro and the registry row.
    # New tenant or rotate=True: users are (re)created with the given passwords or freshly generated secrets, returned ONCE as
    #   result["credentials"] = {rw_user, rw_password, ro_user, ro_password} (never stored). db.ro() is configured automatically.
    # Existing tenant without rotate: passwords are NOT reset, only the ACL rules are re-applied; a supplied password that
    #   does not match raises Conflict; result["credentials"] is None. Result also has created, rotated, schema, rules, isolation.
    # rw user: reads/writes team_<tenant>, READ-ONLY on commons (ACL selector); ro user: read-only on both.
def ensure_tenant_access(db: HiveDB, tenant: str, password_rw: str | None, password_ro: str | None) -> None
    # re-applies the ACL rules without resetting passwords; recreates a missing user from the given password; NotFound otherwise
def set_tenant_meta(db: HiveDB, tenant: str, meta: dict) -> dict    # merge into the Tenant node in commons (None removes a key); returns stored meta
def get_tenant_meta(db: HiveDB, tenant: str) -> dict                # {} when none
def delete_tenant(db: HiveDB, tenant: str) -> None       # GRAPH.DELETE (+ snapshots) + ACL DELUSER + registry row + published skills
def acl_rules(db: HiveDB, tenant: str) -> dict            # for the UI: the ACL lines in force
def snapshot(db: HiveDB, tenant: str, label: str) -> str  # GRAPH.COPY team_<tenant> team_<tenant>__snap_<ts>; writes Snapshot node in commons; returns snapshot graph name
                                                          # (ts is bumped when two snapshots land in the same millisecond; the copy is deleted if the registry write fails)
def list_snapshots(db: HiveDB, tenant: str) -> list[dict]

# hiveboard/temporal.py
def now_ms() -> int
def iso_to_ms(s: str) -> int
def ms_to_iso(ms: int) -> str

# hiveboard/memory.py   (episodic + semantic)
def remember_person(db, tenant, person: dict) -> str                 # {id?, name, role?}
def remember_meeting(db, tenant, meeting: dict) -> str               # {id?, title, started_at, ended_at?, source_uri?}
def remember_episodes(db, tenant, meeting_id: str, episodes: list[dict]) -> int
    # episode: {id?, seq, speaker_id, text, t_start, t_end, t_occurred, embedding?}; creates HAS_EPISODE, SPOKEN_BY, NEXT.
    # An out-of-order batch is spliced in, so the NEXT chain stays linear. Publishes ONE episode.ingested per call.
def remember_email_episodes(db, tenant, thread_id: str, episodes: list[dict]) -> int
def remember_entities(db, tenant, entities: list[dict]) -> int       # {id?, name, type, embedding?}; MERGE on name_key = lower(trim(name))
def upsert_entities(db, tenant, entities: list[dict]) -> dict[str, str]   # same, returns {input name: effective entity id}
def link_mentions(db, tenant, episode_id: str, entity_ids: list[str]) -> int
def remember_fact(db, tenant, fact: dict) -> dict
    # fact: {id?, subject, predicate, object, text, confidence, speaker_id, episode_id, entity_ids: list[str],
    #        kind: "fact"|"decision"|"commitment", due_at?: int, valid_from?: int, embedding?}
    # key = f"{subject}|{predicate}" lowercased. Lookup, ingest and supersession are ONE atomic statement (18_remember_fact).
    # An identical ACTIVE fact (same key, same trimmed case-insensitive object) is returned unchanged (existing=True) unless an
    # explicit id is given. ACTIVE facts with the same key and a different object are reported under "conflicts", or expired and
    # linked with SUPERSEDES when supersede=True. Raises Conflict when supersede=True and a conflicting fact is valid from LATER
    # (a late import of an earlier statement: use insert_fact_in_chain). Re-ingesting an existing id never rewrites identity or
    # valid_from. Returns {"id", "superseded": [ids], "conflicts": [ids], "existing": bool}.
def supersede_fact(db, tenant, old_id: str, new_fact: dict) -> dict  # explicit supersession (12_supersede_fact.cypher), atomic;
    # returns {"id", "superseded": [old_id]}. NotFound if old_id is missing; Conflict if nothing was superseded: old fact not ACTIVE
    # (a concurrent writer won), different key, or new.valid_from < old.valid_from.
def insert_fact_in_chain(db, tenant, fact: dict, before_id: str) -> dict
    # late import of an EARLIER statement, atomic (19_insert_fact_in_chain.cypher). The new fact is born superseded between the
    # predecessor(s) of before_id and before_id; the chain head never changes. If the statement restates a chain member (same key and
    # normalised object, or id == before_id) nothing is inserted: the existing fact is linked CONFIRMED_BY the episode.
    # Returns {"id", "inserted", "confirmed", "before_id", "superseded": [ids]}. NotFound for a missing before_id; Conflict for a key
    # mismatch or when before is not later than the statement.
def retract_fact(db, tenant, fact_id: str, reason: str) -> None
def active_facts(db, tenant, entity_id: str | None = None, key: str | None = None, limit: int = 500) -> list[dict]   # entity -> 1A_active_facts_for_entity
def belief_at(db, tenant, t: int, entity_id: str | None = None, known_by: int | None = None, limit: int = 500) -> list[dict]
    # 31_belief_at_time.cypher. known_by = transaction time: a fact superseded or retracted AFTER known_by still counts as believed then.
def why(db, tenant, node_id: str) -> dict
    # {"node": {...}, "speaker": {...}, "meeting": {...}, "thread": {...}, "episode": {...} (earliest source),
    #  "episodes": [every DERIVED_FROM episode, earliest first], "source": {...}, "entities": [...],
    #  "history": [facts in SUPERSEDES chain], "superseded_by": [...], "supersedes": [...],
    #  "cypher": "<query text>", "subgraph": {"nodes": [...], "edges": [...]}}
def recall(db, tenant, query_embedding: list[float], k: int = 8, now: int | None = None, label: str = "Fact") -> dict
    # hybrid: vector KNN -> 1-hop expansion -> hive.score() -> ranked; returns {"items": [...], "cypher": str, "subgraph": {...}}
def fulltext(db, tenant, text: str, label: str = "Episode", k: int = 10) -> list[dict]

# hiveboard/board.py   (coordination; A2A-shaped states: submitted | working | input_required | completed | failed)
def register_agent(db, tenant, agent_id: str, name: str, capabilities: list[str], model: str) -> None
def submit_task(db, tenant, kind: str, payload: dict, requires: list[str], about_ids: list[str] = (), priority: int = 5) -> str
def claim(db, tenant, task_id: str, agent_id: str, expected_version: int, lease_ms: int = 120000) -> int | None
    # CAS; None = lost the race, stale version, or the task is addressed (handed off) to another agent. Sets lease_until.
def heartbeat(db, tenant, task_id: str, agent_id: str, lease_ms: int = 120000) -> bool   # extend the lease of a working task you own
def reap_expired(db, tenant, now: int | None = None, lease_ms: int = 120000) -> list[str]
    # working tasks with an expired lease -> submitted, version + 1, owner_agent NULL, (task)-[:LEASE_EXPIRED {at}]->(agent); returns task ids
def next_open_task(db, tenant, agent_id: str) -> dict | None     # highest priority, then oldest, submitted task whose REQUIRES ⊆ agent HAS;
                                                                 # only unaddressed tasks or tasks addressed to the agent
def handoff(db, tenant, task_id: str, from_agent: str, to_agent: str, expected_version: int, summary: str, subgraph_ids: list[str]) -> int | None
    # requires status working and owner == from_agent; the task returns to submitted addressed to to_agent
def complete(db, tenant, task_id: str, agent_id: str, artifact: dict | None = None) -> None   # artifact: {kind, uri?, text?}
def fail(db, tenant, task_id: str, agent_id: str, reason: str) -> None          # owner only, task working or input_required, else NotFound
def need_input(db, tenant, task_id: str, agent_id: str, question: str) -> None  # owner only, task working or input_required, else NotFound
def list_tasks(db, tenant, status: str | None = None, limit: int = 50) -> list[dict]
def list_agents(db, tenant) -> list[dict]
def task_trace(db, tenant, task_id: str) -> dict           # claims, handoffs, lease expiries, artifacts, used skills, in order

# hiveboard/skills.py   (procedural memory)
def learn_skill(db, tenant, goal: str, steps: list[dict], learned_from: list[str], embedding: list[float] | None, version: int = 1) -> str
    # step: {order, tool, args_template (json str), guard?}
def retrieve_skill(db, tenant, goal_embedding: list[float], k: int = 3) -> list[dict]   # best active by success_rate then distance, with steps (no embedding on the wire)
def record_outcome(db, tenant, skill_id: str, agent_id: str, ok: bool, task_id: str | None = None) -> dict  # updates runs, success_rate; RAN edge
def deprecate_skill(db, tenant, old_id: str, new_id: str) -> None
def skill_pagerank(db, tenant) -> list[dict]               # algo.pageRank over Skill via USED edges
def publish_to_commons(db, tenant, skill_id: str) -> str   # copies Skill+Steps into commons graph with origin tenant

# hiveboard/events.py   (Redis pub/sub on the same server)
def publish(db, tenant, event: str, payload: dict) -> None          # channel f"team_{tenant}:events", JSON {event, payload, ts}
def subscribe(db, tenant) -> Iterator[dict]                           # blocking generator; async variant asubscribe()
# Event names: episode.ingested, fact.created, fact.superseded, commitment.created, commitment.updated,
#              task.submitted, task.claimed, task.handed_off, task.completed, task.failed, task.input_required,
#              task.lease_expired, skill.learned, skill.ran
# The substrate is the only publisher of memory events; payload schemas (incl. the full fact.superseded payload with
# old_object/new_object/subject/due_at/episode_id/head_changed) are in packages/hiveboard/hiveboard/EVENTS.md.
# episode.ingested fires once per remember_episodes call; fact.created / commitment.created never fire for a fact born
# superseded by insert_fact_in_chain (that publishes fact.superseded with head_changed=false).

# hiveboard/analytics.py   (Track 3 queries)
def who_knows(db, tenant, entity_name: str, limit: int = 500) -> list[dict]
def open_commitments(db, tenant, person_id: str | None = None, limit: int = 500) -> list[dict]
def contradictions(db, tenant, limit: int = 500) -> list[dict]           # two ACTIVE facts, same key, different object
def entity_clusters(db, tenant) -> list[dict]          # algo.WCC over Entity co-mention
def stale_decisions(db, tenant, older_than_ms: int, limit: int = 500) -> list[dict]

# hiveboard/impact.py   (decision-impact tracking)
def import_manifest(db, tenant, manifest: dict) -> int          # atomic; ValueError on a malformed manifest or an unresolved reference
def work_impacts(db, tenant) -> list[dict]                      # candidates are distinct per current fact (shortest SUPERSEDES path)
def save_draft(db, tenant, draft: dict) -> dict | None          # ValueError on a missing required key; Conflict when the draft id belongs to
                                                                # another work item; None when the graph moved on (stale)
def list_drafts(db, tenant) -> list[dict]
```

Conventions
- Embeddings must be exactly 768 floats everywhere (`ValueError` otherwise). Reads project nodes without the vector (`has_embedding` instead).
- Domain errors: `hiveboard.errors.NotFound` and `Conflict`; invalid input raises `ValueError`.
- Every function that runs Cypher attaches the query text to its return under `"cypher"` when the result is shown to users (why, recall, belief_at, analytics). The UI renders it.
- Write queries use `UNWIND $rows AS r MERGE ...` with parameters; never string-format values into Cypher.
- Read paths for user-facing answers use `graph.ro_query` with `timeout=3000`.
- `hive.score(valid_from, confidence, distance, now)` is the UDF in `hiveboard/udf/score.js`: `recency * importance * similarity`, where recency = exp(-age_days/30), importance = confidence, similarity = 1 - distance (clamped). Higher is better.
