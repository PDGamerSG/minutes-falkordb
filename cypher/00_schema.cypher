// Minutes / Hive Board schema. Run once per tenant graph (idempotent: FalkorDB ignores duplicate index creation errors in ensure_schema).
// Validated on FalkorDB 6.0.1 on 2026-10-03. Vector score returned by db.idx.vector.queryNodes is a DISTANCE (lower = closer).
// One statement per line; comment lines start with //. hiveboard.schema.ensure_schema runs every statement and then the constraints below.

// Range indexes (exact match, ranges, IN)
CREATE INDEX FOR (n:Person) ON (n.id)
CREATE INDEX FOR (n:Person) ON (n.email)
CREATE INDEX FOR (n:Meeting) ON (n.id)
CREATE INDEX FOR (n:Meeting) ON (n.started_at)
CREATE INDEX FOR (n:EmailThread) ON (n.id)
CREATE INDEX FOR (n:Episode) ON (n.id)
CREATE INDEX FOR (n:Episode) ON (n.t_occurred)
CREATE INDEX FOR (n:Episode) ON (n.source_kind)
CREATE INDEX FOR (n:Entity) ON (n.id)
CREATE INDEX FOR (n:Entity) ON (n.name)
CREATE INDEX FOR (n:Fact) ON (n.id)
CREATE INDEX FOR (n:Fact) ON (n.status)
CREATE INDEX FOR (n:Fact) ON (n.valid_from)
CREATE INDEX FOR (n:Fact) ON (n.valid_to)
CREATE INDEX FOR (n:Fact) ON (n.key)
CREATE INDEX FOR (n:Decision) ON (n.id)
CREATE INDEX FOR (n:Commitment) ON (n.id)
CREATE INDEX FOR (n:Commitment) ON (n.status)
CREATE INDEX FOR (n:Commitment) ON (n.due_at)
CREATE INDEX FOR (n:Task) ON (n.id)
CREATE INDEX FOR (n:Task) ON (n.status)
CREATE INDEX FOR (n:Agent) ON (n.id)
CREATE INDEX FOR (n:Capability) ON (n.name)
CREATE INDEX FOR (n:Skill) ON (n.id)
CREATE INDEX FOR (n:Skill) ON (n.status)
CREATE INDEX FOR (n:Step) ON (n.id)
CREATE INDEX FOR (n:Artifact) ON (n.id)
CREATE INDEX FOR (n:Snapshot) ON (n.id)
CREATE INDEX FOR (n:Snapshot) ON (n.tenant)
CREATE INDEX FOR (n:Tenant) ON (n.slug)

CREATE INDEX FOR (n:WorkItem) ON (n.id)
CREATE INDEX FOR (n:Document) ON (n.id)
CREATE INDEX FOR (n:FollowUpDraft) ON (n.id)

// Full-text (RediSearch). Sanitize query strings: a bare underscore breaks the tokenizer.
CREATE FULLTEXT INDEX FOR (n:Episode) ON (n.text)
CREATE FULLTEXT INDEX FOR (n:Fact) ON (n.text)
CREATE FULLTEXT INDEX FOR (n:Decision) ON (n.text)

// Vector (HNSW). EmbeddingGemma = 768 dims, normalized -> cosine.
CREATE VECTOR INDEX FOR (n:Episode) ON (n.embedding) OPTIONS {dimension:768, similarityFunction:'cosine'}
CREATE VECTOR INDEX FOR (n:Fact) ON (n.embedding) OPTIONS {dimension:768, similarityFunction:'cosine'}
CREATE VECTOR INDEX FOR (n:Skill) ON (n.embedding) OPTIONS {dimension:768, similarityFunction:'cosine'}
CREATE VECTOR INDEX FOR (n:Entity) ON (n.embedding) OPTIONS {dimension:768, similarityFunction:'cosine'}

// Unique constraints are created with the Redis command (needs the exact-match index above first):
// GRAPH.CONSTRAINT CREATE <graph> UNIQUE NODE Person PROPERTIES 1 id
// ... same for Meeting, EmailThread, Episode, Entity, Fact, Decision, Commitment, Task, Agent, Skill, Step, Artifact, Snapshot
// (hiveboard.schema.UNIQUE_ID_LABELS is the list the code applies.)
