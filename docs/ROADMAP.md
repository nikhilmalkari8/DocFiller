# Roadmap

Living document — update this whenever a ticket starts, moves, or completes. This is the fastest way for a new session to understand "where are we right now."

## Current focus
Frontend and backend are being developed together, no strict ordering — work happens on whichever piece a given ticket touches.

## Done
- Backend API: upload, map (LLM-powered), generate endpoints working end-to-end
- Deployment pipeline: backend → Railway, frontend → Vercel
- CORS configured for the deployed frontend domain
- Backend test suite (46 tests, all 4 services + all 3 API routes) — see `docs/tickets/completed/001-backend-test-suite.md`. Last non-TDD ticket; strict TDD applies from here on. Deployed and live.
- Frontend color palette: muted slate/steel-blue replaces the old indigo/violet/purple theme — see `docs/tickets/completed/002-muted-dark-color-palette.md`. Deployed and live at https://docfiller-app.vercel.app.

## In progress
- TICKET-003 (bulk "generate all rows" + setup modal + naming column) — backend and frontend implemented, all tests passing, real end-to-end check done locally. Not yet through `qa-reviewer` / moved to `ready-for-deploy/`.
- TICKET-004 (PDF/Word format choice in the setup modal) — planned, depends on TICKET-003 landing first (edits 003's modal and `/api/generate-all`).

## Planned
_(nothing else queued — see docs/tickets/pending/ for what's active)_

## Done (deployment infra)
- Vercel deployment pipeline fully fixed and confirmed working end-to-end: `docfiller-app` (the real production project) is connected to `nikhilmalkari8/DocFiller` on GitHub with Root Directory set to `frontend`, the unrelated stray project `doc-filler` has been deleted, and a real git-triggered production build succeeded (commit `7329b11`, deployment `dpl_FH42zYQJTHTSh6ZkLg4kp1W1QBkN`, `READY`). Every future push to `main` now auto-deploys both backend (Railway) and frontend (Vercel) with no manual steps. See `docs/DECISIONS.md` for the full discovery.

## Not planned / explicitly out of scope for now
- Moving session storage off the in-memory dict (Redis/DB, TTL/cleanup-on-close). Explicitly raised and explicitly declined by Nikhil (2026-08-25) — known debt, staying "until server restart" as-is. Don't build this without being asked again.
