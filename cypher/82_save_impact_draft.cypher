// Revalidate the selected version, open work and dependency document inside the write query.
// The draft is scoped on (id, work_item_id): the same id can never attach to two work items (the unique constraint on
// FollowUpDraft.id turns a reuse for another work item into a constraint error, which impact.save_draft reports as Conflict).
MATCH (w:WorkItem {id: $work_item_id, status: 'open'})-[:DEPENDS_ON]->(baseline:Fact {id: $baseline_fact_id})
WITH w, baseline
MATCH (w)-[:OWNED_BY]->(:Person {id: $owner_id})
WITH w, baseline
MATCH (w)-[:DOCUMENTED_IN]->(doc:Document {id: $document_id})
WITH w, baseline, doc
MATCH (candidate:Fact {status: 'active'}) WHERE candidate.key = baseline.key
WITH w, baseline, doc, collect(candidate) AS active
WHERE size(active) = 1
WITH w, baseline, doc, active[0] AS current
WHERE current.id = $current_fact_id AND current.object <> baseline.object AND baseline.status <> 'retracted'
WITH w, baseline, doc, current
MATCH (current)-[:SUPERSEDES*1..24]->(baseline)
WITH DISTINCT w, doc, current
MERGE (draft:FollowUpDraft {id: $id, work_item_id: $work_item_id})
ON CREATE SET draft.payload = $payload, draft.created_at = $created_at
MERGE (draft)-[:FOR_WORK]->(w)
MERGE (draft)-[:BASED_ON]->(current)
MERGE (draft)-[:DOCUMENTED_IN]->(doc)
RETURN draft.payload
