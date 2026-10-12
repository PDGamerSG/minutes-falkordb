// 41_skill_outcome: record one run of a skill. success_rate is the running mean computed with the pre-increment run count.
// Params: $id (skill), $agent, $ok (1.0 or 0.0), $outcome ('ok'|'failed'), $task_id (or NULL), $now. Returns the skill without its embedding.
MATCH (s:Skill {id: $id})
WITH s, s.runs AS prev
SET s.runs = prev + 1,
    s.success_rate = ((s.success_rate * prev) + $ok) / (prev + 1),
    s.last_run_at = $now
WITH s
OPTIONAL MATCH (a:Agent {id: $agent})
FOREACH (x IN CASE WHEN a IS NULL THEN [] ELSE [a] END | CREATE (x)-[:RAN {at: $now, outcome: $outcome}]->(s))
WITH s
OPTIONAL MATCH (t:Task {id: $task_id})
FOREACH (x IN CASE WHEN t IS NULL THEN [] ELSE [t] END | MERGE (x)-[:USED]->(s))
RETURN s {.id, .goal, .version, .runs, .success_rate, .status, .created_at, .last_run_at, .deprecated_at,
          labels: labels(s), has_embedding: s.embedding IS NOT NULL} AS s
