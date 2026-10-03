// 74_list_tenants: Tenant registry rows from `commons`. No params.
MATCH (t:Tenant)
RETURN t.slug AS slug, t.display_name AS display_name, t.graph AS graph, t.rw_user AS rw_user, t.ro_user AS ro_user, t.created_at AS created_at
ORDER BY t.slug
