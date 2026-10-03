// 72_upsert_tenant: Tenant registry row in `commons`. Params: $slug, $display_name, $graph, $rw_user, $ro_user, $now.
MERGE (t:Tenant {slug: $slug})
ON CREATE SET t.created_at = $now
SET t.display_name = $display_name, t.graph = $graph, t.rw_user = $rw_user, t.ro_user = $ro_user
RETURN t.slug AS slug
