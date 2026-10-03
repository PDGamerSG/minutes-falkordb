// 14_active_facts: ACTIVE facts, optionally filtered by entity id and/or key, with speaker and source container. Params: $entity, $key, $limit.
// Nodes are returned as map projections without the 768-d embedding (returning whole nodes costs ~0.5 ms per node on the wire).
MATCH (f:Fact {status: 'active'})
WHERE $key IS NULL OR f.key = $key
OPTIONAL MATCH (f)-[:ABOUT]->(en:Entity)
WITH f, collect(DISTINCT en {.id, .name, .type, labels: labels(en)}) AS entities
WHERE $entity IS NULL OR any(x IN entities WHERE x.id = $entity)
OPTIONAL MATCH (f)-[:STATED_BY]->(p:Person)
OPTIONAL MATCH (f)-[:DERIVED_FROM]->(ep:Episode)
OPTIONAL MATCH (c)-[:HAS_EPISODE]->(ep)
RETURN f {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to, .created_at,
          .expired_at, .due_at, .decided_at, .retract_reason, labels: labels(f), has_embedding: f.embedding IS NOT NULL} AS f,
       entities,
       p {.id, .name, .role, .email, labels: labels(p)} AS speaker,
       ep.id AS episode_id,
       c {.id, .title, .subject, .source_uri, .started_at, labels: labels(c)} AS container
ORDER BY f.valid_from DESC
LIMIT $limit
