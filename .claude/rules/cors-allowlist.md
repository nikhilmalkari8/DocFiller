---
paths:
  - "backend/main.py"
---

# CORS allowlist

`main.py` hardcodes allowed frontend origins in the CORS middleware rather than allowing all origins. If a new frontend deployment URL is added (new Vercel preview, custom domain, etc.), this allowlist needs updating too, or requests from that origin will silently fail. Already broke once for this reason (see `docs/DECISIONS.md`, "Fix CORS: allow Vercel frontend domain"). Check this whenever frontend deployment configuration changes.
