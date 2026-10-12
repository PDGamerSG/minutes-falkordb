// 1A_active_facts_for_entity: ACTIVE facts ABOUT one entity, anchored on the Entity id index (finding 12), optional key filter.
// Params: $entity, $key (or NULL), $limit. Same columns as 14_active_facts.
MATCH (anchor:Entity {id: $entity})<-[:ABOUT]-(f:Fact {status: 'active'})
WHERE $key IS NULL OR f.key = $key
WITH DISTINCT f
OPTIONAL MATCH (f)-[:ABOUT]->(en:Entity)
WITH f, collect(DISTINCT en {.id, .name, .type, labels: labels(en)}) AS entities
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
