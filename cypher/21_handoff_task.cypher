// 21_handoff_task: hand a WORKING task to another agent with a subgraph reference (ids of the nodes the receiver should read).
// Params: $id, $from (current owner), $to, $v (expected version), $now, $summary, $ids (subgraph node ids).
// The task returns to 'submitted' addressed to $to (owner_agent = $to) so only that agent can claim it (20 checks the addressee).
// Zero rows = stale version, not the owner, or the task is not 'working' (completed/failed/parked tasks cannot be handed off).
MATCH (t:Task {id: $id, owner_agent: $from, version: $v, status: 'working'})
WITH t
MATCH (to:Agent {id: $to})
SET t.owner_agent = $to, t.status = 'submitted', t.version = $v + 1, t.updated_at = $now, t.lease_until = NULL
CREATE (t)-[:HANDED_OFF {at: $now, from_agent: $from, summary: $summary, subgraph_ids: $ids}]->(to)
RETURN t.version AS version
