// 04_upsert_entity: MERGE entities on the normalised key `name_key = lower(trim(name))`; `name` keeps the display form
// of the first mention. Params: $now, $rows = [{id, name, name_key, type?, embedding?}].
// The id is only assigned on create: an existing entity keeps its id. Returns the effective id per input name.
UNWIND $rows AS r
MERGE (e:Entity {name_key: r.name_key})
ON CREATE SET e.id = r.id, e.name = r.name, e.created_at = $now
SET e.type = coalesce(r.type, e.type),
    e.embedding = CASE WHEN r.embedding IS NULL THEN e.embedding ELSE vecf32(r.embedding) END
RETURN r.name AS name, e.id AS id
