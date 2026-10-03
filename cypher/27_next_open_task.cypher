// 27_next_open_task: oldest 'submitted' task an agent can take: REQUIRES is a subset of the agent's HAS capabilities,
// and the task is either unaddressed or was handed off to this agent. Params: $agent.
MATCH (a:Agent {id: $agent})
OPTIONAL MATCH (a)-[:HAS]->(c:Capability)
WITH a, collect(c.name) AS caps
MATCH (t:Task {status: 'submitted'})
WHERE t.owner_agent IS NULL OR t.owner_agent = a.id
OPTIONAL MATCH (t)-[:REQUIRES]->(r:Capability)
WITH t, caps, collect(r.name) AS reqs
WHERE all(x IN reqs WHERE x IN caps)
RETURN t, reqs
ORDER BY t.created_at ASC, t.priority DESC
LIMIT 1
