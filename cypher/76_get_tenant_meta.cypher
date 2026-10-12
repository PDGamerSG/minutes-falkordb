// 76_get_tenant_meta: the metadata JSON string of a tenant's registry row in `commons` (NULL when unset). Params: $slug.
MATCH (t:Tenant {slug: $slug})
RETURN t.meta AS meta
