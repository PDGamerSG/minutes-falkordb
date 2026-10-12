// 15_fulltext: RediSearch full-text lookup over a label's text index. Params: $label ('Episode'|'Fact'|'Decision'), $q (sanitised), $k.
// The node is projected without its embedding (union of Episode and Fact fields; absent fields are null and dropped by the caller).
CALL db.idx.fulltext.queryNodes($label, $q) YIELD node, score
RETURN node {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to, .created_at,
             .expired_at, .due_at, .decided_at, .seq, .t_start, .t_end, .t_occurred, .t_ingested, .source_kind, .message_id,
             labels: labels(node), has_embedding: node.embedding IS NOT NULL} AS node, score
ORDER BY score DESC
LIMIT $k
