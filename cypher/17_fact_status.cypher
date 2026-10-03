// 17_fact_status: existence and status check for a fact before an explicit supersession. Params: $id.
MATCH (f:Fact {id: $id})
RETURN f.id AS id, f.status AS status, f.key AS key, f.object AS object
