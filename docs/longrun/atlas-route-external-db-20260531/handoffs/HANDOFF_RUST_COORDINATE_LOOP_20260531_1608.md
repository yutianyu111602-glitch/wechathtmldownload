# Handoff: Rust Club Coordinate Loop

Updated: 2026-05-31 16:08 CST

## 1. Main Problem

Rust Club `rust_club_daqing` now has a user-supplied poster address candidate, but it still lacks provider-accepted taxi-grade coordinates and must not be written to production until geocode + reverse confirmation passes.

## 2. Scope

- Repo: `C:\code\githubstar\wechathtmldownload`
- Branch: `codex/atlas-db-unification-20260531`
- Goal lane: Atlas/HUAIDJ weekly coordinate/address repair and solidification.
- In scope: Rust Club address/coordinate verification, fixed venue registry solidification, mini-program taxi-grade map gate, SSOT/report updates.
- Out of scope without a separate final gate: CloudRun deploy, mini-program upload/review, DB1/DB2/DB3 production mutation, graph/vector public writes, media fetch/cache/proxy, secret printing.

## 3. Current Reality

### Confirmed

- Current release has `208` items; `207/208` have usable geo.
- Registry after S44 solidification has `77/77` active venues with geo.
- Current release items using registry geo are now `207/208`.
- The remaining known missing coordinate is `rust_club:74c857fda5f80128` / `rust_club_daqing` / `Rust Club 锈蚀俱乐部` / `大庆`.
- User supplied candidate address: `大庆市龙凤区东风新村学伟大街 大庆市黎明湖酒吧一条街三号集装箱`.
- Candidate was captured in `tools\stage7_rewrite\reports\rust_club_user_address_candidate_s45_20260531\rust_club_candidate_current.json`.
- Tencent probe with current env key/SK produced accepted `0`, review `2`, status `111` for paired signature and unsigned fallback.
- No Rust Club address/coordinate was written to production registry/current release.
- Mini-program detail map action now requires taxi-grade evidence and no longer requests user location before `wx.openLocation`.

### Hypotheses

- The user-supplied poster address is likely the right venue address, but it still needs provider acceptance and reverse-geocoder confirmation.
- Tencent status `111` is likely a key/SK/control-plane mismatch for the current Windows environment, not proof the address is wrong.
- Amap or a corrected Tencent pair may be able to geocode this address.

### Unverified

- Exact Rust Club GCJ-02 coordinate.
- Whether Tencent key/SK in the current process is the newest console key pair.
- Whether the poster phone field should be stored anywhere. Current decision: do not copy it into reports/registry.
- Whether the `59` older active registry rows are all still latest; freshness audit says they require external recheck before claiming all addresses are latest.

## 4. Work Performed

Changed or added:

- `apps\weekly_activity_miniprogram\utils\format.js`
- `apps\weekly_activity_miniprogram\pages\detail\detail.js`
- `apps\weekly_activity_miniprogram\tests\format-quality.test.cjs`
- `apps\weekly_activity_miniprogram\tests\detail-map-location.test.cjs`
- `tools\stage7_rewrite\scripts\audit_weekly_coordinate_freshness_queue.py`
- `tools\stage7_rewrite\tests\test_audit_weekly_coordinate_freshness_queue.py`
- `tools\stage7_rewrite\registries\weekly_venues_seed.json`
- `package.json`
- `reports\WEEKLY_TAXI_GRADE_COORDINATE_REGISTRY_GATE_S42_20260531.md`
- `reports\WEEKLY_RUST_CLUB_USER_ADDRESS_CANDIDATE_S45_20260531.md`

Important artifacts:

- `tools\stage7_rewrite\reports\weekly_venue_registry_geo_coverage_s44_after_solidify_20260531\weekly_venue_registry_geo_coverage.json`
- `tools\stage7_rewrite\reports\weekly_coordinate_freshness_queue_s44_after_solidify_20260531\weekly_coordinate_freshness_queue.json`
- `tools\stage7_rewrite\reports\weekly_coordinate_quality_audit_s44_after_solidify_20260531\weekly_coordinate_quality_audit.json`
- `tools\stage7_rewrite\reports\rust_club_user_address_tencent_probe_s45_20260531\report.json`
- `tools\stage7_rewrite\reports\rust_club_user_address_tencent_probe_s45_20260531\provider_results.jsonl`

Registry rows solidified from current trusted data:

- `abyss_shanghai`
- `bar_sos_chongqing`
- `ccr_chengdu`
- `gum_guangzhou`

## 5. Verification Status

Passed:

- `node apps\weekly_activity_miniprogram\tests\format-quality.test.cjs`
- `node --test apps\weekly_activity_miniprogram\tests\detail-map-location.test.cjs apps\weekly_activity_miniprogram\tests\ra-entity-navigation.test.cjs` -> `12` passed
- `node --check apps\weekly_activity_miniprogram\utils\format.js`
- `node --check apps\weekly_activity_miniprogram\pages\detail\detail.js`
- `python -m pytest tools\stage7_rewrite\tests\test_audit_weekly_coordinate_freshness_queue.py tools\stage7_rewrite\tests\test_audit_weekly_venue_registry_geo_coverage.py tools\stage7_rewrite\tests\test_audit_weekly_coordinate_quality.py -q` -> `9` passed
- `python -m pytest tools\stage7_rewrite\tests\test_weekly_registries.py tools\stage7_rewrite\tests\test_audit_weekly_coordinate_freshness_queue.py tools\stage7_rewrite\tests\test_audit_weekly_venue_registry_geo_coverage.py tools\stage7_rewrite\tests\test_audit_weekly_coordinate_quality.py -q` -> `15` passed
- `npm run weekly:venue-registry-geo:audit -- --report-dir tools\stage7_rewrite\reports\weekly_venue_registry_geo_coverage_s44_after_solidify_20260531`
- `npm run weekly:coordinate-freshness:audit -- --out-dir tools\stage7_rewrite\reports\weekly_coordinate_freshness_queue_s44_after_solidify_20260531`
- `npm run weekly:coordinate-quality:audit -- --out-dir tools\stage7_rewrite\reports\weekly_coordinate_quality_audit_s44_after_solidify_20260531`

Failed or blocked:

- Rust Club Tencent provider probe still returned `111`; accepted geocodes `0`.
- Freshness audit is still `safe_to_claim_all_latest=false` because Rust Club is missing and `59` active registry rows predate `2026-05-22`.

Not run:

- No Amap provider probe in this slice; Windows env did not expose Amap key.
- No production deploy/upload/review.
- No DB1/DB2/DB3 mutation.

## 6. Current Blocker

The current blocker is Rust Club coordinate acceptance. The user supplied a plausible address from poster evidence, but Tencent verification in the current Windows environment fails with status `111`. This blocks writing taxi-grade coordinates because provider acceptance and reverse confirmation are required before a user-facing navigation coordinate can be exposed.

Unblocks:

- Correct Tencent WebService key/SK pair in process, or
- Amap WebService key configured in process, or
- Another trusted geocoder lane that returns a GCJ-02 coordinate plus reverse-address confirmation for the candidate address.

## 7. Next Best Entry

Open first:

`C:\code\githubstar\wechathtmldownload\reports\WEEKLY_RUST_CLUB_USER_ADDRESS_CANDIDATE_S45_20260531.md`

Then rerun the candidate with a working provider:

```powershell
python tools\stage7_rewrite\scripts\geocode_weekly_activity_places.py --current-json tools\stage7_rewrite\reports\rust_club_user_address_candidate_s45_20260531\rust_club_candidate_current.json --provider amap --limit 1 --sleep-ms 0 --out-dir tools\stage7_rewrite\reports\rust_club_user_address_amap_probe_s46_20260531
```

If Amap is not available, fix Tencent key/SK process configuration and rerun:

```powershell
python tools\stage7_rewrite\scripts\geocode_weekly_activity_places.py --current-json tools\stage7_rewrite\reports\rust_club_user_address_candidate_s45_20260531\rust_club_candidate_current.json --provider tencent --limit 1 --sleep-ms 0 --out-dir tools\stage7_rewrite\reports\rust_club_user_address_tencent_probe_s46_20260531
```

Only after accepted geocode plus reverse confirmation should the agent patch `weekly_venues_seed.json` and current release.

## 8. Warnings / Pitfalls

- Do not use the old Beijing/将台路 coordinate for Rust Club.
- Do not print key/SK values.
- Do not store the poster phone number unless the user explicitly asks for a public contact field and a privacy/product boundary is written.
- Do not claim all addresses are latest; current freshness audit explicitly says `safe_to_claim_all_latest=false`.
- Do not run repeated bulk geocoding; use one-row provider review for Rust and fixed registry reuse for normal publication.
- Do not mark the active goal complete while Rust coordinate and rendered DevTools coverage remain unresolved.

## 9. OpenHuman Import Status

- imported: yes
- namespace: `wechathtmldownload-atlas`
- source_id: `1780214973_9ffd33c5`
- chunk_ids: `24 chunks`
- reason if not imported:

## 10. HTML Companion Artifact Status

- html_path: `C:\code\githubstar\wechathtmldownload\docs\longrun\atlas-route-external-db-20260531\handoffs\HANDOFF_RUST_COORDINATE_LOOP_20260531_1608.html`
- opened: no
- reason if not produced or not opened: produced for next-agent review; not opened because the requested next step is background thread handoff.
