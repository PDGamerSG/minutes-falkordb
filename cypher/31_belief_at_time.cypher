// 31_belief_at_time: what was true at valid time $t (bi-temporal). Params: $t, $entity (or NULL), $known_by (or NULL), $limit.
// valid_from <= t < valid_to selects facts true at T. $known_by restricts to what had been ingested by that time (created_at <= K)
// and, because supersession and retraction are only learned at expired_at, a fact expired AFTER K still counts as believed at K
// (finding 3). Without $known_by, retracted facts are excluded for every T and superseded facts count inside their window.
MATCH (f:Fact)
WHERE f.valid_from <= $t
  AND ($known_by IS NULL OR f.created_at <= $known_by)
  AND (f.status <> 'retracted' OR ($known_by IS NOT NULL AND f.expired_at > $known_by))
  AND (f.valid_to IS NULL OR f.valid_to > $t OR ($known_by IS NOT NULL AND f.expired_at > $known_by))
WITH f
OPTIONAL MATCH (f)-[:ABOUT]->(en:Entity)
WITH f, collect(DISTINCT en {.id, .name, .type, labels: labels(en)}) AS entities
WHERE $entity IS NULL OR any(x IN entities WHERE x.id = $entity)
OPTIONAL MATCH (f)-[:STATED_BY]->(p:Person)
RETURN f {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to, .created_at,
          .expired_at, .due_at, .decided_at, .retract_reason, labels: labels(f), has_embedding: f.embedding IS NOT NULL} AS f,
       entities,
       p {.id, .name, .role, .email, labels: labels(p)} AS speaker
ORDER BY f.valid_from DESC
LIMIT $limit
