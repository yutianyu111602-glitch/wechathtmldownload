# Crystallization Candidates

Updated: 2026-05-31 10:58 CST

- Candidate SOP: before Atlas/Weekly production changes, run `npm run weekly:deploy-upload:preflight`, then any lane-specific relation/geo/source guards, then update the longrun manifest.
- Candidate skill improvement: OpenClaw weekly skill should treat coordinates as fixed DB/provider-confirmed state, not as a per-run geocode quota consumer.
- Candidate DJ Interview SOP: collect drafts with `services\weekly_activity_cloudrun\templates\dj_interview_intake_template.md`, dry-run `npm run weekly:dj-interview:import`, then import to private sidecar and review workbench before any DB/graph promotion.
