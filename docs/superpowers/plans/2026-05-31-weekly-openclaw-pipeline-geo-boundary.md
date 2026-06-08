# Weekly OpenClaw Pipeline Geo Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the OpenClaw weekly release pipeline's venue DB geo boundary executable and regression-tested so geocode, venue-anchor patching, and `zero_geo_count` gates cannot quietly re-enter the release path.

**Architecture:** Add one report-only Python audit script under `tools/stage7_rewrite/scripts` that scans named shell scripts and flags forbidden operational lines while allowing explanatory comments. Add focused pytest coverage with temporary shell-script fixtures, then run the audit against the live WSL scripts and record the result in current docs.

**Tech Stack:** Python 3 standard library, pytest, WSL shell scripts, existing Stage7 report directory conventions.

---

### Task 1: Plan Artifact

**Files:**
- Create: `docs/superpowers/plans/2026-05-31-weekly-openclaw-pipeline-geo-boundary.md`

- [x] **Step 1: Save this implementation plan**

Write the current file before code changes so the execution path is explicit.

### Task 2: Add Report-Only Audit Script

**Files:**
- Create: `tools/stage7_rewrite/scripts/audit_weekly_openclaw_pipeline_geo_boundary.py`

- [x] **Step 1: Define forbidden operational patterns**

Include these blocked patterns for non-comment shell lines:

```python
FORBIDDEN_OPERATIONAL_PATTERNS = {
    "apply_venue_anchors": re.compile(r"\bapply_venue_anchors\.py\b"),
    "anchor_patch": re.compile(r"\banchor_patch\s*\("),
    "zero_geo_count": re.compile(r"\bzero_geo_count\b"),
    "geocode_runner": re.compile(r"\b(?:geocode_weekly_activity_places|apply_weekly_geocodes_to_api_package)\.py\b"),
    "map_api_geo_key": re.compile(r"\b(?:TENCENT_MAP_KEY|AMAP_KEY|AMAP_SECRET|LBS_SK)\b"),
}
```

- [x] **Step 2: Scan only operational lines**

Treat blank lines and lines whose first non-space character is `#` as comments. Report findings with script path, line number, pattern code, and line text for any remaining match.

- [x] **Step 3: Emit JSON and markdown reports**

Default output directory:

```text
tools/stage7_rewrite/reports/weekly_openclaw_pipeline_geo_boundary_audit_20260531
```

The JSON report must include `decision`, `script_count`, `finding_count`, `findings`, and `checked_scripts`.

- [x] **Step 4: Return non-zero on findings**

The CLI exits `0` when `finding_count == 0`; otherwise exits `1`.

### Task 3: Add Focused Pytest Coverage

**Files:**
- Create: `tools/stage7_rewrite/tests/test_audit_weekly_openclaw_pipeline_geo_boundary.py`

- [x] **Step 1: Test comments are allowed**

Create temporary shell scripts containing comment-only mentions of `apply_venue_anchors.py`, `anchor_patch()`, `zero_geo_count`, and `geocode_weekly_activity_places.py`. Assert no findings.

- [x] **Step 2: Test operational violations are blocked**

Create a temporary shell script with executable lines calling `apply_venue_anchors.py`, defining `anchor_patch()`, checking `zero_geo_count`, and invoking `geocode_weekly_activity_places.py`. Assert all relevant codes are present.

- [x] **Step 3: Test report writing**

Run `write_reports()` on a passing result and assert both JSON and markdown files exist and the JSON decision is `weekly_openclaw_pipeline_geo_boundary_passed`.

### Task 4: Run Live WSL Audit

**Files:**
- Read: `\\wsl.localhost\Ubuntu\home\pc\scripts\huaidj-weekly-openclaw-stable.sh`
- Read: `\\wsl.localhost\Ubuntu\home\pc\scripts\huaidj-weekly-pipeline.sh`
- Create: `tools/stage7_rewrite/reports/weekly_openclaw_pipeline_geo_boundary_audit_20260531/weekly_openclaw_pipeline_geo_boundary_audit.json`
- Create: `tools/stage7_rewrite/reports/weekly_openclaw_pipeline_geo_boundary_audit_20260531/weekly_openclaw_pipeline_geo_boundary_audit.md`

- [x] **Step 1: Run the new audit against live WSL scripts**

```powershell
python tools\stage7_rewrite\scripts\audit_weekly_openclaw_pipeline_geo_boundary.py `
  --script \\wsl.localhost\Ubuntu\home\pc\scripts\huaidj-weekly-openclaw-stable.sh `
  --script \\wsl.localhost\Ubuntu\home\pc\scripts\huaidj-weekly-pipeline.sh
```

Expected: exit `0`, decision `weekly_openclaw_pipeline_geo_boundary_passed`.

### Task 5: Update Current Truth Docs

**Files:**
- Modify: `docs/current-runtime.md`
- Modify: `docs/CURRENT_CODE_MAP.md`
- Modify: `reports/WEEKLY_OPENCLAW_PIPELINE_VENUE_DB_GEO_REMOVAL_20260531.md`
- Modify: `\\wsl.localhost\Ubuntu\home\pc\reports\MASTER_FULL_UNDERSTANDING_20260530.md`

- [x] **Step 1: Record the audit script and report path**

Add the audit script, test file, report directory, and live-pass decision to the existing 2026-05-31 OpenClaw pipeline venue DB geo boundary notes.

### Task 6: Verification

**Files:**
- Test: `tools/stage7_rewrite/tests/test_audit_weekly_openclaw_pipeline_geo_boundary.py`

- [x] **Step 1: Run focused pytest**

```powershell
python -m pytest tools\stage7_rewrite\tests\test_audit_weekly_openclaw_pipeline_geo_boundary.py -q
```

Expected: all tests pass.

- [x] **Step 2: Run shell syntax check for live WSL scripts**

```powershell
wsl.exe -e bash -lc "bash -n /home/pc/scripts/huaidj-weekly-openclaw-stable.sh && bash -n /home/pc/scripts/huaidj-weekly-pipeline.sh"
```

Expected: exit `0`.

- [x] **Step 3: Check scoped whitespace**

```powershell
git diff --check -- docs/current-runtime.md docs/CURRENT_CODE_MAP.md reports/WEEKLY_OPENCLAW_PIPELINE_VENUE_DB_GEO_REMOVAL_20260531.md tools/stage7_rewrite/scripts/audit_weekly_openclaw_pipeline_geo_boundary.py tools/stage7_rewrite/tests/test_audit_weekly_openclaw_pipeline_geo_boundary.py
```

Expected: no whitespace errors beyond repository line-ending warnings.

### Task 7: Fixed Venue DB Coverage Follow-Up

**Files:**
- Modify: `tools/stage7_rewrite/registries/weekly_venues_seed.json`
- Modify: `tools/stage7_rewrite/scripts/archive_old/validate_weekly_registries.py`
- Create: `tools/stage7_rewrite/scripts/audit_weekly_venue_registry_geo_coverage.py`
- Test: `tools/stage7_rewrite/tests/test_audit_weekly_venue_registry_geo_coverage.py`
- Modify: `tools/stage7_rewrite/tests/test_weekly_registries.py`
- Create: `reports/WEEKLY_VENUE_DB_GEO_COVERAGE_20260531.md`

- [x] **Step 1: Backfill active registry geo gaps**

Backfilled `nuts_chongqing` and `gas_nation_tianjin` from current-release coordinate evidence for the same verified addresses.

- [x] **Step 2: Represent unresolved Rust as a known blocker**

Allowed `pending_geocode` venue status and kept `rust_club_daqing` as explicit unresolved 大庆 street-level address/coordinate blocker instead of writing a stale or invented coordinate.

- [x] **Step 3: Add registry-vs-release coverage audit**

Added `audit_weekly_venue_registry_geo_coverage.py`, which reads registry/current release only, performs no map API calls, and emits JSON/Markdown reports.

- [x] **Step 4: Verify fixed venue DB coverage**

Ran registry validator and focused pytest. Current result: `73/73` active registry venues have geo, current release `207/208` items have geo, unexpected missing geo `0`, registry/current mismatches above `2500m` `0`.
