# Minutes: a three-minute Company Brain demo

Updated October 10, 2026. Keep the original audit/work dates and the eligibility disclosure in the readiness report. Use the README setup, synthetic data, a real FalkorDB and visible model-mode labels.

## Before recording

Seed meetings/emails with `--extract gold`, then run `data/seed_work.py --tenants orbit`. The expected overview has 5 tracked work items: 3 need review, 1 aligned, 1 closed. The manifests name the reviewed gold facts; they are not automatically generated dependencies.

The verified local demonstration uses `LLM_BACKEND=fake EMBED_BACKEND=fake`: scripted answers and deterministic test vectors. Leave GitHub credentials unset. Frontend `NEXT_PUBLIC_MOCK` must be unset. Check `/health`, `/t/orbit`, and the source links. Audio is optional; transcript evidence must work.

Say once: “These are synthetic meetings, emails and a delivery register in a real FalkorDB. Reviewed labels and scripted agent policies make this demo reproducible. Live extraction is evaluated separately.”

## 0:00–0:20 — Enter the company memory

Open the Chrome-inspired entrance, then Orbit. Explain: “A team changes a decision. The people doing the work need to know what that change affects.”

The sculpture illustrates connected memory; it is not the actual graph. The source and decision counts below it come from FalkorDB.

## 0:20–1:15 — The relationship that changes the action

In **The ripple effect**, open **Update the payment integration runbook**.

Expected: **Razorpay → PayU**, with **Priya** responsible. Open **Original decision** and **Current decision** to inspect their transcript evidence. Open **Dependency document** to show the authored rule: this runbook contains vendor-specific API instructions.

Say: “It isn't enough that these records mention payments. This document explicitly says the runbook depends on that vendor decision. FalkorDB follows the real supersession chain to identify the work that needs review.”

Expand **Recorded graph relationships** to show the actual nodes and edges. The work points to its baseline fact, owner and dependency document; the current fact points back through `SUPERSEDES`. **How FalkorDB found the impact** exposes the executed query.

## 1:15–1:45 — An accountable next step

Use **Prepare follow-up**. Show the local draft with the owner, changed values, both fact IDs, and dependency-document ID. Reload and reopen the work: the saved draft remains.

Say: “This draft stays in Minutes. Nothing has been sent.” If a rehearsal already created it, show the existing saved draft instead of pretending a new one was generated.

Select **Closed**: the completed vendor sandbox spike receives no new draft. Select **Aligned**: the release checklist still agrees with October 16. These counterexamples are part of the demonstration, not incidental data.

## 1:45–2:20 — Who owns the work?

Open Chat and ask **Who owns the decision log?**

Expected: **Rahul**, citing the September 29 email. Open **Why this answer** and the source email. Aditya announces the assignment; Rahul owns the work and accepts it. This distinguishes ownership from participation.

## 2:20–2:45 — What was known then?

Ask **What did we believe about the UPI flow as of 2026-09-10?**

Expected: **September 24**, with kickoff evidence and no later deadline evidence. The present recorded deadline is September 28, and the flow is completed. A historical due date does not mean the work is still overdue.

## 2:45–3:00 — Boundaries and close

Switch to Nimbus. Its impact view has no imported work dependencies; this does not mean the whole company is healthy. Orbit records do not appear in that tenant graph. HTTP user authentication remains future work.

Close: “Minutes connects the decision, the evidence, the affected work and the accountable person. FalkorDB determines which follow-up is justified.”

## Backup demonstration

Board's **Simulate “move it to Friday”** changes the PayU integration date and triggers Scheduler → FollowUp task handoff. Show claimed/handed-off/artifact/completed trace and the **simulated** label. This is a source-state simulation, not live document extraction or a real issue being created. Use a fresh disposable corpus if you need repeatable before/after dates.

## Interactive decision-impact rehearsal

Use a disposable tenant seeded with the Orbit kickoff and customer-call recap via gold extraction. Keep the five-item Orbit fixture intact for the timed script. Each **Connect work** submission creates an additional tracked item; reseeding a delivery manifest does not delete these additions.

1. Click **Connect work**. Enter **Prepare the vendor onboarding guide**, choose **Priya**, and keep status **Open**.
2. Search **Payments Service**, choose the earlier **Razorpay** vendor decision, and explain: “The guide contains vendor-specific API and merchant setup instructions that must be reviewed when the provider changes.” Check **This is synthetic demo work** and save.
3. Show **Needs review**, **Razorpay → PayU**, and **Priya**. Inspect the source evidence, dependency note and graph path. Prepare a follow-up, reload, and show the same saved draft.
4. Open the pencil action. Click **Use current decision: PayU** and update the explanation to record that the guide has been reviewed against PayU. Save. The work becomes **Aligned** and the old draft leaves the current item while remaining in history. This action records a review; it does not modify an external document.
5. Edit the work again, set **Completed**, and save. Show **Closed**, with no new follow-up action.

This is the interactive extension of the main demo: an explicitly recorded relationship changes a review recommendation, and the user's review changes the graph's result.

## Submission evidence

- Record from a reproducible setup with source links and model modes visible.
- Disclose AI assistance and work dates; retain the rules/eligibility note.
- Include public source, setup instructions, key Cypher and the declared Track 3.
- Report live extraction separately. The existing P .42 / R .59 / F1 .49 evaluation was not improved or rerun by these changes.
- Use test and HTTP smoke evidence from `docs/audit`; do not present it as a live-model or hosted-performance evaluation.
