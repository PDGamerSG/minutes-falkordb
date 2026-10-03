// 52_contradictions: pairs of ACTIVE facts with the same key (subject|predicate) but a different object. No params.
MATCH (f:Fact {status: 'active'})
WITH f.key AS key, collect(f {.id, .kind, .subject, .predicate, .object, .key, .text, .confidence, .status, .valid_from, .valid_to,
                              .created_at, .expired_at, .due_at, labels: labels(f)}) AS facts
WHERE size(facts) > 1
UNWIND facts AS a
UNWIND facts AS b
WITH key, a, b
WHERE a.id < b.id AND a.object <> b.object
RETURN key, a, b
ORDER BY key
