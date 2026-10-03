// 28_list_tasks: tasks newest first, optional status filter. Params: $status (or NULL), $limit.
MATCH (t:Task)
WHERE $status IS NULL OR t.status = $status
OPTIONAL MATCH (t)-[:REQUIRES]->(c:Capability)
WITH t, collect(DISTINCT c.name) AS requires
OPTIONAL MATCH (t)-[:ABOUT]->(x)
RETURN t, requires, collect(DISTINCT x.id) AS about
ORDER BY t.created_at DESC
LIMIT $limit
