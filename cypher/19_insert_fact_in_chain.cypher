// 19_insert_fact_in_chain: a late import of an EARLIER statement about a key (its valid_from precedes the chain member
// $before_id). ONE statement (finding 1): the new fact is born 'superseded' with valid_from = vf, valid_to = before.valid_from,
// expired_at = $now; before -[:SUPERSEDES]-> new; whatever `before` superseded with valid_from <= vf (the predecessor(s))
// is re-wired to hang off the new fact (its valid_to becomes vf). The head of the chain never changes.
// It REFUSES to self-supersede: when the new statement restates a chain member (same key, same normalised object, or the
// same id as `before`), nothing is inserted; the existing fact is linked to the episode (DERIVED_FROM + CONFIRMED_BY {at})
// and `confirmed` is true with `id` = the existing fact's id. Preference: before, then the predecessor, then any member.
// Params: $before_id, $now, $row (same shape as 18). Zero rows: $before_id does not exist.
// `error`: 'key_mismatch' (different key) or 'not_before' (before.valid_from <= vf: this is not a mid-chain insertion;
// use remember_fact/supersede_fact). Nothing is written when `error` is set.
MATCH (before:Fact {id: $before_id})
OPTIONAL MATCH (ep:Episode {id: $row.episode_id})
OPTIONAL MATCH (m:Meeting)-[:HAS_EPISODE]->(ep)
OPTIONAL MATCH (sp:Person {id: $row.speaker_id})
OPTIONAL MATCH (ow:Person {id: coalesce($row.owner_id, $row.speaker_id)})
WITH before, ep, m, sp, ow, coalesce($row.valid_from, ep.t_occurred, $now) AS vf
OPTIONAL MATCH (en:Entity) WHERE en.id IN $row.entity_ids
WITH before, ep, m, sp, ow, vf, collect(en) AS ens
OPTIONAL MATCH (ch:Fact {key: before.key})
WHERE ch.status <> 'retracted'
WITH before, ep, m, sp, ow, vf, ens, collect(ch) AS chain
OPTIONAL MATCH (before)-[stale:SUPERSEDES]->(after:Fact)
WHERE after.key = before.key AND after.valid_from <= vf
WITH before, ep, m, sp, ow, vf, ens, chain, collect(stale) AS stale_edges, collect(after) AS afters
WITH before, ep, m, sp, ow, vf, ens, afters, stale_edges,
     [x IN chain WHERE toLower(trim(coalesce(x.object, ''))) = $row.object_norm] AS same,
     [a IN afters WHERE toLower(trim(coalesce(a.object, ''))) = $row.object_norm] AS same_after
WITH before, ep, m, sp, ow, vf, ens, afters, stale_edges,
     CASE WHEN before.id = $row.id OR toLower(trim(coalesce(before.object, ''))) = $row.object_norm THEN before
          WHEN size(same_after) > 0 THEN same_after[0]
          WHEN size(same) > 0 THEN same[0]
          ELSE NULL END AS confirm
WITH before, ep, m, sp, ow, vf, ens, afters, stale_edges, confirm,
     CASE WHEN before.key <> $row.key THEN 'key_mismatch'
          WHEN confirm IS NULL AND before.valid_from <= vf THEN 'not_before'
          ELSE NULL END AS error
WITH before, ep, m, sp, ow, vf, ens, afters, stale_edges, confirm, error,
     CASE WHEN error IS NULL AND confirm IS NULL THEN [$row] ELSE [] END AS rows
FOREACH (r IN rows |
  MERGE (f:Fact {id: r.id})
  ON CREATE SET f.created_at = $now, f.status = 'superseded', f.kind = r.kind, f.subject = r.subject, f.predicate = r.predicate,
                f.object = r.object, f.key = r.key, f.valid_from = vf, f.valid_to = before.valid_from, f.expired_at = $now
  SET f.text = coalesce(r.text, f.text), f.confidence = coalesce(r.confidence, f.confidence), f.due_at = coalesce(r.due_at, f.due_at),
      f.embedding = CASE WHEN r.embedding IS NULL THEN f.embedding ELSE vecf32(r.embedding) END
  FOREACH (_ IN CASE WHEN r.kind = 'decision' THEN [1] ELSE [] END | SET f:Decision SET f.decided_at = coalesce(f.decided_at, vf))
  FOREACH (_ IN CASE WHEN r.kind = 'commitment' THEN [1] ELSE [] END | SET f:Commitment))
WITH before, ep, m, sp, ow, vf, ens, afters, stale_edges, confirm, error, rows
OPTIONAL MATCH (f:Fact {id: $row.id})
WITH before, ep, m, sp, ow, vf, ens, afters, stale_edges, confirm, error, CASE WHEN size(rows) = 0 THEN NULL ELSE f END AS f
FOREACH (x IN CASE WHEN f IS NULL OR ep IS NULL THEN [] ELSE [ep] END | MERGE (f)-[:DERIVED_FROM]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR m IS NULL OR $row.kind <> 'decision' THEN [] ELSE [m] END | MERGE (f)-[:DECIDED_IN]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR sp IS NULL THEN [] ELSE [sp] END | MERGE (f)-[:STATED_BY]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR sp IS NULL OR $row.kind <> 'decision' THEN [] ELSE [sp] END | MERGE (f)-[:MADE_BY]->(x))
FOREACH (x IN CASE WHEN f IS NULL OR ow IS NULL OR $row.kind <> 'commitment' THEN [] ELSE [ow] END | MERGE (f)-[:OWNED_BY]->(x))
FOREACH (x IN CASE WHEN f IS NULL THEN [] ELSE ens END | MERGE (f)-[:ABOUT]->(x))
FOREACH (x IN CASE WHEN f IS NULL THEN [] ELSE stale_edges END | DELETE x)
FOREACH (a IN CASE WHEN f IS NULL THEN [] ELSE afters END | SET a.valid_to = vf MERGE (f)-[s:SUPERSEDES]->(a) SET s.at = $now)
FOREACH (b IN CASE WHEN f IS NULL THEN [] ELSE [before] END | MERGE (b)-[s:SUPERSEDES]->(f) SET s.at = $now)
FOREACH (c IN CASE WHEN confirm IS NULL OR error IS NOT NULL OR ep IS NULL THEN [] ELSE [confirm] END |
  MERGE (c)-[:DERIVED_FROM]->(ep) MERGE (c)-[k:CONFIRMED_BY]->(ep) SET k.at = $now)
RETURN CASE WHEN confirm IS NOT NULL THEN confirm.id ELSE $row.id END AS id,
       f IS NOT NULL AS inserted, (error IS NULL AND confirm IS NOT NULL) AS confirmed, error,
       [a IN afters | a.id] AS superseded, [a IN afters | a.object] AS old_objects,
       before.id AS before_id, vf AS valid_from
