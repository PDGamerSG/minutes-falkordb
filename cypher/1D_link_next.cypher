// 1D_link_next: MERGE the intended NEXT edges. Params: $nodes = [{id, next}] with next not null.
UNWIND $nodes AS n
MATCH (a:Episode {id: n.id}), (b:Episode {id: n.next})
MERGE (a)-[:NEXT]->(b)
RETURN count(*) AS linked
