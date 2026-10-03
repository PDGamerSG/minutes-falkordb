// 20_claim_task: compare-and-set claim. Zero rows = another agent won (or the task is no longer submitted at this version).
// Params: $id (task), $v (expected version), $agent, $now. FalkorDB serialises writes per graph, so exactly one claimant sees the row.
MATCH (t:Task {id: $id, status: 'submitted', version: $v})
MATCH (a:Agent {id: $agent})
SET t.status = 'working', t.version = $v + 1, t.owner_agent = $agent, t.updated_at = $now
CREATE (t)-[:CLAIMED_BY {at: $now}]->(a)
RETURN t.version AS version
