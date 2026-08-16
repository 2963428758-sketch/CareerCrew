# T4.2 — Persisted feedback UI and restoration

## Delivered

- Added a typed authenticated feedback client for `PUT`/`DELETE`/thread `GET`, including response validation and existing Chinese API/network error conventions.
- Reworked feedback controls to persist before changing selected state: likes revoke on the second click; dislikes use the backend reason IDs, optional comment, and the explicitly unchecked consent copy.
- Added a shared API-backed per-thread feedback cache. Each stable assistant message refreshes the current thread feedback during history restoration, while regenerated versions stay separate because state is keyed by backend `message_id`.
- Wired stable `messageId` + thread ID through chat, matcher, resume, interview, consult, and knowledge. Streaming and legacy messages without a stable ID retain copy/regenerate behavior but never render feedback controls.

## Verification

- `npm run test -- src/lib/feedback.test.ts src/components/conversation/FeedbackArea.test.tsx src/components/conversation/MessageActions.test.tsx`
  - PASS: 3 files, 13 tests.
- `npm run build`
  - PASS: TypeScript build and Vite production build.
- `npm run lint`
  - PASS with 2 pre-existing `react(only-export-components)` warnings in `components/ui/button.tsx` and `components/ui/badge.tsx`.

## Scope notes

- The shared worktree already had unrelated page/header/search changes. This task stages only the feedback-specific hunks in those files.
- No reviewer, dashboard, evaluation, or backend feedback persistence changes were made.

## Follow-up fixes

- Reset the negative-feedback form on every open, close, and cancel; users must select a fresh reason and explicitly opt in to context sharing each time.
- Missing stable IDs now hide feedback only. Copy and regenerate controls remain available, while stable-ID regenerate requests preserve prior versions and their per-message feedback in the wired chat, matcher, and resume views.
- Guarded feedback hydration with a per-thread mutation generation so an older initial GET cannot overwrite a completed PUT or DELETE; malformed GET payloads now surface an error, and runtime reason values are allowlisted.

## Follow-up verification

- `npm run test -- src/lib/feedback.test.ts src/components/conversation/FeedbackArea.test.tsx src/components/conversation/MessageActions.test.tsx src/store/streamStore.test.ts` — PASS (24 tests).
- `npm run build` — PASS.
- `npm run lint` — PASS with the existing two Fast Refresh warnings in `components/ui/button.tsx` and `components/ui/badge.tsx`.
