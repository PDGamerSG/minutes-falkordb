// 22_complete_task: owner completes a task, optionally producing an Artifact. Params: $id, $agent, $now, $artifact ({id, kind, uri?, text?} or NULL).
MATCH (t:Task {id: $id, owner_agent: $agent})
WHERE t.status IN ['working', 'input_required']
SET t.status = 'completed', t.version = t.version + 1, t.updated_at = $now, t.completed_at = $now
FOREACH (art IN CASE WHEN $artifact IS NULL THEN [] ELSE [$artifact] END |
  CREATE (ar:Artifact {id: art.id, kind: art.kind, uri: art.uri, text: art.text, created_at: $now})
  CREATE (t)-[:PRODUCED]->(ar))
RETURN t.version AS version
