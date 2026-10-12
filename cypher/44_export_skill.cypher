// 44_export_skill: read a skill with its steps and provenance ids (get_skill, publish_to_commons). Params: $id, $with_embedding.
// By default the skill is a map projection without its 768-d embedding; publish_to_commons passes $with_embedding = true and
// receives the whole node (a vecf32 cannot be returned as a bare column).
MATCH (s:Skill {id: $id})
OPTIONAL MATCH (s)-[st:STEP]->(step:Step)
WITH s, collect({order: st.order, id: step.id, tool: step.tool, args_template: step.args_template, guard: step.guard}) AS steps
OPTIONAL MATCH (s)-[:LEARNED_FROM]->(o)
RETURN CASE WHEN $with_embedding THEN s ELSE s {.id, .goal, .version, .runs, .success_rate, .status, .created_at, .last_run_at,
          .deprecated_at, labels: labels(s), has_embedding: s.embedding IS NOT NULL} END AS s,
       steps, collect(DISTINCT o.id) AS learned_from
