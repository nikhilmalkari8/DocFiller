# TICKET-007: Word/PDF fill gaps found while fixing TICKET-006

**Status:** Pending (nothing started; items below are findings, each marked verified or not)
**Created:** 2026-10-04
**Moved to ready-for-deploy:** —
**Completed (deployed):** —

## Request
Not requested by Nikhil directly — collected from the TICKET-006 planner probe and QA review so they aren't lost. None is a regression; all exist today. Prioritise with Nikhil before building; each would need its own plan.

## Findings
1. **Leading/trailing spaces are dropped** (verified by probe: `"   pad   |"` renders as `"pad   |"`). `<w:t>` has no `xml:space="preserve"`, and Excel values reach the template unstripped, so this does happen. Fix means editing the surrounding `<w:t>` tag, not just the value.
2. **Placeholder split across runs is silently left unfilled** (**unverified**). In real Word templates `«Name»` can be broken across several XML text pieces; the field is still listed at upload but never filled. Start by detecting/warning.
3. **A value equal to another field's placeholder text gets filled** (verified by QA: `{"A": "«B»", "B": "X"}` → A's cell ends up `X`; order-dependent). A single-pass regex substitution over all `«name»` keys would fix it. Low likelihood.
4. **Only `word/document.xml` is processed** — placeholders in headers, footers and footnotes (`header1.xml` etc.) are never filled. Relevant only if bond forms merge fields there.
5. **A literal CR in a value is normalised to LF** by XML parsers; newlines and tabs render as spaces. Matches today's behaviour; fix only if exact line breaks matter (would need `<w:br/>`).
6. **`fill_pdf` writes values as one unwrapped line** — long values (e.g. amount in words, 60–100 chars) overflow on many PDF templates (flagged in TICKET-005; overlaps sub-project 3).

## Plan
_To be written by the `planner` agent when picked up._

## Implementation
_Not started._

## Tests
_Not started._

## Impact
Correctness on real Word templates; none urgent individually. Items 2 and 4 depend on what real client templates actually look like — worth checking one real (local, uncommitted) template before deciding.
