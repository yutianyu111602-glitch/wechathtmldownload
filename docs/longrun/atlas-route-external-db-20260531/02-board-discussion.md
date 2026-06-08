# Board Discussion

Updated: 2026-05-31 06:10 CST

## Round 1: Facts

- The system already has working public relation surfaces on `weekly-api-015`.
- The repo has many historical docs and generated artifacts; current truth must come from `docs\current-runtime.md`, `docs\DOCUMENTATION_INDEX.md`, `docs\CURRENT_CODE_MAP.md`, repo rules, and current tests.
- Address/coordinate truth is high risk because previous runs mixed old coordinates, provider quotas, and fallback registries.
- Mixtape/outlink support is product-relevant, but copyright-safe behavior means link out, not audio caching.

## Round 2: Conflicts

- User permits production deploy/upload, but no-diff deployments should not be created just to show activity.
- User says not to care about Git, but destructive cleanup can still lose current work and is not needed.
- Historical Atlas docs contain many report-only candidates; production-effective state must stay separate from local candidate state.

## Round 3: Decision

- Build a report-only inventory first, then use it as the shared contract for field/database/route work.
- Address/coordinate writes require provider/source cross-check evidence; otherwise emit blocked rows.
- Mixtape/outlink work should start as metadata/outlink fields and mini-program jump-to-original UX.
- Deploy/upload only after runtime code or data package changes are verified by targeted tests and public smoke.
