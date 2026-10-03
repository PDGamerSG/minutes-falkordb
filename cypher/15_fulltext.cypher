// 15_fulltext: RediSearch full-text lookup over a label's text index. Params: $label ('Episode'|'Fact'|'Decision'), $q (sanitised), $k.
CALL db.idx.fulltext.queryNodes($label, $q) YIELD node, score
RETURN node, score
ORDER BY score DESC
LIMIT $k
