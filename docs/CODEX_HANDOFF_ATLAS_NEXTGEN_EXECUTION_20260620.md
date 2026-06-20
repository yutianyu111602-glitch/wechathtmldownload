# Codex Handoff — ATLAS Next-Gen Execution (Phases 2–4) — 2026-06-20

Continue the next-gen atlas build. Phase 1 is DONE; this doc is the full thinking +
exact steps for Phases 2–4 so you can execute without re-deriving anything.

Design: [ATLAS_NEXTGEN_DESIGN_20260620.md](ATLAS_NEXTGEN_DESIGN_20260620.md) ·
Step log: [CLAUDE_STEPLOG_ATLAS_20260620.md](CLAUDE_STEPLOG_ATLAS_20260620.md) ·
Pickup: [CLAUDE_HANDOFF_20260620.md](CLAUDE_HANDOFF_20260620.md).

## State (verified this session)
- **Phase 1 DONE** (commit `dbca8e1`): `tools/atlas_rebuild/build_atlas_serving_v2.py`
  → `atlas_serving_v2.sqlite` with unified `subject` (dj 12262 / venue 1562 / org 2888 /
  series 5666 = 22378) + per-type profiles, event_count, spans, resident/roster/edition counts,
  series→venue/organizer FKs, aliases. `--selftest` + `_validate` green.
- Sources: Stage3 `_fleet_14w_g5_80k_increment_20260620/merged/entities_resolved.sqlite`
  (`canonical_entity`, `resolved_event`, `event_participant`, `dj_b2b`, `dj_affiliation`,
  `event_source`, `alias`, `merge_queue`); Stage4 `…/merged/atlas_serving_candidate.sqlite`
  (`dj_relation_rollup` 199484, `dj_venue_rollup` 29843, `dj_org_rollup` 65528, `dj_bio_atom` 52671).
- **ID ALIGNMENT VERIFIED 100%**: every `src_dj_id/dst_dj_id/venue_id/org_id/dj_id` in the
  Stage4 rollups is already a v2 `subject_id` (e.g. `dj:$andy`, `venue:jar`, `org:jar`). So
  relations link directly to subjects with no remap. This is the key enabler for Phase 2.
- DB artifacts (`*.sqlite` under `_fleet_*`) are **regenerable, not committed**. Commit scripts only.
- Boundary: candidate-only — no prod DB write / CloudRun deploy / mini-program upload.
  `same_label` withdrawn; `b2b` preserved. G6 + daily delta still running; refresh off the
  newest accepted `merged/` when they land (`meta.generation`).
- **Codex Phase 4 slice DONE** (2026-06-20): `export_starmap_layout.py --source v2`
  now reads `atlas_serving_v2.sqlite` and emits `atlas.starmap.v2` layouts for six lenses:
  `b2b_universe`, `residency_map`, `label_roster`, `series`, `city`, `style`.
  `apps/atlas_starmap_web` loads `atlas_layout.<lens>.json` through a compact lens switcher.
  Verified outputs: B2B 1298/8000, residency 1500/4259, label 1500/3711, series 867/995,
  city 1126/4273, style 1308/8000. Web build green.
- **Codex Phase 3 geo slice DONE** (2026-06-20): `backfill_venue_geo.py` is wired into
  `npm run atlas:rebuild` as `atlas:v2:geo`. It reads only confirmed local geo sources
  (`current_release/current.json` + `mapLocationBook.js`) and fills null `venue_profile.geo_*`
  values. Current G5 v2 run: 68/1562 venues backfilled; `residency_map` contains 39 selected
  venue geo anchors and now projects those anchors from lat/lng.

## Phase 2 — unify relations (do this next)
Extend `build_atlas_serving_v2.py`: add `--serving <atlas_serving_candidate.sqlite>` and build a
`relation` table (skip if `--serving` absent so Phase 1 still standalone).
```sql
CREATE TABLE relation(
  relation_id TEXT PRIMARY KEY, src_subject_id TEXT, dst_subject_id TEXT, relation_type TEXT,
  weight REAL, same_event_count INTEGER, b2b_count INTEGER, label_zh TEXT,
  first_seen_at TEXT, last_seen_at TEXT, public_state TEXT, sample_evidence_json TEXT);
CREATE INDEX ix_relation_src ON relation(src_subject_id);
CREATE INDEX ix_relation_dst ON relation(dst_subject_id);
CREATE INDEX ix_relation_type ON relation(relation_type);
```
Populate (relation_id = `sha1(src|type|dst)[:16]`):
- `dj_relation_rollup` → type `b2b` if `b2b_count>0` else `collab`; weight=`relation_score`,
  same_event_count, b2b_count, label_zh=`relation_label_zh`, evidence=`sample_evidence_json`,
  first/last from the rollup. (DJ↔DJ; ~199k rows — fine.)
- `dj_venue_rollup` → `resident_at` (dj→venue); weight=`score`, same_event_count=`event_count`,
  label_zh="驻场/常演", first/last from rollup.
- `dj_org_rollup` → `signed_to` (dj→org); weight=`score`, evidence=`sample_evidence_json`,
  label_zh from `org_type`.
- `series_profile` → `held_at` (series→venue_subject_id) and `presented_by`
  (series→organizer_subject_id), weight=`edition_count`.
Then set `subject.relation_count` = degree per subject. Validate: every src/dst ∈ subject
(expected 100%), print per-type counts. Optionally add `observation(target_kind,target_id,
source_kind,source_ref_id,generation,confidence,observed_at)` for provenance (design §2.4) — can defer.
Verify: `--selftest` (extend the synthetic with a serving fixture), then real run; assert
`relation` non-empty + no dangling endpoints.

## Phase 3 — dimensions
- **Geo backfill (venues) DONE first slice:** `backfill_venue_geo.py` conservatively matches
  normalized venue name+city/address against `services/weekly_activity_cloudrun/data/current_release/current.json`
  and `apps/weekly_activity_miniprogram/utils/mapLocationBook.js`. It leaves nulls when unmatched,
  writes a report to `tools/atlas_rebuild/_starmap_out/venue_geo_backfill_report.json`, and is
  part of `atlas:rebuild`. Current run backfilled 68 venues; do not claim complete venue geo.
- **Styles:** build `style` + `subject_style` from `dj_profile.styles_json` (and event `genre`) —
  normalize the long noisy style lists (cap, dedup synonyms). Enables the 曲风光谱 lens / coloring.
- **Bio:** `dj_bio_atom` already in the serving candidate (52671 atoms, verbatim, EN+ZH). Carry it
  into the contract `subject/{urn}/bio` and the DJ detail panel (group by language, show source).

## Phase 4 — star map v2 (first slice done)
- `export_starmap_layout.py`: supports `--source v2 --serving-v2 <atlas_serving_v2.sqlite>`,
  `--lens`, and `--all-lenses`. It reads `subject` + `relation` and emits `atlas.starmap.v2`
  with `urn/type/facets/geo/styles`.
- Implemented lenses: `b2b_universe`, `residency_map`, `label_roster`, `series`, `city`, `style`.
  `residency_map` now projects venue anchors that have `geo` via lat/lng and keeps missing-geo
  anchors on a deterministic fallback shell.
- graph-ui (`apps/atlas_starmap_web`): compact lens switcher in the left workbench panel,
  static `atlas_layout.<lens>.json` loading with b2b fallback, v2 type fields, series detail,
  and edge colors for `held_at` / `presented_by`.
- Still pending inside Phase 4: richer per-edge event drill UI, time scrubber, search-to-focus,
  and optional real geo projection after Phase 3.
- Keep v1 (`atlas_starmap.layout.v1`, 1746 nodes) valid until v2 lands; app loads by `schemaVersion`.

## Run / refresh
```
npm run atlas:v2:selftest   # selftests (build_atlas_serving_v2 + export_starmap_layout)
npm run atlas:v2            # build atlas_serving_v2.sqlite — subjects + relations (Phase 1+2 DONE)
npm run atlas:v2:geo        # backfill vetted venue geo into the candidate v2 DB
npm run atlas:starmap       # regenerate all v2 lens layouts into the web app
npm run atlas:web           # build the atlas_starmap_web app
npm run atlas:rebuild       # all of the above, in order
# atlas_layout.json is kept as a b2b_universe compatibility copy.
```
When G6 / daily delta land, repoint `--stage3`/`--serving` to the newest accepted `merged/` and
re-run the chain; `meta.generation` should track which ramp produced the data.

## Gotchas
- IDs already aligned — do NOT add a remap layer. Use rollup ids as subject ids directly.
- Geo is still sparse: current G5 v2 backfills 68/1562 venues, and only 39 of the selected
  residency-map venue anchors have real geo. Missing venues intentionally remain null/fallback.
- `relation` for DJ↔DJ is ~199k rows; the star map must threshold (top by weight) per the existing
  `--min-score/--max-nodes/--max-edges` caps — don't dump all into the 3D scene.
- cbm MCP isn't wired into the Claude Code session; use its CLI:
  `codebase-memory-mcp.exe cli <tool> '<json>'` (strip the leading `level=info` log line).
- Commit scripts, not the `*.sqlite` artifacts. Two-commit style: `feat(atlas): …` then docs.
