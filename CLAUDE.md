# Dindu (DocFiller)

Fills document templates (PDF/Word) from Excel data, using an LLM to map template placeholders to Excel columns. Full detail in `docs/PROJECT.md` — read it before starting real work if you haven't already this session.

**Real use, real documents.** Not experimental — treat correctness and data handling as high stakes. See `docs/PROJECT.md` for specifics (data goes to third-party LLMs, held in-memory server-side).

## Stack
- Backend: FastAPI, Python 3.11, `backend/` — deployed to Railway
- Frontend: Next.js 16.3.2, React 19, TypeScript, `frontend/` — deployed to Vercel, real single-page UI already built (see `docs/PROJECT.md`)

## Before starting work
1. Read `docs/ROADMAP.md` for current priorities and what's in flight
2. Check `docs/tickets/pending/` and `docs/tickets/ready-for-deploy/` for anything already active
3. Skim relevant entries in `docs/DECISIONS.md` if touching something with prior history

## Workflow for any feature/bugfix (actual code work)
Full ceremony applies per global preferences (brainstorm → plan → TDD → verify) — this is not optional for code changes on this project.

**Choosing the planning/review tooling:** for a single coherent change — the normal case, one feature or bugfix touching a handful of related files — use the `planner` agent for the plan step and the `qa-reviewer` agent for the verify step; the plan goes straight into the ticket's `Step → verify` format. Reserve `superpowers:writing-plans` + `superpowers:subagent-driven-development` for genuinely large, decomposable work: multiple independent subsystems that could each be built by a separate subagent in its own worktree (e.g. building out the real frontend UI, or anything with parallelizable, non-overlapping pieces). Don't default to the heavier superpowers tooling for a routine ticket — it writes plans to `docs/superpowers/plans/`, a different location and format than `docs/tickets/`, and fragments the ticket system built here.

**Dispatching `planner` is mandatory, not a judgment call.** `planner` is pinned to `model: opus`. The point of dispatching it isn't just "get a plan written" — it's that planning/architecture happens at Opus tier while the orchestrating session and implementation stay on the cheaper default model (Sonnet). Skipping the dispatch because "I already read the relevant files, this is redundant" defeats that split even when the resulting plan would look identical — always dispatch it for the plan step on real code work, no exceptions for how well-explored the task already feels. This explicitly overrides the general "don't spawn agents unless asked, handle it inline" session default for this one case: that default exists to avoid pointless dispatch overhead, but this dispatch isn't pointless, it's the entire mechanism for the model-tiering split. See `docs/DECISIONS.md` for the full reasoning.

1. Create `docs/tickets/pending/NNN-short-slug.md` from `docs/tickets/TEMPLATE.md` when starting
2. Write the plan into it (`Step → verify: check` format)
3. TDD: write the failing test first, then implement
4. Once implemented and tests pass, move the ticket file to `docs/tickets/ready-for-deploy/`
5. Once actually deployed and confirmed live, move it to `docs/tickets/completed/`
6. Update `docs/ROADMAP.md` at each transition
7. If a real architectural/technical decision was made along the way, add an entry to `docs/DECISIONS.md`

This workflow doesn't apply to non-code work (org/config/docs changes) — see global `CLAUDE.md` for that scope boundary.

## Running it
- Backend: `cd backend && uvicorn main:app --reload` (port 8000)
- Frontend: `cd frontend && npm run dev` (port 3000)

## Testing
Backend test suite exists (`backend/tests/`, run with `pytest` from `backend/`). Frontend has a real UI (see Stack above) but no component-level test suite yet — one interim harness exists (`frontend/tests/`, `npm run test:tokens`). See `docs/TESTING.md` for conventions.
