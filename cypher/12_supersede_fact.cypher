// 12_supersede_fact: expire ACTIVE facts and link the replacement (already ingested with 11_ingest_fact) to them.
// Params: $new_id, $old_ids, $now. valid_to = when the new statement took effect (new.valid_from); expired_at = now (transaction time).
// Returns the ids actually superseded.
MATCH (new:Fact {id: $new_id})
UNWIND $old_ids AS oid
MATCH (old:Fact {id: oid})
WHERE old.id <> new.id AND old.status = 'active'
SET old.valid_to = coalesce(new.valid_from, $now), old.expired_at = $now, old.status = 'superseded'
MERGE (new)-[s:SUPERSEDES]->(old)
SET s.at = $now
RETURN collect(old.id) AS superseded
