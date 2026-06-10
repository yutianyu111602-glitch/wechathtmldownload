# Handoff Consistency Fix Report — 2026-06-10

## Fixes Applied

### P0-1: Push/TLS Contradiction — FIXED

**Before**: `HANDOFF_COMPLETION_REPORT` said "push blocked by TLS", Outstanding Items listed "Git push blocked by TLS" as HIGH.
**After**: Changed to PUSHED_TO_PRIVATE_REPO. Added push evidence: commit hashes `77d6904` and `6279d8b`, remote `private/main`, 434 total pushed files. Outstanding item struck through.

### P0-2: better-sqlite3 Status Contradiction — FIXED

**Before**: Handoff report said "rebuilt successfully", but `06_RUNTIME_STATE_TRUTH_TABLE.md` said "NEEDS REBUILD".
**After**: Truth table changed to REBUILT_OK with note "local verified; new clones may need `npm rebuild better-sqlite3`".

### P0-3: Sample Data Path Contradiction — FIXED

**Before**: `EXTERNAL_ARTIFACTS_MANIFEST.md` said `data/samples/（待创建）`. Actual samples at `services/weekly_activity_cloudrun/data/samples/`.
**After**: Created `data/samples/README.md` as repo-level index pointing to actual location. Updated EXTERNAL_ARTIFACTS_MANIFEST.md to point to `services/weekly_activity_cloudrun/data/samples/`. No more "待创建".

### P0-4: 00_AI_README Old API and Doc Paths — FIXED

**Before**: Listed `/api/v1/activities`, `/api/v1/djs`, `/api/v1/venues` (nonexistent routes). Doc reading order pointed to old file names like `06_API_CONTRACTS.md`, `13_SECURITY_PRIVACY.md`.
**After**: Replaced with actual weekly API routes (`/api/weekly/current`, `/api/weekly/by-city/:city`, etc.). Updated doc reading order to use current filenames (`06_RUNTIME_STATE_TRUTH_TABLE.md`, `03_API_CONTRACTS_WEEKLY.md`, etc.).

### P0-5: Item Count 171 vs 155 — FIXED

**Before**: Truth table stated by-id=155, enrichments=155, but current.json=171.
**After**: Verified via `git ls-tree` that ALL counts are 171. The 155 was stale from an earlier data pack. Added "Item Count Semantics" section with verification commands. Generated `item_count_semantics_probe.json`.

### P0-6: External Artifacts Manifest — UPDATED

**Before**: Many sha256 fields were `<path>` or `-`. Had "data/samples/（待创建）".
**After**: Replaced placeholder sha256 with `UNKNOWN_NEEDS_HUMAN`. Added current selected serving DB path. Added weekly increment packages. Removed stale entries (NIGHT_WATCHER, product PDF). Added sample data entry. Removed "待创建".

### P0-7: DEEPSEEK_API_KEY Risk — ADDRESSED

**Created**: `docs/security/SECRET_ROTATION_NOTICE_20260610.md` — P0 human action to rotate key. Key value never recorded. Verification commands included. Updated handoff report Outstanding Items to mark this as P0 HUMAN with reference to the new doc.

### P1-1: API Contracts Strengthened — DONE

**Before**: Weekly API routes listed with only description and response shape.
**After**: Added columns for Backend Handler, Frontend Call Site, Test File. Added Known Risks table.

## Still UNKNOWN

| Item | Status | Action |
|------|--------|--------|
| atlas_merged.sqlite sha256 | UNKNOWN_NEEDS_HUMAN | Cannot compute — file on WSL, 3.8GB |
| atlas_serving.sqlite sha256 | UNKNOWN_NEEDS_HUMAN | Cannot compute — file in reports/, 1.6GB |
| Weekly increment package sizes | UNKNOWN_NEEDS_HUMAN | On D: drive, cannot scan |
| CloudRun deployment status | NOT DEPLOYED | Human must deploy |
| Mini-program upload status | NOT UPLOADED | Human must upload |
| DEEPSEEK_API_KEY rotation | PENDING HUMAN ACTION | Key still on local disk |
| llm/enrichments/ 0 files on Windows FS | UNEXPLAINED_FS_ISSUE | Git tree has 171; likely sparse-checkout or NTFS |

## Requires Human Confirmation

1. **Rotate DEEPSEEK_API_KEY** — `docs/security/SECRET_ROTATION_NOTICE_20260610.md`
2. **Deploy CloudRun** — `docs/10_DEPLOYMENT_SOP.md`
3. **Upload mini-program** — `docs/10_DEPLOYMENT_SOP.md`
4. **Investigate llm/enrichments/ filesystem discrepancy** — 171 in git, 0 on disk
5. **Compute sha256 for large databases** if needed for verification

## Conclusion

**READY_FOR_ASSISTANT_DEEP_RESEARCH**

All P0 contradictions fixed. Remaining items are human actions (key rotation, deploy, upload) or uncomputable hashes on large files. No documentation contradictions remain that would mislead the next AI.
