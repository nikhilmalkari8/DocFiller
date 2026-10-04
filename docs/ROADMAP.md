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
- Bulk "Generate All Rows" + setup modal + naming column — see `docs/tickets/completed/003-bulk-generate-all-rows.md`. QA-reviewed (3 bugs found and fixed, most severe a filename-collision data-loss bug in Download All). Deployed and live.
- PDF/Word output format choice via headless LibreOffice conversion — see `docs/tickets/completed/004-format-choice-download.md`. QA-reviewed (2 bugs found and fixed: Skip permanently hiding the Format selector, and an unhandled LibreOffice subprocess timeout able to crash an entire bulk batch). Deployed and live — `GET /api/health` confirms `pdf_conversion: true` on production, verified with a real end-to-end PDF generation round trip against the live backend using synthetic data.

## In progress
_(nothing in flight — TICKET-005 is implemented and awaiting deploy confirmation, below)_

## Ready for deploy
- **TICKET-005 — Transformation engine** (`docs/tickets/ready-for-deploy/005-transformation-engine.md`). Sub-project 1 of the "zero-config bond form" goal. Implemented with TDD (262 backend tests pass, up from 103), independently QA-reviewed (2 bugs found and fixed), verified end-to-end against a local server with synthetic data. **Not deployed.** Backward compatible and inert in production: no frontend change, and `/api/map` doesn't return transforms unless asked.
- Pending: **TICKET-006** (`docs/tickets/pending/006-word-fill-xml-escaping.md`) — Word fill doesn't XML-escape values; not yet reproduced.

## Planned
Goal (Nikhil, 2026-10-04): upload an untagged bond form (`.docx` or `.pdf`) + Excel → AI finds fields, maps them, applies transformations (amount in words, dates, currency, join/split…) → generates all forms, with as close to zero manual configuration as possible. The same form is reused across batches, so a form is analysed once and saved as a reviewable **recipe**. Detection approach: text + geometry → LLM (vision LLM only later, if scanned PDFs matter). Remaining sub-projects, in order, each with its own spec → plan → build cycle:
2. Word field detection + write-back + recipe model
3. PDF field detection + write-back (exact original typography is not achievable for PDFs with subset fonts — closest visual match)
4. Recipe storage (Railway volume vs Postgres, undecided) + review UI

## Done (deployment infra)
- Vercel deployment pipeline fully fixed and confirmed working end-to-end: `docfiller-app` (the real production project) is connected to `nikhilmalkari8/DocFiller` on GitHub with Root Directory set to `frontend`, the unrelated stray project `doc-filler` has been deleted, and a real git-triggered production build succeeded (commit `7329b11`, deployment `dpl_FH42zYQJTHTSh6ZkLg4kp1W1QBkN`, `READY`). Every future push to `main` now auto-deploys both backend (Railway) and frontend (Vercel) with no manual steps. See `docs/DECISIONS.md` for the full discovery.

## Not planned / explicitly out of scope for now
- Moving session storage off the in-memory dict (Redis/DB, TTL/cleanup-on-close). Explicitly raised and explicitly declined by Nikhil (2026-08-25) — known debt, staying "until server restart" as-is. Don't build this without being asked again.
