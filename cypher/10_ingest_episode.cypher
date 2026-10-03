// 10_ingest_episode: upsert Episodes under one container (Meeting or EmailThread) with provenance edges.
// Params: $container_id, $now, $rows = [{id, seq, text, t_start?, t_end?, t_occurred, source_kind ('utterance'|'email'|'doc_chunk'),
//   speaker_id? (utterance -> SPOKEN_BY + ATTENDED), sender_id? (email -> SENT_BY), recipients? [{id, cc}] (email -> SENT_TO{cc}),
//   in_reply_to_id? (email -> REPLIES_TO), prev_id? (-> NEXT chain), message_id?, embedding? (768 floats)}].
// Rows must be ordered by seq; the caller fills prev_id with the previous episode id. Returns the number of episodes touched.
UNWIND $rows AS r
MATCH (m {id: $container_id}) WHERE m:Meeting OR m:EmailThread
MERGE (e:Episode {id: r.id})
SET e.seq = r.seq, e.text = r.text, e.t_start = r.t_start, e.t_end = r.t_end,
    e.t_occurred = r.t_occurred, e.t_ingested = $now,
    e.source_kind = coalesce(r.source_kind, 'utterance'), e.message_id = r.message_id,
    e.embedding = CASE WHEN r.embedding IS NULL THEN e.embedding ELSE vecf32(r.embedding) END
MERGE (m)-[:HAS_EPISODE]->(e)
WITH m, e, r
OPTIONAL MATCH (sp:Person {id: r.speaker_id})
FOREACH (p IN CASE WHEN sp IS NULL THEN [] ELSE [sp] END | MERGE (e)-[:SPOKEN_BY]->(p) MERGE (p)-[:ATTENDED]->(m))
WITH e, r
OPTIONAL MATCH (sb:Person {id: r.sender_id})
FOREACH (p IN CASE WHEN sb IS NULL THEN [] ELSE [sb] END | MERGE (e)-[:SENT_BY]->(p))
WITH e, r
OPTIONAL MATCH (prev:Episode {id: r.prev_id})
FOREACH (p IN CASE WHEN prev IS NULL THEN [] ELSE [prev] END | MERGE (p)-[:NEXT]->(e))
WITH e, r
OPTIONAL MATCH (parent:Episode {id: r.in_reply_to_id})
FOREACH (p IN CASE WHEN parent IS NULL THEN [] ELSE [parent] END | MERGE (e)-[:REPLIES_TO]->(p))
WITH e, r
UNWIND (CASE WHEN size(coalesce(r.recipients, [])) = 0 THEN [NULL] ELSE r.recipients END) AS to
OPTIONAL MATCH (rcpt:Person {id: to.id})
FOREACH (p IN CASE WHEN rcpt IS NULL THEN [] ELSE [rcpt] END | MERGE (e)-[s:SENT_TO]->(p) SET s.cc = coalesce(to.cc, false))
RETURN count(DISTINCT e) AS episodes
