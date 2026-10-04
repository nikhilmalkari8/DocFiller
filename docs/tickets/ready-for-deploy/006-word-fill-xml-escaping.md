# TICKET-006: Word fill doesn't XML-escape values (corrupt .docx on `&`, `<`, `>`)

**Status:** Ready for Deploy (implemented and verified locally 2026-10-04; NOT deployed)
**Created:** 2026-10-04
**Moved to ready-for-deploy:** 2026-10-04
**Completed (deployed):** —

## Request
Reported while planning TICKET-005 (flagged as R3 there); Nikhil asked for it to be tracked as a separate bugfix ticket rather than folded into the transformation engine.

`services/word_processor.py::fill_word_template` (lines ~48–49) inserts each value straight into `word/document.xml` with `doc_xml.replace(f"«{field_name}»", safe_value)` and no XML escaping. A value containing `&`, `<` or `>` — e.g. a surety principal named `Smith & Sons LLC` — should produce a malformed `document.xml` and therefore a corrupt `.docx`. This exists today with plain copied values; TICKET-005's `join` transform makes it more likely.

**Verified** by the `planner` probe (see Plan): the bug is real, and on the DOCX/original path it fails *silently* — a 200 response carrying a corrupt `.docx`; on the PDF path LibreOffice refuses to convert (500 / error row).

## Plan
Written by `planner` 2026-10-04. Strict TDD: every behaviour change below gets a failing test, and that test is seen failing *for the right reason*, before any line of `services/word_processor.py` changes. All commands run from `backend/`.

### Verification probe (done during planning, no repo files written)
Ran `fill_word_template(make_valid_docx_bytes(["Name"]), {"Name": v})` and parsed the output `word/document.xml`:

| value | result today |
|---|---|
| `Smith & Sons LLC` | **malformed XML** (`not well-formed (invalid token)`) |
| `a < b` | **malformed XML** |
| `AT&amp;T` (literal text) | parses, but text silently becomes `AT&T`, so data is changed without any error |
| `x\x0by` (vertical-tab control char) | **malformed XML**, and `escape()` alone does **not** fix this (see Q1) |
| `a > b`, `O'Brien "Q"`, `  pad  `, `l1\nl2` | parse fine |

Real LibreOffice (`fill → flatten → convert_to_pdf`, soffice 26.2.5.2):
- Unescaped `Smith & Sons LLC`: **`ConversionError: Failed to convert document to PDF`**. So `/api/generate` with `output_format=pdf` returns a 500, and in bulk that row becomes `status: error`.
- Unescaped on the DOCX/original path: **no error at all**. The response is a 200 containing a corrupt `.docx` (bulk reports `status: ok`). This is the worst case, because it fails silently.
- With `xml.sax.saxutils.escape` applied: `Smith & Sons LLC`, `a < b > c`, `O'Brien "Q"` all appear correctly in the PDF.
- Existing behaviour unrelated to escaping: `"   pad   |"` renders as `"pad   |"` (leading whitespace dropped because `<w:t>` has no `xml:space="preserve"`), and `\n` and `\t` render as spaces. Excel values reach the template **unstripped** (`excel_parser` only strips headers), so leading/trailing spaces do actually occur.
- The output zip is **not byte-deterministic even today**: `zipfile.writestr` stamps the current time into each entry, so two fills of the same input made a second or more apart differ. "Byte-identical DOCX behaviour" therefore has to be pinned **per zip part** (exact `document.xml` bytes + every other part + entry order), not on the whole-zip bytes.

### Insertion-point audit
- `fill_word_template` (word_processor.py:47–49) is the **only** place a value is written into XML. `main._fill_document` only passes `fill_values` through, and `_build_fill_values` / transforms produce plain strings.
- `flatten_merge_fields` writes no values. It only regex-deletes structural runs. It is still *affected*: its patterns scan for `</w:r>`, so an unescaped value containing literal `</w:r>` / `<w:instrText` could today change what it deletes. After escaping, a value can never contain a literal `<`, so this is closed off. A test pins it (step 4).
- The **search key** `«{field_name}»` must **not** be escaped. `extract_merge_fields` regexes the *raw* XML, so a field name with an `&` in it comes back already entity-encoded (`A&amp;B`) and matches the raw placeholder as-is. Escaping the key would double-encode it and silently stop filling that field. A test pins it (step 2).
- PDF templates (`fill_pdf`, PyMuPDF) don't go through XML, so they're out of scope here (not probed).

### Steps
```
0. Baseline: `pytest -q -rs` from backend/ → verify: all green; note total count (TICKET-005 is being worked on concurrently, so record the count of tests/test_word_processor.py + tests/test_format_converter.py separately as the stable baseline); the two real-soffice tests report PASSED, not SKIPPED.

1. FAILING unit tests (tests/test_word_processor.py) — XML well-formedness + exact round-trip.
   Add helper `_wt_text(docx_bytes)`: read word/document.xml, `xml.etree.ElementTree.fromstring` it (raises on malformed XML), return "".join of every `{w-ns}t` element's `.text or ""`.
   a. parametrize value over ["Smith & Sons LLC", "a < b", "a > b", "AT&amp;T", "O'Brien \"Q\"", "</w:t></w:r><w:r><w:t>injected"]:
      fill make_valid_docx_bytes(["Name"]) → assert `_wt_text(filled) == value` exactly.
   b. Two-field doc, Name="Smith & Sons LLC", Date="2024-01-15" → parses, text == "Smith & Sons LLC2024-01-15" (whole document survives, order preserved).
   → verify: `pytest tests/test_word_processor.py -q` shows failures for `&`, `<`, `AT&amp;T`, injection, 1b — failing with `xml.etree.ElementTree.ParseError: not well-formed` (or, for AT&amp;T, `'AT&T' != 'AT&amp;T'`), NOT ImportError/fixture errors. The `>` and quote cases PASS pre-fix: that is expected; they are regression guards that a future "escape quotes too / use a different escaper" change can't break, and the plan states this explicitly so nobody mistakes them for "passing failing tests".

2. CHARACTERIZATION tests that must pass BOTH before and after the fix (write now, see them pass now):
   a. "No special characters ⇒ document.xml identical to today": parametrize value over ["John Doe", "2024-01-15", "", "  pad  ", "l1\nl2", "Ünïcødé €", "50,000.00"]; assert filled word/document.xml bytes == original document.xml decoded, `.replace("«Name»", value)`, re-encoded utf-8 — exact bytes. Also assert every other zip part is byte-identical and `namelist()` order is unchanged.
   b. None still → "" (existing test covers; leave it).
   c. Key is not escaped: hand-built document.xml whose display text is `«A&amp;B»` with instrText `MERGEFIELD A&amp;B`; `extract_merge_fields` returns ["A&amp;B"]; filling {"A&amp;B": "X"} replaces it (placeholder gone, "X" present, XML parses).
   → verify: `pytest tests/test_word_processor.py -q -k "<new names>"` all PASS on the unfixed code (proves they pin existing behaviour rather than new behaviour).

3. FAILING real-LibreOffice test (tests/test_format_converter.py), same `@pytest.mark.skipif(shutil.which("soffice") is None, ...)` pattern as the existing two:
   `test_real_conversion_preserves_xml_special_characters`: value "Smith & Sons LLC <Ltd>" → fill_word_template → flatten_merge_fields → convert_to_pdf → pymupdf text; assert "Smith & Sons LLC <Ltd>" in text and "&amp;" not in text and "&lt;" not in text.
   → verify: `pytest tests/test_format_converter.py -q -rs` shows this test FAILED (with ConversionError, matching the probe), not SKIPPED; the two existing real tests still PASSED.

4. FAILING flatten-path unit test (tests/test_word_processor.py): fill then flatten with value "Smith & Sons LLC" and with value "</w:r>MERGEFIELD" → `_wt_text(flattened) == value`, and "fldChar"/"instrText" absent.
   → verify: fails pre-fix with ParseError (right reason).

5. FAILING API tests (tests/test_main.py — see risk R1 about the concurrent session):
   a. `/api/generate`, Word template (make_docx_bytes(["Name","Date"])), Excel row ["Smith & Sons LLC", "2024-01-15"], no output_format → 200, unzip resp.content, document.xml parses, contains text "Smith & Sons LLC".
   b. `/api/generate-all` same data, two rows (one with "&", one plain) → both status ok, each base64-decoded docx's document.xml parses and contains its own value.
   → verify: both fail pre-fix with ParseError (today: 200 + silently corrupt docx — this test is the one that documents the silent-corruption mode).

6. FIX: in `fill_word_template` only: `from xml.sax.saxutils import escape`; `safe_value = escape(str(value)) if value is not None else ""`. Key `f"«{field_name}»"` untouched. Add a short comment explaining why (values are text content of <w:t>; key is matched against raw XML so must stay raw). No change to flatten_merge_fields, main.py, or the PDF path.
   → verify: `pytest tests/test_word_processor.py tests/test_format_converter.py -q -rs` — all step 1/3/4 tests now PASS, step 2 characterization tests still PASS, real-soffice tests PASSED (not SKIPPED); then `pytest tests/test_main.py -q -k "generate"` — step 5 tests PASS.

7. Control characters — DEPENDS ON Q1. Default recommendation if no answer: write FAILING test first (value "x\x0by" and "\x00") asserting output XML parses AND [chosen behaviour], then implement.
   → verify: test fails pre-change with ParseError, passes after; step 2a characterization tests still pass (none of their values contain control chars).

8. Leading/trailing whitespace (xml:space="preserve") — DEPENDS ON Q2. If in scope: FAILING test first — value "  pad  " → parsed `<w:t>` for the field carries xml:space="preserve" and _wt_text == "  pad  "; plus real-soffice assertion that PDF text contains "  pad" (probe showed leading spaces dropped today). Implementation must add the attribute ONLY when the value has leading/trailing whitespace, and must handle a <w:t> that already has attributes, so step 2a stays byte-identical for plain values. NOTE: step 2a currently includes "  pad  " — if Q2 is "yes", move that value out of 2a into this step's test (deliberate behaviour change, recorded here).
   → verify: new test fails pre-change (attribute missing / PDF text "pad"), passes after; step 2a (minus the moved case) still passes.

9. Newlines/tabs — DEPENDS ON Q3. Default: out of scope; add a characterization test pinning today's behaviour ("l1\nl2" stays a literal "\n" in <w:t>, XML parses) so any later change is deliberate.
   → verify: test passes pre- and post-fix.

10. Full regression + real-path check: `pytest -q -rs` → verify: all green, count = baseline + new tests, zero SKIPPED for the soffice tests. Then a manual end-to-end check: run backend locally, upload a real Word template + an Excel row "Smith & Sons LLC", download DOCX and PDF; `soffice --headless --convert-to pdf` the downloaded .docx in a scratch dir succeeds, and the downloaded PDF visibly shows "Smith & Sons LLC" → verify: both open without a repair prompt.

11. Docs: fill in this ticket's Implementation/Tests sections; add a line to docs/TESTING.md under the real-LibreOffice section naming the new real test; move ticket to ready-for-deploy/ and update docs/ROADMAP.md → verify: files reflect state; `git diff --stat` touches only word_processor.py, the three test files, and docs.
```

### Design questions for Nikhil (answer before implementation; defaults stated)
- **Q1 – XML-illegal control characters** (`\x00–\x08`, `\x0b`, `\x0c`, `\x0e–\x1f`). `escape()` doesn't handle these, and they still corrupt the docx. They're rare from Excel (Alt+Enter gives `\n`, which is legal) but possible with pasted text. Options: (a) strip them silently; (b) fail that document with a clear error (single → 400/500 with a message, bulk → row `status: error`); (c) leave as-is (still corrupts). The project's "never guess" stance in TICKET-005 points to (b), but silently dropping an invisible vertical-tab is arguably harmless. **Planner's recommendation: (b), or (a) if you'd rather never fail a row on an invisible character. Needs your call.**
- **Q2 – `xml:space="preserve"` for leading/trailing whitespace.** This already happens today and is unrelated to escaping: leading spaces from Excel cells are dropped in both Word and PDF. Fixing it means touching the enclosing `<w:t>` tag, so it's no longer a plain `str.replace`. In scope for 006, or a separate ticket? **Recommendation: separate ticket.** It's cosmetic, not corruption, and keeping 006 to a one-line escaping fix keeps the "byte-identical for plain values" guarantee trivially true.
- **Q3 – Newlines.** `\n` in a value renders as a space today. Real line breaks need `</w:t><w:br/><w:t>` splicing. **Recommendation: out of scope; pin current behaviour (step 9).**
- **Q4 – Placeholder split across runs.** `fill_word_template` only matches `«Name»` when it's contiguous within one string. In real Word-authored templates the display text can get split across several `<w:r>`/`<w:t>` (rsid/proofing/formatting edits). The field is then **silently left unfilled** (not corrupted), and upload still lists it because `extract_merge_fields` reads `instrText`, not the display text. Escaping doesn't affect this, because only the value is escaped and never the search key. Synthetic fixtures can't show it, and it's a separate pre-existing bug. **Recommendation: separate ticket.** A cheap first step there would be detecting "mapped field whose «display text» wasn't found" and reporting it instead of silently returning an unfilled doc.
- **Q5 – Value containing another placeholder's display text** (e.g. a cell literally containing `«Date»`). The replace loop would then fill `Date` *inside* that value. This is pre-existing and not changed by escaping (`«»` aren't escaped). Low likelihood. Flagging only.

### Risks
- **R1 – test_main.py conflict:** the concurrent TICKET-005 session adds API tests to `tests/test_main.py`. Step 5 touches the same file. Either sequence step 5 after that session lands, or append the tests in a clearly separate block at the end of the file. word_processor.py / test_word_processor.py / test_format_converter.py are not touched by that session.
- **R2:** step 1's `>`/quote cases and all of step 2 pass before the fix. That's intended (guards/characterization), but the reviewer should not count them as TDD-red evidence. The red evidence is the `&`, `<`, `AT&amp;T`, injection, flatten, real-soffice and API cases.

## Implementation
Decisions (Nikhil: "complete everything"): Q1 control characters → **fail with a clear error** (fits "never guess"); Q2–Q5 → out of scope, tracked in TICKET-007.
- `backend/services/word_processor.py` — `fill_word_template` now XML-escapes each value (`xml.sax.saxutils.escape`: `& < >`) before inserting it. The search key (`«FieldName»`) is deliberately **not** escaped — field names come out of the raw XML already entity-encoded, so escaping would double-encode and silently stop that field filling (a test pins it). New `UnsupportedCharacterError(ValueError)` for characters XML 1.0 can't represent at all (C0 controls except tab/LF/CR, lone surrogates, U+FFFE/U+FFFF); the message names the field, never the value.
- `backend/main.py` — `/api/generate` maps `UnsupportedCharacterError` to a 400; in `/api/generate-all` it becomes a per-row `error` through the existing generic handler (other rows continue).
- `flatten_merge_fields` needed no change (it writes no values; escaping also closes off a value containing `</w:r>` altering what it strips). `fill_pdf` doesn't go through XML and is unaffected.
- Behaviour change worth knowing: a value that already contains an entity, e.g. `AT&amp;T`, used to be silently decoded to `AT&T`; it is now kept literally as typed. Intentional.

## Tests
Suite: **262 → 302 passing** (`cd backend && pytest -q`); `tests/test_format_converter.py` 15 passed (real LibreOffice), none skipped. Written test-first; failures confirmed for the right reason (`ParseError: not well-formed`, `DID NOT RAISE`) before the fix. Tests that pass both before and after are intentional characterization pins.
- `tests/test_word_processor.py` — exact text round-trip through well-formed XML for `& < > AT&amp; ' "` and an injection attempt; two fields together; **ordinary values leave `document.xml` byte-identical** (and every other zip part + entry order); field name with `&`; flatten-after-fill; illegal characters (incl. range boundaries and lone surrogates) raise `UnsupportedCharacterError` naming the field not the value; legal-but-unusual characters (DEL, NEL, U+2028, U+FFFD, astral) are accepted.
- `tests/test_format_converter.py` — real soffice: PDF text contains a literal `Smith & Sons LLC <Ltd>`, no `&amp;`/`&lt;`.
- `tests/test_main.py` — `/api/generate` (original) returns a well-formed docx for `&`; `/api/generate-all` row is `ok` and well-formed; illegal character → clean 400 (single) and a per-row error with other rows ok (bulk), without leaking the value.

### QA review (independent, 2026-10-04)
No blockers; escaping confirmed against a long adversarial list (CDATA, `]]>`, numeric entities, 4 MB values, astral chars) and the tests confirmed genuinely red without the fix. Acted on: **F1** lone surrogates gave a 500 echoing the character → added to the illegal set; **F3** range boundaries were untested (shrinking the regex passed all tests) → boundary + must-accept cases added; **F6** no bulk test → added. Not changed, recorded in TICKET-007: **F2** a literal CR in a value is normalised to LF by XML parsers (pre-existing); **F4** a value equal to another field's placeholder text gets filled; **F5** only `word/document.xml` is processed (headers/footers/footnotes never filled).

## Impact
Fixes silent corruption of real documents whose data contains `&`/`<` (company names like `Smith & Sons LLC`). No new dependencies, no API shape change; one new 400 case. Byte-identical output for ordinary values.
