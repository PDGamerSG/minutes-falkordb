# Decision impact implementation

Authorized scope: strengthen the Company Brain and redesign its UI in parallel. Frontend ownership is delegated to `frontend_redesign`; this thread owns backend work.

## Outcome

A versioned synthetic delivery document explicitly links each work item to one recorded fact and an accountable person. FalkorDB follows `current Fact → SUPERSEDES → baseline Fact ← DEPENDS_ON ← WorkItem → OWNED_BY → Person`. The product identifies open work based on an outdated decision, shows both the decision source and the document asserting the dependency, and stores a local follow-up draft. Co-mention is never sufficient to establish a dependency.

## Boundaries

Reuse graph tenancy, fact/source projections, existing API error handling and deterministic fake support. Add additive WorkItem/Document schema and bounded Cypher; preserve all existing source ingestion. Import is explicit and validates every referenced fact/person before graph mutation. One baseline per work item keeps the initial feature reviewable. A model does not invent work links. No external ticket/message is sent. Authentication and live extraction quality are separate known limitations.

## Delivery

1. Add failing real graph tests for changed/unchanged/closed/unrelated facts, idempotent import, owner, document evidence, unknown references, tenant isolation and multi-hop chains.
2. Implement graph storage/query and API views; add the same behavior to FakeHive.
3. Add API tests and idempotent draft creation that refuses stale or ambiguous decisions.
4. Seed a small explicit public synthetic delivery manifest against existing fact IDs; expose GET impact and POST draft for the new overview.
5. Verify real API payloads and full backend suite; coordinate frontend integration and end-to-end review.

Done when the known decision reversals produce exactly the linked open work, existing alignments/closed work do not receive drafts, the evidence path is inspectable, drafts persist across sessions and do not duplicate, and the frontend can exercise it with the real graph.
