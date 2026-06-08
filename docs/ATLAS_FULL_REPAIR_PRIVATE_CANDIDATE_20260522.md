# Atlas Full Repair Private Candidate

Updated: 2026-05-22 03:01 CST

Project: `C:\code\githubstar\wechathtmldownload`

## Purpose

This document records the full repair candidate run after the first public-safe `atlas_serving.sqlite`.

This is intentionally a private repair candidate, not a public deploy artifact. It accepts `review_candidate` participant repairs to maximize coverage for quality review, but the DB is marked `deployable_public=0`.

## Artifacts

- Builder: `tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py`
- Test: `tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py`
- Private repair DB: `reports\atlas_serving_repair_full_private_20260522\atlas_serving.sqlite`
- Manifest: `reports\atlas_serving_repair_full_private_20260522\manifest.json`
- Summary: `reports\atlas_serving_repair_full_private_20260522\summary.md`
- Latest build logs:
  - `reports\atlas_serving_repair_full_private_20260522\build_full_repair_20260522-025619.out.log`
  - `reports\atlas_serving_repair_full_private_20260522\build_full_repair_20260522-025619.err.log`

## Build Mode

- `participant_acceptance`: `aggressive-private`
- `deployable_public`: `False`
- `review_candidates_included`: `True`
- source SQLite writes: `False`
- network calls: `False`
- LLM/model calls: `False`
- raw source URL columns copied: `False`
- archive HTML path columns copied: `False`

The builder now supports these modes:

- `strict`: public deploy candidate; accepts raw participants and `auto_candidate` participant repairs only.
- `balanced`: intermediate review candidate; accepts only high-confidence review participant repairs.
- `aggressive-private`: full private repair candidate; accepts all ready review participant repairs after noise filters. Do not deploy directly.

## Final Counts

Final run: `2026-05-22T02:56:26`

- Raw events scanned: `608,678`
- Performance events materialized: `538,034`
- DJ profiles: `55,791`
- DJ-event edges: `1,415,016`
- Directed DJ relation edges: `772,998`
- DJ-venue rollups: `109,705`
- DJ-org rollups: `324,151`
- Venue subjects: `6,067`
- Org/radio subjects: `23,444`
- Evidence refs: `115,963`
- Search documents: `623,336`
- Precomputed graph windows: `55,791`
- DB size: about `2.08 GB`
- Build elapsed: `248.042` seconds

## Delta Versus Strict Public Candidate

Strict public candidate:

- Performance events: `467,769`
- DJ profiles: `51,593`
- DJ-event edges: `1,104,301`
- Directed DJ relation edges: `611,140`
- Search documents: `547,374`
- Graph windows: `51,593`

Private full repair candidate adds:

- `+70,265` performance events
- `+4,198` DJ profiles
- `+310,715` DJ-event edges
- `+161,858` directed DJ relation edges
- `+75,962` search documents
- `+4,198` graph windows

Participant repair contribution:

- auto participant repairs: `71,022`
- private review participant repairs: `70,265`
- remaining `review_only` after aggressive-private: `2,649`
- remaining `not_ready`: `37,952`
- remaining `missing`: `25,776`
- product/noise events skipped: `4,267`

## Verification

Commands passed:

- `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py`
- `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py -q`
- Full private repair build with `--participant-acceptance aggressive-private`

DB metadata:

- `participant_acceptance=aggressive-private`
- `deployable_public=0`
- `raw_source_url_columns_copied=0`
- `archive_html_path_columns_copied=0`

Security checks:

- forbidden schema columns containing `source_url`, `archive_raw_html_path`, `raw_json`, or `article_uid`: `0`
- `evidence_ref.public_url_allowed != 0`: `0`
- public text hits for `mp.weixin`, `raw.html`, or `D:/`: `0`
- wine/alcohol/menu public search hits: `0`

Spot checks:

- `MaFoL` search top result: `dj / MaFoL`
- `MaFoL` private repair profile: `196` events, `76` source refs, `19` venue rollups, `138` collaborators, `39` org rollups
- `DaRou` private repair profile: `84` events, `31` source refs, `10` venue rollups, `38` collaborators, `13` org rollups
- `SHCR`, `BYYB`, `BAIHUI`, `CDCR` remain radio/media subjects, not DJ profiles
- Search latency spot check over mixed terms: min `0.452 ms`, p50 `9.46 ms`, max `35.333 ms`

## Interpretation

The strict public candidate remains the deployable baseline. The private full repair candidate is valuable for deeper local review because it recovers a large amount of DJ performance history that was stuck behind `review_candidate` participant inference.

The private candidate should be used to:

1. sample and score review-repaired events by source account, venue, DJ, and relation impact;
2. promote only high-confidence repair classes back into a future public `strict` or `balanced` build;
3. identify the remaining hard gaps: `25,776` missing, `37,952` not-ready, and `2,649` still review-only rows;
4. drive a small local-LLM or human-review batch only on high-value unresolved DJ/event rows.

Do not deploy this DB directly to `atlas.huaidj.club`.
