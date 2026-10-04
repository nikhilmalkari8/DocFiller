---
paths:
  - "backend/services/transforms.py"
  - "backend/services/llm_mapper.py"
---

# Value transformations (amount in words, dates, currency, join…)

These produce text printed on real legal/financial documents (bond forms). A wrong value is worse than a visible error.

- **Money is `Decimal`, never float.** No `float(` anywhere in `transforms.py` (a test enforces it). Don't introduce float arithmetic "just for formatting".
- **Never guess.** Ambiguous or malformed input (negatives, odd comma grouping, scientific notation, more than 2 non-zero decimals, slash/text dates, non-ASCII digits, blank where a value is required) raises `TransformError`; it is never rounded, coerced or "best-effort" parsed. Loosening a parser needs an explicit decision recorded in `docs/DECISIONS.md`.
- **The LLM only selects from `CATALOG`.** It never writes conversion logic, and nothing it proposes reaches `apply_transform` without passing `validate_spec` against the real Excel columns (same principle as `llm-mapping-verification.md`). Don't add a path that passes an LLM-produced spec through unvalidated.
- **Every new catalog transform needs table-driven tests first** — exact expected strings plus an explicit error table — and a `description` + `example` (the mapper prompt is generated from `CATALOG`; a test enforces both).
- **Two error classes stay distinct:** `TransformSpecError` (bad spec → reject the whole request with 400 before filling anything) vs `TransformError` (bad cell value → 400 single / per-row `error` in bulk, other rows continue).
- **Error messages must not echo whole cell values** — use `_shown()` (truncated). Cells can hold sensitive data.
- Output must be deterministic and independent of the server's locale/platform (no `strftime` month names, no locale-dependent formatting).
