// 23_task_trace: everything that happened to a task, for the board UI. Params: $id.
MATCH (t:Task {id: $id})
OPTIONAL MATCH (t)-[c:CLAIMED_BY]->(ca:Agent)
WITH t, collect({t: c.at, type: 'claimed', agent: ca.id}) AS claims
OPTIONAL MATCH (t)-[h:HANDED_OFF]->(ha:Agent)
WITH t, claims, collect({t: h.at, type: 'handed_off', agent: h.from_agent, to_agent: ha.id, summary: h.summary, subgraph_ids: h.subgraph_ids}) AS handoffs
OPTIONAL MATCH (t)-[:PRODUCED]->(ar:Artifact)
WITH t, claims, handoffs, collect({t: ar.created_at, type: 'artifact', artifact: {id: ar.id, kind: ar.kind, uri: ar.uri, text: ar.text}}) AS artifacts
OPTIONAL MATCH (t)-[:USED]->(s:Skill)
WITH t, claims, handoffs, artifacts, collect({t: t.updated_at, type: 'skill_used', skill: {id: s.id, goal: s.goal}}) AS skills
OPTIONAL MATCH (t)-[:ABOUT]->(x)
RETURN t, claims, handoffs, artifacts, skills, collect(DISTINCT x.id) AS about
