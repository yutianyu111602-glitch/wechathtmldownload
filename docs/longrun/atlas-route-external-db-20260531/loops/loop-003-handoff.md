# Loop 003 Handoff - Missing Geo Provider Recheck

Updated: 2026-05-31 06:40 CST

## Status

S3 is blocked with evidence, not silently passed.

The only current-release missing-geo row is `rust_club:74c857fda5f80128` / `Rust Club 锈蚀俱乐部` in `大庆`. Tencent and Amap checks did not produce an acceptable street-level coordinate, so no address or coordinate was written.

## Evidence

- Decision report: `reports\WEEKLY_GEOCODE_MISSING_GEO_PROVIDER_RECHECK_20260531.md`.
- Queue-only report: `tools\stage7_rewrite\reports\weekly_geocode_missing_geo_queue_20260531\report.json`.
- Tencent Windows report: `tools\stage7_rewrite\reports\weekly_geocode_missing_geo_tencent_20260531\provider_results.jsonl`.
- Tencent WSL LBS report: `tools\stage7_rewrite\reports\weekly_geocode_missing_geo_tencent_wsl_lbs_20260531\provider_results.jsonl`.
- Amap WSL report: `tools\stage7_rewrite\reports\weekly_geocode_missing_geo_amap_20260531\provider_results.jsonl`.

## Verification

- `python -m pytest tools\stage7_rewrite\tests\test_geocode_weekly_activity_places.py -q` passed `18`.
- Queue-only candidate count is `1`.
- Tencent provider returned status `111` in Windows and WSL runs.
- Amap provider returned API OK but `strong_place_matches=0`.

## Boundary

- Do not use the stale Beijing coordinate for Rust Club.
- Do not write a guessed 大庆 coordinate without provider/source cross-check.
- Do not print map keys or SK values; only env names and provider status codes are safe to record.

## Next Resume Cursor

Continue S4 from `docs\longrun\atlas-route-external-db-20260531\04-prd.json`: audit and harden mixtape / external music outlinks so the mini-program jumps to original links and never caches/proxies copyrighted audio.
