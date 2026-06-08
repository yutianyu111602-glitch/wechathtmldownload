# Weekly Mini-Program Aggregate Child Poster And Geo Repair - 2026-06-06

## Current Result

- Local current package: `services/weekly_activity_cloudrun/data/current_release`
- Item count: 155
- Package quality report: `tools/stage7_rewrite/reports/weekly_current_quality_after_agg_child_poster_restore_20260606.json`
- Result: `ok=true`
- Remaining advisory: `missing_geo_count=6`

## Root Cause

The 155 package did not miss CloudBase uploads. The missing 11 aggregate-child posters were caused by a stale repair output.

Earlier repair logic disabled aggregate-child source links to prevent child event cards from opening a parent weekly/monthly overview article, but the same flow also cleared poster fields. That mixed two separate concepts:

- source action suppression: required for aggregate-child items whose source article is a parent overview
- CloudBase activity poster retention: required for frontend poster rendering through `wx.cloud.getTempFileURL`

The correct package truth is still CloudBase `cloud://.../weekly-posters/...` file IDs. Public WeChat image URLs are not valid package truth because they can fail under mini-program domain and anti-scrape constraints.

## Code Fix

`tools/stage7_rewrite/scripts/repair_weekly_release_conflicts.py` already preserves internal CloudBase poster file IDs when aggregate-child source links are disabled.

This session fixed the validator contract in:

- `tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py`
- `tools/stage7_rewrite/tests/test_validate_weekly_release_package_quality.py`

The validator now treats `poster_source=cloudbase_storage` as a valid source enum when the same item has a real internal `cloud://.../weekly-posters/...` poster file ID. It still rejects `poster_source=wechat_article` or parent/public poster residue on aggregate-child rows.

## Data Repair

The 11 missing file IDs were restored from the previously repaired package:

- source package: `tools/stage7_rewrite/reports/manual_repair_probe_20260606_agg_child_poster_preserve/current.json`
- restore report: `tools/stage7_rewrite/reports/weekly_current_agg_child_poster_restore_patch_20260606.json`
- repair report: `tools/stage7_rewrite/reports/weekly_current_repair_after_agg_child_poster_restore_20260606.json`

The current 155 package and the probe package had identical item IDs and no non-poster field differences. Only poster fields were restored.

## Verification

Commands:

```powershell
python -m unittest tools.stage7_rewrite.tests.test_validate_weekly_release_package_quality -v
python -m unittest tools.stage7_rewrite.tests.test_repair_weekly_release_conflicts -v
python tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py --api-dir services/weekly_activity_cloudrun/data/current_release --report tools/stage7_rewrite/reports/weekly_current_quality_after_agg_child_poster_restore_20260606.json --require-internal-posters --enforce-window-start
node --test tests/cloud-poster-url.test.cjs tests/page-source-routing.test.cjs tests/source-articles.test.cjs tests/poster-pool.test.cjs tests/production-data-source.test.cjs
```

Results:

- validator tests: 20/20 pass
- repair tests: 26/26 pass
- package quality: `ok=true`, `missing_internal_poster_count=0`, `invalid_poster_storage_count=0`
- frontend poster/source tests: 33/33 pass

## Manual Geo Update - 2026-06-06 15:28 CST

User-confirmed Tencent map picker overrides were applied with:

- input: `tools/stage7_rewrite/reports/weekly_manual_place_overrides_user_confirmed_20260606_pools_ruaalab_tin.jsonl`
- backup: `tools/stage7_rewrite/reports/weekly_manual_place_override_backup_20260606_pools_ruaalab_tin`
- package report: `services/weekly_activity_cloudrun/data/current_release/manual_place_override_apply_report.json`
- quality report: `tools/stage7_rewrite/reports/weekly_current_quality_after_manual_geo_pools_ruaalab_tin_20260606.json`

Applied rows:

| id | city | venue | coordinate | address | POI ID |
| --- | --- | --- | --- | --- | --- |
| `pools:149bc4362ef89ac8` | 大理 | POOLS / Love POOLS | `25.596385,100.227515` | 云南省大理白族自治州大理市下关街道洱河南路下关金港中民城市广场B幢1-58号 | `1816199312489970978` |
| `pools:855d2fb1630e3b86` | 大理 | POOLS / Love POOLS | `25.596385,100.227515` | 云南省大理白族自治州大理市下关街道洱河南路下关金港中民城市广场B幢1-58号 | `1816199312489970978` |
| `ruaalab:172c7ad6767164ab` | 三亚 | RUAALAB | `18.301517,109.450217` | 海南省三亚市天涯区回辉四村一路 | `7019913020037636495` |
| `tin:ac5703ce1b232217` | 成都 | 厅Tin | `30.588569,104.080481` | 四川省成都市锦江区国华街 | empty in Tencent picker |

The manual override script was patched to support `三亚 -> sanya`, with a regression test in `tools/stage7_rewrite/tests/test_apply_weekly_manual_place_overrides.py`.

After this update, package quality remains `ok=true`, and `missing_geo_count=2`.

Additional user-confirmed Tencent map picker override applied at 2026-06-06 15:48 CST:

- input: `tools/stage7_rewrite/reports/weekly_manual_place_overrides_user_confirmed_20260606_cedar_kitchen.jsonl`
- backup: `tools/stage7_rewrite/reports/weekly_manual_place_override_backup_20260606_cedar_kitchen`
- quality report: `tools/stage7_rewrite/reports/weekly_current_quality_after_manual_geo_cedar_kitchen_20260606.json`

| id | city | venue | coordinate | address | POI ID |
| --- | --- | --- | --- | --- | --- |
| `cedar_kitchen:0f0b0d4c2e8f88b4` | 上海 | Cedar Kitchen(茂名南路店) | `31.223088,121.461366` | 上海市黄浦区瑞金二路街道巨鹿路272号 | `3608572956257176042` |

After the Cedar Kitchen update, package quality remains `ok=true`, and `missing_geo_count=1`.

TRUST correction applied at 2026-06-06:

- report: `tools/stage7_rewrite/reports/weekly_current_trust_floating_promoter_venue_fix_20260606.json`
- quality report: `tools/stage7_rewrite/reports/weekly_current_quality_after_trust_floating_promoter_venue_fix_20260606.json`

Rule: `TRUST 相信电音` is a promoter/label, not a fixed venue. For TRUST rows, venue must come from the event source article/title. For `trust:5b3d09797685195f`, the venue was corrected from `TRUST 相信电音` to `阿派朗创造力星球(朝阳公园店)` based on the title evidence `@ 阿派朗创造力星球 (朝阳公园店)`. The item keeps `account/promoter/source_account_name=TRUST 相信电音`.

After this correction, package quality remains `ok=true`, and `missing_geo_count=1`; the missing row now correctly names the venue as `阿派朗创造力星球(朝阳公园店)`.

## Remaining Geo Work

These rows still need source-backed address or provider verification before coordinate write.

| id | title | city | venue |
| --- | --- | --- | --- |
| `trust:5b3d09797685195f` | `TRUST × SURĀ｜Wave Rave 06.13 @ 阿派朗创造力星球 (朝阳公园店)` | 北京 | 阿派朗创造力星球(朝阳公园店) |

## Guardrail

Do not blindly clear poster fields when disabling aggregate-child source actions. The release package should keep:

- `source_action.available=false`
- `source_action.disabled_reason=aggregate_child_parent_article`
- empty parent source hash fields
- real internal `cloud://.../weekly-posters/...` poster file IDs
- `poster_storage=cloudbase`
- `poster_source=cloudbase_storage`
