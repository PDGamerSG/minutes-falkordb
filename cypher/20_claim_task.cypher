// 20_claim_task: compare-and-set claim. Zero rows = another agent won, the task is no longer submitted at this version,
// or it was handed off to a different agent (owner_agent is the addressee after a handoff).
// Params: $id (task), $v (expected version), $agent, $now, $lease_ms. FalkorDB serialises writes per graph, so exactly one
// claimant sees the row. The claim carries a lease (lease_until); board.heartbeat extends it, board.reap_expired reclaims it.
MATCH (t:Task {id: $id, status: 'submitted', version: $v})
WHERE t.owner_agent IS NULL OR t.owner_agent = $agent
WITH t
MATCH (a:Agent {id: $agent})
SET t.status = 'working', t.version = $v + 1, t.owner_agent = $agent, t.updated_at = $now, t.lease_until = $now + $lease_ms
CREATE (t)-[:CLAIMED_BY {at: $now}]->(a)
RETURN t.version AS version
