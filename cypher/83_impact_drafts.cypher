// Local, unsent follow-up drafts, persisted independently of browser sessions.
MATCH (draft:FollowUpDraft)
RETURN draft.payload
ORDER BY draft.created_at DESC, draft.id
LIMIT 200
