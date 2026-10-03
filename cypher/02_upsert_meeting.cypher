// 02_upsert_meeting: upsert a Meeting (episode container for utterances). Params: $rows = [{id, title, started_at, ended_at?, source_uri?}].
UNWIND $rows AS r
MERGE (m:Meeting {id: r.id})
SET m.title = r.title, m.started_at = r.started_at, m.ended_at = r.ended_at, m.source_uri = r.source_uri
RETURN m.id AS id
