// 60_pagerank_skills: PageRank over the Task -[:USED]-> Skill graph; only Skill nodes are returned. No params.
// Label NULL lets the algorithm walk Task nodes too (USED never connects two Skills directly).
CALL algo.pageRank(NULL, 'USED') YIELD node, score
WITH node, score WHERE node:Skill
RETURN node.id AS id, node.goal AS goal, node.runs AS runs, node.success_rate AS success_rate, score
ORDER BY score DESC
