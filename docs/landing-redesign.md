# Minutes landing redesign

The landing page now follows a shorter story: company memory → animated Capture/Connect/Recall walkthrough → interactive product examples → scroll-driven memory sculpture → oversized Minutes signature. Workspace selection and creation live at `/workspaces`.

## Visual direction

- Cal.com informed the Cal Sans display typography; the font and OFL license are served locally.
- Latitude informed the spacing and restrained Inter body type. Dub informed the fine page rails and product framing.
- Stripe informed the shallow angled transition into the ending. Drizzle's direct “Ask Docs” entry informed the compact assistant.
- One cobalt accent (`#3155ed`), cool neutral text and borders, and a continuous navy ending with a blue spotlight replace the disconnected gradient bands. The silver/blue sculpture and oversized `minutes.` wordmark remain.
- The product introduction sits left-aligned beside its description, directly above the tabs.

## Behavior

- The 24-second original video has three eight-second chapters. It is silent, looping, inline, and has no visible play/pause controls. It pauses offscreen and when the document is hidden; interrupted playback attempts do not cancel future autoplay. Reduced motion leaves the poster still. Chapter selection and a text transcript remain available.
- The ending pins for a native scroll sequence, with a separate readable explanation for Gather → Connect → Remember. Scrolling back reverses the sequence. Buttons move to the corresponding stage; mouse dragging rotates the sculpture. No wheel/touch events are intercepted. Short viewports and reduced-motion settings use an unpinned layout; reduced motion keeps manual mode selection without animated transitions. A static SVG handles unavailable WebGL.
- The bottom assistant opens a nonmodal, keyboard-accessible panel. Choose a workspace, write a question or select a suggestion, then continue to `/t/{workspace}/chat?q=...`. The question is prefilled for review, not silently submitted. Loading, error/retry, empty, and disabled states are included.
- The large answer demonstration, homepage workspace directory, and FAQ block have been removed. Existing workspace creation remains on the dedicated directory page.

## Motion pass

- The hero now uses one restrained SVG thread to carry meeting, decision, email, and people source cards into a shared-memory mark. Cards drift on long, low-contrast loops while the dashed paths move slowly enough to read as a living system instead of a loading indicator.
- T3 Code informed the floating source marks and staggered arrival; 100xDevs informed the focused headline surrounded by a small constellation and the spotlight treatment. The result stays specific to Minutes and the existing cobalt/navy system.
- The landing navigation is now a translucent instrument-panel rail with numbered section links, a live context status, and a clear workspace action. It becomes slightly denser as the page scrolls and remains a compact single row on mobile.
- All ambient motion is disabled under `prefers-reduced-motion`; the hero layout remains readable with the decorative layer still present but static.

## Validation

- Targeted ESLint and scoped landing TypeScript checks passed, including the shared shell, new components, and sculpture.
- Browser checks covered widths 320, 390, 1280, and 1440: no page overflow; feature tabs and source/history/draft interactions work; the scroll sequence advances and reverses; the WebGL fallback renders.
- Verified video progress (0.669 → 2.170 seconds), loop rollover (23.5 → 1.376 seconds), chapter seeking, offscreen pause and resume, and absence of playback controls.
- Verified assistant suggestions and custom questions, workspace selection, Unicode/ampersand/quote preservation in the chat handoff, Escape dismissal and focus return. No chat question or external message was submitted during verification.
- Full-project TypeScript remains affected by existing API/type mismatches and Syncthing conflict copies outside this change. Native preview reports an Electron preload startup error; fresh page inspection showed no application hydration error.

## Video production

The requested Mac/Cardboard path was attempted but unavailable: the Mac responded over Tailscale, while SSH was refused before authentication and the alternative T3 interface required pairing. No Cardboard project or Mac thread was created. The delivered video was rendered locally. The reproducible renderer and complete Cardboard production brief are in `docs/video/`.
