// 31_belief_at_time: what was true at valid time $t (bi-temporal). Params: $t, $entity (or NULL), $known_by (or NULL).
// valid_from <= t < valid_to selects facts true at T; $known_by additionally restricts to what had been ingested by that time.
// Retracted facts are excluded for every T; superseded facts still count inside their validity window.
MATCH (f:Fact)
WHERE f.status <> 'retracted'
  AND f.valid_from <= $t AND (f.valid_to IS NULL OR f.valid_to > $t)
  AND ($known_by IS NULL OR f.created_at <= $known_by)
OPTIONAL MATCH (f)-[:ABOUT]->(en:Entity)
WITH f, collect(DISTINCT en {.id, .name, .type, labels: labels(en)}) AS entities
WHERE $entity IS NULL OR any(x IN entities WHERE x.id = $entity)
OPTIONAL MATCH (f)-[:STATED_BY]->(p:Person)
RETURN f {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to, .created_at,
          .expired_at, .due_at, .decided_at, .retract_reason, labels: labels(f), has_embedding: f.embedding IS NOT NULL} AS f,
       entities,
       p {.id, .name, .role, .email, labels: labels(p)} AS speaker
ORDER BY f.valid_from DESC
