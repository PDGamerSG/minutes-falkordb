// 05_link_mentions: Episode -[:MENTIONS]-> Entity for each id, plus CO_MENTIONED edges between all entity pairs
// mentioned together (feeds algo.WCC in 61_wcc_entities). Params: $episode_id, $entity_ids. Returns mention count.
MATCH (ep:Episode {id: $episode_id})
UNWIND $entity_ids AS eid
MATCH (en:Entity {id: eid})
MERGE (ep)-[:MENTIONS]->(en)
WITH ep, collect(DISTINCT en) AS ens
UNWIND ens AS a
UNWIND ens AS b
WITH size(ens) AS mentions, a, b, CASE WHEN a.id < b.id THEN [1] ELSE [] END AS pair
FOREACH (_ IN pair | MERGE (a)-[c:CO_MENTIONED]->(b) ON CREATE SET c.weight = 1 ON MATCH SET c.weight = c.weight + 1)
RETURN DISTINCT mentions
