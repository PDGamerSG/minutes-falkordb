// 43_deprecate_skill: retire a skill in favour of a newer one. Params: $old_id, $new_id, $now.
MATCH (old:Skill {id: $old_id}), (new:Skill {id: $new_id})
SET old.status = 'deprecated', old.deprecated_at = $now
MERGE (old)-[:DEPRECATED_BY]->(new)
RETURN old.id AS id
