# FalkorDB issue drafts

Three drafts for [FalkorDB/FalkorDB](https://github.com/FalkorDB/FalkorDB/issues), written while building Minutes.
None of them has been posted. Every output block below is real output captured with `redis-cli` inside the
containers on 2026-10-03. Timing lines (`Cached execution`, `Query internal execution time`) are removed and
unchanged fields are elided with `...` where marked; nothing else is edited.

Common environment for all three:

| | 6.0.1 | 4.22.0 |
|---|---|---|
| Image | `falkordb/falkordb:latest` (`sha256:e2765e207e5b...`, created 2026-10-01) | `falkordb/falkordb:v4.22.0` (`sha256:4ac83f55062d...`, created 2026-09-30) |
| `MODULE LIST` | `graph` ver `60001`, `vectorset` ver `1` | `graph` ver `42200`, `vectorset` ver `1` |
| `INFO server` | `redis_version:8.10.2`, `os:Linux 6.6.87.2-microsoft-standard-WSL2 x86_64` | same |
| Module args | `MAX_QUEUED_QUERIES 25 TIMEOUT 1000 RESULTSET_SIZE 10000` (image defaults), `THREAD_COUNT 32` | same |
| Host | Windows 11 Home 10.0.26200, Docker Desktop 29.5.3 (WSL2), Intel i9-13900HX | same |

Containers were started with `docker run -d -p <port>:6379 <image>` and no extra arguments.

---

## 1. `GRAPH.MEMORY USAGE` reports whole megabytes (truncated) and does not count vector indexes

**Title:** `GRAPH.MEMORY USAGE` returns 0 for every field on graphs under ~1 MB per component, and `indices_sz_mb` ignores HNSW vector indexes

### Environment

See the table above. Same behaviour on 6.0.1 and 4.22.0.

### What we saw first

Our benchmark records `GRAPH.MEMORY USAGE team_<tenant>` after each run. On a freshly seeded tenant graph (about 250
nodes, dozens of them carrying 768-d `vecf32` embeddings, with 4 HNSW vector indexes, 3 full-text indexes and 30 range
indexes) every field comes back as `0` on both engines. After a 15 s load, a tenant graph of 5008 nodes (mostly Facts
with embeddings) reports `total_graph_sz_mb 8`, `Fact 7` and `indices_sz_mb 1`. Narrowing it down shows
two separate problems: values are whole megabytes (a plain graph with 6000 nodes and 3000 edges reports `0` in every
field), and the memory of an HNSW vector index is not reflected in `indices_sz_mb` at all.

### Reproduction

```
redis-cli GRAPH.QUERY mem_plain "UNWIND range(1, 3000) AS i CREATE (:Person {id: i, name: 'person ' + toString(i)})-[:KNOWS]->(:Person {id: i + 100000})"
redis-cli GRAPH.MEMORY USAGE mem_plain

redis-cli GRAPH.QUERY mem_vec "UNWIND range(1, 3000) AS i CREATE (:Doc {id: i, text: 'document number ' + toString(i), embedding: vecf32([j IN range(1, 768) | rand()])})"
redis-cli INFO memory | grep '^used_memory:'
redis-cli GRAPH.QUERY mem_vec "CREATE VECTOR INDEX FOR (n:Doc) ON (n.embedding) OPTIONS {dimension:768, similarityFunction:'cosine'}"
redis-cli GRAPH.QUERY mem_vec "CREATE FULLTEXT INDEX FOR (n:Doc) ON (n.text)"
redis-cli GRAPH.QUERY mem_vec "CREATE INDEX FOR (n:Doc) ON (n.id)"
redis-cli GRAPH.QUERY mem_vec "CALL db.indexes() YIELD label, properties, types, status RETURN label, properties, types, status"
redis-cli INFO memory | grep '^used_memory:'
redis-cli GRAPH.MEMORY USAGE mem_vec
redis-cli GRAPH.MEMORY USAGE mem_vec SAMPLES 1000
```

### Actual output (6.0.1)

A graph with 6000 nodes, 9000 properties and 3000 edges reports zero everywhere:

```
> redis-cli GRAPH.MEMORY USAGE mem_plain
total_graph_sz_mb
0
label_matrices_sz_mb
0
relation_matrices_sz_mb
0
amortized_node_block_sz_mb
0
amortized_node_attributes_by_label_sz_mb
Person
0
amortized_unlabeled_nodes_attributes_sz_mb
0
amortized_edge_block_sz_mb
0
amortized_edge_attributes_by_type_sz_mb
KNOWS
0
indices_sz_mb
0
```

3000 nodes with 768-d vectors plus three indexes:

```
> redis-cli INFO memory | grep '^used_memory:'          (after creating the 3000 nodes, before the indexes)
used_memory:15771472
> redis-cli GRAPH.QUERY mem_vec "CALL db.indexes() YIELD label, properties, types, status RETURN label, properties, types, status"
label
properties
types
status
Doc
[embedding, text, id]
{embedding: [VECTOR], text: [FULLTEXT], id: [RANGE]}
OPERATIONAL
> redis-cli INFO memory | grep '^used_memory:'          (after the three indexes are OPERATIONAL)
used_memory:29065936
> redis-cli GRAPH.MEMORY USAGE mem_vec
total_graph_sz_mb
9
label_matrices_sz_mb
0
relation_matrices_sz_mb
0
amortized_node_block_sz_mb
0
amortized_node_attributes_by_label_sz_mb
Doc
9
amortized_unlabeled_nodes_attributes_sz_mb
0
amortized_edge_block_sz_mb
0
amortized_edge_attributes_by_type_sz_mb

indices_sz_mb
0
```

`SAMPLES 1000` returns the same values.

Vector index alone (same 3000 nodes without `text`, only the vector index created):

```
> redis-cli INFO memory | grep '^used_memory:'          (before CREATE VECTOR INDEX)
used_memory:15238880
> redis-cli GRAPH.QUERY mem_vec "CALL db.indexes() YIELD label, types, status RETURN label, types, status"
label
types
status
Doc
{embedding: [VECTOR]}
OPERATIONAL
> redis-cli INFO memory | grep '^used_memory:'          (after, index OPERATIONAL)
used_memory:27807776
> redis-cli GRAPH.MEMORY USAGE mem_vec
total_graph_sz_mb
8
...
indices_sz_mb
0
```

The vector index adds 12.6 MB to `used_memory` (11.6 MB on 4.22.0) and `indices_sz_mb` reports `0` on both.

For the three-index case 4.22.0 gives the same picture (`used_memory` 14977600 before the indexes, 27347128 after;
`total_graph_sz_mb 9`, `indices_sz_mb 0`). `MEMORY USAGE <graph key>` returns `32` (bytes, the key stub) on both
engines, so Redis' own command is no help either.

### Expected

1. Sizes with sub-megabyte precision (a double, or bytes), so a graph of a few MB or less does not report `0` in every
   field. Today values appear to be truncated to whole MB: 3000 x 768 x 4 bytes = 9.2 MB of vectors is reported as `9`,
   and the 6000-node graph as `0`.
2. `indices_sz_mb` should include the vector index memory. One HNSW index over 3000 x 768-d vectors grew
   `used_memory` by 12.6 MB on 6.0.1 (11.6 MB on 4.22.0); with a full-text and a range index added the growth was
   13.3 MB (12.4 MB), while `indices_sz_mb` stayed `0` in every case. Something is counted on the loaded benchmark
   graph (`1` MB with 30 range, 3 full-text and 4 vector indexes over about 2000 embedded nodes), so the gap may be
   specific to vector indexes; we have not isolated it further.

### Impact

`GRAPH.MEMORY USAGE` is the only per-graph memory view (one graph per tenant is the recommended multi-tenant
pattern), so it is what a per-tenant quota, a billing line or a "this tenant is getting big" alert would read. For
typical small tenant graphs it reports nothing, and for vector-heavy graphs it misses what is often the largest
component (the HNSW index holds its own copy of the vectors). Our product falls back to showing node counts.

Side note seen during this repro, possibly unrelated: on 4.22.0, `UNWIND range(1, 3000) AS i CREATE (:Doc {...})`
reports `Labels added: 3000` (6.0.1 reports `Labels added: 1`).

---

## 2. ACL `%R~<graph>` denies `GRAPH.RO_QUERY` because the command declares its key as RW

**Title:** `GRAPH.RO_QUERY` key spec carries `RW access update`, so the documented `%R~` read-only ACL selector returns NOPERM

### Environment

See the table above. Same behaviour on 6.0.1 and 4.22.0.

### What the docs say

The ACL page (https://docs.falkordb.com/commands/acl.html) gives `ACL SETUSER reader on >pass +GRAPH.RO_QUERY %R~*`
as the read-only example and states that whether a command needs read or write permission on a graph "is derived
from the command's key specifications".

### Reproduction

```
redis-cli COMMAND GETKEYSANDFLAGS GRAPH.RO_QUERY g "MATCH (n) RETURN n"
redis-cli COMMAND GETKEYSANDFLAGS GET k
redis-cli GRAPH.QUERY acl_demo "CREATE (:Doc {id: 1})"
redis-cli ACL SETUSER ro_sel reset on '>pw' +GRAPH.RO_QUERY '%R~acl_demo'
redis-cli ACL SETUSER rw_sel reset on '>pw' +GRAPH.RO_QUERY +GRAPH.QUERY '%RW~acl_demo'
redis-cli ACL SETUSER ro_pat reset on '>pw' +GRAPH.RO_QUERY '~acl_demo'
redis-cli --user ro_sel --pass pw GRAPH.RO_QUERY acl_demo "MATCH (d:Doc) RETURN d.id"
redis-cli --user rw_sel --pass pw GRAPH.RO_QUERY acl_demo "MATCH (d:Doc) RETURN d.id"
redis-cli --user ro_pat --pass pw GRAPH.RO_QUERY acl_demo "MATCH (d:Doc) RETURN d.id"
redis-cli --user ro_pat --pass pw GRAPH.QUERY acl_demo "CREATE (:Doc {id: 2})"
redis-cli --user ro_pat --pass pw GRAPH.RO_QUERY acl_demo "CREATE (:Doc {id: 2})"
redis-cli --user ro_pat --pass pw GRAPH.RO_QUERY other_graph "MATCH (n) RETURN count(n)"
redis-cli ACL DRYRUN ro_sel GRAPH.RO_QUERY acl_demo "MATCH (d:Doc) RETURN d.id"
```

### Actual output (6.0.1; 4.22.0 is identical apart from timings)

Key flags, compared with a plain Redis read command:

```
> COMMAND GETKEYSANDFLAGS GRAPH.RO_QUERY g "MATCH (n) RETURN n"
g
RW
access
update
> COMMAND GETKEYSANDFLAGS GET k
k
RO
access
```

`COMMAND INFO GRAPH.RO_QUERY` shows the same key spec (`flags RW access update`, `begin_search index 1`,
`find_keys range lastkey 0`), identical to `GRAPH.QUERY`, while the command flags themselves are `readonly module noscript blocking`.

ACL checks:

```
> redis-cli --user ro_sel --pass pw GRAPH.RO_QUERY acl_demo "MATCH (d:Doc) RETURN d.id"
NOPERM No permissions to access a key

> redis-cli --user rw_sel --pass pw GRAPH.RO_QUERY acl_demo "MATCH (d:Doc) RETURN d.id"
d.id
1

> redis-cli --user ro_pat --pass pw GRAPH.RO_QUERY acl_demo "MATCH (d:Doc) RETURN d.id"
d.id
1

> redis-cli --user ro_pat --pass pw GRAPH.QUERY acl_demo "CREATE (:Doc {id: 2})"
NOPERM User ro_pat has no permissions to run the 'graph.QUERY' command

> redis-cli --user ro_pat --pass pw GRAPH.RO_QUERY acl_demo "CREATE (:Doc {id: 2})"
graph.RO_QUERY is to be executed only on read-only queries

> redis-cli --user ro_pat --pass pw GRAPH.RO_QUERY other_graph "MATCH (n) RETURN count(n)"
NOPERM No permissions to access a key

> redis-cli ACL DRYRUN ro_sel GRAPH.RO_QUERY acl_demo "MATCH (d:Doc) RETURN d.id"
User ro_sel has no permissions to access the 'acl_demo' key
```

`ACL LOG` records the denial as `reason key`, `object acl_demo`, `username ro_sel`.

### Expected

`GRAPH.RO_QUERY` cannot modify the graph (it rejects write clauses itself), so its key spec should be `RO access`
and `%R~acl_demo` should allow it, as the documentation example implies. Alternatively, the docs should not present
`%R~` as the read-only recipe.

### Correction to our own notes

`%RW~acl_demo` does work for `GRAPH.RO_QUERY` (it is equivalent to `~acl_demo`). Only the read-only selector `%R~` fails.
Our README and `hiveboard/tenancy.py` say both `%R~` and `%RW~` fail; that should read "`%R~` fails".

### Workaround

Restrict by command and use a full key pattern:
`ACL SETUSER team_x_ro reset on >pw +GRAPH.RO_QUERY ~team_x`. The user can read `team_x`, cannot run `GRAPH.QUERY`,
cannot write through `GRAPH.RO_QUERY` (the engine rejects write clauses) and cannot touch other graphs (output above).

### Impact

The documented way to give an agent or a BI tool read-only access to one graph does not work, and the failure looks
like a misconfiguration (`NOPERM No permissions to access a key`). Users end up granting `~graph` (read-write key
access) and relying on command-level rules, which is easy to get wrong: adding `+@all` or `+GRAPH.QUERY` later silently
turns a "read-only" user into a writer. The same RW key spec on `GRAPH.EXPLAIN`, `GRAPH.PROFILE` and other read
commands is worth checking in the same fix.

---

## 3. A `WHERE` on a `MATCH` is silently dropped when the next clause is another `MATCH` (6.0.1 regression)

**Title:** 6.0.1 drops the WHERE filter of a MATCH that is followed by another MATCH on the same variable (wrong results; correct in 4.22.0)

### Environment

See the table above. Reproduces on 6.0.1. Does not reproduce on 4.22.0 (correct results, `Filter` op present in the plan).

### Background

We first saw this as "a multi-type relationship (`SPOKEN_BY|SENT_BY|SENT_TO`) after a filtered MATCH loses the filter"
and worked around it with `WITH` barriers. While minimising it we found that the multi-type relationship is not needed:
a single relationship type, or no third MATCH at all, is enough. The trigger is `MATCH ... WHERE <predicate>` followed
directly by another `MATCH` that reuses the variable. Inline property maps (`MATCH (en:Entity {name: 'Alpha'})`) are not
affected, and neither is `OPTIONAL MATCH` as the second clause.

### Reproduction

```
redis-cli GRAPH.QUERY issue3 "CREATE (a:Entity {name:'Alpha'}), (b:Entity {name:'Beta'}), (p1:Person {id:'p1'}), (p2:Person {id:'p2'}), (p3:Person {id:'p3'}), (e1:Episode {id:'e1'})-[:MENTIONS]->(a), (e2:Episode {id:'e2'})-[:MENTIONS]->(b), (e3:Episode {id:'e3'})-[:MENTIONS]->(b), (e1)-[:SPOKEN_BY]->(p1), (e2)-[:SENT_BY]->(p2), (e3)-[:SENT_TO]->(p3), (e3)-[:SENT_BY]->(p2)"

# minimal: two MATCH clauses
redis-cli GRAPH.QUERY   issue3 "MATCH (en:Entity) WHERE en.name = 'Alpha' MATCH (ep:Episode)-[:MENTIONS]->(en) RETURN en.name, ep.id ORDER BY ep.id"
redis-cli GRAPH.EXPLAIN issue3 "MATCH (en:Entity) WHERE en.name = 'Alpha' MATCH (ep:Episode)-[:MENTIONS]->(en) RETURN en.name, ep.id ORDER BY ep.id"

# the shape we hit in production (who talked or wrote about an entity)
redis-cli GRAPH.QUERY   issue3 "MATCH (en:Entity) WHERE toLower(en.name) = toLower('alpha') MATCH (ep:Episode)-[:MENTIONS]->(en) MATCH (ep)-[r:SPOKEN_BY|SENT_BY|SENT_TO]->(p:Person) RETURN en.name, ep.id, type(r), p.id ORDER BY ep.id, p.id"
redis-cli GRAPH.EXPLAIN issue3 "MATCH (en:Entity) WHERE toLower(en.name) = toLower('alpha') MATCH (ep:Episode)-[:MENTIONS]->(en) MATCH (ep)-[r:SPOKEN_BY|SENT_BY|SENT_TO]->(p:Person) RETURN en.name, ep.id, type(r), p.id ORDER BY ep.id, p.id"

# a WHERE on the second MATCH replaces the first one instead of being ANDed with it
redis-cli GRAPH.QUERY   issue3 "MATCH (en:Entity) WHERE en.name = 'Alpha' MATCH (ep:Episode)-[:MENTIONS]->(en) WHERE ep.id <> 'e2' RETURN en.name, ep.id ORDER BY ep.id"
redis-cli GRAPH.EXPLAIN issue3 "MATCH (en:Entity) WHERE en.name = 'Alpha' MATCH (ep:Episode)-[:MENTIONS]->(en) WHERE ep.id <> 'e2' RETURN en.name, ep.id ORDER BY ep.id"

# controls
redis-cli GRAPH.QUERY issue3 "MATCH (en:Entity) WHERE en.name = 'Alpha' WITH en MATCH (ep:Episode)-[:MENTIONS]->(en) RETURN en.name, ep.id ORDER BY ep.id"
redis-cli GRAPH.QUERY issue3 "MATCH (en:Entity {name: 'Alpha'}) MATCH (ep:Episode)-[:MENTIONS]->(en) RETURN en.name, ep.id ORDER BY ep.id"
redis-cli GRAPH.QUERY issue3 "MATCH (ep:Episode)-[:MENTIONS]->(en:Entity) WHERE en.name = 'Alpha' RETURN en.name, ep.id ORDER BY ep.id"
```

### Actual output on 6.0.1 (timing lines removed)

Minimal case: rows for `Beta` come back, and the plan has no `Filter` at all.

```
> GRAPH.QUERY issue3 "MATCH (en:Entity) WHERE en.name = 'Alpha' MATCH (ep:Episode)-[:MENTIONS]->(en) RETURN en.name, ep.id ORDER BY ep.id"
en.name
ep.id
Alpha
e1
Beta
e2
Beta
e3
> GRAPH.EXPLAIN issue3 "MATCH (en:Entity) WHERE en.name = 'Alpha' MATCH (ep:Episode)-[:MENTIONS]->(en) RETURN en.name, ep.id ORDER BY ep.id"
Sort
    Project
        Conditional Traverse | (en)<-(ep:Episode)
            Node By Label Scan | (en:Entity)
```

Production shape:

```
> GRAPH.QUERY issue3 "MATCH (en:Entity) WHERE toLower(en.name) = toLower('alpha') MATCH (ep:Episode)-[:MENTIONS]->(en) MATCH (ep)-[r:SPOKEN_BY|SENT_BY|SENT_TO]->(p:Person) RETURN en.name, ep.id, type(r), p.id ORDER BY ep.id, p.id"
en.name
ep.id
type(r)
p.id
Alpha
e1
SPOKEN_BY
p1
Beta
e2
SENT_BY
p2
Beta
e3
SENT_BY
p2
Beta
e3
SENT_TO
p3
> GRAPH.EXPLAIN issue3 "MATCH (en:Entity) WHERE toLower(en.name) = toLower('alpha') MATCH (ep:Episode)-[:MENTIONS]->(en) MATCH (ep)-[r:SPOKEN_BY|SENT_BY|SENT_TO]->(p:Person) RETURN en.name, ep.id, type(r), p.id ORDER BY ep.id, p.id"
Sort
    Project
        Conditional Traverse | (ep)-[r:SENT_BY|SENT_TO|SPOKEN_BY]->(p:Person)
            Conditional Traverse | (en)<-(ep:Episode)
                Node By Label Scan | (en:Entity)
```

Second WHERE present: only the second predicate survives (`Beta`/`e3` is returned, `e2` is filtered).

```
> GRAPH.QUERY issue3 "MATCH (en:Entity) WHERE en.name = 'Alpha' MATCH (ep:Episode)-[:MENTIONS]->(en) WHERE ep.id <> 'e2' RETURN en.name, ep.id ORDER BY ep.id"
en.name
ep.id
Alpha
e1
Beta
e3
> GRAPH.EXPLAIN issue3 "MATCH (en:Entity) WHERE en.name = 'Alpha' MATCH (ep:Episode)-[:MENTIONS]->(en) WHERE ep.id <> 'e2' RETURN en.name, ep.id ORDER BY ep.id"
Sort
    Project
        Conditional Traverse | (ep)->(en:Entity)
            Filter
                Node By Label Scan | (ep:Episode)
```

Other variants that return the same wrong rows on 6.0.1: `WHERE en.name STARTS WITH 'A'`, `WHERE en.name = $n` with
`CYPHER n='Alpha'`, an unlabelled `MATCH (en) WHERE ...`, the reversed direction `MATCH (en)<-[:MENTIONS]-(ep:Episode)`,
and a single relationship type in the third clause (`-[:SENT_BY]->` returns only the two `Beta` rows).
`MATCH (ep:Episode) WHERE ep.id = 'e2' MATCH (ep)-[:MENTIONS]->(en:Entity) RETURN ...` returns e1, e2 and e3.

Controls on 6.0.1, all correct (`Alpha`, `e1` only): the `WITH en` barrier, the inline property map
`{name: 'Alpha'}`, a single MATCH with the WHERE after it, and `OPTIONAL MATCH` as the second clause. With the
barrier the plan keeps the filter:

```
> GRAPH.EXPLAIN issue3 "MATCH (en:Entity) WHERE toLower(en.name) = toLower('alpha') WITH en MATCH (ep:Episode)-[:MENTIONS]->(en) WITH DISTINCT ep MATCH (ep)-[r:SPOKEN_BY|SENT_BY|SENT_TO]->(p:Person) RETURN ep.id, type(r), p.id ORDER BY ep.id, p.id"
Sort
    Project
        Conditional Traverse | (ep)-[r:SPOKEN_BY|SENT_BY|SENT_TO]->(p:Person)
            Distinct
                Project
                    Conditional Traverse | (en)<-(ep:Episode)
                        Project
                            Filter
                                Node By Label Scan | (en:Entity)
```

### Same query on 4.22.0 (correct)

```
> GRAPH.QUERY issue3 "MATCH (en:Entity) WHERE en.name = 'Alpha' MATCH (ep:Episode)-[:MENTIONS]->(en) RETURN en.name, ep.id ORDER BY ep.id"
en.name
ep.id
Alpha
e1
> GRAPH.EXPLAIN issue3 "MATCH (en:Entity) WHERE en.name = 'Alpha' MATCH (ep:Episode)-[:MENTIONS]->(en) RETURN en.name, ep.id ORDER BY ep.id"
Results
    Sort
        Project
            Conditional Traverse | (en)->(ep:Episode)
                Filter
                    Node By Label Scan | (en:Entity)
```

All the variants listed above also return only `Alpha`/`e1` on 4.22.0.

### Expected

`MATCH (a) WHERE p(a) MATCH (a)-->(b)` must return only rows where `p(a)` holds, and a WHERE on the second MATCH must
be combined with the first (AND), as on 4.22.0. The plan should contain a `Filter` for `en.name = 'Alpha'`.

### Impact

Silent wrong results, no error. `MATCH ... WHERE ... MATCH ...` is one of the most common Cypher shapes (look up a node
by a computed or non-equality predicate, then expand), and it is what LLM text-to-Cypher tools generate. On 6.0.1 every
such query ignores its first filter and scans the whole label, so it is also slower. In a multi-tenant or
access-filtered design, a dropped `WHERE n.owner = $user` leaks data. Workaround: put `WITH <vars>` between the clauses,
use an inline property map for equality, or move the WHERE after the last MATCH.
