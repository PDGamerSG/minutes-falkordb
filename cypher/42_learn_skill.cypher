// 42_learn_skill: create a Skill (procedural memory) with ordered Steps and LEARNED_FROM provenance.
// Params: $id, $goal, $version, $embedding (or NULL), $steps [{id, order, tool, args_template, guard}], $learned_from [ids], $now.
CREATE (s:Skill {id: $id, goal: $goal, version: $version, runs: 0, success_rate: 0.0, status: 'active', created_at: $now})
SET s.embedding = CASE WHEN $embedding IS NULL THEN NULL ELSE vecf32($embedding) END
WITH s
UNWIND (CASE WHEN size($steps) = 0 THEN [NULL] ELSE $steps END) AS st
FOREACH (x IN CASE WHEN st IS NULL THEN [] ELSE [st] END |
  CREATE (step:Step {id: x.id, order: x.order, tool: x.tool, args_template: x.args_template, guard: x.guard})
  CREATE (s)-[:STEP {order: x.order}]->(step))
WITH DISTINCT s
UNWIND (CASE WHEN size($learned_from) = 0 THEN [NULL] ELSE $learned_from END) AS src
OPTIONAL MATCH (o {id: src})
FOREACH (x IN CASE WHEN o IS NULL THEN [] ELSE [o] END | MERGE (s)-[:LEARNED_FROM]->(x))
RETURN DISTINCT s.id AS id
