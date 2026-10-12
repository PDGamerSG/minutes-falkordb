// 1B_episode_window: ids of a container's episodes from $from_seq on, in seq order (the window that NEXT re-linking touches).
// Params: $container_id, $from_seq (0 for the whole container).
MATCH (m {id: $container_id})-[:HAS_EPISODE]->(e:Episode)
WHERE (m:Meeting OR m:EmailThread) AND e.seq >= $from_seq
RETURN e.id AS id
ORDER BY e.seq, e.id
