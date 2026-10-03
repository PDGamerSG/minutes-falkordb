// 01_upsert_person: upsert Person nodes by id. Params: $rows = [{id, name, role?, email?}]. Returns ids.
UNWIND $rows AS r
MERGE (p:Person {id: r.id})
SET p.name = coalesce(r.name, p.name),
    p.role = coalesce(r.role, p.role),
    p.email = coalesce(r.email, p.email)
RETURN p.id AS id
