// 32_why_path: provenance for a Fact/Decision/Commitment: every DERIVED_FROM episode (earliest first; the first one is the
// primary source), the primary episode's speaker (SPOKEN_BY for utterances, SENT_BY for emails, STATED_BY fallback), its container
// (Meeting or EmailThread), entities and the SUPERSEDES chain in both directions. Params: $id.
// Everything is projected without embeddings; `older`/`newer` are the full chains (up to 10 hops), newest first is done by the caller.
MATCH (f:Fact {id: $id})
OPTIONAL MATCH (f)-[:DERIVED_FROM]->(e:Episode)
WITH f, e
ORDER BY e.t_occurred ASC, e.seq ASC
WITH f, collect(e) AS eps
WITH f, eps, CASE WHEN size(eps) = 0 THEN NULL ELSE eps[0] END AS ep
OPTIONAL MATCH (ep)-[:SPOKEN_BY]->(sp:Person)
OPTIONAL MATCH (ep)-[:SENT_BY]->(sb:Person)
OPTIONAL MATCH (f)-[:STATED_BY]->(st:Person)
OPTIONAL MATCH (m:Meeting)-[:HAS_EPISODE]->(ep)
OPTIONAL MATCH (th:EmailThread)-[:HAS_EPISODE]->(ep)
WITH f, eps, ep, coalesce(sp, sb, st) AS speaker, m, th
OPTIONAL MATCH (f)-[:ABOUT]->(en:Entity)
WITH f, eps, ep, speaker, m, th, collect(DISTINCT en {.id, .name, .type, labels: labels(en)}) AS entities
OPTIONAL MATCH (f)-[:SUPERSEDES*1..10]->(older:Fact)
WITH f, eps, ep, speaker, m, th, entities,
     collect(DISTINCT older {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to,
                             .created_at, .expired_at, .due_at, labels: labels(older)}) AS older
OPTIONAL MATCH (newer:Fact)-[:SUPERSEDES*1..10]->(f)
RETURN f {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to, .created_at,
          .expired_at, .due_at, .decided_at, .retract_reason, labels: labels(f), has_embedding: f.embedding IS NOT NULL} AS f,
       ep {.id, .seq, .text, .t_start, .t_end, .t_occurred, .t_ingested, .source_kind, .message_id, labels: labels(ep)} AS ep,
       speaker {.id, .name, .role, .email, labels: labels(speaker)} AS speaker,
       m {.id, .title, .started_at, .ended_at, .source_uri, labels: labels(m)} AS m,
       th {.id, .subject, .started_at, labels: labels(th)} AS th,
       entities, older,
       collect(DISTINCT newer {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to,
                               .created_at, .expired_at, .due_at, labels: labels(newer)}) AS newer,
       [x IN eps | x {.id, .seq, .text, .t_start, .t_end, .t_occurred, .t_ingested, .source_kind, .message_id, labels: labels(x)}] AS episodes
