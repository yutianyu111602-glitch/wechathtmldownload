# Atlas Serving Read Model Production Run

Updated: 2026-05-22 02:55 CST

Project: `C:\code\githubstar\wechathtmldownload`

## Purpose

This document records the first full public-safe Atlas serving read model for the DJ-first graph product.

The important boundary: this is a production candidate artifact for serving, not a raw database publication. The private `atlas.sqlite`, recovered source URLs, archive raw HTML paths, and raw JSON stay dark.

## Artifacts

- Builder: `tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py`
- Test: `tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py`
- Serving DB: `reports\atlas_serving_read_model_20260522\atlas_serving.sqlite`
- Manifest: `reports\atlas_serving_read_model_20260522\manifest.json`
- Summary: `reports\atlas_serving_read_model_20260522\summary.md`
- Latest build logs:
  - `reports\atlas_serving_read_model_20260522\build_full_20260522-024334.out.log`
  - `reports\atlas_serving_read_model_20260522\build_full_20260522-024334.err.log`

## Final Full Build Counts

Final run: `2026-05-22T02:43:40`

- Raw events scanned: `608,678`
- Public-safe performance events materialized: `467,769`
- DJ profiles: `51,593`
- DJ-event edges: `1,104,301`
- Directed DJ relation edges: `611,140`
- DJ-venue rollups: `103,231`
- DJ-org rollups: `296,365`
- Venue subjects: `5,637`
- Org/radio subjects: `22,375`
- Evidence refs: `113,553`
- Search documents: `547,374`
- Precomputed graph windows: `51,593`
- Serving DB size: `1,803,362,304` bytes, about `1.72 GB`
- Full build elapsed: `222.72` seconds

## Critical Fixes During The Run

### Event ID Fullness Fix

The first full run exposed a serious false-fullness bug: `409,222` events were folded by the older `source_uid#evid` identity.

Fix: public event IDs now use a hashed stable ID from `source_article_uid + row_pk + evid + title/time/place`. This avoids raw article UID leakage and prevents massive event collapse.

Result after fix:

- `duplicate_event_ids_skipped`: `0`
- `performance_events`: increased from `135,236` to `469,940` before product-noise filtering
- final product-noise-filtered `performance_events`: `467,769`

### Product / Alcohol Noise Gate

A validation probe found `57` public search rows containing wine/alcohol/menu terms after the first full pass.

Fix: event-level product noise gate now blocks wine/menu/product text before events enter DJ history, search, or graph windows. This catches cases where the participant list contains a real DJ but the event is actually a wine/menu/product promotion.

Final validation:

- `events_skipped_product_noise`: `4,267`
- `wine_search_hits`: `0`

### Radio / Media Classification

User-confirmed radio/media terms are not DJs:

- `SHCR`
- `BYYB`
- `BAIHUI`
- `CDCR`

Final validation keeps these as `radio` subjects, not `dj` profiles:

- `SHCR`: radio, `1,042` events
- `BYYB`: radio, `135` events
- `BAIHUI`: radio, `99` events
- `CDCR`: radio, `159` events

## Final Verification

Commands passed:

- `python -m py_compile tools\stage7_rewrite\scripts\build_atlas_serving_read_model.py`
- `python -m pytest tools\stage7_rewrite\tests\test_build_atlas_serving_read_model.py -q`
- Full build with `--confirm-production-candidate RUN_ATLAS_SERVING_FULL --graph-window-limit 0 --force`

Full build process:

- stderr bytes: `0`
- source SQLite writes: `False`
- network calls: `False`
- LLM/model calls: `False`
- raw source URL columns copied: `False`
- archive HTML path columns copied: `False`

Security checks over serving DB:

- forbidden schema columns containing `source_url`, `archive_raw_html_path`, `raw_json`, or `article_uid`: `0`
- `evidence_ref.public_url_allowed != 0`: `0`
- public text hits for `mp.weixin`, `raw.html`, or `D:/`: `0`
- wine/alcohol/menu public search hits: `0`

Search / graph spot checks:

- `MaFoL` search top result: `dj / MaFoL`
- `MaFoL` profile: `149` events, `68` source refs, `18` venue rollups, `108` collaborators, `36` org rollups
- `MaFoL` graph window: present
- `DaRou` search top result: `dj / DaRou`
- `OIL`, `ALL`, `DADA`, `TAG`: searchable as venue/org surfaces
- `SHCR`, `BYYB`, `BAIHUI`, `CDCR`: searchable as radio/media surfaces

Search latency spot check over 10 mixed terms:

- min: `0.401 ms`
- p50: `1.163 ms`
- max: `42.303 ms`
- tokenizer: SQLite FTS5 `trigram`
- type selector required: `False`

## Production Boundary

This run did not deploy to the Singapore VPS or CloudRun. The produced artifact is ready for the next serving integration step, but public exposure still must pass the anti-scrape gate:

- Cloudflare proxy and Turnstile/session gate active
- Nginx rate limits and origin lock configured
- no bulk export endpoint
- graph API must return only capped windows from `graph_window_cache`
- detail API must return public rollups and hashed evidence refs only
- raw `atlas.sqlite`, URL sidecars, raw HTML paths, and review queues remain private

## Next Execution

1. Wire the Atlas graph API to `atlas_serving.sqlite` instead of raw `atlas.sqlite`.
2. Make the Chinese UI read from `search_document`, `dj_profile`, `dj_event`, `dj_relation_rollup`, `dj_venue_rollup`, `dj_org_rollup`, and `graph_window_cache`.
3. Run browser verification on `/atlas/graph`: one-box search, MaFoL profile, venue search, radio search, graph window load, pan/zoom/roam.
4. Only after local verification, copy the serving DB and server code to `atlas.huaidj.club` behind Cloudflare/Turnstile/Nginx gates.
5. Keep review-only repair rows private until a later local review batch promotes them.
