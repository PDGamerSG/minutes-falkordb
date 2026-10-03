// 70_record_snapshot: Snapshot metadata written into `commons` after GRAPH.COPY. Params: $id, $tenant, $graph_name, $label, $now.
MERGE (s:Snapshot {id: $id})
SET s.tenant = $tenant, s.graph_name = $graph_name, s.label = $label, s.taken_at = $now
RETURN s.graph_name AS name
