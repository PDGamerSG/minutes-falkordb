// 45_import_skill_commons: write a published skill into the shared `commons` graph with its origin tenant.
// Params: $id, $goal, $version, $origin_tenant, $origin_id, $runs, $success_rate, $embedding (or NULL), $steps, $now.
MERGE (s:Skill {id: $id})
SET s.goal = $goal, s.version = $version, s.status = 'active', s.origin_tenant = $origin_tenant, s.origin_id = $origin_id,
    s.runs = $runs, s.success_rate = $success_rate, s.published_at = $now,
    s.embedding = CASE WHEN $embedding IS NULL THEN s.embedding ELSE vecf32($embedding) END
WITH s
OPTIONAL MATCH (s)-[old:STEP]->(oldstep:Step)
DELETE old, oldstep
WITH DISTINCT s
UNWIND (CASE WHEN size($steps) = 0 THEN [NULL] ELSE $steps END) AS st
FOREACH (x IN CASE WHEN st IS NULL THEN [] ELSE [st] END |
  CREATE (step:Step {id: x.id, order: x.order, tool: x.tool, args_template: x.args_template, guard: x.guard})
  CREATE (s)-[:STEP {order: x.order}]->(step))
RETURN DISTINCT s.id AS id
