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
_(nothing yet — see docs/tickets/pending/ and docs/tickets/ready-for-deploy/ for anything currently active)_

## Planned
- Frontend test suite — Vitest + React Testing Library, added as part of the ticket that first builds/changes real frontend component behavior (this is now overdue: a real single-page UI already exists in `frontend/src/app/page.tsx`, contrary to what this file previously said)
- Eventually: move session storage off in-memory dict to something durable (Redis/DB) before this scales past single-instance/single-session use — not urgent yet, but known debt

## Done (deployment infra)
- Vercel deployment pipeline fully fixed and confirmed working end-to-end: `docfiller-app` (the real production project) is connected to `nikhilmalkari8/DocFiller` on GitHub with Root Directory set to `frontend`, the unrelated stray project `doc-filler` has been deleted, and a real git-triggered production build succeeded (commit `7329b11`, deployment `dpl_FH42zYQJTHTSh6ZkLg4kp1W1QBkN`, `READY`). Every future push to `main` now auto-deploys both backend (Railway) and frontend (Vercel) with no manual steps. See `docs/DECISIONS.md` for the full discovery.

## Not planned / explicitly out of scope for now
_(nothing marked yet)_
