// 71_list_snapshots: snapshots of one tenant from `commons`, newest first. Params: $tenant.
MATCH (s:Snapshot {tenant: $tenant})
RETURN s.id AS id, s.graph_name AS name, s.label AS label, s.taken_at AS taken_at
ORDER BY s.taken_at DESC
