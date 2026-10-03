// 25_register_agent: upsert an Agent and its capabilities (Agent -[:HAS]-> Capability). Params: $id, $name, $model, $caps, $now.
MERGE (a:Agent {id: $id})
SET a.name = $name, a.model = $model, a.last_seen = $now
WITH a
UNWIND (CASE WHEN size($caps) = 0 THEN [NULL] ELSE $caps END) AS cap
FOREACH (c IN CASE WHEN cap IS NULL THEN [] ELSE [cap] END | MERGE (k:Capability {name: c}) MERGE (a)-[:HAS]->(k))
RETURN DISTINCT a.id AS id
