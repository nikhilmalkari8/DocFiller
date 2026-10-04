# TICKET-006: Word fill doesn't XML-escape values (corrupt .docx on `&`, `<`, `>`)

**Status:** Pending (found by `planner` while planning TICKET-005, 2026-10-04; not yet verified by a failing test; not started)
**Created:** 2026-10-04
**Moved to ready-for-deploy:** —
**Completed (deployed):** —

## Request
Reported while planning TICKET-005 (flagged as R3 there); Nikhil asked for it to be tracked as a separate bugfix ticket rather than folded into the transformation engine.

`services/word_processor.py::fill_word_template` (lines ~48–49) inserts each value straight into `word/document.xml` with `doc_xml.replace(f"«{field_name}»", safe_value)` and no XML escaping. A value containing `&`, `<` or `>` — e.g. a surety principal named `Smith & Sons LLC` — should produce a malformed `document.xml` and therefore a corrupt `.docx`. This exists today with plain copied values; TICKET-005's `join` transform makes it more likely.

**Unverified claim:** this is the planner's reading of the code. Step 1 below is to prove it with a failing test before anything is fixed.

## Plan
_To be written by the `planner` agent when this ticket is picked up (mandatory per project `CLAUDE.md`). Expected shape:_
```
1. Failing test: fill a template with value "Smith & Sons LLC" (and "<", ">"), assert output document.xml parses as XML and the text round-trips → verify: test fails for the right reason
2. Escape values (xml.sax.saxutils.escape) at the insertion point; check other insertion points (flatten path, any other replace) → verify: test passes, existing word_processor tests unchanged
3. Check whether fill_pdf / LibreOffice conversion path is affected → verify: converted PDF text contains the literal "&"
```

## Implementation
_Not started._

## Tests
_Not started._

## Impact
Correctness on real documents: today a name with `&` may silently yield an unopenable Word file. Independent of TICKET-005; no dependency in either direction.
