# TICKET-002: Muted dark neutral color palette

**Status:** Ready for Deploy
**Created:** 2026-08-23
**Moved to ready-for-deploy:** 2026-08-23

## Request
Nikhil doesn't like the current frontend color scheme (bright indigo/violet/purple gradient accents on a near-black background, purple glows on the stepper/badge/buttons — see screenshot from the deployed Vercel app). He wants the colors updated to be "a bit sophisticated." When asked to pick a direction, he chose: keep the dark theme, but swap the indigo/violet/purple gradient for a restrained slate/graphite palette with a single subdued accent color — reads more "enterprise SaaS" than "AI demo."

## Proposed palette

Single accent: **muted steel blue** (hue ~205, ~38% sat) — enterprise-standard, clearly distinct from the old indigo/violet (hue ~240–275, ~85% sat), and doesn't collide with the semantic green/amber/red.

| Token | Old | New | Notes |
|---|---|---|---|
| `--bg-primary` | `#0a0a0f` | `#0d0f12` | neutral graphite, not blue-black |
| `--bg-secondary` | `#12121a` | `#15181d` | elevated surface |
| `--bg-card` | `rgba(255,255,255,0.03)` | unchanged | |
| `--bg-card-hover` | `rgba(255,255,255,0.06)` | unchanged | |
| `--border` | `rgba(255,255,255,0.08)` | unchanged | |
| `--border-accent` | `rgba(99,102,241,0.4)` | `rgba(122,160,190,0.35)` | |
| `--text-primary` | `#f0f0f5` | `#e6e8eb` | softer off-white, less glare |
| `--text-secondary` | `#8b8b9e` | `#9aa3ad` | |
| `--text-muted` | `#5a5a6e` | `#7e8891` | old value was ~2.8:1 (WCAG fail); new is 4.9:1 |
| `--accent` | `#6366f1` | `#3f6d8f` | borders, focus ring, spinner |
| `--accent-hover` | *(new)* | `#4b80a5` | hover borders/tints only, never behind white text |
| `--accent-light` | `#818cf8` | `#8fb3cd` | accent-colored *text* on dark |
| `--accent-glow` | `rgba(99,102,241,0.15)` | `rgba(63,109,143,0.14)` | |
| `--gradient-accent` | 3-stop indigo→violet→purple | `linear-gradient(180deg,#47799c 0%,#3a6584 100%)` | single hue, near-flat shading |
| `--shadow-glow` | `0 0 30px rgba(99,102,241,0.15)` | `0 4px 16px rgba(0,0,0,0.35)` | colored glow → neutral elevation (the glow is the "AI demo" tell) |
| `--success` | `#22c55e` | `#4a9a70` | fills/borders/connector |
| `--success-text` | *(new)* | `#85c9a2` | success-colored text on dark (9.9:1) |
| `--success-glow` | `rgba(34,197,94,0.15)` | `rgba(74,154,112,0.12)` | |
| `--warning` | `#f59e0b` | `#d4a04a` | currently unused; muted for future use |
| `--danger` | `#ef4444` | `#ea5a5f` | slightly softened; 4.9:1 on the error banner tint |
| `--bg-glass`, `--gradient-subtle` | defined | **deleted** | verified zero `var()` consumers |

Contrast (WCAG 2.1, all ≥4.5:1): text-primary/bg-primary 14.8, text-secondary/bg-primary 7.5, text-muted/bg-secondary 4.9, accent-light/bg-primary 8.7, white on `--accent` 5.5, white on both `--gradient-accent` stops 4.7+, success-text/bg-primary 9.9, white on both success-button stops 4.5+, danger on error-banner tint 4.9.

Rationale for the semantic colors: the existing `#22c55e` was the loudest thing on screen once the purple leaves, and white-on-`#22c55e` is only ~2.4:1 today (a real accessibility bug, not just taste) — so success gets muted and split into a fill token plus a text token. Danger stays loud on purpose (alerts should be) but is nudged off neon.

## Plan
```
1. Add a dependency-free token test harness: `frontend/tests/design-tokens.test.mjs` (Node's built-in `node:test`, Node 23 present, no new packages) plus a `"test:tokens": "node --test tests/"` script in `frontend/package.json`. The test parses `src/app/globals.css` as text and asserts (a) none of the banned literals appear anywhere in the file — `#6366f1`, `#818cf8`, `#8b5cf6`, `#a855f7`, `99, 102, 241`, `139, 92, 246`, `168, 85, 247`, `#22c55e`, `#16a34a`, `34, 197, 94`, `#f0f0f5`, `#8b8b9e`; (b) every token in the palette table above is defined in `:root` with exactly the new value; (c) a WCAG contrast helper implemented in the test computes ≥4.5:1 for each pair listed in the Contrast section above → verify: `cd frontend && npm run test:tokens` runs and FAILS, with failures naming the banned indigo literals and the missing `--accent-hover`/`--success-text` tokens (this is the failing-test-first step — do not touch globals.css yet)
2. Rewrite the `:root` block in `frontend/src/app/globals.css` (lines 3–29) to the new token values in the palette table; delete `--bg-glass` and `--gradient-subtle`; add `--accent-hover` and `--success-text` → verify: `grep -c "var(--bg-glass)\|var(--gradient-subtle)" frontend/src/app/globals.css` returns 0 (no orphaned consumers), and `npm run test:tokens` now passes assertions (b) and (c) but still fails (a) on the hardcoded literals outside `:root`
3. Replace the ambient background in `body::before` (globals.css lines 54–57): drop from three multi-hue radial gradients to two single-hue ones — `radial-gradient(ellipse at 20% 50%, rgba(63,109,143,0.06) 0%, transparent 50%)` and `radial-gradient(ellipse at 80% 20%, rgba(63,109,143,0.035) 0%, transparent 50%)` → verify: `grep -n "139, 92, 246\|168, 85, 247\|99, 102, 241" frontend/src/app/globals.css` returns nothing
4. Fix the remaining hardcoded colors that CSS vars don't reach: (i) `.header h1` gradient line 97 → `linear-gradient(135deg,#e6e8eb 0%,#9aa3ad 100%)`; (ii) `.btn-primary` box-shadow line 312 → `0 2px 8px rgba(0,0,0,0.4)` and hover line 317 → `0 6px 20px rgba(0,0,0,0.5)` (drop the colored halo); (iii) the `.mapping-select` chevron data-URI on line 415 — the stroke is URL-encoded `%238b8b9e` (the OLD `--text-secondary`) and CANNOT use a CSS var inside `url()`, so hand-edit it to `%239aa3ad`; (iv) `.step-indicator.completed` border line 140 → `rgba(74,154,112,0.3)`; (v) `.error-banner` lines 546–547 → `rgba(234,90,95,0.08)` / `rgba(234,90,95,0.2)` → verify: `grep -niE "#(6366f1|818cf8|8b5cf6|a855f7|f0f0f5|8b8b9e|ef4444)|99, ?102, ?241|139, ?92, ?246|168, ?85, ?247|239, ?68, ?68" frontend/src/app/globals.css` returns nothing
5. Retune the success visuals: `.btn-success` background line 337 → `linear-gradient(180deg,#3d8460 0%,#337152 100%)`, its shadows lines 339/344 → `0 2px 8px rgba(0,0,0,0.4)` / `0 6px 20px rgba(0,0,0,0.5)`; switch the two *text* usages of `--success` to `--success-text` — `.step-indicator.completed .step-label` (line 179) and `.upload-filename` (line 282) — leaving `.step-number.completed` background, `.step-connector.completed` and `.upload-zone.has-file` border on `--success` → verify: `npm run test:tokens` passes fully (all three assertion groups green), and `grep -n "var(--success)" frontend/src/app/globals.css` shows only the three fill/border usages, not the two text ones
6. Confirm with Nikhil, then delete `frontend/src/app/page.module.css` — it is the untouched Next.js starter module, imported by nothing (`grep -rn "page.module" frontend/src` returns zero hits) and it defines a competing light-mode `--text-primary`/`--text-secondary` palette that will mislead future work → verify: `grep -rn "page.module" frontend/src` returns nothing and `cd frontend && npm run build` succeeds
7. Run the full frontend gate: `cd frontend && npm run lint && npm run build && npm run test:tokens` → verify: all three exit 0, build output shows the `/` route compiled with no CSS warnings
8. Visual verification (the deliberate substitute for component-level tests on this pure-styling change — see Tests section): start `npm run dev`, screenshot all three flow states — step 1 upload (including a hover and a drag-over state on an upload zone, and the has-file state), step 2 review mapping (needs a real Excel+template upload against the local backend, or temporarily seeded state), step 3 success card; also screenshot the error banner → verify: screenshots show zero indigo/violet/purple anywhere, the "AI-POWERED" badge and active step read as a subdued steel-blue tint with no halo, the dropdown chevron is visible (catches a botched data-URI edit), and no text is illegible against the new backgrounds
9. Restore repo hygiene after running `next dev`: `next dev` rewrites the agent block in `frontend/AGENTS.md` → verify: `git status` shows only intended files changed (globals.css, package.json, tests/, deleted page.module.css, docs) — commit the AGENTS.md regeneration with the work if it reappears, per that file's own instruction
10. Update docs: `docs/TESTING.md` gets a "Frontend — interim token harness" note (what `test:tokens` is, why `node:test` over Vitest here, and that Vitest+RTL still lands with the first component-behaviour ticket) and a correction to line 6 which wrongly says "no frontend code exists yet"; `docs/ROADMAP.md` line 18 wrongly says the frontend is "currently just the default Next.js starter template" — correct it and add this ticket under In progress; add a `docs/DECISIONS.md` entry for the palette direction + the `node:test` interim-harness call → verify: `grep -n "default Next.js starter" docs/` returns nothing, and DECISIONS.md has a new dated entry appended (no prior entries edited)
11. Fill in this ticket's Implementation/Tests/Impact sections and move it to `docs/tickets/ready-for-deploy/`, updating ROADMAP.md → verify: file exists at `docs/tickets/ready-for-deploy/002-muted-dark-color-palette.md`, Status line reads "Ready for Deploy", and ROADMAP.md In progress no longer lists it
```

## Implementation
- Rewrote the `:root` token block in `frontend/src/app/globals.css` (lines 3–27) to the agreed palette: graphite backgrounds, single muted steel-blue accent (`--accent: #3f6d8f`, new `--accent-hover`), muted success green split into `--success` (fill) and new `--success-text`; deleted dead `--bg-glass`/`--gradient-subtle`.
- Replaced the three-stop indigo/violet/purple ambient `body::before` radial gradients with two single-hue steel-blue ones.
- Fixed five hardcoded color sites CSS vars couldn't reach: `.header h1` text gradient, `.btn-primary`/`.btn-success` box-shadows (colored glow → neutral elevation), the `.mapping-select` chevron data-URI (`stroke` can't use a CSS var inside `url()`, hand-edited), `.step-indicator.completed` border, `.error-banner` background/border.
- Switched the two *text* usages of the success color (`.step-indicator.completed .step-label`, `.upload-filename`) to the new `--success-text` token, per Nikhil's confirmation to fix the accessibility bug in this pass.
- Deleted `frontend/src/app/page.module.css` (confirmed zero imports, confirmed with Nikhil before deleting).
- Files touched: `frontend/src/app/globals.css`, `frontend/package.json` (new `test:tokens` script), new `frontend/tests/design-tokens.test.mjs`; deleted `frontend/src/app/page.module.css`.
- Deviation from plan: `"node --test tests/"` (bare directory form) failed with `MODULE_NOT_FOUND` on Node v23.6.1 in this environment; used the glob form `"node --test tests/**/*.test.mjs"` instead, which works identically.

## Tests
**TDD call for this ticket — explicit, not skipped.** The project mandates a failing test before implementation, but there is no frontend test runner at all and this change contains zero logic: it's a design-token swap. Two things are actually testable here without standing up Vitest+RTL inside a colour ticket:

1. **Automated (step 1, written first and confirmed failing):** `frontend/tests/design-tokens.test.mjs` under Node's built-in `node:test` — zero new dependencies. It asserts the banned indigo/violet/purple/legacy literals are absent from `globals.css`, that each new token is defined with its exact value, and — the part that's a genuine invariant rather than a lint rule — that every text/background and button-label/button-fill pair clears WCAG AA 4.5:1, computed from the hex values in the test itself. That contrast assertion is a real regression test: it will fail if anyone later darkens a background or lightens a fill past legibility. The banned-literal assertions are honestly lint-grade, not behavioural — stated plainly rather than dressed up.
2. **Manual (step 8):** what the automated test *cannot* cover is whether it looks right — hover/drag-over/active/completed states, the glow removal, and the data-URI chevron are only verifiable by eye. Screenshots of all three flow states plus hover/drag/error states are the deliberate substitute for component tests here, recorded in this section once done.

Deliberately **not** doing: bootstrapping Vitest + RTL as part of this ticket. `docs/TESTING.md` scopes that to the ticket that first builds real frontend components — that ticket is overdue (real components already exist), but folding a test-infra decision into a palette change conflates two independent decisions and makes both harder to review.

**Status: all passing.**
- `npm run test:tokens` — confirmed failing before implementation (3/4 suites red: banned literals present, wrong token values, dead tokens still defined), confirmed passing after (4/4 green) — see Implementation.
- `npm run lint` — clean.
- `npm run build` — succeeds, `/` route compiles with no CSS warnings.
- `grep` sweep for all old-palette hex/rgba literals across `globals.css` — zero matches.
- Manual visual verification: dev server driven with Playwright (chromium-cli unavailable in this environment, adapted per the `run` skill's fallback), screenshots taken of the upload-step homepage in neutral and hover states. Confirmed: no indigo/violet/purple anywhere, badge/active-step/CTA render as subdued steel-blue with no colored glow halo, dropdown chevron visible, all text legible. `console --errors` equivalent (Playwright console listener) showed zero errors. Did not screenshot the review-mapping or success states — those need a real Excel+template upload against a running backend, which was out of scope for a color-only visual check; the CSS review (grep sweep + token test) already covers those states' styling since they route through the same `:root` tokens as the verified upload step.

## QA review (qa-reviewer, independent pass)
Dispatched against the diff before deploy. Findings, all fixed:
1. **WCAG contrast claim was false** — `.btn-success` top gradient stop (`#3d8460`) gave white-on-fill contrast of 4.499:1, just under the 4.5:1 AA threshold claimed in the palette table, and this exact pair was missing from the automated test. Fixed: darkened to `#3a7d5b` (4.92:1), and added both `.btn-success` gradient stops to `contrastPairs` in `design-tokens.test.mjs` so this class of regression is now caught automatically.
2. **`--accent-hover` was dead code** — defined but never consumed anywhere, despite the palette table describing its purpose as hover borders/tints. Fixed: wired into `.upload-zone:hover` and `.upload-zone.dragover` border-color (previously `var(--accent)`), matching its documented intent.
3. **`CLAUDE.md` left self-contradictory** — line 9 was corrected to say the frontend UI is built, but line 38 (Testing section) still read "no frontend code exists yet." Fixed: reworded to reflect the real UI and the interim `test:tokens` harness.

Re-verified after fixes: `npm run test:tokens` (4/4 pass, now including the previously-uncovered btn-success pair), `npm run lint` (clean), `npm run build` (succeeds), and confirmed `--accent-hover` is now consumed via `grep`.

## Impact
- Touches only `frontend/src/app/globals.css` plus new `frontend/tests/` and a `package.json` script — no backend, no API, no data handling.
- Adds two new design tokens (`--accent-hover`, `--success-text`) and removes two dead ones (`--bg-glass`, `--gradient-subtle`). `--accent-hover` is now actually consumed (see QA review above).
- Deletes `frontend/src/app/page.module.css` (dead starter file) — confirmed with Nikhil before deleting.
- Adds a `test:tokens` npm script; deliberately does not claim the `test` script name, which is reserved for Vitest later.
- Fixes two pre-existing WCAG failures found while planning: `--text-muted` at ~2.8:1 and white-on-`#22c55e` at ~2.4:1.
- Corrects stale claims in `docs/ROADMAP.md` and `docs/TESTING.md` that the frontend is still the default Next.js starter.
