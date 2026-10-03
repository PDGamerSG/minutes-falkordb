// 11_ingest_fact: upsert semantic memory nodes (Fact, plus :Decision or :Commitment label by kind) with provenance.
// Params: $now, $rows = [{id, kind ('fact'|'decision'|'commitment'), subject, predicate, object, key, text, confidence,
//   valid_from? (defaults to the episode's t_occurred, then $now), due_at?, speaker_id? (-> STATED_BY; MADE_BY for decisions),
//   owner_id? (-> OWNED_BY for commitments, defaults to speaker), episode_id? (-> DERIVED_FROM; DECIDED_IN meeting for decisions),
//   entity_ids? (-> ABOUT), embedding?}].
// Bi-temporal: valid_from/valid_to = when it was true; created_at/expired_at = when we learned/unlearned it. Returns count.
UNWIND $rows AS r
OPTIONAL MATCH (ep:Episode {id: r.episode_id})
OPTIONAL MATCH (m:Meeting)-[:HAS_EPISODE]->(ep)
MERGE (f:Fact {id: r.id})
ON CREATE SET f.created_at = $now, f.status = 'active', f.valid_to = NULL, f.expired_at = NULL
SET f.kind = r.kind, f.subject = r.subject, f.predicate = r.predicate, f.object = r.object, f.key = r.key,
    f.text = r.text, f.confidence = r.confidence, f.due_at = r.due_at,
    f.valid_from = coalesce(r.valid_from, ep.t_occurred, $now),
    f.embedding = CASE WHEN r.embedding IS NULL THEN f.embedding ELSE vecf32(r.embedding) END
FOREACH (_ IN CASE WHEN r.kind = 'decision' THEN [1] ELSE [] END | SET f:Decision SET f.decided_at = coalesce(r.valid_from, ep.t_occurred, $now))
FOREACH (_ IN CASE WHEN r.kind = 'commitment' THEN [1] ELSE [] END | SET f:Commitment)
FOREACH (x IN CASE WHEN ep IS NULL THEN [] ELSE [ep] END | MERGE (f)-[:DERIVED_FROM]->(x))
FOREACH (x IN CASE WHEN m IS NULL OR r.kind <> 'decision' THEN [] ELSE [m] END | MERGE (f)-[:DECIDED_IN]->(x))
WITH f, r
OPTIONAL MATCH (sp:Person {id: r.speaker_id})
FOREACH (x IN CASE WHEN sp IS NULL THEN [] ELSE [sp] END | MERGE (f)-[:STATED_BY]->(x))
FOREACH (x IN CASE WHEN sp IS NULL OR r.kind <> 'decision' THEN [] ELSE [sp] END | MERGE (f)-[:MADE_BY]->(x))
WITH f, r
OPTIONAL MATCH (ow:Person {id: coalesce(r.owner_id, r.speaker_id)})
FOREACH (x IN CASE WHEN ow IS NULL OR r.kind <> 'commitment' THEN [] ELSE [ow] END | MERGE (f)-[:OWNED_BY]->(x))
WITH f, r
UNWIND (CASE WHEN size(coalesce(r.entity_ids, [])) = 0 THEN [NULL] ELSE r.entity_ids END) AS eid
OPTIONAL MATCH (en:Entity {id: eid})
FOREACH (x IN CASE WHEN en IS NULL THEN [] ELSE [en] END | MERGE (f)-[:ABOUT]->(x))
RETURN count(DISTINCT f) AS facts
