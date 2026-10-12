// 12_supersede_fact: explicit supersession in ONE statement: ingest the replacement and expire exactly $old_id.
// Params: $old_id, $now, $row = {id, kind, subject, predicate, object, object_norm, key, text, confidence, valid_from?, due_at?,
//   speaker_id?, owner_id?, episode_id?, entity_ids, embedding?}.
// Zero rows: $old_id does not exist. `error` is non-null and nothing is written when the old fact is not ACTIVE
// ('not_active', e.g. a concurrent writer superseded it first), the keys differ ('key_mismatch'), the new statement is valid
// from before the old one ('backdated': use chain insertion, 19), or new = old ('self'). Otherwise the new fact is created
// ACTIVE, the old one gets valid_to = new.valid_from (valid time) and expired_at = $now (transaction time), and
// new -[:SUPERSEDES {at}]-> old is linked.
MATCH (old:Fact {id: $old_id})
OPTIONAL MATCH (ep:Episode {id: $row.episode_id})
OPTIONAL MATCH (m:Meeting)-[:HAS_EPISODE]->(ep)
OPTIONAL MATCH (sp:Person {id: $row.speaker_id})
OPTIONAL MATCH (ow:Person {id: coalesce($row.owner_id, $row.speaker_id)})
WITH old, ep, m, sp, ow, coalesce($row.valid_from, ep.t_occurred, $now) AS vf
OPTIONAL MATCH (en:Entity) WHERE en.id IN $row.entity_ids
WITH old, ep, m, sp, ow, vf, collect(en) AS ens
WITH old, ep, m, sp, ow, vf, ens,
     CASE WHEN old.id = $row.id THEN 'self'
          WHEN old.status <> 'active' THEN 'not_active'
          WHEN old.key <> $row.key THEN 'key_mismatch'
          WHEN vf < old.valid_from THEN 'backdated'
          ELSE NULL END AS error
WITH old, ep, m, sp, ow, vf, ens, error, CASE WHEN error IS NULL THEN [$row] ELSE [] END AS rows
FOREACH (r IN rows |
  MERGE (f:Fact {id: r.id})
  ON CREATE SET f.created_at = $now, f.status = 'active', f.kind = r.kind, f.subject = r.subject, f.predicate = r.predicate,
                f.object = r.object, f.key = r.key, f.valid_from = vf
  SET f.text = coalesce(r.text, f.text), f.confidence = coalesce(r.confidence, f.confidence), f.due_at = coalesce(r.due_at, f.due_at),
      f.embedding = CASE WHEN r.embedding IS NULL THEN f.embedding ELSE vecf32(r.embedding) END
  FOREACH (_ IN CASE WHEN r.kind = 'decision' THEN [1] ELSE [] END | SET f:Decision SET f.decided_at = coalesce(f.decided_at, vf))
  FOREACH (_ IN CASE WHEN r.kind = 'commitment' THEN [1] ELSE [] END | SET f:Commitment))
WITH old, ep, m, sp, ow, vf, ens, error, rows
OPTIONAL MATCH (f:Fact {id: $row.id})
WITH old, ep, m, sp, ow, vf, ens, error, CASE WHEN size(rows) = 0 THEN NULL ELSE f END AS f
FOREACH (x IN CASE WHEN f IS NULL OR ep IS NULL THEN [] ELSE [ep] END | MERGE (f)-[:DERIVED_FROM]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR m IS NULL OR $row.kind <> 'decision' THEN [] ELSE [m] END | MERGE (f)-[:DECIDED_IN]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR sp IS NULL THEN [] ELSE [sp] END | MERGE (f)-[:STATED_BY]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR sp IS NULL OR $row.kind <> 'decision' THEN [] ELSE [sp] END | MERGE (f)-[:MADE_BY]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR ow IS NULL OR $row.kind <> 'commitment' THEN [] ELSE [ow] END | MERGE (f)-[:OWNED_BY]->(x))
FOREACH (x IN CASE WHEN f IS NULL THEN [] ELSE ens END | MERGE (f)-[:ABOUT]->(x))
FOREACH (o IN CASE WHEN f IS NULL THEN [] ELSE [old] END |
  SET o.valid_to = vf, o.expired_at = $now, o.status = 'superseded'
  MERGE (f)-[s:SUPERSEDES]->(o) SET s.at = $now)
RETURN $row.id AS id, error, old.id AS old_id, old.object AS old_object, old.due_at AS old_due_at, old.valid_from AS old_valid_from,
       vf AS valid_from, f IS NOT NULL AS written
