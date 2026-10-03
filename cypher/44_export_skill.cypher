// 44_export_skill: read a skill with its steps and provenance ids (used by publish_to_commons and list views). Params: $id.
MATCH (s:Skill {id: $id})
OPTIONAL MATCH (s)-[st:STEP]->(step:Step)
WITH s, collect({order: st.order, id: step.id, tool: step.tool, args_template: step.args_template, guard: step.guard}) AS steps
OPTIONAL MATCH (s)-[:LEARNED_FROM]->(o)
RETURN s, steps, collect(DISTINCT o.id) AS learned_from
