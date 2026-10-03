// 61_wcc_entities: weakly connected components over Entity nodes joined by CO_MENTIONED edges (written by 05_link_mentions). No params.
CALL algo.WCC({nodeLabels: ['Entity'], relationshipTypes: ['CO_MENTIONED']}) YIELD node, componentId
RETURN componentId AS component, collect({id: node.id, name: node.name, type: node.type}) AS entities
ORDER BY size(entities) DESC, component ASC
