// 51_open_commitments: ACTIVE commitments with owner and the person who stated them, optionally for one person, soonest due first. Params: $person (or NULL).
MATCH (c:Fact:Commitment {status: 'active'})
OPTIONAL MATCH (c)-[:OWNED_BY]->(p:Person)
WITH c, p
WHERE $person IS NULL OR p.id = $person
OPTIONAL MATCH (c)-[:STATED_BY]->(sp:Person)
WITH c, p, sp
OPTIONAL MATCH (c)-[:ABOUT]->(en:Entity)
RETURN c {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to, .created_at,
          .expired_at, .due_at, labels: labels(c), has_embedding: c.embedding IS NOT NULL} AS c,
       p {.id, .name, .role, .email, labels: labels(p)} AS owner,
       sp {.id, .name, .role, .email, labels: labels(sp)} AS speaker,
       collect(DISTINCT en {.id, .name, .type, labels: labels(en)}) AS entities
ORDER BY coalesce(c.due_at, 9223372036854775807) ASC, c.valid_from DESC
