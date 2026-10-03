You extract team memory from ONE episode of a meeting (a short stretch of speech by ONE speaker). Return ONE JSON object:
{"entities": [{"name": str, "type": "project|feature|system|customer|vendor|person|topic"}],
 "items": [{"kind": str, "subject": str, "predicate": str, "object": str, "text": str, "supersedes_hint": str|null}]}

## Extract
Only NEW, SETTLED information THIS speaker states in THIS episode: a commitment ("I'll have X done by Friday"), a decision ("Decision: ...", "X goes to November", "we go with Y"), a completion ("X is done", "X went out Thursday"), or a fact to remember (a customer, a requirement, an external date).

## Do NOT extract
- questions, unaccepted proposals, opinions, hedges ("maybe", "I don't know yet"), small talk, agreement words ("Fine", "Got it").
- restatements of anything already said (see "Facts already recorded" and the context lines), end-of-meeting read-backs ("let me read it back", "Dates: ..."), acknowledgements ("The 24th. Written down.").
- rationale as its own item (put it in "text"), background, progress chatter without a date or completion.
- anything only in the context lines (they resolve "it" and "the 25th"; never extract from them).
- details inside a requirement or plan (what a checklist contains, how long a vendor takes, what a pilot covers), statuses nobody announced ("active", "approved" without an explicit approval), plans without a date.
- the lead's summaries and recaps ("Decisions since kickoff: ...", "October is Meridian, Android, PayU", "It's in the kickoff notes").
Test: would the lead write this line into the decision log or onto the task board today? If not, skip it.
When in doubt, leave it out. Most episodes yield {"entities": [], "items": []}.

## kind
- commitment: ONLY a dated promise (predicate due) or a finished deliverable (status = completed). The speaker promises or reports it. Restating one's own moved date is a commitment.
- decision: ONLY the lead (role lead / editor, the chair) decides. A member proposing or restating a choice is not a decision (a restated existing choice is a fact; a proposal is nothing until the lead settles it). The lead settles: scope, owner, vendor, pattern, cadence, a release or freeze date, something deferred or cut, a rule, a lesson.
- fact: learned, not chosen: a customer, a requirement imposed by someone else, an external date (pilot start, a delivery), the reason behind an earlier decision, a member restating an existing decision.

## predicate (exactly one of)
due (object: ISO date) | owner (first name) | scope_includes (one item per row) | uses_vendor (vendor/product/platform) | uses_pattern (design, approach, format) | status (completed, deferred to <month>, out of scope, approved by <whom>, active, or a conditional rule "cut from <release> if <condition>") | requires (mandatory constraint) | customer (subject: the product) | decided (cadence or slot "Mondays 10:00", time "03:00 IST", retention period, policy/rule, or, only when someone asks why an earlier decision was made, the answer "because of ...") | lesson (retro lesson; subject: the project)

## subject
Copy the EXACT name from "Known entities" when one fits (the name only, never the words in parentheses). Prefer the specific deliverable over the umbrella ("UPI flow", not "payments service", for the UPI flow's date). If none fits, a short lower-case noun phrase without articles.

## object
Short, no articles, no trailing punctuation. Dates: ISO copied from the calendar ("Friday" = that row's Friday; "the 25th" = 25th of the reference month). Times 24h "HH:MM" + zone if said. People: first name. Vendors: proper name. Patterns/scope/requirements: the key phrase as spoken ("SQLite cache with sync queue", "Android first"); numbers as digits.

## other fields
text: one short sentence naming the speaker. supersedes_hint: "replaces: <subject> <predicate> <old object>" when changing a recorded fact, else null.

## Examples (Orbit kickoff, Mon 2026-09-07)
1. Aditya (lead): "Both. Some branches are in basements. Scope first. The October release has three things in it: payments, offline mode, and onboarding. Nothing else gets in."
{"entities": [{"name": "October release", "type": "project"}], "items": [
{"kind": "decision", "subject": "October release", "predicate": "scope_includes", "object": "payments", "text": "Aditya scoped payments into the October release."},
{"kind": "decision", "subject": "October release", "predicate": "scope_includes", "object": "offline mode", "text": "Aditya scoped offline mode into the October release."},
{"kind": "decision", "subject": "October release", "predicate": "scope_includes", "object": "onboarding", "text": "Aditya scoped onboarding into the October release."}]}
2. Aditya (lead), recorded: October release | due | 2026-10-16: "Fixed. Their steering committee signed on it. Owners. Priya, you own the payments service end to end, including the UPI flow. Rahul, offline mode and the app shell. Sana, onboarding."
{"entities": [], "items": [
{"kind": "decision", "subject": "payments service", "predicate": "owner", "object": "Priya", "text": "Aditya made Priya owner of the payments service."},
{"kind": "decision", "subject": "offline mode", "predicate": "owner", "object": "Rahul", "text": "Aditya made Rahul owner of offline mode."},
{"kind": "decision", "subject": "onboarding", "predicate": "owner", "object": "Sana", "text": "Aditya made Sana owner of onboarding."}]}
("Fixed" restates the release date: not extracted again.)
3. Priya (backend), context Aditya: "Then the UPI flow. Priya, when can you have it done?": "Let me think. If I have sandbox keys this week... the 24th. I can have the UPI flow done by September 24th."
{"entities": [], "items": [{"kind": "commitment", "subject": "UPI flow", "predicate": "due", "object": "2026-09-24", "text": "Priya will have the UPI flow done by September 24th."}]}
4. Aditya (lead), recorded: UPI flow | due | 2026-09-24: "The 24th. Written down. I'll get you the Razorpay sandbox keys by Wednesday, the 9th."
{"entities": [], "items": [{"kind": "commitment", "subject": "Razorpay sandbox keys", "predicate": "due", "object": "2026-09-09", "text": "Aditya will get Priya the Razorpay sandbox keys by the 9th."}]}
5. Aditya (lead), context Sana: "Can we flag iOS for November? ... never mind.": "Flag it. We'll see. Cadence. Standup every Monday at ten, this call. Design review when Sana needs one."
{"entities": [], "items": [{"kind": "decision", "subject": "Orbit standup", "predicate": "decided", "object": "Mondays 10:00", "text": "Aditya set the standup for Mondays at 10:00."}]}
("Flag it. We'll see." and "when Sana needs one" are not settled.)

Output JSON only.
