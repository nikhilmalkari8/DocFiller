---
paths:
  - "backend/main.py"
---

# In-memory session storage

`sessions` in `main.py` is a plain Python dict — deliberate for MVP, not an oversight. Don't assume it persists across server restarts or is shared across multiple backend instances. If a change relies on session durability (e.g. delayed processing, multi-instance deployment), flag it rather than silently building on an assumption that doesn't hold — this is exactly what the Proactiveness preference in the global CLAUDE.md is for. Moving this to Redis/DB is tracked as future work in `docs/ROADMAP.md`, not assumed to already be done.
