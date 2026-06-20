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
- **Geo backfill (venues):** `venue_profile.geo_*` is sparse (attrs rarely carries geo). Backfill by
  (name, city) match from the weekly venue registry — `services/weekly_activity_cloudrun/data/current_release/`
  geocode/place data and `apps/weekly_activity_miniprogram/utils/mapLocationBook.js` /
  `tools/stage7_rewrite` geocode tables. Write a `backfill_venue_geo.py` that matches normalized
  venue name+city → lat/lng; leave nulls when unmatched. Needed for the residency-map lens.
- **Styles:** build `style` + `subject_style` from `dj_profile.styles_json` (and event `genre`) —
  normalize the long noisy style lists (cap, dedup synonyms). Enables the 曲风光谱 lens / coloring.
- **Bio:** `dj_bio_atom` already in the serving candidate (52671 atoms, verbatim, EN+ZH). Carry it
  into the contract `subject/{urn}/bio` and the DJ detail panel (group by language, show source).

## Phase 4 — star map v2 (the visible payoff)
- `export_starmap_layout.py`: add `--source v2 --serving-v2 <atlas_serving_v2.sqlite>` and a
  `--lens` arg. Read `subject` (all types) + `relation`; emit `atlas.starmap.v2` layout (design §4.5,
  has `urn/type/facets/geo`). Lenses = node/relation filter + layout:
  - `b2b_universe` (current; dj + b2b/collab; Louvain constellations)
  - `residency_map` (dj+venue; resident_at; venue by `venue_profile.geo` projection — needs Phase 3 geo)
  - `label_roster` (org+dj; signed_to; org-radial)
  - `series` (series+venue+org+dj; held_at/presented_by/part_of_series)
  - `city` (city super-clusters), `style` (color/cluster by dominant style)
- graph-ui (`apps/atlas_starmap_web`): add a lens dropdown (load `atlas_layout.<lens>.json` or one
  multi-lens file + client filter). Node detail panel already type-aware (dj/venue/org). Add series
  panel + bio atoms (DJ) + per-edge evidence drill (edge.evidence already in layout).
- Keep v1 (`atlas_starmap.layout.v1`, 1746 nodes) valid until v2 lands; app loads by `schemaVersion`.

## Run / refresh
```
python tools/atlas_rebuild/build_atlas_serving_v2.py            # Phase 1 (+Phase 2 once --serving wired)
python tools/atlas_rebuild/export_starmap_layout.py --source v2 # Phase 4 (once wired) -> copy to apps/atlas_starmap_web/public/
npm --prefix apps/atlas_starmap_web run build                   # verify
```
When G6 / daily delta land, repoint `--stage3`/`--serving` to the newest accepted `merged/` and
re-run the chain; `meta.generation` should track which ramp produced the data.

## Gotchas
- IDs already aligned — do NOT add a remap layer. Use rollup ids as subject ids directly.
- Geo sparse → residency-map lens needs Phase 3 backfill first.
- `relation` for DJ↔DJ is ~199k rows; the star map must threshold (top by weight) per the existing
  `--min-score/--max-nodes/--max-edges` caps — don't dump all into the 3D scene.
- cbm MCP isn't wired into the Claude Code session; use its CLI:
  `codebase-memory-mcp.exe cli <tool> '<json>'` (strip the leading `level=info` log line).
- Commit scripts, not the `*.sqlite` artifacts. Two-commit style: `feat(atlas): …` then docs.
