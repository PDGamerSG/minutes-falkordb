// 29_list_agents: agents with capabilities and a derived state ('working' if they own a working task). No params.
MATCH (a:Agent)
OPTIONAL MATCH (a)-[:HAS]->(c:Capability)
WITH a, collect(DISTINCT c.name) AS capabilities
OPTIONAL MATCH (t:Task {status: 'working', owner_agent: a.id})
RETURN a, capabilities, count(t) AS working
ORDER BY a.id
