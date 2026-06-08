# Capture Queue Plan — 2026-05-01T12:03:13+08:00

- story: US-003 no-WeChat fallback
- source baseline: existing 93K release/US-002 completed artifacts
- action: do not launch capture while WeChat RED
- planned acceptance when WeChat returns: generate queue of URLs not in existing release, then dry-run 50 only after gate.
- current safety: latest 6h RED=2, post-RED non-RED=1, current danger=0.
