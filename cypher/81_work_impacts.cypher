// Only explicit dependencies count. No co-mention or vector similarity establishes impact.
MATCH (w:WorkItem)-[:DEPENDS_ON]->(baseline:Fact)
OPTIONAL MATCH (w)-[:OWNED_BY]->(owner:Person)
WITH w, baseline, owner
MATCH (w)-[:DOCUMENTED_IN]->(doc:Document)
WITH w, baseline, owner, doc
OPTIONAL MATCH (current:Fact {status: 'active'})
WHERE current.key = baseline.key
WITH w, baseline, owner, doc, current
OPTIONAL MATCH path=(current)-[:SUPERSEDES*0..24]->(baseline)
RETURN w {.id, .title, .status, .rationale} AS item,
       baseline {.id, .subject, .predicate, .object, .key, .kind, .status, .valid_from} AS baseline,
       owner {.id, .name} AS owner,
       doc {.id, .title, .uri, .content, .synthetic} AS document,
       collect(DISTINCT {fact: current {.id, .subject, .predicate, .object, .key, .kind, .status, .valid_from},
                         via: [n IN nodes(path) | n.id]}) AS candidates
ORDER BY w.id
LIMIT 200
