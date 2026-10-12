// 2A_reap_tasks: return WORKING tasks whose lease expired to 'submitted' (unaddressed) so another agent can claim them.
// Params: $now, $lease_ms (fallback lease for tasks claimed before leases existed: updated_at + $lease_ms).
// version + 1 invalidates the stale owner's CAS; owner_agent is cleared; a (t)-[:LEASE_EXPIRED {at, agent}]->(Agent) edge keeps the trace.
MATCH (t:Task {status: 'working'})
WHERE coalesce(t.lease_until, t.updated_at + $lease_ms) < $now
WITH t, t.owner_agent AS owner
OPTIONAL MATCH (a:Agent {id: owner})
SET t.status = 'submitted', t.version = t.version + 1, t.owner_agent = NULL, t.lease_until = NULL, t.updated_at = $now,
    t.lease_expired_at = $now
FOREACH (x IN CASE WHEN a IS NULL THEN [] ELSE [a] END | CREATE (t)-[:LEASE_EXPIRED {at: $now, agent: owner}]->(x))
RETURN t.id AS id, owner AS agent, t.version AS version
