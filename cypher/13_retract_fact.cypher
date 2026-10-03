// 13_retract_fact: mark a fact as never-true (status 'retracted'); it drops out of belief_at for every T. Params: $id, $reason, $now.
MATCH (f:Fact {id: $id})
SET f.status = 'retracted', f.expired_at = $now, f.valid_to = coalesce(f.valid_to, $now), f.retract_reason = $reason
RETURN f.id AS id
