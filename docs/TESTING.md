# Testing

## Current state
Backend: full test suite exists (46 tests, `backend/tests/`), covering all four service modules plus all three API routes — see `docs/tickets/ready-for-deploy/001-backend-test-suite.md` (moves to `completed/` once deployed) for what it covers and why. This was a one-time retroactive pass to establish a baseline; every ticket from here on follows strict TDD (failing test before implementation), regardless of task size, per standing preference in the global `CLAUDE.md`.

Frontend: a real single-page UI exists (`frontend/src/app/page.tsx`, `globals.css`). Vitest + RTL landed with TICKET-003 (bulk "generate all rows" + setup modal), the first ticket that changed real component behavior. See "Frontend — Vitest + React Testing Library" below for conventions, and "Frontend — interim token harness" for the earlier CSS-only exception (TICKET-002).

## Backend — pytest
`pytest` and `httpx` (for FastAPI's `TestClient`) are in `backend/requirements.txt`.

Convention: tests live in `backend/tests/`, mirroring `backend/services/` — e.g. a test for `services/excel_parser.py` goes in `backend/tests/test_excel_parser.py`. API route tests (using FastAPI's `TestClient`) go in `backend/tests/test_main.py`. Shared fixtures — including synthetic Excel/PDF/Word file builders (`make_excel_bytes`/`make_pdf_bytes`/`make_docx_bytes`), built in-code via the same libraries the app itself uses to read them — live in `backend/tests/conftest.py`. No binary sample files are committed to the repo; fixtures are generated at test time.

Any test touching LLM mapping (`services/llm_mapper.py`) must mock `_map_with_openai`/`_map_with_gemini` — never make a real API call in a test, and never rely on the real key in `.env` being present or absent.

Run with: `pytest` from `backend/`.

## Frontend — Vitest + React Testing Library
Set up per `frontend/node_modules/next/dist/docs/01-app/02-guides/testing/vitest.md` (version-specific — check that doc before assuming a different Next.js version's setup applies, per `frontend/AGENTS.md`'s version-drift rule). Config: `frontend/vitest.config.mts`, `environment: 'jsdom'`, scoped to `include: ['src/**/*.test.{ts,tsx}']` so it doesn't collide with the separate `node:test`-based `test:tokens` harness in `frontend/tests/`.

Convention: colocate test files next to what they test — `page.tsx` + `page.test.tsx` in the same folder. RTL tests stub `fetch` via `vi.stubGlobal` and must also stub `URL.createObjectURL`/`revokeObjectURL`, which jsdom does not implement. Call `cleanup()` (from `@testing-library/react`) and `vi.unstubAllGlobals()` in `afterEach` — Vitest does not auto-cleanup between tests by default the way Jest does.

Run with: `npm run test` from `frontend/`. The `test` script name is reserved for Vitest — don't repurpose it for the interim harness below.

## Frontend — interim token harness (`test:tokens`)
For TICKET-002 (color palette change), there was no frontend test runner yet and nothing to TDD in the traditional sense — a pure CSS design-token swap has no logic to exercise with component tests. Rather than bootstrap Vitest+RTL as a side effect of a styling ticket (conflating a test-infra decision with a styling change), a zero-dependency harness was added: `frontend/tests/design-tokens.test.mjs`, run via Node's built-in `node:test` (`npm run test:tokens` from `frontend/`). It asserts old color literals are absent, new tokens match agreed values, and — the one part that's a genuine regression test rather than a lint rule — that every text/background and button-label/fill color pair clears WCAG AA (4.5:1 contrast), computed in the test itself. This harness is scoped to design tokens only; it doesn't replace Vitest+RTL, which still lands with the first component-behavior ticket.

## Updating this file
Add a note here whenever test tooling or conventions meaningfully change (new framework, new coverage expectation, new fixture pattern). This file tracks *how testing works here*, not a log of individual test runs — that's what CI/git history is for.
