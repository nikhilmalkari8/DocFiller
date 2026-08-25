# TICKET-003: Generate documents for all Excel rows, not just one

**Status:** Ready for Deploy
**Created:** 2026-08-25
**Moved to ready-for-deploy:** 2026-08-25

## Request
Nikhil: "when I give you 3 rows in the source excel, I need 3 different documents, you are considering only 1st row I guess. check on that." Investigated first — this isn't a bug, the app was built single-row-by-design: `/api/generate` always takes exactly one `row_index` (default 0), and the frontend's Row Selector lets the user manually pick one row per generate. There is no existing bulk-generation capability at all.

First clarification (via AskUserQuestion): keep the existing single-row picker for one-off generation, and add a separate "Generate All Rows" action that produces one document per row in the sheet. Delivery: individual download button per generated document (not a zip).

Second clarification (mid-planning, supersedes parts of the above): "see I will upload an excel I have 5 rows in it. 5 documents generated. Or we can do this thing, I upload 2 documents and I click upload and analyze, show a pop up asking for name and the document format they want to see it in. then submit, then we can start. Name they should be able to select a column in the source excel. We have to make the document name, the value or string in that column with respective row. Did you get it ? and then when documents geerated, we can give a download all button, which will zip all documents. clean UX"

Net effect on scope: (a) a **setup modal** appears right after Upload & Analyze, where the user picks which Excel column supplies the document name (and, eventually, the output format); (b) generated filenames come from that column's value for each row, not from a row number; (c) a **Download All (zip)** button is added *alongside* the per-document download buttons — the earlier "not a zip" instruction is now "both".

## Proposed design

### API shape — one synchronous endpoint, documents returned inline, no server-side retention

**Decision:** add `POST /api/generate-all`. It generates all N documents in a single synchronous request and returns them **inline as base64 in the JSON response**. There is **no** follow-up `GET /api/download/{session_id}/{row_index}` endpoint, and generated documents are **not** stored in the `sessions` dict.

Request:
```json
{ "session_id": "…", "mapping": { "Applicant Name": "Name", … }, "filename_column": "Bond Number" }
```

Response (HTTP 200 even with per-row failures):
```json
{
  "total_rows": 5,
  "success_count": 4,
  "error_count": 1,
  "skipped_count": 0,
  "results": [
    { "row_index": 0, "status": "ok", "label": "BND-1041",
      "filename": "BND-1041.pdf", "mime_type": "application/pdf",
      "content_base64": "JVBERi0…", "error": null },
    { "row_index": 1, "status": "error", "label": "BND-1042",
      "filename": null, "mime_type": null, "content_base64": null,
      "error": "Failed to fill template: …" }
  ]
}
```

**Why inline base64 rather than "generate now, download later" (the obvious alternative):**
- The alternative requires holding N filled documents in the in-memory `sessions` dict until each is downloaded, with no TTL and no eviction — the session already holds `excel_bytes` + `template_bytes` forever; adding N filled documents per session makes an existing, known memory leak materially worse.
- **It would also depend on session durability between the generate call and each download click** — and per `.claude/rules/in-memory-sessions.md` that assumption does not hold: a Railway restart/redeploy (which happens on every push to `main`) or any future second backend instance silently breaks every download link the user is looking at, after the work was already done. Inline return has no such window: once the response lands, the bytes are in the browser and the backend is stateless again. **This is the flag that rule asks for — this ticket deliberately avoids relying on session durability rather than building on it.**
- It matches the frontend's existing download mechanism exactly (`Blob` + `URL.createObjectURL` + synthetic `<a download>` — see `handleDownload` in `page.tsx`), so per-row download is the same code path already in use, just per item.
- It is also what makes **client-side zipping** possible without a second round of work (see below).
- Cost: base64 inflates the payload ~33%. Acceptable at this project's real scale (5 rows in Nikhil's example; templates are single-digit-MB at worst), and bounded explicitly by the row cap below.

**Why one request rather than the frontend looping `/api/generate` N times:** the loop needs no backend work, but it re-parses the workbook and re-opens the template N times, and puts filename derivation, collision handling, and per-row error classification in the browser where they can't be unit-tested against the real fill logic. One endpoint keeps all of that in Python where the pytest suite already exercises it.

**Row cap:** `MAX_BULK_ROWS = 200`. Above that, return `400` with `"Too many rows (N). Bulk generation is limited to 200 rows per request."` A single synchronous request is the right call for a handful of rows; it is the wrong call for thousands (proxy/Railway request timeouts, multi-hundred-MB JSON). Failing loudly beats an opaque gateway timeout. If real sheets ever exceed this, chunked/async generation is a follow-up ticket, not something to silently absorb here.

**Partial success is supported — one bad row must not block the others.** Each row is generated inside its own `try/except`; a failure records `status: "error"` with the message and generation continues. Real client sheets are messy (a single odd cell value can make `pymupdf.insert_text` fail), and losing 4 good documents because row 2 is bad is strictly worse than showing 4 downloads plus one visible error.

**Blank rows are skipped, not generated.** If every mapped column is empty for a row, it gets `status: "skipped"` and no document. `parse_excel`'s `total_rows` counts whatever `iter_rows` yields, which in openpyxl read-only mode can include trailing phantom rows — without this, "I gave 5 rows" could yield 7 blank documents.

### Filenames come from a user-chosen Excel column

New pure module `backend/services/filenames.py`, with `build_filenames(rows, filename_column, ext) -> list[str]` — batch, because collision handling needs to see all rows at once. Rules, in order:

1. Raw name = `str(row[filename_column])`, trimmed.
2. Sanitize: replace filesystem-illegal characters (`/ \ : * ? " < > |`) and control chars with `_`, collapse runs of whitespace to a single `_`, strip leading/trailing dots and spaces (a leading dot hides the file; a trailing dot breaks on Windows).
3. Truncate to 60 characters.
4. Empty after sanitizing (blank cell, or `filename_column` missing/not chosen) → fall back to `row_{n}` with `n` 1-based.
5. **Collision handling:** if the same sanitized name appears more than once, every colliding entry gets `_row_{n}` appended. Two rows named "John Doe" become `John_Doe_row_2.pdf` and `John_Doe_row_4.pdf`. This matters much more now than it did before: identical names inside a zip are a genuine data-loss risk, since some extractors silently overwrite.
6. Append the template's own extension.

`filename_column` is optional on the API (falls back to rule 4 for every row) so the endpoint stays robust if the frontend ever omits it. The same optional `filename_column` is added to `POST /api/generate` so a single-row download is named consistently with a bulk one — backward compatible, existing tests keep passing untouched.

### Frontend UX

**1 — Setup modal, right after Upload & Analyze.** When `handleUpload` finishes (upload + auto-map both complete), instead of dropping straight into the Review step, a modal opens:

- Title: "Set up your documents"
- Field: **Document name from column** — a `<select>` of `excel_columns`, defaulting to the first column, with live helper text showing what the first row would actually be named (`e.g. "BND-1041.pdf"`) using `excel_preview[0]`. Seeing the real resulting filename before committing is the whole value of asking up front.
- Field: **Format** — see the TICKET-004 note below. In this ticket it renders as a static, non-interactive line (`Format: PDF — same as your template`), *not* a dropdown with one option.
- Buttons: `Continue` (primary) and `Skip` (secondary — proceeds with the row-number fallback naming).

Submitting proceeds to the existing **Review Mapping** step, which is unchanged apart from a line in the `.row-selector` bar showing `Naming documents by: Bond Number` with a small `Change` button that reopens the modal. *(Interpretation flagged below: "then we can start" is read as "continue into the normal Review Mapping flow", not "skip review and generate immediately" — the mapping review is the main correctness safeguard on real client documents and shouldn't be bypassed.)*

Implemented as a `role="dialog" aria-modal="true"` overlay div (not native `<dialog>`, which needs an imperative `showModal()` effect and is awkward to drive from RTL), closable on `Escape` and on overlay click, with focus moved to the select on open.

**2 — Review step keeps everything it has.** Row selector and `✨ Generate Document` (`.btn-success`) stay exactly as-is. A third button, `📚 Generate All Rows (N)`, joins the same `.actions` row using `.btn-primary`. `.actions` is already `display:flex; gap:12px; justify-content:flex-end`, so no layout change is needed. While generating, the existing `.status-bar` + `.spinner` shows `Generating N documents…` (indeterminate — it's one request; the row cap is what keeps that honest).

**3 — Results reuse the existing `generate` step**, so the 3-step stepper is untouched. New state `bulkResults: BulkResult[] | null`; when non-null, the `step === "generate"` branch renders the bulk results card instead of the single-document success card.

**4 — Results card** reuses `.card` + `.mapping-table` (already styled for exactly this kind of row list), three columns: `Document` (the filename, e.g. `BND-1041.pdf`), `Status`, `Action`. `ok` rows get a `📥 Download` `.btn .btn-secondary`; `error`/`skipped` rows show the reason instead of a button. A summary line above reads `4 of 5 documents generated · 1 failed`, and when `error_count > 0` the existing `.error-banner` appears once above the table.

**5 — Download All (zip), client-side.** A `📦 Download All (4)` `.btn-primary` sits above the table next to the summary. It zips only the `ok` results into `filled_documents.zip` **in the browser using `jszip`**, since the bytes are already there. The alternative — a server-side zip endpoint using stdlib `zipfile` (zero new dependencies) — would have to re-run every row's fill a second time purely to package them, doubling the wait for no benefit, or else retain the documents server-side, which is exactly what the design above rejects. Client-side zipping keeps the backend stateless and the work done once. **This adds one new frontend runtime dependency (`jszip`), which needs approval before install.**

**6 — Card footer:** `← Back to Mapping` (`.btn-secondary`, returns to `review` keeping session/mapping/name-column) and `↻ Fill Another` (existing `handleReset`, which also clears `bulkResults` and `filenameColumn`).

**7 — New CSS: two classes only.** `.modal-overlay` (fixed full-screen scrim + flex centering) and `.status-error` (`color: var(--danger)`, because per-row failure text in muted grey reads as incidental rather than as a failure). The modal body itself reuses `.card`, its dropdown reuses `.mapping-select`, its buttons reuse `.actions actions-center` + `.btn-*`, and skipped-row text reuses `.preview-value`. All values come from existing `:root` tokens.

### Relationship to TICKET-004 (format choice) — deliberately not merged

The modal Nikhil described asks for **name and format**. The format half is TICKET-004's entire scope, and its cost is not UI: it needs DOCX→PDF conversion, which on Railway means adding headless LibreOffice (or similar) to the build — a real deployment risk, in a repo where every push to `main` auto-deploys. **Recommendation: build the modal here with the name-column picker only, and let TICKET-004 turn the static "Format" line into a real selector.** That keeps the risky infra change isolated in its own ticket where a failed deploy is diagnosable, and means this ticket's actual ask — 5 rows in, 5 documents out — isn't blocked behind a build-toolchain problem. The modal is shaped for it now, so 004 becomes a backend change plus one `<select>`. See Open questions if you'd rather merge them or do 004 first.

### Testing approach

**Backend: strict TDD** — failing pytest tests before implementation, in `backend/tests/test_excel_parser.py`, a new `backend/tests/test_filenames.py`, and `backend/tests/test_main.py`, using the existing in-code fixture builders. Baseline to protect: 46 tests currently passing.

**Frontend: this ticket bootstraps Vitest + React Testing Library, and does real TDD with it.** `docs/TESTING.md` and the 2026-08-23 DECISIONS entry both scope the real frontend test setup to "the first ticket that builds/changes real component behavior" — TICKET-003 is precisely that ticket (TICKET-002 was a pure CSS token swap with no logic, which is why it got the interim `node:test` token harness instead). Unlike 002 there is no justification for another interim workaround: the deferred decision has come due, and a modal with conditional flow plus a results list is exactly the kind of behavior that needs component tests.

Scope discipline: the new Vitest suite covers **only the new modal + bulk behavior plus one smoke render** — explicitly *not* a retroactive pass over all of `page.tsx` (that was TICKET-001's one-time role on the backend; a frontend equivalent is a separate ticket). Setup follows `frontend/node_modules/next/dist/docs/01-app/02-guides/testing/vitest.md`. `page.tsx` is a `"use client"` component with no async server component, so RTL renders it directly. Tests stub `fetch` via `vi.stubGlobal` and must also stub `URL.createObjectURL`/`revokeObjectURL`, which jsdom does not implement.

## Plan
```
1. Add a failing test `test_get_all_rows_returns_every_data_row` to `backend/tests/test_excel_parser.py`: build a 3-row sheet with `make_excel_bytes(["Name","Date"], …)`, assert `get_all_rows(bytes)` returns a 3-element list of dicts equal to what `get_row_data` returns for indices 0/1/2, plus a case asserting `[]` for a headers-only sheet → verify: `cd backend && python -m pytest tests/test_excel_parser.py -q` fails with `ImportError`/`AttributeError` on `get_all_rows` specifically, not on anything else

2. Implement `get_all_rows(file_bytes) -> list[dict[str, str]]` in `backend/services/excel_parser.py`, opening the workbook once (same read-only/data-only load and header extraction as `get_row_data`, stringifying values identically) → verify: `python -m pytest tests/test_excel_parser.py -q` passes and full `python -m pytest -q` is 46 + new, all green

3. Add failing `backend/tests/test_filenames.py` covering `build_filenames(rows, filename_column, ext)`: (a) plain values → `["BND-1041.pdf", "BND-1042.pdf"]`; (b) `a/b:c*d` → sanitized to `a_b_c_d.pdf` with no illegal chars remaining; (c) a 90-char value → basename truncated to 60 chars; (d) blank cell → `row_2.pdf`; (e) `filename_column=None` → every name is `row_{n}.pdf`; (f) leading/trailing dots and spaces stripped; (g) **collision** — two rows both "John Doe" (rows 2 and 4) → `John_Doe_row_2.pdf` and `John_Doe_row_4.pdf`, and asserting `len(set(result)) == len(result)` for a sheet where every row shares one name → verify: `python -m pytest tests/test_filenames.py -q` fails on the missing `services/filenames` module, with all 7 cases collected

4. Implement `backend/services/filenames.py::build_filenames` per the six rules in Proposed design → verify: `python -m pytest tests/test_filenames.py -q` fully green and `python -m pytest -q` shows no regression in the other 46

5. Add failing route tests for `POST /api/generate-all` to `backend/tests/test_main.py`, all using the existing `_upload` helper: (a) unknown session → 404; (b) 3-row PDF template with `filename_column: "Name"` → 200, `total_rows == 3`, `success_count == 3`, filenames are the three Name values with `.pdf`, each `content_base64` decodes to bytes starting with `%PDF` and containing that row's own value; (c) request omitting `filename_column` → filenames are `row_1.pdf`/`row_2.pdf`/`row_3.pdf`; (d) Word `.docm` template → per-result `mime_type` is `application/vnd.ms-word.document.macroEnabled.12` and filenames end `.docm`; (e) partial failure — `monkeypatch` `main.fill_pdf` to raise only for the second row's values → 200, `success_count == 2`, `error_count == 1`, `results[1].status == "error"` with non-null `error`, rows 0 and 2 still `ok` with content; (f) a row whose mapped columns are all empty → `status == "skipped"`, `content_base64 is None`; (g) a sheet with `MAX_BULK_ROWS + 1` rows → 400 containing `"limited to 200 rows"` → verify: `python -m pytest tests/test_main.py -q` shows exactly these new tests failing with 404 (route not registered) while all 46 pre-existing tests still pass

6. Refactor `backend/main.py` with no behavior change: extract `_build_fill_values(mapping, row_data) -> dict` and `_fill_document(session, fill_values) -> tuple[bytes, str, str]` (bytes, mime_type, ext); rewrite `/api/generate` to call them → verify: `python -m pytest -q` still passes all 46 pre-existing tests with zero edits to existing test files (step-5 tests still failing)

7. Implement `POST /api/generate-all` in `backend/main.py`: `GenerateAllRequest(session_id, mapping, filename_column: Optional[str] = None)`, 404 on unknown session, `MAX_BULK_ROWS = 200` constant + 400 guard, one `get_all_rows` call, `build_filenames` over all rows up front, per-row `try/except` classifying `ok`/`error`/`skipped`, `label` = the raw name-column value, base64 via `base64.b64encode(...).decode()` → verify: `python -m pytest -q` fully green (46 + all new), and `python -m pytest -q -k "generate"` shows both single-row and bulk suites passing

8. Add an optional `filename_column` to `GenerateRequest` and use `build_filenames` for the single-row `Content-Disposition`, with a new test asserting `filename="BND-1041.pdf"` when the column is supplied → verify: the new test passes AND the three pre-existing `test_generate_*` tests still assert `filename="filled_document.pdf"` unchanged (proving backward compatibility), full suite green

9. Install Vitest + RTL in `frontend/` per `node_modules/next/dist/docs/01-app/02-guides/testing/vitest.md` (`npm i -D vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/dom vite-tsconfig-paths`), add `vitest.config.mts` (`plugins: [tsconfigPaths(), react()]`, `environment: 'jsdom'`) and `"test": "vitest run"` to `package.json`, leaving `test:tokens` untouched; add `frontend/src/app/page.test.tsx` with a shared `renderAndUpload()` helper (stubs `fetch` for `/api/upload` + `/api/map` with a 5-row sheet, stubs `URL.createObjectURL`/`revokeObjectURL`) and one smoke test asserting the `DocFiller` h1 → verify: `cd frontend && npm run test` passes the smoke test, `npm run test:tokens` still passes unchanged

10. Add failing RTL tests for the setup modal: (a) after Upload & Analyze resolves, a `role="dialog"` appears and the Review-step mapping table is NOT yet rendered; (b) it contains a combobox listing every Excel column, defaulting to the first; (c) helper text shows the resulting first-row filename and updates when a different column is selected; (d) `Continue` closes the dialog and reveals the mapping table; (e) `Skip` also closes it and reveals the mapping table; (f) after continuing, the Review step shows `Naming documents by: <column>` and a `Change` button that reopens the dialog; (g) `Escape` closes it → verify: `npm run test` fails on exactly these seven, smoke still passing

11. Implement the modal in `frontend/src/app/page.tsx`: `filenameColumn` + `showSetupModal` state, `handleUpload` opening it instead of falling through to Review, `role="dialog" aria-modal="true"` overlay with Escape/overlay-click close, focus-on-open, the column `<select>` (`.mapping-select`), the live filename preview from `excelPreview[0]`, the static Format line, Continue/Skip, and the `Naming documents by:` + `Change` affordance in the Review step → verify: `npm run test` green for smoke + all seven modal tests, `npx tsc --noEmit` clean

12. Add failing RTL tests for the bulk flow: (a) Review renders a button matching `/Generate All Rows \(5\)/` alongside the existing `Generate Document`; (b) clicking it POSTs exactly once to a URL ending `/api/generate-all`, with a body containing `session_id`, `mapping`, and the chosen `filename_column`, and no `row_index`; (c) a canned response with 4 `ok` + 1 `error` renders 5 result rows, exactly 4 `Download` buttons, the error row's message with no button, and a summary matching `/4 of 5/`; (d) clicking one row's `Download` calls `URL.createObjectURL` once and sets the anchor `download` to that result's `filename`; (e) `Download All (4)` produces a single `URL.createObjectURL` call with a `Blob` and an anchor named `filled_documents.zip`; (f) a non-200 `/api/generate-all` renders the existing error banner and leaves the user on the Review step → verify: `npm run test` fails on exactly these six, with the modal + smoke tests still passing

13. Install `jszip` (`npm i jszip` — **needs approval, one new runtime dependency**) and implement the bulk UI in `page.tsx`: `BulkResult` type, `bulkResults` state, `handleGenerateAll`, `handleDownloadResult` (base64 → `Uint8Array` → `Blob` → existing anchor flow), `handleDownloadAll` (jszip over `ok` results → `filled_documents.zip`), the `📚 Generate All Rows (N)` button, the `Generating N documents…` status bar, the results card branch inside `step === "generate"` using `.card`/`.mapping-table`/`.btn-secondary`/`.error-banner`, and `setBulkResults(null)` + `setFilenameColumn("")` in `handleReset` → verify: `npm run test` fully green (smoke + 7 modal + 6 bulk), `npx tsc --noEmit` clean

14. Add the two new CSS rules (`.modal-overlay`, `.status-error`) to `frontend/src/app/globals.css` using only existing `:root` tokens — no other CSS changes → verify: `npm run test:tokens` still passes (no old color literals reintroduced, contrast assertions unaffected) and `git diff --stat frontend/src/app/globals.css` shows roughly a dozen added lines and zero deletions

15. Manual end-to-end check against a local stack (`cd backend && uvicorn main:app --reload`, `cd frontend && npm run dev`) with a real **5-row** Excel, against both a PDF template and a `.docx` template → verify: the modal appears after Upload & Analyze and previews a real filename; "Generate All Rows (5)" yields 5 result rows named from the chosen column; opening two downloaded files shows *different* row data in each (the original reported symptom); `Download All` produces a zip that extracts to 5 distinctly-named files; and the existing single-row Generate still works unchanged

16. Update docs: `docs/PROJECT.md` API list gains `/api/generate-all` and notes `filename_column`; `docs/TESTING.md` promotes the frontend Vitest+RTL section from "not yet added" to real, noting scope (modal + bulk + smoke) and the `fetch`/`URL.createObjectURL` stubbing convention; `docs/DECISIONS.md` gains three dated append-only entries — (i) inline-base64 bulk response with no server-side retention, and why session durability was deliberately not relied on, (ii) client-side zip via jszip rather than a server-side zip endpoint, (iii) Vitest+RTL landing here as the first component-behavior ticket, plus a note that the format half of the setup modal was deliberately deferred to TICKET-004 to isolate the LibreOffice build risk; `docs/ROADMAP.md` moves "Frontend test suite" out of Planned → verify: `grep -n "generate-all" docs/PROJECT.md` and `grep -n "Vitest" docs/TESTING.md docs/ROADMAP.md` return the new content, and `git diff docs/DECISIONS.md` shows additions only, no modified lines

17. Run the `qa-reviewer` agent over the full diff, then move this ticket to `docs/tickets/ready-for-deploy/` with the status/date header updated and Implementation/Tests/Impact filled in → verify: `python -m pytest -q` (backend) and `npm run test && npm run test:tokens` (frontend) all green, `git status` shows the ticket under `ready-for-deploy/`, and `docs/ROADMAP.md` lists TICKET-003 as ready-for-deploy
```

## Open questions for Nikhil (flag before implementing)
1. **The Format half of the modal is deferred to TICKET-004** — recommended, because format choice requires DOCX→PDF conversion, which means adding headless LibreOffice to the Railway build: a real deploy risk in a repo where every push to `main` auto-deploys. Isolating it keeps "5 rows in, 5 documents out" from being blocked behind a build-toolchain problem. In this ticket the modal shows Format as a static line rather than a one-option dropdown. Say if you'd rather merge 004 in, or do 004 first so the modal ships complete.
2. **"then submit, then we can start" is read as "continue into the normal Review Mapping step"**, not "skip review and generate immediately." The mapping review is the main correctness safeguard on real client documents, so bypassing it isn't something to infer. Confirm if you actually meant generation should kick off straight from the modal.
3. **`jszip` is a new frontend runtime dependency** (~100KB), needed for Download All. The zero-dependency alternative is a server-side zip endpoint, but it would have to re-fill every row a second time just to package them. Approve the install, or take the slower stateless-server route.
4. **Duplicate names in the chosen column** get `_row_{n}` appended to every colliding file (`John_Doe_row_2.pdf`, `John_Doe_row_4.pdf`). Silent collisions inside a zip risk actual data loss, so uniqueness is enforced rather than trusted — but if you'd rather see a visible warning in the results card when duplicates occur, that's a small addition.
5. **200-row cap** — deliberate but arbitrary. Bigger sheets need chunked/async generation, which is its own ticket rather than a bigger number.
6. **Blank rows are skipped** rather than producing blank documents, since openpyxl can report phantom trailing rows. The alternative is always emitting exactly `total_rows` documents.

## Implementation
Backend: `services/excel_parser.get_all_rows`, `services/filenames.build_filenames`, `main.py` refactored (`_build_fill_values`/`_fill_document` extracted, no behavior change to `/api/generate`), new `POST /api/generate-all`, optional `filename_column` added to `/api/generate` too. Frontend: setup modal (name-column picker, live filename preview, Continue/Skip/Escape/overlay-click, `Naming documents by: … [Change]` in Review), `Generate All Rows (N)` button, bulk results card (per-row status/Download, summary line, error banner), `Download All` via `jszip`. Vitest + RTL bootstrapped (`vitest.config.mts`, `frontend/src/app/page.test.tsx`). `tsconfig.json` excludes `vitest.config.mts` from `tsc --noEmit` due to a Vite-version type collision between Next 16's bundled Vite and Vitest's own (config-file-only, doesn't affect app code or runtime).

Deviation from plan: the plan's original filename scheme (label = first mapped value) was superseded mid-planning by a direct instruction to use a user-chosen Excel column instead — reflected in the plan before implementation started, not a deviation from what was actually built.

## Tests
Backend: 66/66 pytest passing (46 pre-existing + 20 new — `get_all_rows`, `build_filenames` incl. collision/sanitization/truncation, `/api/generate-all` incl. partial failure, skip, 200-row cap, and `filename_column` on `/api/generate`). Frontend: 16/16 Vitest passing (8 modal, 8 bulk flow) + 4/4 `test:tokens` unchanged. `npx tsc --noEmit`, `npm run lint`, `npm run build` all clean.

Real (non-mocked) end-to-end check done locally: uploaded a genuine 3-row synthetic Excel + PDF template through an actual running backend+frontend via Playwright — setup modal appeared with correct live filename preview, "Generate All Rows (3)" produced 3 result rows, downloaded two individually and confirmed **their content genuinely differs row-to-row** (the exact symptom originally reported), "Download All" produced a valid zip (`PK` magic bytes confirmed), zero browser console errors. Word/.docm path is covered by backend tests here; its own real end-to-end check happens in TICKET-004, which is specifically about format handling.

## QA review (qa-reviewer, independent pass)
Dispatched against the diff before deploy — read every changed file end-to-end, re-ran both suites independently, and reasoned through (then executed) the specific edge cases worth checking on a real-documents app. Found 3 confirmed bugs, ranked most severe first, all fixed:

1. **`build_filenames` collision suffixing wasn't actually collision-proof — genuine data-loss bug.** The dedup pass only checked for collisions among *original* sanitized basenames, then suffixed every colliding entry with `_row_{n}` — but never re-checked the *suffixed result* against the full final set. A row whose raw value happened to sanitize to exactly `{other_name}_row_{n}` for the exact `n` a colliding row would be suffixed to produced two identical filenames. In `Download All`, `zip.file()` silently overwrites one document with the other — a real financial document lost with no error shown. Reproduced by execution (`test_suffixed_name_colliding_with_another_rows_raw_value_stays_unique`), fixed with a final uniqueness pass that guarantees true uniqueness regardless of input (appends `_dup{n}` to anything still colliding after the row-suffix pass, checked against a running seen-set).
2. **Regenerating a single document after a prior bulk run showed stale bulk results, hiding the new document.** `handleGenerate` never cleared `bulkResults`, and the render branch picks the bulk results table whenever `bulkResults !== null` — so after Generate All Rows → Back to Mapping → Generate Document, the freshly generated document became inaccessible from the UI (no download button anywhere for it). Fixed: `handleGenerate` now clears `bulkResults` on success. Also wired `filename_column` into `handleGenerate`'s request body while in there, since the backend already supported it (step 8) but the frontend never sent it for the single-row path.
3. **"Skip" in the setup modal was a no-op duplicate of "Continue."** Both buttons called the same handler; `filenameColumn` is pre-populated with the first Excel column on upload, and Skip never cleared it — so there was no UI path that actually reached the documented `row_{n}` fallback naming behavior. Fixed with a separate `handleSkipSetup` that clears `filenameColumn` before closing the modal.

Also fixed, minor: `get_all_rows`/`build_filenames` calls in `/api/generate-all` were unwrapped — unlike every other fallible call in this codebase, an exception there would 500 the whole batch instead of failing cleanly. Now wrapped, returning a clean 400.

Re-verified after fixes: 66/66 backend, 16/16 frontend, tsc/lint/build/tokens all clean.

## Impact
No breaking changes — `/api/generate`'s existing behavior and response shape are unchanged; `filename_column` is optional and additive on both endpoints. New dependencies: `jszip` (frontend runtime), `vitest`/`@vitejs/plugin-react`/`jsdom`/`@testing-library/react`/`@testing-library/dom`/`vite-tsconfig-paths` (frontend dev). New files: `backend/services/filenames.py`, `backend/tests/test_filenames.py`, `frontend/vitest.config.mts`, `frontend/src/app/page.test.tsx`. Sets up TICKET-004 (format choice), which is planned as a direct follow-on edit to this ticket's modal and `/api/generate-all` — must land after this ticket, not independently.
