# Ping常 Atlas Weekly Refresh Plan

Date: 2026-05-22
Repo: `C:\code\githubstar\wechathtmldownload`

## Goal

Refresh the local weekly/Atlas lane from the current WeChat exporter state, check Ping常 (杭州) freshness, rerun the full local weekly pipeline, update local derived data artifacts, and record the reusable workflow as a Codex skill.

## Boundaries

- Do not print secrets, cookies, or raw auth keys.
- Do not use 9router.
- Do not deploy CloudRun, upload/review the mini-program, write Neo4j/Qdrant/production SQLite, or mutate raw `atlas.sqlite`.
- Local writes are allowed for dated outputs, reports, skill files, prompt/test changes, and read-only Atlas bridge artifacts.

## Steps

1. Read current docs and handoff surfaces for weekly, Ping常, and Atlas boundaries.
2. Preserve dirty repo state with a non-destructive backup.
3. Check latest downloaded Ping常 article time, rerun Ping常 history fetch, and compare old/new URL sets.
4. Verify exporter session and rerun `weekly_activity_next_week_pipeline.ps1 -SkipUpload` against current exporter data.
5. Patch online DeepSeek prompt field coverage and `field_evidence_refs` sanitization while the pipeline has not reached Step 3.7.
6. Validate prompt changes with focused tests.
7. Build Atlas weekly snapshot/observations after the API package exists, then run observation ingest dry-run.
8. Create and validate `wechat-atlas-weekly-refresh` skill plus an EvolveR-lite experience card.
9. Update current docs/registration surfaces and close with exact counts, output paths, and unresolved risks.

## Live Status

- Repo backup: completed at `C:\code\.git-workspace-backups\wechathtmldownload\20260522-110339`.
- Ping常 history rerun: completed; no new Ping常 URL beyond `2026-05-20 09:31:49`.
- Global weekly pipeline: completed locally from fresh exporter queue. Queue summary: `12791` rows, `1731` new, latest post date `2026-05-22`; dated API package has `176` current items and staged release `weekly-current-20260522` has `215` files.
- DeepSeek prompt/test patch: completed; transient Step 3.7 Pro adjudication timeout on 1 row was fixed by adding retry/backoff and repairing that row. `test_weekly_activity_deepseek_enrichment.py` passed `10/10`; DeepSeek summary now has `failed=0`.
- Skill creation: completed; `C:\Users\pc\.codex\skills\wechat-atlas-weekly-refresh`.
- Atlas bridge/data closeout: completed. Dated API and `services\weekly_activity_cloudrun\data\current_release` both have `weekly_entity_snapshot.json` and `weekly_entity_observations.jsonl`; observation ingest dry-runs passed with `176/176` source URL hashes and `0` leak hits.
- Quality report: `tools\stage7_rewrite\reports\weekly_refresh_quality_20260522.md` and `.json`.
- Boundary kept: no CloudRun deploy, no mini-program upload/review, no raw `atlas.sqlite` mutation, no Neo4j/Qdrant/production SQLite write.
