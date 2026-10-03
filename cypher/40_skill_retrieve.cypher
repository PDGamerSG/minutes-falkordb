// 40_skill_retrieve: best ACTIVE skills for a goal: vector KNN over Skill.embedding, ordered by success_rate then distance, with steps.
// Params: $goal (768 floats), $n (candidates), $k (results). Steps with a NULL id come from skills without steps; the caller drops them.
CALL db.idx.vector.queryNodes('Skill', 'embedding', $n, vecf32($goal)) YIELD node AS s, score AS distance
WHERE s.status = 'active'
OPTIONAL MATCH (s)-[st:STEP]->(step:Step)
WITH s, distance, collect({order: st.order, id: step.id, tool: step.tool, args_template: step.args_template, guard: step.guard}) AS steps
RETURN s {.id, .goal, .version, .runs, .success_rate, .status, .created_at, .last_run_at, labels: labels(s), has_embedding: true} AS s,
       distance, steps
ORDER BY s.success_rate DESC, distance ASC
LIMIT $k
