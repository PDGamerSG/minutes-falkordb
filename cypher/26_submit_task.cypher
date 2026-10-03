// 26_submit_task: create a Task in A2A state 'submitted' (version 0) with REQUIRES capabilities and ABOUT links.
// Params: $id, $kind, $payload (JSON string), $requires, $about_ids, $priority, $now.
CREATE (t:Task {id: $id, kind: $kind, status: 'submitted', version: 0, owner_agent: NULL, priority: $priority,
                payload: $payload, created_at: $now, updated_at: $now})
WITH t
UNWIND (CASE WHEN size($requires) = 0 THEN [NULL] ELSE $requires END) AS req
FOREACH (c IN CASE WHEN req IS NULL THEN [] ELSE [req] END | MERGE (k:Capability {name: c}) MERGE (t)-[:REQUIRES]->(k))
WITH DISTINCT t
UNWIND (CASE WHEN size($about_ids) = 0 THEN [NULL] ELSE $about_ids END) AS aid
OPTIONAL MATCH (x {id: aid})
FOREACH (y IN CASE WHEN x IS NULL THEN [] ELSE [x] END | MERGE (t)-[:ABOUT]->(y))
RETURN DISTINCT t.id AS id
