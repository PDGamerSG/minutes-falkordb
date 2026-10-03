// 53_stale_decisions: ACTIVE decisions decided before $cutoff (epoch ms) that nothing has superseded. Params: $cutoff.
MATCH (d:Fact:Decision {status: 'active'})
WHERE coalesce(d.decided_at, d.valid_from) < $cutoff
OPTIONAL MATCH (d)-[:MADE_BY]->(p:Person)
OPTIONAL MATCH (d)-[:ABOUT]->(en:Entity)
RETURN d {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to, .created_at,
          .expired_at, .due_at, .decided_at, labels: labels(d), has_embedding: d.embedding IS NOT NULL} AS d,
       p {.id, .name, .role, .email, labels: labels(p)} AS decider,
       collect(DISTINCT en {.id, .name, .type, labels: labels(en)}) AS entities
ORDER BY coalesce(d.decided_at, d.valid_from) ASC
