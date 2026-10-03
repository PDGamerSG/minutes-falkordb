from gen_lib import D, C, F

A, P, R, S = "spk_aditya", "spk_priya", "spk_rahul", "spk_sana"
FARAH, NIKHIL = "ext_meridian_compliance", "ext_razorpay_am"

ORBIT_ROSTER = [
    {"id": A, "name": "Aditya", "role": "lead", "email": "aditya@orbit.example"},
    {"id": P, "name": "Priya", "role": "backend", "email": "priya@orbit.example"},
    {"id": R, "name": "Rahul", "role": "mobile", "email": "rahul@orbit.example"},
    {"id": S, "name": "Sana", "role": "design", "email": "sana@orbit.example"},
]
EXTERNAL = {
    FARAH: {"id": FARAH, "name": "Farah Siddiqui", "email": "compliance@meridianbank.example"},
    NIKHIL: {"id": NIKHIL, "name": "Nikhil Rao", "email": "am@razorpay.example"},
}


def people(*ids):
    out = []
    for i in ids:
        if i in EXTERNAL:
            out.append(EXTERNAL[i])
        else:
            out.append(next(p for p in ALL_ROSTERS if p["id"] == i))
    return out


# ---------------------------------------------------------------------------
# thread 1, Wed 2026-09-09: onboarding wireframes, approved with one change
# ---------------------------------------------------------------------------
T1_MSGS = [
    dict(sender=S, to=[A], cc=[R], sent_at="2026-09-09T11:12:00+05:30", reply_to=None, body=(
        "Hi Aditya,\n\n"
        "First pass of the onboarding flow is in Figma: https://figma.example/orbit/onboarding-v1\n\n"
        "Five screens, as agreed at kickoff: Welcome, phone verification, PIN setup, permissions, and a five-card tour. "
        "These are wireframes, not final visuals. I'm still on track for the finished onboarding screens by the 19th.\n\n"
        "Two things I'd like a call on:\n"
        "1. The tour is five cards. Is that too many for field agents?\n"
        "2. PIN setup is a 4-digit PIN. Meridian's summary deck didn't specify a length.\n\n"
        "Rahul, cc'ing you so you see the screen inventory early.\n\n"
        "Sana"),
        items=[C("onboarding screens", "due", "2026-09-19", confirms={"subject": "onboarding screens", "predicate": "due"})]),
    dict(sender=A, to=[S], cc=[R], sent_at="2026-09-09T13:40:00+05:30", reply_to=0, body=(
        "Sana,\n\n"
        "Approved, with one change: cut the tour from five cards to three. The agents will swipe past five; three they might read. "
        "Everything else stands.\n\n"
        "4-digit PIN is fine. Meridian confirmed a 4-digit PIN on the summary call, keep it.\n\n"
        "Aditya\n\n"
        "On Wed, 9 Sep 2026 at 11:12, Sana <sana@orbit.example> wrote:\n"
        "> First pass of the onboarding flow is in Figma ...\n"
        "> 1. The tour is five cards. Is that too many for field agents?"),
        items=[D("onboarding tour", "uses_pattern", "three cards", tag="approval with one change (email)"),
               D("PIN setup", "uses_pattern", "4-digit PIN")]),
    dict(sender=R, to=[S], cc=[A], sent_at="2026-09-09T14:05:00+05:30", reply_to=1, body=(
        "Three cards is also less work for me, so no complaints.\n\n"
        "One question: does the permissions screen ask for location? Offline sync doesn't need it, and Meridian's agents will say no anyway.\n\n"
        "Rahul")),
    dict(sender=S, to=[R], cc=[A], sent_at="2026-09-09T15:22:00+05:30", reply_to=2, body=(
        "No location. The permissions screen asks for camera and notifications only. Camera for the inspection photos, notifications for sync status.\n\n"
        "Updating the tour to three cards now. Final screens still by the 19th.\n\n"
        "Sana"),
        items=[D("permissions screen", "scope_includes", "camera and notifications only")]),
    dict(sender=A, to=[S, R], cc=[], sent_at="2026-09-09T15:30:00+05:30", reply_to=3, body=(
        "Good. Closing this thread, see you Monday.\n\nAditya")),
]

# ---------------------------------------------------------------------------
# thread 2, Thu 2026-09-17: UPI flow moves 26th -> 29th by email (cross-source)
# ---------------------------------------------------------------------------
T2_MSGS = [
    dict(sender=P, to=[A], cc=[R], sent_at="2026-09-17T14:02:00+05:30", reply_to=None, body=(
        "Aditya,\n\n"
        "Quick heads-up on the UPI flow, as promised yesterday: I'm not waiting for Monday.\n\n"
        "I submitted the Razorpay merchant KYC for UPI autopay mandates this morning. Their support just confirmed it takes "
        "five business days for sandbox mandate activation, not three. That puts the unlock on Thursday the 24th at the earliest, "
        "and I need two full days after that to test mandates against real callbacks.\n\n"
        "So I'm moving the UPI flow from Friday the 25th to Monday the 28th. The one-time UPI path already works and will be "
        "on staging by Friday the 25th regardless; this move is only about mandates.\n\n"
        "Rahul, cc'ing you because your shell tests against staging, not against my branch, so your dates don't change.\n\n"
        "Priya"),
        items=[C("UPI flow", "due", "2026-09-28", supersedes={"subject": "UPI flow", "predicate": "due"},
                 tag="cross-source supersession (email): UPI flow 25th -> 28th"),
               F("Razorpay merchant KYC", "due", "2026-09-24"),
               C("payments service staging deploy", "due", "2026-09-25")]),
    dict(sender=A, to=[P], cc=[R], sent_at="2026-09-17T14:35:00+05:30", reply_to=0, body=(
        "Priya,\n\n"
        "Acknowledged. The UPI flow is Monday the 28th. Noted on the board.\n\n"
        "That is the second move on this one (24th, 25th, now 28th). Decision: if it moves again, we cut UPI autopay mandates "
        "from the October release and ship one-time UPI only. I would rather ship less than ship late.\n\n"
        "Thanks for not waiting for Monday.\n\n"
        "Aditya\n\n"
        "On Thu, 17 Sep 2026 at 14:02, Priya <priya@orbit.example> wrote:\n"
        "> So I'm moving the UPI flow from Friday the 25th to Monday the 28th."),
        items=[D("UPI autopay mandates", "status", "cut from October release if the UPI flow slips again",
                 tag="acknowledgement + conditional decision (email)")]),
    dict(sender=R, to=[P], cc=[A], sent_at="2026-09-17T15:10:00+05:30", reply_to=0, body=(
        "Fine by me. I test against staging, so the 25th is the date I care about.\n\n"
        "If mandates do get cut, tell me early so I can hide the autopay toggle rather than ship a dead button.\n\n"
        "Rahul")),
    dict(sender=P, to=[R], cc=[A], sent_at="2026-09-17T15:18:00+05:30", reply_to=2, body=(
        "Will do. You'll know on Thursday the 24th either way; that's when the KYC unlocks, or doesn't.\n\n"
        "Priya")),
]

# ---------------------------------------------------------------------------
# thread 3, Fri 2026-09-18: Rahul <-> Meridian compliance on the drawer requirement
# ---------------------------------------------------------------------------
T3_MSGS = [
    dict(sender=R, to=[FARAH], cc=[A, S], sent_at="2026-09-18T09:35:00+05:30", reply_to=None, body=(
        "Hello Farah,\n\n"
        "Rahul here, I'm building the Orbit mobile app for the Meridian pilot. Sana's review of your accessibility checklist found "
        "that our planned bottom tab bar gives about 48 dp per tab on your 5-inch rugged devices, below your minimum. "
        "We decided on Wednesday to replace it with a side drawer.\n\n"
        "Before I build it, two questions on the checklist:\n"
        "1. Is 56 dp a hard minimum for primary navigation targets, or a recommendation?\n"
        "2. Does a side drawer satisfy the single-landmark rule if it opens from a 56 dp button in the top bar and is announced as navigation?\n\n"
        "Mockup of the drawer attached (orbit-drawer-mockup-v1.pdf). Aditya mentioned you need to sign it off; happy to adjust.\n\n"
        "Thanks,\nRahul"),
        items=[F("Orbit navigation", "uses_pattern", "side drawer", confirms={"subject": "Orbit navigation", "predicate": "uses_pattern"})]),
    dict(sender=FARAH, to=[R], cc=[A, S], sent_at="2026-09-18T12:48:00+05:30", reply_to=0, body=(
        "Dear Rahul,\n\n"
        "Thank you for checking before building; most vendors do not.\n\n"
        "1. 56 dp is a hard minimum (checklist section 4.2, Primary navigation targets). It comes from our field study with gloved "
        "agents and is not negotiable for the pilot.\n"
        "2. Yes. A side drawer satisfies section 4.5 provided the trigger is at least 56 dp, the drawer is announced as Navigation "
        "to TalkBack, and focus moves into the drawer when it opens. Your mockup does all three.\n\n"
        "Please consider the drawer mockup approved by Meridian Bank compliance as of today. The tab bar proposal would not have passed.\n\n"
        "We will have further items for the payment flows on the call on the 23rd with Aditya and Priya.\n\n"
        "Kind regards,\n"
        "Farah Siddiqui\n"
        "Compliance, Meridian Bank"),
        items=[F("Meridian accessibility checklist", "requires", "56dp minimum primary navigation target",
                 tag="external party states the requirement behind the reversal"),
               F("side drawer", "status", "approved by Meridian compliance")]),
    dict(sender=A, to=[FARAH], cc=[R, S], sent_at="2026-09-18T13:05:00+05:30", reply_to=1, body=(
        "Farah, thank you. We will treat this as the formal sign-off on the drawer mockup. Rahul, that closes my commitment to get "
        "the mockup signed off by today.\n\n"
        "Sana, please add sections 4.2 and 4.5 to our design review template.\n\n"
        "Aditya"),
        items=[C("drawer mockup sign-off", "status", "completed", tag="completion (email)")]),
    dict(sender=R, to=[FARAH], cc=[A, S], sent_at="2026-09-18T13:20:00+05:30", reply_to=1, body=(
        "Thanks Farah, that's exactly what I needed. Building it now; the side drawer will be in the app by Wednesday the 23rd as planned.\n\n"
        "Rahul"),
        items=[C("side drawer", "due", "2026-09-23", confirms={"subject": "side drawer", "predicate": "due"})]),
    dict(sender=S, to=[A], cc=[R], sent_at="2026-09-18T14:02:00+05:30", reply_to=2, body=(
        "Added 4.2 and 4.5 to the template. I also re-measured the onboarding buttons at 56 dp against her numbers; they pass.\n\n"
        "Sana")),
]

# ---------------------------------------------------------------------------
# thread 4, Thu 2026-09-24: Priya tells Razorpay's AM about the PayU switch
# ---------------------------------------------------------------------------
T4_MSGS = [
    dict(sender=P, to=[NIKHIL], cc=[A], sent_at="2026-09-24T10:15:00+05:30", reply_to=None, body=(
        "Hi Nikhil,\n\n"
        "I wanted you to hear this from us directly. Our launch customer, Meridian Bank, mandates PayU as the payment provider for the "
        "Orbit pilot; their compliance team confirmed it yesterday and will not onboard a second provider. Orbit's payments service is "
        "therefore moving from Razorpay to PayU for the October release.\n\n"
        "Two requests:\n"
        "1. Please keep our sandbox account open until at least October 1st. We are finishing the one-time UPI flow and the autopay "
        "mandate tests against it (merchant KYC came through this morning, thank you) and will swap the provider underneath afterwards.\n"
        "2. Please don't close the merchant account. We have a second prospect, Kestrel Logistics, and no vendor constraint there yet.\n\n"
        "Nothing about your team's support caused this. It's the customer's licence.\n\n"
        "Regards,\nPriya"),
        items=[D("payments service", "uses_vendor", "PayU", supersedes={"subject": "payments service", "predicate": "uses_vendor"},
                 tag="cross-source supersession (email): vendor Razorpay -> PayU, told to the vendor"),
               F("Razorpay merchant KYC", "status", "approved")]),
    dict(sender=NIKHIL, to=[P], cc=[A], sent_at="2026-09-24T12:40:00+05:30", reply_to=0, body=(
        "Hi Priya,\n\n"
        "Understood, and thank you for telling us rather than going quiet. Confirming:\n"
        "- Sandbox access stays open for 90 days from today, so well past October 1st.\n"
        "- The merchant account stays active at no cost. KYC is complete, so Kestrel or any future project can go live without repeating it.\n\n"
        "If Meridian's position changes, we'd be glad to talk about a joint integration. Also, the UPI collect callback issue you reported "
        "on the 11th is fixed in sandbox as of yesterday, for what it's worth.\n\n"
        "Best,\nNikhil Rao\nAccount Manager, Razorpay"),
        items=[F("Razorpay sandbox", "status", "open for 90 days"),
               F("Razorpay merchant account", "status", "active")]),
    dict(sender=A, to=[NIKHIL], cc=[P], sent_at="2026-09-24T13:02:00+05:30", reply_to=1, body=(
        "Nikhil, appreciated. For the record on our side: the Orbit payments service uses PayU for the October release, superseding our "
        "kickoff decision on Razorpay, because Meridian Bank's compliance team mandates it. We'll come back to you for Kestrel if their "
        "compliance allows.\n\n"
        "Aditya"),
        items=[D("payments service", "uses_vendor", "PayU", confirms={"subject": "payments service", "predicate": "uses_vendor"})]),
    dict(sender=P, to=[A], cc=[R], sent_at="2026-09-24T13:30:00+05:30", reply_to=2, subject="Re: Orbit payments: switching provider to PayU (internal)", body=(
        "Internal only, Nikhil dropped.\n\n"
        "PayU sandbox keys arrived. Their UPI callbacks fire within two seconds, so the polling workaround goes away. "
        "PayU integration still on for Thursday, October 1st.\n\n"
        "Rahul, the Razorpay SDK can come out of the shell whenever; staging already points at the provider interface.\n\n"
        "Priya"),
        items=[C("PayU integration", "due", "2026-10-01", confirms={"subject": "PayU integration", "predicate": "due"})]),
    dict(sender=R, to=[P], cc=[A], sent_at="2026-09-24T13:41:00+05:30", reply_to=3, body=(
        "SDK's out as of this morning. Two files and a gradle line. Done.\n\nRahul"),
        items=[C("Razorpay SDK removal", "status", "completed", tag="completion (email), a day early")]),
]

# ---------------------------------------------------------------------------
# thread 5, Tue 2026-09-29: retro prep, action item, GitHub issue #42
# ---------------------------------------------------------------------------
T5_MSGS = [
    dict(sender=A, to=[R, P, S], cc=[], sent_at="2026-09-29T09:20:00+05:30", reply_to=None, body=(
        "Team,\n\n"
        "Ahead of tomorrow's retro (Wednesday 10:00), two things.\n\n"
        "1. Action item for Rahul: set up a decision log in the mobile repo, one entry per decision with the date, who decided, and the "
        "rationale. Tracked here: https://github.com/orbit-app/mobile/issues/42. Due Friday, October 2nd. Backfill it from the kickoff, "
        "the design review and the Meridian recap.\n\n"
        "2. Everyone: add one went-well and one didn't-go-well as a comment on issue #42 before 10:00 tomorrow, so we don't spend the "
        "retro remembering.\n\n"
        "Aditya"),
        items=[D("decision log", "owner", "Rahul", tag="action item with GitHub issue URL (Artifact link)"),
               C("decision log", "due", "2026-10-02")]),
    dict(sender=R, to=[A], cc=[P, S], sent_at="2026-09-29T09:48:00+05:30", reply_to=0, body=(
        "Accepted. Decision log by Friday the 2nd, in docs/decisions.md, one file, and I'll link each entry to the issue. "
        "Backfilling from the kickoff notes first; the Razorpay one is going to make a good first entry.\n\n"
        "Rahul"),
        items=[C("decision log", "due", "2026-10-02", confirms={"subject": "decision log", "predicate": "due"})]),
    dict(sender=P, to=[A], cc=[R, S], sent_at="2026-09-29T11:05:00+05:30", reply_to=0, body=(
        "Comment added to #42.\n\n"
        "Also, for the record, since this is the date everyone has been watching: the UPI flow is done as of last night, one-time and "
        "autopay mandates, tested against the Razorpay sandbox. Monday the 28th, as promised in my email on the 17th. "
        "The PayU swap continues, still October 1st.\n\n"
        "Priya"),
        items=[C("UPI flow", "status", "completed", tag="completion (email, the day before the retro)")]),
    dict(sender=S, to=[A], cc=[R, P], sent_at="2026-09-29T11:40:00+05:30", reply_to=0, body=(
        "Done, comment's on the issue. Mine for went-well is the checklist as a baseline. For didn't-go-well: I can't remember why we "
        "chose the drawer without looking it up, which is sort of the point of Rahul's log.\n\n"
        "Sana")),
    dict(sender=A, to=[S], cc=[R, P], sent_at="2026-09-29T11:52:00+05:30", reply_to=3, body=(
        "That is exactly the point. See you at ten.\n\nAditya")),
]

# ---------------------------------------------------------------------------
# nimbus and quill: one thread each, one supersession each
# ---------------------------------------------------------------------------
NIMBUS_ROSTER = [
    {"id": "spk_meera", "name": "Meera", "role": "data lead", "email": "meera@nimbus.example"},
    {"id": "spk_dev", "name": "Dev", "role": "data engineer", "email": "dev@nimbus.example"},
    {"id": "spk_anika", "name": "Anika", "role": "analyst", "email": "anika@nimbus.example"},
]
QUILL_ROSTER = [
    {"id": "spk_tara", "name": "Tara", "role": "editor", "email": "tara@quill.example"},
    {"id": "spk_omar", "name": "Omar", "role": "writer", "email": "omar@quill.example"},
]
ALL_ROSTERS = ORBIT_ROSTER + NIMBUS_ROSTER + QUILL_ROSTER

NIMBUS_T1_MSGS = [
    dict(sender="spk_dev", to=["spk_meera"], cc=["spk_anika"], sent_at="2026-09-22T16:40:00+05:30", reply_to=None, body=(
        "Meera,\n\n"
        "I said the 23rd was real. It isn't. The schema registry is up and it rejected Monday's load, correctly, because the source team "
        "added two nullable columns over the weekend. Fixing the models is a day.\n\n"
        "I'm moving the events pipeline from Wednesday the 23rd to Friday the 25th. The registry did its job, which is the only good news here.\n\n"
        "Dev"),
        items=[C("events pipeline", "due", "2026-09-25", supersedes={"subject": "events pipeline", "predicate": "due"}, tag="supersession (email)")]),
    dict(sender="spk_meera", to=["spk_dev"], cc=["spk_anika"], sent_at="2026-09-22T17:05:00+05:30", reply_to=0, body=(
        "Acknowledged. The 25th. Anika, that pushes the Lumen dashboard; tell me a date you believe.\n\nMeera")),
    dict(sender="spk_anika", to=["spk_meera"], cc=["spk_dev"], sent_at="2026-09-22T17:30:00+05:30", reply_to=1, body=(
        "The Lumen dashboard moves to Tuesday the 29th. I need two working days after the pipeline lands, and I'm not promising a weekend.\n\nAnika"),
        items=[C("Lumen dashboard", "due", "2026-09-29", supersedes={"subject": "Lumen dashboard", "predicate": "due"}, tag="supersession (email)")]),
    dict(sender="spk_meera", to=["spk_dev", "spk_anika"], cc=[], sent_at="2026-09-22T17:41:00+05:30", reply_to=2, body=(
        "Fine. Both moves noted. Nothing else moves without a reason I can give finance.\n\nMeera")),
]

QUILL_T1_MSGS = [
    dict(sender="spk_omar", to=["spk_tara"], cc=[], sent_at="2026-09-21T10:30:00+05:30", reply_to=None, body=(
        "Tara,\n\n"
        "Legal came back, but only on half of it. The pricing paragraph is still with their external counsel and they've said Thursday the 24th.\n\n"
        "I'm moving the launch post from Friday the 25th to Tuesday the 29th, so it goes out with the newsletter. If legal misses Thursday, "
        "I'll publish without the pricing paragraph, as we agreed.\n\n"
        "Omar"),
        items=[C("launch post", "due", "2026-09-29", supersedes={"subject": "launch post", "predicate": "due"}, tag="supersession (email)")]),
    dict(sender="spk_tara", to=["spk_omar"], cc=[], sent_at="2026-09-21T11:02:00+05:30", reply_to=0, body=(
        "Agreed, the 29th. One change while we wait: the launch post leads the Tuesday newsletter that week instead of the essay, "
        "so you get that week off the essay.\n\nTara"),
        items=[D("newsletter", "scope_includes", "launch post leads the September 29 issue")]),
    dict(sender="spk_omar", to=["spk_tara"], cc=[], sent_at="2026-09-21T11:10:00+05:30", reply_to=1, body=(
        "Deal. The interview outlines for October are still on for Thursday the 24th.\n\nOmar"),
        items=[C("interview outlines", "due", "2026-09-24", confirms={"subject": "interview outlines", "predicate": "due"})]),
]

THREADS = [
    ("orbit_thread_001", "thr_orbit_001", "Onboarding flow, first pass (wireframes)", people(S, A, R), T1_MSGS),
    ("orbit_thread_002", "thr_orbit_002", "UPI flow: moving to Monday the 28th", people(P, A, R), T2_MSGS),
    ("orbit_thread_003", "thr_orbit_003", "Orbit navigation: side drawer vs accessibility checklist", people(R, FARAH, A, S), T3_MSGS),
    ("orbit_thread_004", "thr_orbit_004", "Orbit payments: switching provider to PayU", people(P, NIKHIL, A, R), T4_MSGS),
    ("orbit_thread_005", "thr_orbit_005", "Retro prep and action item: decision log (issue #42)", people(A, R, P, S), T5_MSGS),
    ("nimbus_thread_001", "thr_nimbus_001", "Events pipeline: moving to Friday the 25th", people("spk_dev", "spk_meera", "spk_anika"), NIMBUS_T1_MSGS),
    ("quill_thread_001", "thr_quill_001", "Launch post: legal still reviewing", people("spk_omar", "spk_tara"), QUILL_T1_MSGS),
]

ROSTERS = [
    ("orbit_roster.json", ORBIT_ROSTER),
    ("nimbus_roster.json", NIMBUS_ROSTER),
    ("quill_roster.json", QUILL_ROSTER),
]
