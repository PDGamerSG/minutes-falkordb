// 03_upsert_thread: upsert an EmailThread (episode container for email messages). Params: $rows = [{id, subject, started_at}].
UNWIND $rows AS r
MERGE (t:EmailThread {id: r.id})
SET t.subject = r.subject, t.started_at = r.started_at
RETURN t.id AS id
