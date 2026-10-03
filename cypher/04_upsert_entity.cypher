// 04_upsert_entity: MERGE entities on name (caller normalises case/whitespace). Params: $now, $rows = [{id, name, type?, embedding?}].
// The id is only assigned on create: an existing entity keeps its id. Returns the effective id per name.
UNWIND $rows AS r
MERGE (e:Entity {name: r.name})
ON CREATE SET e.id = r.id, e.created_at = $now
SET e.type = coalesce(r.type, e.type),
    e.embedding = CASE WHEN r.embedding IS NULL THEN e.embedding ELSE vecf32(r.embedding) END
RETURN r.name AS name, e.id AS id
