// hive.score(valid_from_ms, confidence, distance, now_ms) -> recency * importance * similarity. Higher is better.
//   recency    = exp(-age_days / 30)          age measured from valid_from to now (negative ages clamp to 0)
//   importance = confidence clamped to [0.05, 1]
//   similarity = clamp(1 - distance, 0, 1)    `distance` is the cosine DISTANCE from db.idx.vector.queryNodes (0 = identical)
// Loaded with GRAPH.UDF LOAD REPLACE hive <this file> by hiveboard.udf.loader.load_udfs. UDFs are read-only functions.
function score(valid_from_ms, confidence, distance, now_ms) {
  const from = Number(valid_from_ms);
  const now = Number(now_ms);
  const ageDays = (Number.isFinite(from) && Number.isFinite(now)) ? Math.max(0, (now - from) / 86400000) : 0;
  const recency = Math.exp(-ageDays / 30);
  const c = Number.isFinite(Number(confidence)) ? Number(confidence) : 0.5;
  const importance = Math.min(1, Math.max(0.05, c));
  const d = Number.isFinite(Number(distance)) ? Number(distance) : 1;
  const similarity = Math.min(1, Math.max(0, 1 - d));
  return recency * importance * similarity;
}

falkor.register('score', score);
