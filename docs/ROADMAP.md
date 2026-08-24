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
- Confirm the `docfiller-app` → GitHub auto-deploy actually fires on a real push (connected 2026-08-23, but no push has happened since to prove it end-to-end) — worth checking the next time a frontend change ships. Also worth confirming the project's Root Directory setting is `frontend` in the dashboard, which isn't readable via the current Vercel MCP tools.

## Done (deployment infra)
- Vercel deployment pipeline fixed: `docfiller-app` (the real production project — matches backend CORS, has real traffic) is now connected to `nikhilmalkari8/DocFiller` on GitHub, so pushes to `main` will auto-deploy it going forward. The unrelated stray project `doc-filler` (was auto-deploying instead, but wasn't actually in use) has been deleted. See `docs/DECISIONS.md` for the full discovery and resolution.

## Not planned / explicitly out of scope for now
_(nothing marked yet)_
