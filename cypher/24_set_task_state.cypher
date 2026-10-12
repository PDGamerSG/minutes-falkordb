// 24_set_task_state: owner moves a WORKING or INPUT_REQUIRED task to 'failed' or 'input_required' with a note.
// Params: $id, $agent, $status, $note, $now. Zero rows = not the owner or the task is already terminal (completed/failed) or submitted.
MATCH (t:Task {id: $id, owner_agent: $agent})
WHERE t.status IN ['working', 'input_required']
WITH t
SET t.status = $status, t.version = t.version + 1, t.updated_at = $now, t.lease_until = NULL,
    t.failure_reason = CASE WHEN $status = 'failed' THEN $note ELSE t.failure_reason END,
    t.question = CASE WHEN $status = 'input_required' THEN $note ELSE t.question END
RETURN t.version AS version
