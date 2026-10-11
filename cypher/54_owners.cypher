// 54_owners: explicit assignments take precedence over the speaker fallback on commitments.
// Params: $name. Resolve an assignment to exactly one Person; ambiguous assignments stay unknown.
MATCH (en:Entity) WHERE toLower(en.name) = toLower($name)
WITH en
MATCH (f:Fact {status: 'active'})-[:ABOUT]->(en)
WHERE toLower(f.subject) = toLower(en.name)
WITH collect(DISTINCT f) AS facts
WITH facts, [f IN facts WHERE f.predicate = 'owner'] AS assignments
UNWIND CASE WHEN size(assignments) > 0 THEN assignments ELSE [f IN facts WHERE f.kind = 'commitment'] END AS c
OPTIONAL MATCH (c)-[:OWNED_BY]->(declared:Person)
WITH c, declared, size(assignments) AS assignment_count
OPTIONAL MATCH (resolved:Person)
WHERE c.predicate = 'owner' AND (resolved.id = c.object OR toLower(resolved.name) = toLower(c.object) OR toLower(resolved.email) = toLower(c.object))
WITH c, declared, assignment_count, collect(DISTINCT resolved) AS people
WITH c, CASE WHEN assignment_count > 0 THEN
    CASE WHEN assignment_count = 1 AND size(people) = 1 THEN people[0] ELSE NULL END
    ELSE declared END AS p
WHERE p IS NOT NULL
RETURN DISTINCT c.id AS fact_id, p.id AS person_id, p.name AS person_name
ORDER BY person_name, fact_id
