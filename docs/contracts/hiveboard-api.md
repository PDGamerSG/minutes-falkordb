# Contract: `hiveboard` Python package (the substrate)

Everyone codes against these signatures. Stream A implements them; Stream B consumes them. All timestamps are epoch milliseconds (`int`). All ids are strings (ULIDs or `<prefix>_<slug>`). Every function takes a `tenant: str` (team slug) unless noted. Embeddings are `list[float]` of length 768 or `None`.

```python
# hiveboard/db.py
class HiveDB:
    def __init__(self, url: str = "falkor://localhost:6379", admin_user: str | None = None, admin_password: str | None = None): ...
    def graph(self, tenant: str):            # rw graph handle: falkordb Graph for f"team_{tenant}"
    def ro(self, tenant: str):               # read-only handle (uses the tenant's ro ACL user when configured)
    def commons(self):                       # shared graph "commons"
    def list_tenants(self) -> list[str]
    def usage(self, tenant: str) -> dict     # GRAPH.MEMORY USAGE -> {"total_mb": float, ...}
    def ping(self) -> bool

# hiveboard/schema.py
def ensure_schema(db: HiveDB, tenant: str) -> dict        # runs cypher/00_schema.cypher + constraints, idempotent; returns counts
def load_udfs(db: HiveDB) -> None                         # GRAPH.UDF LOAD REPLACE hive <score.js>

# hiveboard/tenancy.py
def create_tenant(db: HiveDB, tenant: str, display_name: str, password_rw: str, password_ro: str) -> dict
    # creates graph team_<tenant>, runs ensure_schema, creates ACL users team_<tenant>_rw / team_<tenant>_ro
def delete_tenant(db: HiveDB, tenant: str) -> None       # GRAPH.DELETE + ACL DELUSER
def acl_rules(db: HiveDB, tenant: str) -> dict            # for the UI: the ACL lines in force
def snapshot(db: HiveDB, tenant: str, label: str) -> str  # GRAPH.COPY team_<tenant> team_<tenant>__snap_<ts>; writes Snapshot node in commons; returns snapshot graph name
def list_snapshots(db: HiveDB, tenant: str) -> list[dict]

# hiveboard/temporal.py
def now_ms() -> int
def iso_to_ms(s: str) -> int
def ms_to_iso(ms: int) -> str

# hiveboard/memory.py   (episodic + semantic)
def remember_person(db, tenant, person: dict) -> str                 # {id?, name, role?}
def remember_meeting(db, tenant, meeting: dict) -> str               # {id?, title, started_at, ended_at?, source_uri?}
def remember_episodes(db, tenant, meeting_id: str, episodes: list[dict]) -> int
    # episode: {id?, seq, speaker_id, text, t_start, t_end, t_occurred, embedding?}; creates HAS_EPISODE, SPOKEN_BY, NEXT
def remember_entities(db, tenant, entities: list[dict]) -> int       # {id?, name, type, embedding?}; MERGE on name
def link_mentions(db, tenant, episode_id: str, entity_ids: list[str]) -> int
def remember_fact(db, tenant, fact: dict) -> dict
    # fact: {id?, subject, predicate, object, text, confidence, speaker_id, episode_id, entity_ids: list[str],
    #        kind: "fact"|"decision"|"commitment", due_at?: int, valid_from?: int, embedding?}
    # key = f"{subject}|{predicate}" lowercased. If an ACTIVE fact with the same key and different object exists,
    # the caller decides: pass supersede=True to expire it and link SUPERSEDES. Returns {"id", "superseded": [ids]}.
def supersede_fact(db, tenant, old_id: str, new_fact: dict) -> dict  # explicit supersession (12_supersede_fact.cypher)
def retract_fact(db, tenant, fact_id: str, reason: str) -> None
def active_facts(db, tenant, entity_id: str | None = None, key: str | None = None) -> list[dict]
def belief_at(db, tenant, t: int, entity_id: str | None = None) -> list[dict]      # 31_belief_at_time.cypher
def why(db, tenant, node_id: str) -> dict
    # {"node": {...}, "speaker": {...}, "meeting": {...}, "episode": {...}, "history": [facts in SUPERSEDES chain],
    #  "cypher": "<query text>", "subgraph": {"nodes": [...], "edges": [...]}}
def recall(db, tenant, query_embedding: list[float], k: int = 8, now: int | None = None, label: str = "Fact") -> dict
    # hybrid: vector KNN -> 1-hop expansion -> hive.score() -> ranked; returns {"items": [...], "cypher": str, "subgraph": {...}}
def fulltext(db, tenant, text: str, label: str = "Episode", k: int = 10) -> list[dict]

# hiveboard/board.py   (coordination; A2A-shaped states: submitted | working | input_required | completed | failed)
def register_agent(db, tenant, agent_id: str, name: str, capabilities: list[str], model: str) -> None
def submit_task(db, tenant, kind: str, payload: dict, requires: list[str], about_ids: list[str] = (), priority: int = 5) -> str
def claim(db, tenant, task_id: str, agent_id: str, expected_version: int) -> int | None   # CAS; None = lost the race
def next_open_task(db, tenant, agent_id: str) -> dict | None     # oldest submitted task whose REQUIRES ⊆ agent HAS
def handoff(db, tenant, task_id: str, from_agent: str, to_agent: str, expected_version: int, summary: str, subgraph_ids: list[str]) -> int | None
def complete(db, tenant, task_id: str, agent_id: str, artifact: dict | None = None) -> None   # artifact: {kind, uri?, text?}
def fail(db, tenant, task_id: str, agent_id: str, reason: str) -> None
def need_input(db, tenant, task_id: str, agent_id: str, question: str) -> None
def list_tasks(db, tenant, status: str | None = None, limit: int = 50) -> list[dict]
def list_agents(db, tenant) -> list[dict]
def task_trace(db, tenant, task_id: str) -> dict           # claims, handoffs, artifacts, used skills, in order

# hiveboard/skills.py   (procedural memory)
def learn_skill(db, tenant, goal: str, steps: list[dict], learned_from: list[str], embedding: list[float] | None, version: int = 1) -> str
    # step: {order, tool, args_template (json str), guard?}
def retrieve_skill(db, tenant, goal_embedding: list[float], k: int = 3) -> list[dict]   # best active by success_rate then distance, with steps
def record_outcome(db, tenant, skill_id: str, agent_id: str, ok: bool, task_id: str | None = None) -> dict  # updates runs, success_rate; RAN edge
def deprecate_skill(db, tenant, old_id: str, new_id: str) -> None
def skill_pagerank(db, tenant) -> list[dict]               # algo.pageRank over Skill via USED edges
def publish_to_commons(db, tenant, skill_id: str) -> str   # copies Skill+Steps into commons graph with origin tenant

# hiveboard/events.py   (Redis pub/sub on the same server)
def publish(db, tenant, event: str, payload: dict) -> None          # channel f"team_{tenant}:events", JSON {event, payload, ts}
def subscribe(db, tenant) -> Iterator[dict]                           # blocking generator; async variant asubscribe()
# Event names: episode.ingested, fact.created, fact.superseded, commitment.created, commitment.updated,
#              task.submitted, task.claimed, task.handed_off, task.completed, task.failed, skill.learned, skill.ran

# hiveboard/analytics.py   (Track 3 queries)
def who_knows(db, tenant, entity_name: str) -> list[dict]
def open_commitments(db, tenant, person_id: str | None = None) -> list[dict]
def contradictions(db, tenant) -> list[dict]           # two ACTIVE facts, same key, different object
def entity_clusters(db, tenant) -> list[dict]          # algo.WCC over Entity co-mention
def stale_decisions(db, tenant, older_than_ms: int) -> list[dict]
```

Conventions
- Every function that runs Cypher attaches the query text to its return under `"cypher"` when the result is shown to users (why, recall, belief_at, analytics). The UI renders it.
- Write queries use `UNWIND $rows AS r MERGE ...` with parameters; never string-format values into Cypher.
- Read paths for user-facing answers use `graph.ro_query` with `timeout=3000`.
- `hive.score(valid_from, confidence, distance, now)` is the UDF in `hiveboard/udf/score.js`: `recency * importance * similarity`, where recency = exp(-age_days/30), importance = confidence, similarity = 1 - distance (clamped). Higher is better.
