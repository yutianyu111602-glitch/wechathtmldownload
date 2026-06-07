# Worklog And Evidence - Weekly Mini-Program Repair - 2026-06-06

## Skills / Weapons Used

### Skills Loaded

- `agent-skills-zh-router`: Chinese task routing.
- `local-skill-router`: local skill routing and safety boundaries.
- `huaidj-weekly-release-guardian`: weekly mini-program release gates, CloudBase/CloudRun/package distinction.
- `debugging-and-error-recovery`: root-cause workflow and regression guard.
- `handoff-writer`: this acceptance package.
- `documentation-and-adrs`: decision/gotcha documentation.
- `ssot-handoff-reporter`: durable handoff and next-entry format.

### Tools / Scripts Used

- `rg`: code and artifact search.
- Python package validators and repair scripts:
  - `tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py`
  - `tools/stage7_rewrite/scripts/repair_weekly_release_conflicts.py`
  - `tools/stage7_rewrite/scripts/apply_weekly_manual_place_overrides.py`
- Node mini-program tests:
  - `apps/weekly_activity_miniprogram/tests/cloud-poster-url.test.cjs`
  - `apps/weekly_activity_miniprogram/tests/page-source-routing.test.cjs`
  - `apps/weekly_activity_miniprogram/tests/source-articles.test.cjs`
  - `apps/weekly_activity_miniprogram/tests/poster-pool.test.cjs`
  - `apps/weekly_activity_miniprogram/tests/production-data-source.test.cjs`
  - `apps/weekly_activity_miniprogram/tests/detail-map-location.test.cjs`
- `apply_patch`: file edits.
- PowerShell and WSL bridge for local artifact sync.

## Work Performed

### 1. Aggregate-child poster fileId loss

Problem:

- Current 155 package had 11 aggregate-child rows missing CloudBase `cloud://` poster file IDs.
- These rows had source actions disabled correctly, but poster fields were empty.

Root cause:

- A stale repair output conflated source-link suppression with poster suppression.
- Source links for aggregate-child rows should be disabled because they point to parent overview articles.
- Real CloudBase activity poster file IDs must remain.

Fix:

- Restored 11 CloudBase poster file IDs from a verified probe package.
- Rebuilt current package routes and manifest through `repair_weekly_release_conflicts.py`.
- Fixed validator contract so `poster_source=cloudbase_storage` is accepted when a real internal CloudBase poster file ID exists.

Changed/created evidence:

- `tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py`
- `tools/stage7_rewrite/tests/test_validate_weekly_release_package_quality.py`
- `tools/stage7_rewrite/reports/weekly_current_agg_child_poster_restore_patch_20260606.json`
- `tools/stage7_rewrite/reports/weekly_current_repair_after_agg_child_poster_restore_20260606.json`
- `tools/stage7_rewrite/reports/weekly_current_quality_after_agg_child_poster_restore_20260606.json`

### 2. Geo manual confirmations

Applied user-confirmed Tencent map picker rows:

| id | venue | city | coordinate | POI |
| --- | --- | --- | --- | --- |
| `pools:149bc4362ef89ac8` | POOLS / Love POOLS | 大理 | `25.596385,100.227515` | `1816199312489970978` |
| `pools:855d2fb1630e3b86` | POOLS / Love POOLS | 大理 | `25.596385,100.227515` | `1816199312489970978` |
| `ruaalab:172c7ad6767164ab` | RUAALAB | 三亚 | `18.301517,109.450217` | `7019913020037636495` |
| `tin:ac5703ce1b232217` | 厅Tin | 成都 | `30.588569,104.080481` | empty in picker |
| `cedar_kitchen:0f0b0d4c2e8f88b4` | Cedar Kitchen(茂名南路店) | 上海 | `31.223088,121.461366` | `3608572956257176042` |

Important correction:

- There is no Shanghai POOLS for these rows. Both POOLS rows are Dali POOLS / Love POOLS.
- `apply_weekly_manual_place_overrides.py` lacked `三亚 -> sanya`; this was patched and covered by test.

Changed/created evidence:

- `tools/stage7_rewrite/scripts/apply_weekly_manual_place_overrides.py`
- `tools/stage7_rewrite/tests/test_apply_weekly_manual_place_overrides.py`
- `tools/stage7_rewrite/reports/weekly_manual_place_overrides_user_confirmed_20260606_pools_ruaalab_tin.jsonl`
- `tools/stage7_rewrite/reports/weekly_manual_place_overrides_user_confirmed_20260606_cedar_kitchen.jsonl`
- `tools/stage7_rewrite/reports/weekly_current_quality_after_manual_geo_pools_ruaalab_tin_20260606.json`
- `tools/stage7_rewrite/reports/weekly_current_quality_after_manual_geo_cedar_kitchen_20260606.json`

### 3. TRUST promoter / venue correction

Problem:

- `TRUST 相信电音` was being used as `venue_name`.
- User clarified TRUST is a music label/promoter with floating venues.

Fix:

- `trust:5b3d09797685195f` now keeps `account/promoter/source_account_name=TRUST 相信电音`.
- Its event venue is now `阿派朗创造力星球(朝阳公园店)`, extracted from title evidence `@ 阿派朗创造力星球 (朝阳公园店)`.
- Coordinates remain missing until the specific venue's Tencent map picker value is confirmed.

Evidence:

- `tools/stage7_rewrite/reports/weekly_current_trust_floating_promoter_venue_fix_20260606.json`
- `tools/stage7_rewrite/reports/weekly_current_quality_after_trust_floating_promoter_venue_fix_20260606.json`

## Verification Commands And Results

### Python tests

```powershell
python -m unittest tools.stage7_rewrite.tests.test_validate_weekly_release_package_quality -v
```

Result: 20/20 pass.

```powershell
python -m unittest tools.stage7_rewrite.tests.test_repair_weekly_release_conflicts -v
```

Result: 26/26 pass.

```powershell
python -m pytest tools/stage7_rewrite/tests/test_apply_weekly_manual_place_overrides.py -q
```

Result after Sanya test: 2/2 pass.

### Package quality

Latest:

```powershell
python tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py --api-dir services/weekly_activity_cloudrun/data/current_release --report tools/stage7_rewrite/reports/weekly_current_quality_after_trust_floating_promoter_venue_fix_20260606.json --require-internal-posters --enforce-window-start
```

Result:

- `ok=true`
- `hard_failures=[]`
- `item_count=155`
- `missing_internal_poster_count=0`
- `invalid_poster_storage_count=0`
- `aggregate_child_source_enabled_count=0`
- `aggregate_child_poster_suppressed_count=0`
- `missing_geo_count=1`

### Frontend tests

```powershell
node --test tests/detail-map-location.test.cjs tests/production-data-source.test.cjs tests/page-source-routing.test.cjs
```

Result: 16/16 pass.

Earlier broader frontend poster/source tests:

```powershell
node --test tests/cloud-poster-url.test.cjs tests/page-source-routing.test.cjs tests/source-articles.test.cjs tests/poster-pool.test.cjs tests/production-data-source.test.cjs
```

Result: 33/33 pass.

## Dirty Worktree Note

The repo was already dirty with many modified and untracked files before this handoff. Do not run cleanup, reset, checkout, or git clean. Treat all unrelated dirty state as user/project history.

## 2026-06-07 Acceptance Takeover

### Actions Performed

1. Step 2: Confirmed DevTools CLI and project exist — both `True`.
2. Step 4-5: DevTools environment audit — `clean_for_automator_launch=true`.
3. Step 6: `npm run patch:automator-devtools` — `ok: true`, no changes needed.
4. Quality gate: `python tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py` → `ok=true`, all zero counts, `missing_geo_count=0` (TRUST geo confirmed applied).
5. Step 7: `npm run debug:cloud-ai` — `ok: true`, `weeklyAiProxy` connected, `provider=hunyuan-v3`.
6. Step 8: DevTools render proof — DevTools launched on port 9431, 36 items rendered from 06-07 through 06-16, 36/36 CloudBase temp posters, 0 exceptions, 0 public qpic leakage. Test assertion `expectedMinItems=74` stale (written for 06-05 window); render is correct.
7. TRUST `阿派朗创造力星球(朝阳公园店)` geo confirmed: `39.947645, 116.484822`, event_date=2026-06-13.

### Key Evidence Paths

- Quality gate: `tools/stage7_rewrite/reports/weekly_current_quality_deepseektui_cli_full_coverage_20260606.json`
- DevTools render: `apps/weekly_activity_miniprogram/test-artifacts/devtools-current-package-rendered-2026-06-07T04-32-13-434Z/partial-report.json`
- DevTools environment: `tools/stage7_rewrite/reports/weekly_miniprogram_devtools_environment_s55_20260531/weekly_miniprogram_devtools_environment_audit.json`
- TRUST item: `services/weekly_activity_cloudrun/data/current_release/by-id/trustu3a5b3d09797685195f.json`

### Remaining

- Python unit tests (validate/repair/apply_manual_place_overrides): not re-run in this session.
- Node frontend tests (full suite): not re-run in this session.
- DevTools first-load blackhole/60% stall proof: not run.
- CloudRun deploy, CloudBase write, mini-program upload: not executed (boundary respected).

