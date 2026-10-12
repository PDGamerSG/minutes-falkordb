// 2B_heartbeat_task: the owner of a WORKING task extends its lease. Params: $id, $agent, $now, $lease_ms. Zero rows = not the owner / not working.
MATCH (t:Task {id: $id, owner_agent: $agent, status: 'working'})
SET t.lease_until = $now + $lease_ms
RETURN t.id AS id, t.lease_until AS lease_until
