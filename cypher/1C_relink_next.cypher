// 1C_relink_next: make the NEXT chain over one window linear. Params: $nodes = [{id, next}] (next is the id of the
// following episode, or null for the last one), run as two statements by memory._ingest_episode_rows:
//   1. this file: drop every NEXT edge that leaves a window node for anything but its intended successor,
//   2. then MERGE the intended edges (1D_link_next).
UNWIND $nodes AS n
MATCH (a:Episode {id: n.id})-[x:NEXT]->(b:Episode)
WHERE b.id <> coalesce(n.next, '')
DELETE x
RETURN count(x) AS removed
