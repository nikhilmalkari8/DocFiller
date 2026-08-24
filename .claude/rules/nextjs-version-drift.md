---
paths:
  - "frontend/src/**/*.{ts,tsx}"
  - "frontend/**/*.{ts,tsx}"
---

# Next.js version drift

This project uses Next.js 16.3.2 and React 19.2.8 — new enough that APIs, conventions, and file structure may differ from training data. Before writing or editing Next.js-specific code, check `frontend/node_modules/next/dist/docs/` for the actual current API rather than assuming it matches what's already known. Heed deprecation notices found there.
