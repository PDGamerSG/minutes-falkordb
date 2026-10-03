// 73_delete_tenant_meta: remove a tenant's registry row and snapshot metadata from `commons`. Params: $slug.
MATCH (n) WHERE (n:Tenant AND n.slug = $slug) OR (n:Snapshot AND n.tenant = $slug)
DELETE n
RETURN count(n) AS deleted
