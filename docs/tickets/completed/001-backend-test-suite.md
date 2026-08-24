# TICKET-001: Backend test suite covering all existing services + API routes

**Status:** Completed
**Created:** 2026-08-23
**Moved to ready-for-deploy:** 2026-08-23
**Completed (deployed):** 2026-08-23 — shipped to Railway as part of commit 8db4260 (bundled with TICKET-002's push); confirmed live via `GET /api/health` → `{"status":"ok"}` at https://docfiller-production-afa9.up.railway.app

## Request
"do you think we need to add test cases for what we already have in Dindu?" → "I know it is not TDD for now, atleast we can complete till now, do damage control, so that from next every task any task we can follow strict TDD approach we already have." → "cover everything, everything should be ready to follow strict TDD right from next task I give."

Full retroactive test coverage for the existing backend (no frontend code exists yet to test), so this is the last non-TDD ticket and every future ticket can follow strict TDD against a real suite.

## Plan
```
1. Add pytest + httpx to backend/requirements.txt, install → verify: `pytest --version` runs from backend/
2. Create backend/tests/conftest.py: TestClient fixture, synthetic Excel/PDF/Word file fixtures built in-code (openpyxl/pymupdf/zipfile — no committed binary fixtures) → verify: `pytest --collect-only` succeeds with no import errors
3. Write backend/tests/test_excel_parser.py against parse_excel + get_row_data (headers, preview rows, total_rows, empty-header case, out-of-range row) → verify: pytest run, each test's actual-vs-intended behavior confirmed; any mismatch flagged, not silently encoded
4. Write backend/tests/test_llm_mapper.py — _fallback_mapping and _parse_and_validate as pure functions (exact/case-insensitive/substring match, rejection of invented column names per llm-mapping-verification.md); map_fields provider chain with _map_with_openai/_map_with_gemini mocked (no real API calls) covering OpenAI-succeeds, OpenAI-fails-Gemini-succeeds, both-fail-uses-fallback → verify: pytest run, no network calls made (confirm via mock assertion), each branch exercised
5. Write backend/tests/test_pdf_processor.py — extract_placeholders (dedup, none-found) and fill_pdf (round-trip: output no longer contains placeholder text, contains filled value, verified by re-extracting text from the result) → verify: pytest run against synthetic PDF fixture
6. Write backend/tests/test_word_processor.py — extract_merge_fields (dedup, order-preserving) and fill_word_template (round-trip via re-reading output docx XML) → verify: pytest run against synthetic docx fixture
7. Write backend/tests/test_main.py — /api/upload (success shape, bad excel ext, bad template ext, no-placeholders-found), /api/map (unknown session 404, valid session, map_fields mocked), /api/generate (unknown session 404, correct content-type/filename for pdf/.docx/.docm) → verify: pytest run via TestClient, full suite green
8. Full suite run + note results in this ticket's Tests section → verify: `pytest` from backend/ exits 0, all tests passing or failures explicitly triaged and either fixed (real bug) or explained (documented as known/intentional)
```

## Implementation
- `backend/requirements.txt`: added `pytest>=8.0.0`, `httpx>=0.27.0`
- `backend/tests/conftest.py`: `client` (FastAPI `TestClient`) fixture, autouse `clear_sessions` fixture, and in-code builders for synthetic Excel (`make_excel_bytes`)/PDF (`make_pdf_bytes`)/Word (`make_docx_bytes`) fixtures — no binary files committed
- `backend/services/excel_parser.py`: **bug fix**. `parse_excel` and `get_row_data` both used `next(ws.iter_rows(...))` to grab the header row, which raises `StopIteration` on a completely empty worksheet instead of the `ValueError` the function documents/promises. `main.py` already wraps both call sites in `try/except Exception`, so this was never an unhandled crash reaching a client — it surfaced as a 400 either way — but the error message was an empty `str(StopIteration())` instead of the actual documented message. Fixed both functions to use `next(..., None)` with a guard. Found by writing the "no headers" test first — see Tests below. (Corrected per QA review: the initial writeup overstated this as "used to crash.")
- `backend/tests/test_excel_parser.py`, `test_llm_mapper.py`, `test_pdf_processor.py`, `test_word_processor.py`, `test_main.py`: full coverage per the plan

## Tests
46 tests, all passing (`pytest` from `backend/`, 0.21s). Breakdown:
- `test_excel_parser.py` (7): column/preview/total_rows extraction, preview cap at 5 rows, no-headers raises ValueError, missing trailing cells, row lookup by index, out-of-range row, `get_row_data` on a completely empty workbook (added post-QA-review)
- `test_llm_mapper.py` (13): `_fallback_mapping` (exact/normalized/substring/no-match) and `_parse_and_validate` (accepts real columns, **rejects invented column names** per `llm-mapping-verification.md`, case-insensitive match, markdown-fence stripping, missing-placeholder default) as pure functions; `map_fields`'s OpenAI→Gemini→fallback chain with all network calls mocked (no real API calls, no dependency on the real `.env` key)
- `test_pdf_processor.py` (4): placeholder extraction + dedup, fill correctness via re-extracted text, unmapped placeholders left untouched
- `test_word_processor.py` (6): MERGEFIELD extraction + dedup + order, fill correctness via re-read XML, `None` value handling, other zip contents preserved
- `test_main.py` (16): all 3 routes — upload (PDF/Word success, bad extensions, malformed Excel, no-placeholders-found for both template types), map (unknown session 404, success with `map_fields` mocked, mapper-failure 500), generate (unknown session 404, PDF/`.docx`/`.docm` success with correct content-type/filename, and a documented-behavior test for out-of-range `row_index` producing blank fields rather than an error)

**Real bug found and fixed**: `excel_parser.py`'s `StopIteration`-vs-`ValueError` mismatch on an empty worksheet (see Implementation for the corrected description of its actual severity). Exactly the "write test against intended behavior, then fix what fails" case the plan called for — not silently encoded.

## QA Review
Dispatched the `qa-reviewer` agent. Findings and resolution:
1. **`test_map_valid_session_returns_mapping` was a weak tripwire** — the mocked return value happened to be identical to what `_fallback_mapping` would independently produce for those inputs, so the test would pass even if the mock silently failed to engage. **Fixed:** mock now returns a swapped mapping (`{"Name": "Date", "Date": "Name"}`) that `_fallback_mapping` structurally cannot produce, since it always exact-matches "Name"→"Name" first.
2. **`get_row_data`'s half of the `StopIteration` fix was untested** — `test_excel_parser.py` covered `parse_excel`'s empty-workbook case but not the identical code path in `get_row_data`. **Fixed:** added `test_get_row_data_on_completely_empty_workbook_returns_empty_dict`; confirmed against the pre-fix code path that it would have caught the original bug.
3. **"Used to crash" was an overstatement** — `main.py` already wrapped both call sites in `try/except Exception`, so this was always surfaced as a 400, just with an empty/unhelpful message rather than the documented one. **Fixed:** corrected the wording in Implementation above.
4. Confirmed via independent repro: the `monkeypatch.setattr("main.map_fields", ...)` target in `test_main.py` is correct (patches the name as bound into `main`'s own namespace by `from services.llm_mapper import map_fields`, which is what `map_columns()` actually resolves at call time) — not a bug.
5. No secrets, document content, or PII logged anywhere in the suite; no real network calls (confirmed by run time and mock coverage); scope is clean — only `requirements.txt`, `excel_parser.py`, and new test files touched.

All fixes verified: full suite re-run after changes, 46/46 passing.

## Impact
- New dependencies: `pytest`, `httpx` added to `backend/requirements.txt`
- `docs/TESTING.md` gets a note that the suite now exists and how to run it
- `docs/ROADMAP.md`'s "add a real test suite" planned item moves to done (backend half; frontend still pending, no frontend code exists yet)
- Establishes the pattern every future Dindu ticket's TDD step follows
