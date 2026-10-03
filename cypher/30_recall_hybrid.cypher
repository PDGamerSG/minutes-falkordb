// 30_recall_hybrid: vector KNN -> 1-hop graph expansion through shared entities -> policy score in the hive.score UDF.
// Params: $label ('Fact'|'Episode'|'Skill'|'Entity'), $q (768 floats), $n (candidates), $k (results), $now.
// `distance` from db.idx.vector.queryNodes is a cosine DISTANCE (0 = identical); hive.score turns it into a similarity.
// Nodes are returned as map projections (union of the four labels' fields) without the embedding; absent fields are null.
CALL db.idx.vector.queryNodes($label, 'embedding', $n, vecf32($q)) YIELD node AS f, score AS distance
WHERE coalesce(f.status, 'active') = 'active'
OPTIONAL MATCH (f)-[:ABOUT|MENTIONS]->(e:Entity)<-[:ABOUT|MENTIONS]-(g)
WHERE g <> f AND coalesce(g.status, 'active') = 'active'
WITH f, distance,
     collect(DISTINCT e {.id, .name, .type, labels: labels(e)}) AS entities,
     collect(DISTINCT g {.id, .kind, .text, .object, .status, .valid_from, .t_occurred, .source_kind, .confidence, labels: labels(g)})[0..5] AS neighbours
RETURN f {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to, .created_at, .due_at,
          .seq, .t_start, .t_end, .t_occurred, .source_kind, .name, .type, .goal, .version, .runs, .success_rate,
          labels: labels(f), has_embedding: true} AS f,
       distance, entities, neighbours,
       hive.score(coalesce(f.valid_from, f.t_occurred, f.created_at, $now), coalesce(f.confidence, 0.5), distance, $now) AS rank
ORDER BY rank DESC
LIMIT $k
