# Loop 019 Handoff

Updated: 2026-05-31 09:38 CST

## Story

S19 - Guard the source URL map package boundary for historical article jumps.

## Completed

- Added `source_actions` to mini-program `packOptions.ignore`.
- Added a source-routing regression test proving the full source URL map stays out of the mini-program root/package.
- Verified existing source routing still treats Atlas source refs as evidence refs and does not fabricate WeChat URLs from opaque hashes.
- Added report: `reports\WEEKLY_SOURCE_URL_MAP_PACKAGE_BOUNDARY_GUARD_20260531.md`.

## Verification

- `node --test tests\page-source-routing.test.cjs` -> `7 passed`.
- `node --test tests\*.test.cjs` -> `69 passed`.
- `powershell -ExecutionPolicy Bypass -File scripts\Test-CleanCiQuality.ps1` -> `ok=true`, package size `876119`, staging files `68`.

## Boundary

No deploy/upload/review, no CloudRun data rebuild, no DB/graph/vector/source-map mutation, no coordinate write, no LLM call, and no map-provider call occurred.

## Next

Keep source article recovery and historical club posts on the server/evidence route. Do not put the full `source_url_map.json` into the mini-program package.
