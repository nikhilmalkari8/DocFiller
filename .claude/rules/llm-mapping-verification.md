---
paths:
  - "backend/services/llm_mapper.py"
---

# LLM field-mapping correctness

This maps document placeholders to Excel columns for real legal/financial documents (bond forms). A silently wrong mapping fills a real document incorrectly — this isn't a cosmetic bug category. Changes here should include a way to verify mapped output against source data (e.g. a test asserting known placeholder/column pairs map correctly), not just trust model output. Don't loosen `_parse_and_validate`'s validation (that mapped columns must be real Excel columns) without a clear reason. Transform specs the LLM proposes (`allow_transforms`) get the same treatment: any column a spec references (`source`, or `{Column}` tokens in a `join` template) must be a real Excel column, validated via `validate_spec` before the spec is returned. See `transforms.md`.
