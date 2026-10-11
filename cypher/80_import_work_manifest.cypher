// Validate every reference before mutation, then replace each item's current dependency atomically.
// Params: $items, $document. Source documents are immutable by content-derived id in the API.
UNWIND $items AS item
OPTIONAL MATCH (baseline:Fact {id: item.baseline_fact_id})
WITH item, baseline
OPTIONAL MATCH (owner:Person {id: item.owner_id})
WITH collect({item: item, baseline: baseline, owner: owner}) AS rows
WHERE all(row IN rows WHERE row.baseline IS NOT NULL AND row.owner IS NOT NULL)
MERGE (doc:Document {id: $document.id})
ON CREATE SET doc.title = $document.title, doc.uri = $document.uri,
              doc.content = $document.content, doc.synthetic = $document.synthetic
WITH doc, rows
UNWIND rows AS row
WITH doc, row.item AS item, row.baseline AS baseline, row.owner AS owner
MERGE (w:WorkItem {id: item.id})
SET w.title = item.title, w.status = item.status, w.rationale = item.rationale
WITH doc, item, baseline, owner, w
OPTIONAL MATCH (w)-[old:DEPENDS_ON|OWNED_BY|DOCUMENTED_IN]->()
DELETE old
WITH DISTINCT doc, item, baseline, owner, w
MERGE (w)-[:DEPENDS_ON]->(baseline)
MERGE (w)-[:OWNED_BY]->(owner)
MERGE (w)-[:DOCUMENTED_IN]->(doc)
RETURN count(DISTINCT w) AS imported
