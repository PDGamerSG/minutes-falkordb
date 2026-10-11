// 16_last_episode: predecessor of the incoming batch, including retries. Params: $container_id, $before_seq.
MATCH (m {id: $container_id})-[:HAS_EPISODE]->(e:Episode)
WHERE (m:Meeting OR m:EmailThread) AND e.seq < $before_seq
RETURN e.id AS id, e.seq AS seq
ORDER BY e.seq DESC
LIMIT 1
