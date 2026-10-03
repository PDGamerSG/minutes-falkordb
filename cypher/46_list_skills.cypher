// 46_list_skills: every skill with ordered steps and provenance ids, for the skills page. Params: $status (or NULL).
MATCH (s:Skill)
WHERE $status IS NULL OR s.status = $status
OPTIONAL MATCH (s)-[st:STEP]->(step:Step)
WITH s, collect({order: st.order, id: step.id, tool: step.tool, args_template: step.args_template, guard: step.guard}) AS steps
OPTIONAL MATCH (s)-[:LEARNED_FROM]->(o)
RETURN s {.id, .goal, .version, .runs, .success_rate, .status, .created_at, .last_run_at, .deprecated_at,
          labels: labels(s), has_embedding: s.embedding IS NOT NULL} AS s,
       steps, collect(DISTINCT o.id) AS learned_from
ORDER BY s.created_at DESC
