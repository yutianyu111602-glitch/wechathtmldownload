# Claude Step Log — ATLAS Star Map + Weekly Mini-Program — 2026-06-20

Per-step handoff. Each step is independently verified and committed on `main`.
Companion to [CLAUDE_HANDOFF_20260620.md](CLAUDE_HANDOFF_20260620.md) (the architecture + pickup doc).

Run the star map: `npm --prefix apps/atlas_starmap_web run dev` (Vite 5173).
Regenerate data: `python tools/atlas_rebuild/export_starmap_layout.py --out _starmap_out/atlas_layout.json`
then copy to `apps/atlas_starmap_web/public/atlas_layout.json`. Validate any layout:
`python tools/atlas_rebuild/export_starmap_layout.py --validate <path>`.

---

## Step 1 — Weekly mini-program 5-issue fixes — commit `1f04c45`
**What:** venue 未来排期/往期演出 split; artist venue/collab dedup + accurate counts;
DJ history source-open routing + honest no-link state; real source titles + sorted date range.
**Why:** reported bugs (past events in future list, inflated/duplicated stats, history un-openable, "原文" titles).
**Key files:** `apps/weekly_activity_miniprogram/utils/atlasContract.js` (new),
`pages/venue/venue.{js,wxml}`, `pages/artist/artist.js`, `pages/source/source.{js,wxml}`,
`utils/sourceArticles.js`, `utils/i18n.js`, tests.
**Verify:** `npm run test:miniprogram` green (161→164).

## Step 2 — Star map P0+P1 — commit `eed2e59`
**What:** P0 projection `export_starmap_layout.py` (Stage4 serving → cbm `GraphData` layout,
numpy label-propagation communities + Fibonacci-sphere constellations); P1 forked cbm
`graph-ui` (react-three-fiber 3D) into `apps/atlas_starmap_web`, repointed to static
`/atlas_layout.json`, booted into the graph, music title.
**Why:** build the "星图" (3D star map) of the underground EDM scene; cbm graph-ui = the 3D shell,
atlas rebuild = the data engine (we don't need cbm's C engine/store).
**Key files:** `tools/atlas_rebuild/export_starmap_layout.py`, `apps/atlas_starmap_web/**`,
`docs/CLAUDE_HANDOFF_20260620.md`, `docs/ATLAS_STARMAP_FRONTEND_PLAN_20260620.md`,
`docs/CODEX_FRONTEND_ATLAS_DJ_WORKLOG_20260620.md`.
**First lens (B2B universe):** 1296 DJ nodes / 8000 edges / 88 communities (b2b 586 / collab 7414).
**Verify:** `--selftest`, `--validate`, `npm --prefix apps/atlas_starmap_web run build` green.
(Codex co-landed the music-aware NodeDetailPanel, evidence section, edge coloring, mobile drawer.)

## Step 3 — Venue (驻场) anchors — commit `53566fc`
**What:** merge `dj_venue_rollup` name variants → 250 venue nodes at the centroid of their DJs;
`resident_at` edges; venue-aware UI. Fixed a `load_venues` DB-handle leak (finally close).
**Why:** anchor scenes to clubs (multi-entity beyond DJ-DJ); unlock the 驻场 dimension.
**Key files:** `export_starmap_layout.py`, `apps/atlas_starmap_web/public/atlas_layout.json`,
`src/components/EdgeLines.tsx`, `src/components/NodeDetailPanel.tsx`.
**Result:** 1546 nodes (1296 DJ + 250 venue) / 10450 edges (+2450 resident_at).
**Verify:** selftest + validate + web build green.

## Step 4 — Handoff next-steps update — commit `1098188`
**What:** marked venues done, orgs as the quick repeat, in the handoff doc.

## Step 5 — Label/crew/promoter (厂牌) anchors — commit `8a0d43e`
**What:** merge `dj_org_rollup` → 200 org nodes at roster-DJ centroid; `signed_to` edges
carrying org evidence; org-aware UI (厂牌 chip, 关联DJ/类型/证据). `--no-orgs/--max-orgs`.
**Why:** add the 厂牌 dimension (labels/crews/promoters), mirroring venues.
**Key files:** `export_starmap_layout.py`, `apps/atlas_starmap_web/public/atlas_layout.json`,
`src/lib/types.ts` (org_type), `src/components/EdgeLines.tsx`, `src/components/NodeDetailPanel.tsx`.
**Result:** 1746 nodes (1296 DJ / 250 venue / 200 org) / 12733 edges
(b2b 586 / collab 7414 / resident_at 2450 / signed_to 2283).
**Verify:** selftest + validate + web build green.

## Step 6 — Next-gen serving v2 Phase 1: promote venue/org/series to first-class — commit `<this>`
**What:** `tools/atlas_rebuild/build_atlas_serving_v2.py` reads Stage3 `entities_resolved.sqlite`
(unified `canonical_entity` + `resolved_event` + `event_participant`) → `atlas_serving_v2.sqlite`
with a unified `subject` (dj/venue/org/series) + per-type profiles (dj/venue/org/series),
computed event_count, activity span (first/last seen), resident-DJ / roster / edition counts,
series→venue/organizer FKs, and aliases.
**Why:** Stage4 served DJ-only; venues/orgs were denormalized in DJ rollups, series unserved.
This is the biggest unlock (design doc Phase 1) for the multi-entity star map + contract.
**Key files:** `build_atlas_serving_v2.py` (the `.sqlite` is a regenerable artifact, not committed).
**Result:** 22378 subjects — dj 12262 / venue 1562 / org 2888 / series 5666. Real data e.g.
RIVER (长沙, 707 events, 489 resident DJs), SOLO Beijing (label, 525 roster),
series SOLO Rhythms (124 editions @ SOLO Beijing).
**Verify:** `--selftest` + in-build `_validate` (profile↔subject parity + FK integrity) green.
**Run:** `python tools/atlas_rebuild/build_atlas_serving_v2.py` (defaults: G5 Stage3 → merged/atlas_serving_v2.sqlite).

---

## Step 7 — Serving v2 Phase 2: unified typed relation table — commit `<this>`
**What:** `build_atlas_serving_v2.py` gains `--serving` + a `relation` table unifying the 3 DJ
rollups + series FKs: DJ↔DJ b2b/collab (undirected, canonical-ordered), DJ→venue `resident_at`,
DJ→org `signed_to`, series→venue `held_at`, series→org `presented_by`; `subject.relation_count` filled.
**Result:** **205592 relations** — collab 97526 / signed_to 65528 / resident_at 29843 / held_at 5370 /
presented_by 5109 / b2b 2216. `_validate`: 0 dangling endpoints, 0 self-relations.
**Verify:** `--selftest` + in-build `_validate` on real data green.

## Remaining (next agent — see CODEX_HANDOFF_ATLAS_NEXTGEN_EXECUTION_20260620.md)
0. **Phase 4 — point the star map at v2**: `export_starmap_layout.py --source v2` reads `subject`+`relation`,
   emits `atlas.starmap.v2` per-lens layouts (b2b_universe done; residency_map/label_roster/series/city/style);
   add a lens switcher in `apps/atlas_starmap_web`.
1. **Phase 3 — dimensions**: venue geo backfill (sparse; from weekly venue registry), styles taxonomy
   (`subject_style`), bio atoms into the contract/DJ panel.
- **Lens switcher** in the web app (B2B / 驻场地图(geo, schema has lat/lng) / 厂牌花名册 / 城市场景),
  with per-lens node/edge filtering (FilterPanel already toggles label/edge types).
- **Per-pair evidence**: clicking a connection shows that specific edge's events (now node-level aggregate).
- **Refresh off newer data** once G5 completes (`fleet_merge` → serving), then re-run the projection;
  bump `--max-nodes/--max-edges/--max-venues/--max-orgs` for density.
- Time scrubber (first_seen→last_seen), search-to-focus, neighborhood paging for perf.

## Constraints (kept all session)
No CloudRun deploy, no mini-program upload. Didn't touch running G5 / Sanji daily / 14w extraction.
cbm main = Codex's memory tool (we only borrowed `graph-ui`; its MCP isn't wired into this Claude
session — use its CLI `codebase-memory-mcp.exe cli <tool> '<json>'`). Mini-program UI style unchanged.
3D star map is a web app, not in the mini-program.
