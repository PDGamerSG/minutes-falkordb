// 18_remember_fact: lookup + ingest + optional supersession of the ACTIVE facts sharing a key, in ONE statement so
// FalkorDB's per-graph write serialisation keeps "one active fact per key" true under concurrent writers (finding 2).
// Params: $now, $supersede (bool), $explicit_id (bool: the caller supplied the id),
//   $row = {id, kind, subject, predicate, object, object_norm (lower(trim(object))), key, text, confidence, valid_from?, due_at?,
//          speaker_id?, owner_id?, episode_id?, entity_ids, embedding?}.
// Outcomes (always one row):
//   existing  - an identical ACTIVE fact (same key, same normalised object) exists and no explicit id was given:
//               nothing is written, `id` is the existing fact's id.
//   backdated - $supersede is set but an active conflict is valid from later than this statement: nothing is written
//               (the caller must use chain insertion, 19) and the caller raises Conflict.
//   otherwise - MERGE the fact (identity and bi-temporal fields ON CREATE only, finding 8) with its provenance edges;
//               with $supersede every conflicting active fact gets valid_to = new.valid_from, expired_at = $now,
//               status 'superseded' and new -[:SUPERSEDES {at}]-> old. Without $supersede the conflicts are only reported.
OPTIONAL MATCH (ep:Episode {id: $row.episode_id})
OPTIONAL MATCH (m:Meeting)-[:HAS_EPISODE]->(ep)
OPTIONAL MATCH (sp:Person {id: $row.speaker_id})
OPTIONAL MATCH (ow:Person {id: coalesce($row.owner_id, $row.speaker_id)})
WITH ep, m, sp, ow, coalesce($row.valid_from, ep.t_occurred, $now) AS vf
OPTIONAL MATCH (en:Entity) WHERE en.id IN $row.entity_ids
WITH ep, m, sp, ow, vf, collect(en) AS ens
OPTIONAL MATCH (ex:Fact {key: $row.key, status: 'active'})
WITH ep, m, sp, ow, vf, ens, [x IN collect(ex) WHERE x.id <> $row.id] AS existing
WITH ep, m, sp, ow, vf, ens,
     [x IN existing WHERE toLower(trim(coalesce(x.object, ''))) = $row.object_norm] AS same,
     [x IN existing WHERE toLower(trim(coalesce(x.object, ''))) <> $row.object_norm] AS conflicts
WITH ep, m, sp, ow, vf, ens, same, conflicts,
     (size(same) > 0 AND NOT $explicit_id) AS dup,
     ($supersede AND any(c IN conflicts WHERE c.valid_from > vf)) AS backdated
WITH ep, m, sp, ow, vf, ens, same, conflicts, dup, backdated, CASE WHEN dup OR backdated THEN [] ELSE [$row] END AS rows
FOREACH (r IN rows |
  MERGE (f:Fact {id: r.id})
  ON CREATE SET f.created_at = $now, f.status = 'active', f.kind = r.kind, f.subject = r.subject, f.predicate = r.predicate,
                f.object = r.object, f.key = r.key, f.valid_from = vf
  SET f.text = coalesce(r.text, f.text), f.confidence = coalesce(r.confidence, f.confidence), f.due_at = coalesce(r.due_at, f.due_at),
      f.embedding = CASE WHEN r.embedding IS NULL THEN f.embedding ELSE vecf32(r.embedding) END
  FOREACH (_ IN CASE WHEN r.kind = 'decision' THEN [1] ELSE [] END | SET f:Decision SET f.decided_at = coalesce(f.decided_at, vf))
  FOREACH (_ IN CASE WHEN r.kind = 'commitment' THEN [1] ELSE [] END | SET f:Commitment))
WITH ep, m, sp, ow, vf, ens, same, conflicts, dup, backdated, rows
OPTIONAL MATCH (f:Fact {id: $row.id})
WITH ep, m, sp, ow, vf, ens, same, conflicts, dup, backdated, CASE WHEN size(rows) = 0 THEN NULL ELSE f END AS f
FOREACH (x IN CASE WHEN f IS NULL OR ep IS NULL THEN [] ELSE [ep] END | MERGE (f)-[:DERIVED_FROM]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR m IS NULL OR $row.kind <> 'decision' THEN [] ELSE [m] END | MERGE (f)-[:DECIDED_IN]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR sp IS NULL THEN [] ELSE [sp] END | MERGE (f)-[:STATED_BY]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR sp IS NULL OR $row.kind <> 'decision' THEN [] ELSE [sp] END | MERGE (f)-[:MADE_BY]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR ow IS NULL OR $row.kind <> 'commitment' THEN [] ELSE [ow] END | MERGE (f)-[:OWNED_BY]->(x))
FOREACH (x IN CASE WHEN f IS NULL THEN [] ELSE ens END | MERGE (f)-[:ABOUT]->(x))
FOREACH (o IN CASE WHEN f IS NULL OR NOT $supersede THEN [] ELSE conflicts END |
  SET o.valid_to = vf, o.expired_at = $now, o.status = 'superseded'
  MERGE (f)-[s:SUPERSEDES]->(o) SET s.at = $now)
RETURN CASE WHEN dup THEN same[0].id ELSE $row.id END AS id,
       dup AS existing, backdated,
       [c IN conflicts | {id: c.id, object: c.object, valid_from: c.valid_from, due_at: c.due_at}] AS conflicts,
       vf AS valid_from, f IS NOT NULL AS written
