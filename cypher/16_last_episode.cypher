// 16_last_episode: id and seq of the latest episode under a container, so a new batch can continue the NEXT chain. Params: $container_id.
MATCH (m {id: $container_id})-[:HAS_EPISODE]->(e:Episode)
WHERE m:Meeting OR m:EmailThread
RETURN e.id AS id, e.seq AS seq
ORDER BY e.seq DESC
LIMIT 1
