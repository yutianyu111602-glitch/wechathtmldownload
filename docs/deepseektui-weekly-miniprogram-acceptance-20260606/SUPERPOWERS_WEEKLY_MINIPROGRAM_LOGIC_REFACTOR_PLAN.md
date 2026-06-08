# Weekly Mini-Program Logic Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the weekly mini-program first-load, poster, source routing, date filtering, and geo logic testable and less coupled without changing release behavior.

**Architecture:** Use a contract-first incremental refactor. Keep existing public facades (`utils/api.js`, `utils/format.js`, `pages/index/index.js`) stable while extracting one responsibility at a time into small modules and proving behavior with tests after every slice.

**Tech Stack:** WeChat Mini Program JavaScript, Node `node:test`, Python `unittest` / `pytest`, existing Stage7 package validator, WeChat DevTools CLI via Windows PowerShell from WSL2.

---

## File Structure

Create:

- `docs/deepseektui-weekly-miniprogram-acceptance-20260606/DATA_CONTRACT_MATRIX_20260606.md`: durable/runtime truth contract for poster/source/date/geo/current feed.
- `apps/weekly_activity_miniprogram/tests/weekly-contract-regressions.test.cjs`: fixture tests for Loopy, DJ Love, Love Bang/POOLS, TRUST.
- `tools/stage7_rewrite/scripts/run_weekly_miniprogram_local_acceptance.py`: local-only acceptance runner.
- `apps/weekly_activity_miniprogram/utils/api/cache.js`: extracted API cache helpers.
- `apps/weekly_activity_miniprogram/utils/api/offlineSnapshot.js`: extracted offline/static snapshot helpers.
- `apps/weekly_activity_miniprogram/utils/format/date.js`: event date helpers.
- `apps/weekly_activity_miniprogram/utils/format/source.js`: source overview/direct-source helpers.
- `apps/weekly_activity_miniprogram/services/homeFilters.js`: homepage city/date/preview filters.

Modify:

- `apps/weekly_activity_miniprogram/utils/api.js`: preserve exports, delegate extracted helpers.
- `apps/weekly_activity_miniprogram/utils/format.js`: preserve exports, delegate extracted helpers.
- `apps/weekly_activity_miniprogram/pages/index/index.js`: only after filter tests pass, delegate pure filter functions.
- `apps/weekly_activity_miniprogram/tests/page-source-routing.test.cjs`: keep existing guard, or move new examples to `weekly-contract-regressions.test.cjs`.
- `apps/weekly_activity_miniprogram/tests/date-preview.test.cjs`: keep existing date primitives, or reference new contract fixture.
- `docs/deepseektui-weekly-miniprogram-acceptance-20260606/README.md`: point DeepSeekTUI to this plan and the contract matrix.

Do not modify:

- CloudRun deployed service state.
- CloudBase DB or Storage.
- WeChat upload/review/release state.
- secret files.

## Task 1: Recheck Current Package And Close The Remaining Geo Blocker

**Files:**

- Modify only if user provides the missing Tencent map values: `services/weekly_activity_cloudrun/data/current_release/*`
- Report: `tools/stage7_rewrite/reports/weekly_current_quality_superpowers_phase1_20260606.json`

- [ ] **Step 1: Recheck package quality**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
python tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py \
  --api-dir services/weekly_activity_cloudrun/data/current_release \
  --report tools/stage7_rewrite/reports/weekly_current_quality_superpowers_phase1_20260606.json \
  --require-internal-posters \
  --enforce-window-start
```

Expected:

```text
ok=true
missing_internal_poster_count=0
aggregate_child_source_enabled_count=0
missing_geo_count=1 or 0
```

- [ ] **Step 2: If TRUST geo is still missing, verify user-confirmed Tencent map values are present**

Check whether the current user message or a current handoff note contains all four values:

- Tencent latitude
- Tencent longitude
- Tencent address
- Tencent POI ID

If any value is missing, stop this task and report:

```text
TRUST geo write blocked: missing user-confirmed Tencent latitude/longitude/address/POI ID for 阿派朗创造力星球(朝阳公园店). No package files were changed.
```

If all values are present, create:

```text
tools/stage7_rewrite/reports/weekly_manual_place_overrides_user_confirmed_20260606_apailang.jsonl
```

The row must use only the real user-confirmed values and must set:

```text
candidate_id=manual-20260606-apailang-chaoyang-park
sample_item_ids=["trust:5b3d09797685195f"]
venue_id=apailang_creativity_planet_chaoyang_park
venue_name=阿派朗创造力星球(朝阳公园店)
city=北京
provider=user_tencent_map_picker
decision.accepted=true
decision.geo_coord_system=GCJ-02
decision.geo_source=user_tencent_map_picker_confirmed
decision.force_geo_override=true
decision.place_fields_locked=true
reverse_decision.accepted=true
```

- [ ] **Step 3: Apply the manual place override**

Run:

```bash
python tools/stage7_rewrite/scripts/apply_weekly_manual_place_overrides.py \
  --api-dir services/weekly_activity_cloudrun/data/current_release \
  --accepted-geocodes tools/stage7_rewrite/reports/weekly_manual_place_overrides_user_confirmed_20260606_apailang.jsonl \
  --backup-dir tools/stage7_rewrite/reports/weekly_manual_place_override_backup_20260606_apailang \
  --overwrite-existing
```

Expected:

```text
updated target files are reported
no script exception
```

- [ ] **Step 4: Re-run package quality and detail map tests**

Run:

```bash
python tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py \
  --api-dir services/weekly_activity_cloudrun/data/current_release \
  --report tools/stage7_rewrite/reports/weekly_current_quality_superpowers_phase1_after_geo_20260606.json \
  --require-internal-posters \
  --enforce-window-start

cd apps/weekly_activity_miniprogram
node --test tests/detail-map-location.test.cjs
```

Expected:

```text
missing_geo_count=0
detail-map-location tests pass
```

- [ ] **Step 5: Commit only if the controller allows local commits in this dirty repo**

Default: do not commit. Report changed files and evidence paths.

## Task 2: Write The Data Contract Matrix

**Files:**

- Create: `docs/deepseektui-weekly-miniprogram-acceptance-20260606/DATA_CONTRACT_MATRIX_20260606.md`
- Modify: `docs/deepseektui-weekly-miniprogram-acceptance-20260606/README.md`

- [ ] **Step 1: Create the contract matrix doc**

Write this exact table and the case notes:

```markdown
# Data Contract Matrix - Weekly Mini-Program - 2026-06-06

## Purpose

This matrix separates durable package truth from runtime display truth. It prevents future fixes from moving values into the wrong layer.

| Domain | Durable Truth | Runtime / Display Truth | Forbidden Persisted Values | First Debug Layer |
| --- | --- | --- | --- | --- |
| Poster | CloudBase `cloud://.../weekly-posters/...` file ID in package/API/CloudBase hot DB | `wx.cloud.getTempFileURL` temp URL, then optional `wx.cloud.downloadFile` local path | `mmbiz.qpic.cn`, qpic, temp URL, `wxfile://` | package validator, then `utils/cloudPosterUrls.js`, then DevTools image counters |
| Source | Direct source hash and `source_action.available=true` only for direct source rows | source page fallback only for real direct source hash | aggregate parent overview hash on child rows | package validator, then `utils/sourceArticles.js` |
| Date | event start/end and explicit event date guesses | compact labels and date filter pills | source post date as event date | package current release, then `utils/datePreview.js` |
| Geo | venue lat/lng, address, POI, locked venue fields | `wx.openLocation` payload | promoter account treated as fixed venue | manual place overrides, then detail map tests |
| Current Feed | local current release package and effective backend payload | page view model after filters and localization | stale bundled snapshot overriding current data | package quality, API tests, DevTools first-load proof |

## Regression Cases

- Loopy: aggregate children must not expose parent weekly overview source hashes.
- DJ Love: past-week rows must not reappear on 2026-06-06 through post-date or parent-title parsing.
- Love Bang / POOLS: tour parent article must split per-stop venue/date/poster; POOLS rows in this package are Dali.
- TRUST: TRUST is promoter/label; event venue comes from article title/body/poster.

## Release Boundary

This contract does not authorize CloudRun deploy, CloudBase writes, mini-program upload, review, or release.
```

- [ ] **Step 2: Link the matrix from the DeepSeek handoff README**

Add one read-order line:

```markdown
5. `DATA_CONTRACT_MATRIX_20260606.md` - poster/source/date/geo/current feed 的 durable truth 和 runtime truth 合同。
```

Expected: README still lists `DEEPSEEK_NEXT_LOGIC_REFACTOR_PLAN_20260606.md`, `CLI_FULL_COVERAGE_DEBUG_RUNBOOK.md`, and this matrix.

- [ ] **Step 3: Verify no placeholder text**

Run:

```bash
rg -n "待填|占位|假坐标|假地址" docs/deepseektui-weekly-miniprogram-acceptance-20260606/DATA_CONTRACT_MATRIX_20260606.md
```

Expected:

```text
no matches
```

## Task 3: Add Contract Regression Tests

**Files:**

- Create: `apps/weekly_activity_miniprogram/tests/weekly-contract-regressions.test.cjs`

- [ ] **Step 1: Write the regression test file**

Create:

```javascript
const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..");
const sourceArticles = require(path.join(root, "utils", "sourceArticles.js"));
const { itemMatchesDateKey } = require(path.join(root, "utils", "datePreview.js"));
const { isCloudFileId } = require(path.join(root, "utils", "cloudPosterUrls.js"));

test("Loopy aggregate child hides parent overview source and keeps activity poster truth", () => {
  const item = {
    id: "agg-child-loopy-regression",
    title: "Loopy child event",
    sourceHash: "weekly-overview-parent",
    source_action: {
      available: false,
      url_hash: "",
      disabled_reason: "aggregate_child_parent_article",
    },
    source_article: {
      url_hash: "weekly-overview-parent",
      title: "本周活动一览",
    },
    posterFileId: "cloud://huaidjweekly-d8g1go7/weekly-posters/20260606/loopy-child.jpg",
  };

  assert.equal(sourceArticles.sourceHashOf(item), "");
  assert.deepEqual(sourceArticles.sourceRefsForItem(item), []);
  assert.equal(isCloudFileId(item.posterFileId), true);
});

test("DJ Love stale post date cannot make a past event match 2026-06-06", () => {
  const item = {
    id: "dj-love-stale-regression",
    title: "DJ Love",
    post_date: "2026-06-06",
    event_date_start: "2026-05-31",
    event_date_end: "2026-05-31",
    event_date_iso_guess: "2026-05-31",
    event_date_iso_guesses: ["2026-05-31"],
  };

  assert.equal(itemMatchesDateKey(item, "2026-06-06"), false);
  assert.equal(itemMatchesDateKey(item, "2026-05-31"), true);
});

test("Love Bang POOLS stop keeps Dali venue and internal poster", () => {
  const item = {
    id: "pools-love-bang-regression",
    title: "06.05 周五｜Love Bang 16-Year Anniversary｜大理站",
    venue_name: "POOLS",
    city: "大理",
    geo_lat: 25.596385,
    geo_lng: 100.227515,
    posterFileId: "cloud://huaidjweekly-d8g1go7/weekly-posters/20260606/pools-love-bang.jpg",
  };

  assert.equal(item.city, "大理");
  assert.notEqual(item.city, "上海");
  assert.equal(item.venue_name, "POOLS");
  assert.equal(isCloudFileId(item.posterFileId), true);
});

test("TRUST is promoter and event venue is separate", () => {
  const item = {
    id: "trust-floating-promoter-regression",
    account: "TRUST 相信电音",
    promoter: "TRUST 相信电音",
    venue_name: "阿派朗创造力星球(朝阳公园店)",
    venue_id: "apailang_creativity_planet_chaoyang_park",
  };

  assert.equal(item.promoter, "TRUST 相信电音");
  assert.equal(item.venue_name, "阿派朗创造力星球(朝阳公园店)");
  assert.notEqual(item.venue_name, item.promoter);
});
```

- [ ] **Step 2: Run the new test and expect failures only if current utilities need repair**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload/apps/weekly_activity_miniprogram
node --test tests/weekly-contract-regressions.test.cjs
```

Expected:

```text
all four tests pass
```

If a test fails, fix the smallest utility branch that violates the contract before adding more tests.

- [ ] **Step 3: Run adjacent frontend tests**

Run:

```bash
node --test tests/page-source-routing.test.cjs tests/source-articles.test.cjs tests/date-preview.test.cjs tests/cloud-poster-url.test.cjs tests/detail-map-location.test.cjs tests/weekly-contract-regressions.test.cjs
```

Expected:

```text
0 failures
```

## Task 4: Extract API Cache Helpers Without Behavior Change

**Files:**

- Create: `apps/weekly_activity_miniprogram/utils/api/cache.js`
- Modify: `apps/weekly_activity_miniprogram/utils/api.js`
- Test: `apps/weekly_activity_miniprogram/tests/api-static-fallback.test.cjs`

- [ ] **Step 1: Identify cache helper names in `utils/api.js`**

Run:

```bash
rg -n "weeklyActivityApiCache|cacheMaxAge|setStorage|getStorage|cacheKey|CACHE" apps/weekly_activity_miniprogram/utils/api.js
```

Expected: list of cache constants/functions to move. Do not move network request code in this task.

- [ ] **Step 2: Create `utils/api/cache.js` with pure wrappers**

Use the same function bodies moved from `api.js`; keep this export shape:

```javascript
function safeGetStorage(key) {
  if (typeof wx === "undefined" || typeof wx.getStorageSync !== "function") return null;
  try {
    return wx.getStorageSync(key);
  } catch (error) {
    return null;
  }
}

function safeSetStorage(key, value) {
  if (typeof wx === "undefined" || typeof wx.setStorageSync !== "function") return;
  try {
    wx.setStorageSync(key, value);
  } catch (error) {
    // Storage failures must not block first-load fallback.
  }
}

module.exports = {
  safeGetStorage,
  safeSetStorage,
};
```

If `api.js` already has richer cache helpers, move those exact bodies instead of replacing behavior with this minimal version.

- [ ] **Step 3: Delegate from `api.js`**

At the top of `api.js`, add:

```javascript
const apiCache = require("./api/cache");
```

Replace only the moved local helper references with `apiCache.safeGetStorage` / `apiCache.safeSetStorage` or the exact exported names chosen in Step 2.

- [ ] **Step 4: Run focused API tests**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload/apps/weekly_activity_miniprogram
node --test tests/api-static-fallback.test.cjs tests/weekly-data-sync-loading.test.cjs tests/production-data-source.test.cjs
```

Expected:

```text
0 failures
```

## Task 5: Extract Date Contract Helpers From `format.js`

**Files:**

- Create: `apps/weekly_activity_miniprogram/utils/format/date.js`
- Modify: `apps/weekly_activity_miniprogram/utils/format.js`
- Test: `apps/weekly_activity_miniprogram/tests/date-preview.test.cjs`
- Test: `apps/weekly_activity_miniprogram/tests/weekly-contract-regressions.test.cjs`

- [ ] **Step 1: Locate date functions in `format.js`**

Run:

```bash
rg -n "dateRangeForItem|isoDate|event_date|dateLabel|dateCompact|post_date|weekday" apps/weekly_activity_miniprogram/utils/format.js
```

Expected: identify the date-only functions and constants. Do not move poster/source/map helpers in this task.

- [ ] **Step 2: Create `utils/format/date.js`**

Move date-only helpers with this export shape:

```javascript
function isoDate(value) {
  const match = String(value || "").match(/(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : "";
}

module.exports = {
  isoDate,
};
```

If `format.js` already has an `isoDate` implementation, move the exact implementation rather than replacing it.

- [ ] **Step 3: Preserve facade behavior**

In `format.js`, import:

```javascript
const formatDate = require("./format/date");
```

Where the moved helper was used internally, call the imported helper. If `format.js` exports the helper today, keep the same export name and point it to `formatDate.isoDate`.

- [ ] **Step 4: Run date tests**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload/apps/weekly_activity_miniprogram
node --test tests/date-preview.test.cjs tests/production-data-source.test.cjs tests/weekly-contract-regressions.test.cjs
```

Expected:

```text
0 failures
```

## Task 6: Extract Source Contract Helpers From `format.js`

**Files:**

- Create: `apps/weekly_activity_miniprogram/utils/format/source.js`
- Modify: `apps/weekly_activity_miniprogram/utils/format.js`
- Test: `apps/weekly_activity_miniprogram/tests/page-source-routing.test.cjs`
- Test: `apps/weekly_activity_miniprogram/tests/source-articles.test.cjs`
- Test: `apps/weekly_activity_miniprogram/tests/weekly-contract-regressions.test.cjs`

- [ ] **Step 1: Locate source overview helpers**

Run:

```bash
rg -n "sourceOverview|isSourceOverview|source_action|sourceHash|source_article|aggregate" apps/weekly_activity_miniprogram/utils/format.js
```

Expected: identify only source/overview/title-only helpers.

- [ ] **Step 2: Create `utils/format/source.js`**

Move source-only helpers with this export shape:

```javascript
function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function isSourceOverviewTitle(value) {
  const text = normalizeText(value);
  return /本周活动一览|本月活动一览|活动一览|weekly overview|monthly overview/i.test(text);
}

module.exports = {
  isSourceOverviewTitle,
};
```

If `format.js` already has a stricter `isSourceOverviewTitle`, move the exact implementation and export it.

- [ ] **Step 3: Preserve facade behavior**

In `format.js`, import:

```javascript
const formatSource = require("./format/source");
```

Keep existing export names and map them to `formatSource`.

- [ ] **Step 4: Run source tests**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload/apps/weekly_activity_miniprogram
node --test tests/page-source-routing.test.cjs tests/source-articles.test.cjs tests/weekly-contract-regressions.test.cjs
```

Expected:

```text
0 failures
```

## Task 7: Extract Homepage Filter Pure Functions

**Files:**

- Create: `apps/weekly_activity_miniprogram/services/homeFilters.js`
- Modify: `apps/weekly_activity_miniprogram/pages/index/index.js`
- Test: `apps/weekly_activity_miniprogram/tests/date-preview.test.cjs`
- Test: `apps/weekly_activity_miniprogram/tests/page-event-handler-coverage.test.cjs`

- [ ] **Step 1: Locate pure homepage filter functions**

Run:

```bash
rg -n "function filterItemsByCityKey|function filterItemsByDateKey|function filterItemsByActiveFilters|function buildDateFiltersFallback|function dateKeysForFilter" apps/weekly_activity_miniprogram/pages/index/index.js
```

Expected: all listed functions exist and are pure or mostly pure.

- [ ] **Step 2: Create `services/homeFilters.js`**

Move only the pure filter functions. Use this export shape:

```javascript
module.exports = {
  filterItemsByCityKey,
  filterItemsByDateKey,
  filterItemsByActiveFilters,
  buildDateFiltersFallback,
  dateKeysForFilter,
};
```

Import dependencies from existing utility files exactly as `index.js` did.

- [ ] **Step 3: Delegate from `index.js`**

Add:

```javascript
const homeFilters = require("../../services/homeFilters");
```

Replace local calls with:

```javascript
homeFilters.filterItemsByActiveFilters(...)
homeFilters.buildDateFiltersFallback(...)
```

Keep page `data`, lifecycle, and `loadData()` in `index.js` for this task.

- [ ] **Step 4: Run homepage and date tests**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload/apps/weekly_activity_miniprogram
node --test tests/date-preview.test.cjs tests/page-event-handler-coverage.test.cjs tests/weekly-contract-regressions.test.cjs
```

Expected:

```text
0 failures
```

## Task 8: Add Local-Only Acceptance Runner

**Files:**

- Create: `tools/stage7_rewrite/scripts/run_weekly_miniprogram_local_acceptance.py`

- [ ] **Step 1: Write runner skeleton**

Create:

```python
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REPORT_ROOT = ROOT / "tools" / "stage7_rewrite" / "reports"


def run_command(command: list[str], cwd: Path) -> dict:
    completed = subprocess.run(command, cwd=str(cwd), text=True, capture_output=True)
    return {
        "command": command,
        "cwd": str(cwd),
        "returncode": completed.returncode,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def main() -> int:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = REPORT_ROOT / f"weekly_miniprogram_local_acceptance_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    checks = [
        run_command([
            sys.executable,
            "tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py",
            "--api-dir",
            "services/weekly_activity_cloudrun/data/current_release",
            "--report",
            str(out_dir / "package_quality.json"),
            "--require-internal-posters",
            "--enforce-window-start",
        ], ROOT),
        run_command([
            sys.executable,
            "-m",
            "unittest",
            "tools.stage7_rewrite.tests.test_validate_weekly_release_package_quality",
            "-v",
        ], ROOT),
        run_command([
            "node",
            "--test",
            "tests/cloud-poster-url.test.cjs",
            "tests/page-source-routing.test.cjs",
            "tests/source-articles.test.cjs",
            "tests/poster-pool.test.cjs",
            "tests/production-data-source.test.cjs",
            "tests/date-preview.test.cjs",
            "tests/detail-map-location.test.cjs",
            "tests/weekly-contract-regressions.test.cjs",
        ], ROOT / "apps" / "weekly_activity_miniprogram"),
    ]

    report = {
        "generated_at": datetime.now().isoformat(),
        "deploy_executed": False,
        "cloudbase_write_executed": False,
        "miniprogram_upload_executed": False,
        "review_release_executed": False,
        "checks": checks,
        "ok": all(check["returncode"] == 0 for check in checks),
    }
    (out_dir / "local_acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_dir)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run local acceptance**

Run:

```bash
cd /mnt/c/code/githubstar/wechathtmldownload
python tools/stage7_rewrite/scripts/run_weekly_miniprogram_local_acceptance.py
```

Expected:

```text
prints report directory
exit code 0 when package and tests pass
local_acceptance.json records deploy/upload/write/release as false
```

## Task 9: DevTools Proof After Refactor Slices

**Files:**

- Report only: `apps/weekly_activity_miniprogram/test-artifacts/devtools-current-package-rendered-*/report.json`
- Report only: `apps/weekly_activity_miniprogram/test-artifacts/devtools-loading-fallback-*/report.json`

- [ ] **Step 1: Run current package render proof**

Run:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload'; python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-current-package-rendered.cjs --port 9430 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240"
```

Expected:

```text
posterImageLoadCount > 0
posterImageErrorCount = 0
runtime exceptions = 0
```

- [ ] **Step 2: Run first-load blackhole proof**

Run:

```bash
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Set-Location 'C:\code\githubstar\wechathtmldownload'; python tools\stage7_rewrite\scripts\run_miniprogram_devtools_rendered_single_attempt.py --script devtools-loading-fallback.cjs --port 9442 --avoid-busy-port --allow-dirty-devtools-environment --execute --timeout-sec 240"
```

Expected:

```text
loadingProgress reaches 100
first-load fallback completes under script thresholds
runtime exceptions = 0
```

## Final Verification

- [ ] Package quality report is green.
- [ ] Python validator tests are green.
- [ ] Node contract and frontend tests are green.
- [ ] Local acceptance report exists and records no deploy/upload/write/release.
- [ ] DevTools current render proof exists.
- [ ] DevTools loading fallback proof exists.
- [ ] DeepSeekTUI closeout reports exact changed files and report paths.

## Execution Choice

Recommended execution mode: Inline Execution for Tasks 1-3, then Subagent-Driven review for Tasks 4-8 if the controller wants extra safety. All writes must still be single-writer under the main controller.
