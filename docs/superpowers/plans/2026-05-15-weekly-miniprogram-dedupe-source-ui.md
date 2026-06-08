# Weekly Miniprogram Dedupe Source UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix duplicate event display, conservative time and lineup presentation, source-opening behavior, address-copy wording, cross-source audit, and the HUAIDJ plus Pugna visual treatment for the weekly activity mini-program.

**Architecture:** Keep the fastest user-facing fixes in `apps/weekly_activity_miniprogram`: normalize and dedupe compact items before rendering, suppress uncertain time and lineup values in `utils/format.js`, and make title/detail/source interactions explicit in page WXML/JS. Add offline audit and repair scripts under `tools/stage7_rewrite/scripts` so the OpenClaw publishing lane repairs raw duplicate rows, quarantines cross-source conflicts, then fails hard if any raw duplicate or conflict remains before upload.

**Tech Stack:** WeChat Mini Program WXML/WXSS/CommonJS, Node.js test scripts, CloudBase Run static release JSON, PowerShell upload through WeChat DevTools CLI.

---

### Task 1: Add Data-Quality Tests

**Files:**
- Create: `apps/weekly_activity_miniprogram/tests/format-quality.test.cjs`

- [ ] Create tests that assert conservative display behavior:
  - `JACK'N` and `📌 JACK'N` normalize to the same duplicate key.
  - `venue_default` time is hidden, `source_text` time is shown.
  - sentence-like lineup entries are removed.
  - when raw lineup existed but no trusted lineup survives, the item exposes the Chinese hint `点击海报跳转详情页查看`.

Run: `node tests\format-quality.test.cjs`
Expected initially: FAIL because the helper functions do not exist yet.

### Task 2: Normalize, Dedupe, and Suppress Uncertain Fields

**Files:**
- Modify: `apps/weekly_activity_miniprogram/utils/format.js`
- Modify: `apps/weekly_activity_miniprogram/pages/index/index.js`
- Test: `apps/weekly_activity_miniprogram/tests/format-quality.test.cjs`

- [x] Export `dedupeKeyForItem(item)` from `format.js`.
- [x] In `compactItem`, set `timeLabel` only when `event_time_source` or `running_hours_source` is source-grounded (`source_text`, article text, poster OCR/text, or manual verified); never show `venue_default` or `venue_default_override` as a confident time.
- [x] Harden `cleanLineup(item)` by rejecting connective/sentence-like names such as entries containing `成员`, `在 `, `呈现`, `关于`, `你的身体`, or generic labels like `阵容`.
- [x] Add `lineupHint` and `hasLineupHint` to compact items when a raw lineup existed but no trusted names remain.
- [x] In `index.js`, dedupe `current.items` immediately after `compactItem`, keeping the item with the stronger quality score: trusted time, address, description, source hash, lineup, and style.

Run: `node tests\format-quality.test.cjs`
Expected: PASS.

### Task 3: Fix Click Semantics and Copy Wording

**Files:**
- Modify: `apps/weekly_activity_miniprogram/pages/index/index.wxml`
- Modify: `apps/weekly_activity_miniprogram/pages/detail/detail.wxml`
- Modify: `apps/weekly_activity_miniprogram/pages/detail/detail.js`
- Modify: `apps/weekly_activity_miniprogram/pages/source/source.js`
- Modify: `apps/weekly_activity_miniprogram/utils/sourceAction.js`

- [x] Remove title-level `openSource` binding from the index list; list title and row both navigate to detail.
- [x] On the detail page, title remains normal text; poster tap calls `openSourceByHash`.
- [x] Remove source URL clipboard fallback; failed article open navigates to the source page for another open attempt.
- [x] Change address copy feedback to `地址已复制` / `Address copied`.
- [x] Remove the source page copy button so source behavior is open-only, not copy-first.

Manual expected behavior: title opens detail; poster opens official article; address block copies address and shows address-specific feedback.

### Task 4: Date-First List Layout and Pugna-Tinted HUAIDJ Theme

**Files:**
- Modify: `apps/weekly_activity_miniprogram/app.wxss`
- Modify: `apps/weekly_activity_miniprogram/pages/index/index.wxml`
- Modify: `apps/weekly_activity_miniprogram/pages/index/index.wxss`
- Modify: `apps/weekly_activity_miniprogram/pages/detail/detail.wxss`

- [x] Replace each list-row time cell with a compact date block: weekday on top and `MM.DD` below.
- [x] Enlarge `.day-head`, `.event-weekday`, and `.event-day`; remove time emphasis from the timeline.
- [x] Keep HUAIDJ base colors `#0a0a0a`, `#e0e0e0`, and `#7eb8da`.
- [x] Add restrained Pugna accents: acid green `#b6ff3b`, spectral green `#58d86b`, deep violet `#30204a`, and bone white `#e9e5cf`.
- [x] Do not introduce large glow cards, orbs, blurred backgrounds, or marketing-page composition.

Manual expected behavior: the screen still reads as HUAIDJ, but selected states, hints, and section bullets carry a Pugna-like green/violet accent.

### Task 5: Add Cross-Source Audit for OpenClaw

**Files:**
- Create: `tools/stage7_rewrite/scripts/audit_weekly_cross_source_conflicts.py`
- Create: `tools/stage7_rewrite/scripts/repair_weekly_release_conflicts.py`
- Modify: `tools/stage7_rewrite/weekly_activity_next_week_pipeline.ps1`
- Create: `tools/stage7_rewrite/tests/test_repair_weekly_release_conflicts.py`

- [x] Read `services/weekly_activity_cloudrun/data/current_release/current.json` by default.
- [x] Cluster items by normalized title, date, city, and venue.
- [x] Report raw duplicate clusters, effective post-dedupe count, same-title cross-source conflicts, conflicting time values, and conflicting venue/address values.
- [x] Exit non-zero when effective duplicates or high-confidence conflicts exist; raw duplicates remain visible as warnings and can be made fatal with `--fail-on-raw-duplicates`.
- [x] Add a write-mode repair step that keeps the best/newest exact duplicate, rewrites `current/manifest/by-city/by-date/by-id/source_url_map/LLM` materialized files, and writes `repair_report.json`.
- [x] Quarantine same-title/date/city cross-source conflict groups instead of guessing a venue, address, or time.
- [x] Insert pipeline Step 4.5: repair with `--write --quarantine-conflicts`, then audit with `--strict --fail-on-raw-duplicates`.

Run:
- `python tools\stage7_rewrite\scripts\repair_weekly_release_conflicts.py --api-dir services\weekly_activity_cloudrun\data\current_release --write --quarantine-conflicts`
- `python tools\stage7_rewrite\scripts\audit_weekly_cross_source_conflicts.py --input services\weekly_activity_cloudrun\data\current_release\current.json --strict --fail-on-raw-duplicates`

Expected after repair: raw duplicate clusters, effective duplicate clusters, and conflict clusters are all `0`.

### Task 6: Version, Test, Upload

**Files:**
- Modify: `apps/weekly_activity_miniprogram/pages/about/about.js`

- [x] Bump `VERSION` to `0.5.4` and keep `BUILD_DATE` at `2026-05-15`.
- [x] Run:
  - `node tests\api-static-fallback.test.cjs`
  - `node tests\format-quality.test.cjs`
  - `node --test tests/*.test.mjs` from `services/weekly_activity_cloudrun`
  - cross-source audit command from Task 5.
- [x] Upload through WeChat DevTools CLI:
  - version `0.5.4`
  - desc `修复去重、可信时间、阵容保守展示、原文跳转与Pugna配色`

Additional deployment evidence:
- CloudRun deploy created `weekly-api-011`; `cloudrun traffic promote` moved it to 100% traffic.
- Downloaded remote package after promotion contains `TRUSTED_TIME_SOURCES`, `itemQualityScore`, and `dedupeItems` in `src/dataStore.mjs`.
- First UI/data deploy audit before repair: local and downloaded remote `current.json` had `item_count=168`, `effective_item_count=167`, `effective_duplicate_cluster_count=0`, `conflict_cluster_count=0`, but raw duplicate cluster count was still `1`.
- Repair deploy evidence: local and downloaded remote `current.json` now have `item_count=167`, `effective_item_count=167`, `duplicate_cluster_count=0`, `effective_duplicate_cluster_count=0`, `conflict_cluster_count=0`; removed raw duplicate `exit_shanghai:b0fd8ad3a6b02bda`, retained newer `exit_shanghai:7abfce849fee404d`.
- CloudRun redeploy at 2026-05-15 17:34 CST promoted to 100% traffic; downloaded remote package at `C:\Users\pc\AppData\Local\Temp\huaidj-weekly-api-download-20260515_173710` matched the repaired counts and source map.

Expected: tests pass and DevTools CLI reports upload success.
