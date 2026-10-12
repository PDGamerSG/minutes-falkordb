// 75_set_tenant_meta: store free-form tenant metadata (JSON string, e.g. {"embedding_model": ...}) on the registry row in `commons`.
// Params: $slug, $meta (JSON string), $now. The row is created when the tenant has no registry entry yet.
MERGE (t:Tenant {slug: $slug})
ON CREATE SET t.created_at = $now
SET t.meta = $meta, t.meta_updated_at = $now
RETURN t.meta AS meta
