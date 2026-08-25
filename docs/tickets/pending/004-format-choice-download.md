# TICKET-004: Let user choose output format (Word or PDF) in the setup modal

**Status:** Pending
**Created:** 2026-08-25
**Revised:** 2026-08-24 (re-planned after TICKET-003 introduced the setup modal; the earlier per-download format selector design is superseded)

## Request
Nikhil: "I want the documents to be available as pdf too. User should be able to have an option to download their desired format, pdf or docx or their original one itself."

Currently generated documents are only available in whatever format the template was (PDF stays PDF, .docx/.docm stays Word) — no conversion exists at all, and there's no dependency for it in `backend/requirements.txt`.

Clarified direction (via AskUserQuestion): only add DOCX → PDF conversion — skip PDF → DOCX entirely. Flagged and confirmed with Nikhil: DOCX → PDF is standard/reliable; PDF → DOCX is fragile and often lossy (tables/formatting), too risky for real client documents (bond forms, financial paperwork). Practical effect: a PDF-templated document only ever offers "PDF" (== original, nothing to convert); a Word-templated document offers "Word — original" and a new "PDF (converted)" option.

**Second clarification (via AskUserQuestion, supersedes the original per-download design):** format is chosen **once, in TICKET-003's setup modal, and applies to the whole batch** — not per document after generation. The user picks name-column and format together before anything is generated, and every document that run produces comes out in that format.

## Dependency on TICKET-003 — hard, not optional

This ticket is planned **on top of** TICKET-003 (bulk "generate all rows") and must be implemented after it. It assumes 003 has already landed:
- the setup modal (`role="dialog"`, name-column `<select>`, live filename preview, Continue/Skip, and the `Naming documents by: … [Change]` line in the Review step), including the static `Format: …` line this ticket replaces;
- `POST /api/generate-all` with `GenerateAllRequest(session_id, mapping, filename_column)` and the inline-base64 results list;
- `backend/services/filenames.py::build_filenames(rows, filename_column, ext)`;
- `main.py`'s extracted `_build_fill_values` / `_fill_document` helpers;
- Vitest + RTL bootstrapped in `frontend/`, with `frontend/src/app/page.test.tsx` and its `renderAndUpload()` helper.

If 003's shape changes during implementation, re-check steps 7–11 and 13–14 here before starting.

**Note on a small inaccuracy in 003's plan:** its modal renders a hardcoded `Format: PDF — same as your template` line. That's wrong for a Word template (which is not a PDF), and 003 has no way to know the template type because `/api/upload` doesn't return it. This ticket adds `template_type` to `/api/upload` (step 6) and makes the line correct for both cases.

## Proposed design

### 1. Conversion engine: LibreOffice headless via subprocess, installed with nixpacks `aptPkgs`

**Recommendation: `soffice --headless --convert-to pdf`, with LibreOffice installed into the Railway image via `aptPkgs` in `backend/nixpacks.toml`.**

Why, against the alternatives actually considered:

- **Pure-Python libraries don't exist for this.** `docx2pdf` is the usual suggestion but it is a thin wrapper that shells out to Microsoft Word (COM on Windows, AppleScript on macOS) or LibreOffice — it does not remove the system dependency, it hides it. Worse, it would *work locally* on this machine (Microsoft Word.app is installed) and *fail on Railway's Linux container*, which is the worst possible failure shape: green locally, broken in production. Genuinely pure-Python paths (docx → HTML → WeasyPrint, or python-docx → reportlab) re-implement Word layout from scratch and lose tables, columns, headers/footers and exact positioning — unacceptable for bond forms and financial paperwork where the filled document is the deliverable.
- **Third-party cloud conversion APIs (CloudConvert, Adobe, etc.) are rejected on data-handling grounds.** This project already sends *column names, placeholder names and preview values* to OpenAI/Gemini for mapping (see `docs/PROJECT.md`). A conversion API is a materially bigger exposure: it receives the **complete filled client document** — every field, fully populated — not just schema hints. Adding a second third party that sees whole documents, for a feature that can be done locally, isn't a trade worth making here. (If Nikhil disagrees, this is worth an explicit decision entry rather than a silent one.)
- **LibreOffice is the reference implementation for OOXML → PDF fidelity** outside of Word itself, is what almost every self-hosted document pipeline uses, and keeps every byte of the client document inside the existing Railway container.

Install mechanism — `aptPkgs`, not `nixPkgs`:

```toml
[phases.setup]
nixPkgs = ["mupdf", "swig", "freetype", "harfbuzz", "openjpeg", "jbig2dec", "libjpeg", "pkg-config"]
aptPkgs = ["libreoffice-writer", "fonts-liberation"]
```

`aptPkgs` is a documented nixpacks phase field (verified against https://nixpacks.com/docs/configuration/file — "Apt packages: list of packages to install with `apt-get`"), and the nixpacks build image is Debian-based, so this works alongside the existing `nixPkgs` list rather than replacing it. Debian's `libreoffice-writer` (which pulls `libreoffice-core`, providing `/usr/bin/soffice` and the `writer_pdf_Export` filter) is a few hundred MB; the nixpkgs `libreoffice` derivation drags in a much larger GUI closure and is the wrong tool here. `fonts-liberation` supplies metric-compatible substitutes for Arial/Times New Roman — without it, a template using Word's default fonts reflows in the PDF and can push text off a form field. No Java is needed: Writer's PDF export doesn't require it (that's Base/wizards).

Expected cost: image grows by roughly 0.5–1 GB and the Railway build gets a couple of minutes longer. **This is not a proven number — it must be verified against the actual Railway build**, which is why the plan verifies it empirically rather than assuming.

**Runner-up, deliberately not chosen now:** run [Gotenberg](https://gotenberg.dev) (a Docker service wrapping LibreOffice) as a second Railway service and POST the DOCX to it over Railway's private network. That keeps the backend image small, isolates LibreOffice's memory use and crashes, and still lets no data leave Railway. It's rejected for now only because it doubles the number of deployable services for one feature. To keep that door open, all conversion goes behind a single `backend/services/format_converter.py` with a pure `bytes -> bytes` (and `list[bytes] -> list[bytes|None]`) interface and no FastAPI/asyncio knowledge, so swapping subprocess for an HTTP call later is a one-file change.

### 2. Correctness hazard: merge fields must be flattened before conversion

`fill_word_template` replaces the **display text** `«FieldName»` inside each merge field but deliberately leaves the surrounding `MERGEFIELD` field structure (`fldChar begin` / `instrText` / `separate` / result run / `fldChar end`) intact. Word renders the cached result, so the DOCX download shows the filled value — which is why the current behaviour works.

LibreOffice, however, imports `MERGEFIELD` as a *database field* and, with no data source attached, may re-render it from the field instruction — i.e. print `«Name»` (or blank) instead of the filled value. If that happens, the PDF silently comes out **unfilled**, which is exactly this project's worst failure mode: a plausible-looking wrong document handed to a client.

Rather than depend on which way LibreOffice behaves, the PDF path flattens first: a new `flatten_merge_fields(doc_bytes) -> bytes` in `word_processor.py` strips the field-structure runs and leaves the literal filled text. This is applied **only on the conversion path** — the Word download keeps today's exact bytes and behaviour, so nothing about the currently-working Word output changes.

### 3. API shape: one shared `output_format` on both generate endpoints

Both request models take the **same field, same name, same type**:

```python
OutputFormat = Optional[Literal["original", "pdf", "docx"]]   # None == "original"

class GenerateRequest(BaseModel):      # single row (existing)
    session_id: str
    mapping: dict[str, str]
    row_index: Optional[int] = 0
    filename_column: Optional[str] = None   # from TICKET-003
    output_format: OutputFormat = None      # this ticket

class GenerateAllRequest(BaseModel):   # bulk (TICKET-003)
    session_id: str
    mapping: dict[str, str]
    filename_column: Optional[str] = None
    output_format: OutputFormat = None      # this ticket
```

One name and one `Literal` across both endpoints, because the frontend now sends the *same* user choice to whichever endpoint runs — divergent names or a bool on one side and a string on the other is exactly how "PDF on single, DOCX on bulk" bugs happen. Enforced in code by a single shared resolver rather than two copies of the matrix:

```python
_resolve_output(session, output_format) -> (needs_pdf_conversion: bool, ext: str, mime_type: str)
```

called by both routes. Behaviour matrix (identical for both endpoints):

| template_type | output_format | result |
|---|---|---|
| pdf | absent / `original` / `pdf` | filled PDF, no conversion (unchanged code path) |
| pdf | `docx` | **400** — "Converting a PDF template to Word isn't supported." |
| word | absent / `original` / `docx` | filled `.docx`/`.docm` (unchanged code path) |
| word | `pdf` | flatten → convert → PDF, `.pdf` extension, `application/pdf` |
| any | anything else | 422 from pydantic's `Literal` validation |

The resolved `ext` is what gets passed to TICKET-003's `build_filenames(rows, filename_column, ext)`, so bulk filenames are `BND-1041.pdf` when PDF was chosen and `BND-1041.docm` when it wasn't — the naming and format decisions stay consistent by construction instead of by two independent code paths agreeing.

**Exactly one artifact per document, produced at generate time.** The earlier revision of this ticket converted lazily at download time and cached per-format blobs in the browser; that whole mechanism is deleted now that format is chosen up front. What is deliberately *kept* from that reasoning:
- **Never generate both formats.** LibreOffice costs ~1–3 s warm, ~5–10 s cold, ~150–300 MB RSS per run. Producing a Word *and* a PDF copy of every document to cover both cases would double bulk generation time for output the user didn't ask for.
- **Nothing filled is retained server-side.** Generated bytes are streamed out (single) or returned inline as base64 (bulk) and immediately dropped; the `sessions` dict never holds filled client documents. Format choice doesn't change that.
- **No stale-artifact hazard.** Because format is fixed before generation, there is no window in which the page shows one document and the cached blob is another — the failure mode the old plan needed a dedicated cache-invalidation test for simply doesn't exist in this design.

**Bulk conversion is batched, with per-file retry.** Bulk is the new pressure this design has to take. Converting N documents with N separate `soffice` invocations pays the process-startup cost N times (~5–10 s each cold), so 5 rows could take a minute and 200 would be hopeless. LibreOffice accepts many input files in one invocation and writes one PDF per input into `--outdir`, so `format_converter` exposes the **batch call as the primitive**:

```python
convert_many_to_pdf(docs: list[bytes], source_ext: str) -> list[Optional[bytes]]   # None == that file failed
convert_to_pdf(doc_bytes, source_ext) -> bytes                                     # thin wrapper, raises on failure
```

The tradeoff batching introduces is failure isolation: one pathological document could take down a whole `soffice` run and, with it, every other document's conversion — which would violate TICKET-003's explicit "one bad row must not block the others" property. Mitigation, and it's cheap: after the batch run, any input whose output PDF is missing is retried **individually**; only if the individual retry also fails does that row become `status: "error"`. Fast path stays fast, isolation is preserved.

**Concurrency limiter, now included rather than deferred.** The previous revision noted a semaphore as "necessary if bulk ever converts many rows" and deferred it. Bulk exists now, and there's no auth in front of this API, so two overlapping bulk requests could have two LibreOffice processes at ~150–300 MB each competing on a small Railway container. A module-level `asyncio.Semaphore(1)` in `main.py` wraps every conversion call (the semaphore lives in `main.py`, not `format_converter.py`, so the converter module stays sync/pure and Gotenberg-swappable). Serialising conversions costs nothing at this project's real concurrency and removes an OOM-shaped failure.

Two supporting changes carried over unchanged:
- **Off the event loop.** Both routes are `async def`; a multi-second blocking `subprocess.run` inside one stalls the whole event loop (including `/api/health`, which Railway's healthcheck depends on — see `docs/DECISIONS.md`, 2026-08-24). Conversion goes through `starlette.concurrency.run_in_threadpool`.
- **`/api/health` reports converter availability**: `{"status": "ok", "pdf_conversion": true|false}`. Makes "did LibreOffice actually land in the deployed image?" a single `curl` instead of a guess. Leaks nothing sensitive.

Failure handling is explicit and never silent:
- converter binary missing → **503** "PDF conversion is unavailable on this server". On `/api/generate-all` this is checked **before any row is filled**, so a converter-less server fails in milliseconds instead of after 200 fills.
- single-row conversion failed/timed out → **500** "Failed to convert document to PDF: …".
- bulk per-row conversion failure (after individual retry) → that row gets `status: "error"` with the message; the other rows still return `ok`. Consistent with 003's partial-success contract.
- Under no circumstance does a request for PDF fall back to returning the Word file. A silently-wrong-format download is a wrong-deliverable bug.

### 4. Frontend UX — one format choice, in the setup modal

**The Format line in TICKET-003's setup modal becomes the real control.** No selector appears anywhere else: not on the single-document success card, not per row in the bulk results table. One decision, made before generation, applied to everything that run produces.

`/api/upload` additionally returns `template_type` (`"pdf"` | `"word"`) — the backend already computes and stores it, and returning it avoids the frontend re-deriving format rules from a filename in a second place. New `templateType` state in `page.tsx`, set in `handleUpload` alongside the other upload response fields.

**Modal — Format field, conditional on `templateType`:**
- `templateType === "pdf"` → **no control**, keep 003's static line, corrected to say what's actually true: `Format: PDF — same as your template`. There is genuinely nothing to choose (PDF→Word is out of scope by decision), and a one-option dropdown is worse UI than a statement of fact.
- `templateType === "word"` → a real `<select className="mapping-select">` labelled `Format`, two options: `Word — original (.docx/.docm)` (value `original`, default) and `PDF (converted)` (value `pdf`). Default is `original` so the existing, always-works path is what you get by doing nothing.

New state `outputFormat: "original" | "pdf"`, default `"original"`. `docx` is never sent by the UI — it exists on the API only as an explicit synonym for `original` and as the thing that returns 400 for a PDF template; the frontend doesn't need it.

**The modal's live filename preview follows the format choice.** 003's helper text shows what the first row will actually be called (`e.g. "BND-1041.docm"`); selecting PDF must flip that to `e.g. "BND-1041.pdf"`. The preview exists precisely so the user sees the real outcome before committing — leaving a stale extension in it would undercut the whole point of asking up front.

**Review step:** 003's `Naming documents by: Bond Number [Change]` line gains the format, e.g. `Naming documents by: Bond Number · Format: PDF [Change]`, so the choice is visible at the moment of generating rather than only at the moment it was made. Same `Change` button reopens the same modal.

**Both generate paths carry the same value.** `handleGenerate` (single row) and `handleGenerateAll` (bulk) each add `output_format: outputFormat` to their POST body. Nothing else about either flow changes: the single-document success card keeps its one `📥 Download Document` button (the blob it holds is already in the chosen format, and its filename comes from `Content-Disposition` as today), and the bulk results table keeps one `📥 Download` per `ok` row plus `📦 Download All` — each result's `filename`/`mime_type` already come from the server, which now returns `.pdf`/`application/pdf` when PDF was chosen. **No frontend code cares what the format is at download time**, which is the main simplification this redesign buys.

**Spinner copy:** when `outputFormat === "pdf"`, the existing status bars read `Filling and converting to PDF…` / `Generating and converting N documents…`. Conversion is the slow part (potentially tens of seconds for a batch) and an unchanged "Generating…" for that long reads as a hang.

**Reset:** `handleReset` also resets `outputFormat` to `"original"` and `templateType` to `null`, alongside 003's `bulkResults`/`filenameColumn` resets.

**No new CSS is expected** — the select reuses `.mapping-select` inside the existing modal body, and the Review-step line already exists from 003. If anything is needed it's a label-spacing rule using existing tokens only.

### 5. Testing scope call

Backend: strict TDD, `pytest`, per `docs/TESTING.md`. Conversion internals are tested with a mocked `subprocess` (command shape, temp-file handling, batch input/output mapping, retry-on-missing-output, error mapping), plus **one real, unmocked end-to-end conversion test** that converts a real minimal DOCX and asserts the extracted PDF text contains the filled value and does *not* contain `«Name»`. Mocked tests alone would happily pass while producing blank PDFs, so the real one carries the actual correctness weight.

**LibreOffice is already installed locally and verified** (`soffice --version` → `LibreOffice 26.2.5.2`), so that test must **actually run and pass during development**, not skip. It keeps a `skipif(shutil.which("soffice") is None)` guard so the suite stays runnable on a machine without it, but the plan's verify step demands a PASS, not a SKIP — a skipped result on this machine means something is wrong with the test, not with the environment.

Frontend: **no test-infra work in this ticket.** TICKET-003 bootstraps Vitest + RTL, `vitest.config.mts`, the `test` script, and `frontend/src/app/page.test.tsx` with its `renderAndUpload()` helper. This ticket only *adds cases* to that existing file (or a sibling `page.format.test.tsx` if 003's file has grown unwieldy — implementer's call, note it in Implementation). The `renderAndUpload()` helper's `/api/upload` stub needs `template_type` added to its canned response, and needs to be parameterisable (`"word"` vs `"pdf"`) since the whole feature is conditional on it.

## Plan

```
1. Add `make_valid_docx_bytes(field_names)` to `backend/tests/conftest.py` — a complete minimal OOXML package (`[Content_Types].xml`, `_rels/.rels`, `word/document.xml`), unlike the existing `make_docx_bytes` which writes only `word/document.xml` and would not open in LibreOffice at all; leave `make_docx_bytes` untouched so 003's and 001's tests are unaffected → verify: new test asserts `extract_merge_fields(make_valid_docx_bytes(["Name"])) == ["Name"]`; `cd backend && python -m pytest -q` green with no changes to existing test counts

2. Write failing tests in `backend/tests/test_word_processor.py` for `flatten_merge_fields(doc_bytes) -> bytes`: a filled doc in → output `word/document.xml` still contains the filled value, contains no `MERGEFIELD`, no `fldChar`, no `instrText`; output is a valid zip whose other parts are byte-identical to the input's; a doc with no merge fields passes through unchanged → verify: `python -m pytest tests/test_word_processor.py -q` fails with ImportError/AttributeError on the missing function specifically

3. Implement `flatten_merge_fields` in `backend/services/word_processor.py` → verify: step-2 tests pass; full `python -m pytest -q` green; **`fill_word_template`'s own output is unchanged** — its pre-existing tests pass with zero edits, proving the Word download path is untouched

4. Write failing tests in a new `backend/tests/test_format_converter.py` with `subprocess` mocked, covering both entry points: command includes `--headless`, `--convert-to pdf:writer_pdf_Export`, a per-call unique `-env:UserInstallation=file:///…` profile dir (concurrent soffice runs sharing a profile deadlock), an `--outdir` temp dir and a timeout; temp input files keep the source extension (`.docm` stays `.docm` so LibreOffice picks the right filter); `convert_many_to_pdf` passes **all N input paths in one invocation** and returns results **positionally aligned to the input list**; when one expected output PDF is missing, that single input is retried in its own invocation and the others are not re-run; if the retry also fails that slot is `None` while its siblings still return bytes; missing `soffice` raises `ConversionUnavailableError`; a non-zero exit with no outputs at all raises `ConversionError`; `convert_to_pdf` raises `ConversionError` when its one slot comes back `None`; temp dirs are cleaned up on success, failure and exception → verify: `python -m pytest tests/test_format_converter.py -q` fails on the missing `services/format_converter` module with all cases collected

5. Implement `backend/services/format_converter.py`: `convert_many_to_pdf(docs, source_ext) -> list[Optional[bytes]]` as the primitive, `convert_to_pdf(doc_bytes, source_ext) -> bytes` as a thin wrapper over it, `is_conversion_available() -> bool` (`shutil.which("soffice")`), and `ConversionError` / `ConversionUnavailableError`. No asyncio, no FastAPI imports — pure sync bytes-in/bytes-out → verify: step-4 tests pass; full `python -m pytest -q` green

6. Add the real (unmocked) conversion test to `test_format_converter.py`, guarded by `@pytest.mark.skipif(shutil.which("soffice") is None, ...)`: fill `make_valid_docx_bytes(["Name"])` with "John Doe", `flatten_merge_fields`, `convert_to_pdf`, extract text with pymupdf; plus a batch case converting three docs with distinct values in one call → verify: `python -m pytest tests/test_format_converter.py -q -rs` reports these as **PASSED, not skipped** (soffice 26.2.5.2 is installed); extracted text contains each row's own value and contains neither `«Name»` nor `MERGEFIELD`

7. Write failing tests then implement: `template_type` in the `/api/upload` response, and `pdf_conversion` in `/api/health` — updating the existing exact-equality assertion in `test_health_endpoint` deliberately (it currently asserts `resp.json() == {"status": "ok"}`) → verify: new tests assert `template_type == "word"` for a `.docm` upload and `"pdf"` for a PDF upload, and `/api/health` returns 200 with `status == "ok"` and a boolean `pdf_conversion`; full `python -m pytest -q` green

8. Write failing `/api/generate` tests in `backend/tests/test_main.py`, with the converter monkeypatched to a sentinel so the route is tested independently of LibreOffice: word + `"pdf"` → `content-type: application/pdf` and a `.pdf` filename; word + `"docx"`/`"original"`/absent → Word MIME, converter never invoked; pdf template + `"pdf"`/absent → PDF with converter never invoked; pdf + `"docx"` → 400; bogus value → 422; `ConversionUnavailableError` → 503; `ConversionError` → 500; in neither error case is Word content returned; conversion runs off the event loop (monkeypatched converter records `threading.current_thread()`, asserted `!= threading.main_thread()`); with TICKET-003's `filename_column` supplied and `output_format:"pdf"`, `Content-Disposition` is `BND-1041.pdf` not `BND-1041.docm` → verify: `python -m pytest tests/test_main.py -q` fails on exactly these new tests, all pre-existing tests still passing

9. Implement the `/api/generate` changes in `backend/main.py`: the `OutputFormat` alias and field on `GenerateRequest`, the shared `_resolve_output(session, output_format)` helper implementing the matrix, flatten-then-convert via `run_in_threadpool` under the module-level `asyncio.Semaphore(1)`, explicit 400/500/503 mapping → verify: step-8 tests pass; **every pre-existing `/api/generate` test passes unmodified** (backwards compatibility proven, not assumed); full `python -m pytest -q` green

10. Write failing `/api/generate-all` tests (converter still monkeypatched): word template + `output_format:"pdf"` → every `ok` result has `mime_type == "application/pdf"`, a `.pdf` filename, and base64 that decodes to bytes starting with `%PDF`; the converter is called **once** for the batch, not once per row; word + absent/`original` → Word MIME and `.docm` filenames, converter never called; pdf template + `"docx"` → 400; converter unavailable + `"pdf"` → 503 **and `fill_word_template` was never called** (fail-fast before any row work — assert via monkeypatched spy); one row's conversion coming back `None` → that row is `status: "error"` with a non-null message while the others stay `ok` with content (003's partial-success contract holds through conversion); `filename_column` + `"pdf"` → names are the column values with `.pdf` → verify: `python -m pytest tests/test_main.py -q` fails on exactly these, with 003's own generate-all tests still passing

11. Implement `/api/generate-all`'s format support: `output_format` on `GenerateAllRequest`, `_resolve_output` reused, resolved `ext` passed into `build_filenames`, availability check before the fill loop, fill all rows first then one `convert_many_to_pdf` over the `ok` rows' flattened bytes (under the same semaphore, via `run_in_threadpool`), `None` slots downgraded to per-row `status: "error"` → verify: step-10 tests pass; 003's generate-all tests pass unmodified; full `python -m pytest -q` green

12. Add `aptPkgs = ["libreoffice-writer", "fonts-liberation"]` to `[phases.setup]` in `backend/nixpacks.toml` → verify: deferred to step 18 — this genuinely cannot be verified locally (nixpacks isn't installed; the build only runs on Railway). Do NOT claim it works before that step

13. Extend `frontend/src/app/page.test.tsx`'s `renderAndUpload()` helper to include `template_type` in the stubbed `/api/upload` response and accept it as a parameter, then add failing RTL tests: (a) Word template → the modal renders a Format combobox with `Word` and `PDF` options, defaulting to Word; (b) PDF template → **no** Format combobox, the static `same as your template` line instead; (c) selecting PDF updates the filename preview's extension from `.docm` to `.pdf`; (d) after Continue, the Review step shows the chosen format next to `Naming documents by:`; (e) `Generate Document` POSTs `output_format: "pdf"` in its body; (f) `Generate All Rows` POSTs `output_format: "pdf"` in its body; (g) leaving the default and generating sends `output_format: "original"`; (h) `Fill Another` resets the choice — re-uploading shows the Format select back on Word → verify: `cd frontend && npm run test` fails on exactly these eight, with all of 003's existing tests still passing

14. Implement the `page.tsx` changes: `templateType` and `outputFormat` state, `template_type` read in `handleUpload`, the conditional Format `<select>` in the existing modal component, format-aware filename preview, the format shown in the Review-step naming line, `output_format` added to both POST bodies, conversion-aware spinner copy, and both resets in `handleReset` → verify: step-13 tests pass; `npm run test` fully green (003's suite + these); `npx tsc --noEmit` clean; `npm run build` succeeds

15. Add only the CSS actually needed for the modal's Format row in `frontend/src/app/globals.css` — expected to be zero or one rule, reusing existing `:root` tokens and `.mapping-select`; no new colors → verify: `npm run test:tokens` still passes (no stray color literals) and `git diff --stat frontend/src/app/globals.css` shows a handful of added lines at most

16. Manual local end-to-end pass (`cd backend && uvicorn main:app --reload`, `cd frontend && npm run dev`) with a synthetic multi-row Excel and a multi-field **Word** template: (a) choose PDF in the modal, single-row Generate → downloaded file opens as a PDF showing real Excel values, not `«Field»` placeholders, with layout matching the Word original; (b) Generate All Rows with PDF → every row's file is a correctly-filled PDF with a different row's data, and `Download All` yields a zip of `.pdf` files; (c) repeat with format left on Word → identical bytes/behaviour to today; (d) repeat with a **PDF** template → no Format select appears and the flow is unchanged from before this ticket → verify: all four observed, and note the wall-clock time of the PDF bulk run for step 18's timeout question

17. Update docs: `docs/PROJECT.md` (new `format_converter` service, LibreOffice system dependency, `output_format` on both generate endpoints, `template_type` on `/api/upload`, health-response change); `docs/TESTING.md` (the `soffice`-dependent test and that it must pass locally); `docs/DECISIONS.md` — dated append-only entries for (i) LibreOffice-over-cloud-API on data-handling grounds, (ii) flatten-before-convert, (iii) format chosen once in the setup modal rather than per download, and why the per-format blob cache was dropped, (iv) batch conversion with per-file retry plus the `Semaphore(1)` limiter; `docs/ROADMAP.md` → verify: `git diff docs/DECISIONS.md` shows additions only, no modified lines; `grep -n "output_format" docs/PROJECT.md` returns the new content

18. Deploy to Railway and verify the system dependency really landed → verify: Railway build logs show `libreoffice-writer` installed; `curl https://docfiller-production-afa9.up.railway.app/api/health` returns `"pdf_conversion": true`; then a real upload → generate-all → PDF round trip against the live site using a **synthetic** template (never a real client document) returns correctly filled PDFs without a gateway timeout. Record observed build time, image size, and bulk-run duration. Only then move this ticket to `completed/` (`ready-for-deploy/` until this passes)
```

## Open questions / risks (decide before implementation starts)

1. **Batch conversion vs. one `soffice` per document.** Planned as batch-with-individual-retry (section 3) because N cold starts is the difference between ~10 s and ~60 s for a 5-row run. The simpler alternative is a plain loop calling `convert_to_pdf` per row — less code, perfect failure isolation, much slower. Recommendation: batch. Say if you'd rather ship the dumb loop first and optimise only if it's actually too slow.
2. **Row cap for PDF bulk runs.** TICKET-003's `MAX_BULK_ROWS = 200` was sized for filling only. 200 conversions in one synchronous request is a plausible platform-timeout (Railway/proxy) and could take minutes. Options: keep 200 and accept the risk; add a lower `MAX_BULK_PDF_ROWS` (e.g. 50) rejected with a clear message; or leave it and revisit after step 16's measured timing. **Recommendation: leave the cap alone until step 16 gives a real number, then decide** — but this is a deliberate open item, not an oversight.
3. **Concurrency limiter is now in scope** (previously deferred): a module-level `asyncio.Semaphore(1)` serialises all conversions process-wide. Cost is that two users converting at once queue rather than run in parallel; benefit is not OOM-ing a small container with two 300 MB LibreOffice processes on an API with no auth. Flag if you'd rather allow 2.
4. **Image size / build time on Railway is estimated, not measured.** If the build fails or gets unacceptably slow, the fallback is the Gotenberg sidecar service described in section 1 — same `format_converter` interface, so the backend change survives.
5. **This ticket cannot start before TICKET-003 lands.** It edits 003's modal, 003's `/api/generate-all`, 003's `build_filenames` call sites and 003's test file. Doing them in the other order means re-planning both.
6. **`docx` as an API value the UI never sends.** Kept on the `Literal` as an explicit synonym for `original` (and as the thing that 400s on a PDF template) so the API says what it means; the frontend only ever sends `original` or `pdf`. Alternative is dropping `docx` entirely and letting a PDF template + `original` be the only path — simpler API, slightly less self-describing. Low stakes either way.
7. **Untouched by design:** in-memory sessions, PDF→DOCX, and the Word download path's current bytes. `output_format` is additive and optional on both endpoints, so every existing caller keeps working unchanged.

## Implementation
_(pending)_

## Tests
_(pending)_

## Impact
_(pending)_
