# Claude Handoff — Weekly Mini-Program fixes + ATLAS Star Map — 2026-06-20

Session covered **two tracks**. Both have working code on disk; the second was
advanced jointly with Codex. This doc is the single pickup point.

Related docs: [ATLAS_STARMAP_FRONTEND_PLAN_20260620.md](ATLAS_STARMAP_FRONTEND_PLAN_20260620.md) ·
[CODEX_FRONTEND_ATLAS_DJ_WORKLOG_20260620.md](CODEX_FRONTEND_ATLAS_DJ_WORKLOG_20260620.md) ·
[WEEKLY_MINIPROGRAM_ATLAS_FIELD_CONTRACT_20260620.md](WEEKLY_MINIPROGRAM_ATLAS_FIELD_CONTRACT_20260620.md) ·
[WEEKLY_MINIPROGRAM_FRONTEND_CONTRACT_20260619.md](WEEKLY_MINIPROGRAM_FRONTEND_CONTRACT_20260619.md)

---

## TRACK A — Weekly mini-program 5-issue fixes (DONE, staged)

App: `apps/weekly_activity_miniprogram`. The 5 reported issues + fixes:

1. **源文章标题全是"原文" / 日期范围错** → `utils/sourceArticles.js`: `titleFromRef`
   falls back to the event's own `title`/`title_original` (not `账号 原文`); subtitle
   dates now `.sort()`ed before forming the range. `1b`="源文章卡片日期范围错" (confirmed by user).
2. **未来排期混入过去活动** → `pages/venue/venue.js` + `venue.wxml`: new
   `partitionEventsByDate` splits **未来排期 / 往期演出** (header counts upcoming only);
   atlas historical merge no longer inflates the future list. Reuses existing styles.
3. **艺人统计不去重/数字夸大** → atlas DB fragments one venue/DJ across name variants.
   Frontend defensive merge `utils/atlasContract.js` (`mergeVenues`/`mergeCollaborators`/
   `mergeResidentDjs`), wired in `pages/artist/artist.js` (now fetches `/atlas/artist`
   with high limits — the `dj-profile` route hard-caps venueLimit:15 — and overrides
   `venueCount`/`collaboratorCount` from the merged lists). Cross-language aliases
   (OIL↔OIL油, 招待↔ZhaoDai) are left to the atlas rebuild.
4. **DJ历史演出打不开** → `pages/artist/artist.js` keeps `sourceRefId` on atlas events
   (was dropped → routed to the weekly resolver which 404s); `pages/source/source.js`
   stops treating `publicUrl` object as a URL (dead button) and shows an honest
   "no public link" note. Root: atlas evidence is `not_public` by design.
5. **彻底理清逻辑 + 参考RA** → see the two contract docs. UI style kept unchanged
   (user constraint); RA only informed structure (upcoming/past split, dedup, honesty).

Verify: `npm run test:miniprogram` (was 161 green after my changes; Codex later reported 164).
Status: **staged** (mostly). Note `utils/i18n.js` shows `MM` (Codex touched after my stage —
re-add before commit). New files: `utils/atlasContract.js`, `tests/atlas-contract.test.cjs`,
`pages/source/source.{js,wxml}`.

---

## TRACK B — ATLAS underground-electronic-music STAR MAP (星图)

### Decision history (important)
- Goal: a **good-looking, fun 3D "星图"** of the underground EDM scene, replacing the
  old ugly `atlas-universe-game`.
- Evaluated UI bases: **codegraph** (engine, no UI — out), **Understand-Anything**
  (React-Flow 2D dashboard), **codeflow** (1-file D3 2D). User first picked UA, then
  **pivoted to retrofitting cbm's `graph-ui`** because it's **react-three-fiber 3D +
  bloom** = the real "星图" look. cbm itself stays Codex's memory tool; we only borrow
  the `graph-ui` folder.
- **We do NOT need cbm's C engine / store / extractor.** The music graph already exists
  in the atlas rebuild serving DB. graph-ui just renders a precomputed static layout.

### Data flow
```
sanji 13万篇 → tools/atlas_rebuild G5 (VL extract) → Stage3 resolve → Stage4 serving sqlite
   serving = canonical_subject / dj_profile / performance_event / dj_event /
             dj_relation_rollup(b2b/同台,score,sample_evidence_json) / dj_venue_rollup /
             dj_org_rollup / evidence_ref
        │  (P0 projection)
   tools/atlas_rebuild/export_starmap_layout.py  → atlas_layout.json  (cbm GraphData shape)
        │
   apps/atlas_starmap_web (forked cbm graph-ui)  → static fetch /atlas_layout.json → 3D render
```

### P0 — projection (DONE) — `tools/atlas_rebuild/export_starmap_layout.py`
- Reads G4 serving `_fleet_14w_g4_40k_increment_20260620/merged/atlas_serving_candidate.sqlite`
  (8942 DJs, 140808 relations). numpy-only: weighted label-propagation communities +
  Fibonacci-sphere constellation layout; color by community, size by event_count.
- Output `atlas_layout.json`: nodes `{id,x,y,z,label,name,file_path:"星座NN/<dj>",size,color,
  dj_id,city,event_count,community,first_seen_at,last_seen_at}`, edges `{source,target,
  type:b2b|collab,score,same_event,label_zh,evidence:[{title,date,source_ref_id}]}`.
- First lens **B2B universe**: 1296 nodes / 8000 edges / 88 communities / b2b 586 / collab 7414.
- Run: `python export_starmap_layout.py --out _starmap_out/atlas_layout.json` ; self-check
  `--selftest` ; Codex added `--validate` contract guard. Copy output to
  `apps/atlas_starmap_web/public/atlas_layout.json`.

### P1 — graph-ui retrofit (DONE) — `apps/atlas_starmap_web` (canonical, in-repo)
- Forked from cbm `graph-ui` (React19 + react-three-fiber + drei + postprocessing + vite6).
- Repointed: `src/hooks/useGraphData.ts` fetches static `/atlas_layout.json` (no cbm server);
  `src/App.tsx` boots straight into the graph; title "ATLAS · 地下电子音乐星图".
- Codex closeout: `GraphTab.tsx` mobile = filter drawer + fullscreen inspector (desktop
  split-pane kept); `NodeDetailPanel.tsx` is music-aware (DJ city/演出/B2B/同台/星座 +
  证据 events); `EdgeLines.tsx` colors b2b=#f8c56a gold / collab=#38bdf8 teal (additive);
  `scripts/rendered-smoke.mjs` desktop+mobile canvas smoke.
- `src/lib/types.ts` extended with the music extras (dj_id/city/event_count/community + edge
  score/same_event/label_zh/evidence).
- Run: `npm --prefix apps/atlas_starmap_web run dev` (5173) or `run build` (verified green)
  then `run preview`. `npm install` already done.
- ⚠️ There is also a now-redundant scaffold at `C:/code/atlas-starmap` (my original copy
  before Codex moved it in-repo). Safe to delete.

### Verify (Codex-reported)
web build ✓ · rendered smoke ✓ (desktop+mobile canvas non-empty, detail opens) ·
layout contract 1296/8000/586/7414 ✓ · cloudrun static route 3/3 ✓ · miniprogram 164/164 ✓ ·
weekly API 114/114 ✓ · `git diff --check` ✓.

---

## Constraints (HONORED — keep honoring)
- No CloudRun deploy, no mini-program upload/review/release.
- Don't touch the running **G5** extraction, the **Sanji daily** thread, or 14w full extraction.
- cbm main install = Codex's memory tool — don't repurpose it; we only borrowed `graph-ui`.
- Mini-program UI style unchanged. No web-view for official-account articles (white screen).
- 3D star map is a **web** app, not inside the mini-program.

## Git / untracked status (was the recurring risk)
- Mini-program fixes: staged (re-add `utils/i18n.js`, `tests/format-quality.test.cjs` etc.
  that Codex touched post-stage).
- Star map: **staged this session** — 45 files (`apps/atlas_starmap_web` minus node_modules
  via its `.gitignore`, `export_starmap_layout.py`, the 3 docs). 0 node_modules staged.
- **Nothing committed.** Commit when ready, e.g. two commits:
  `feat(mp): atlas frontend contract + venue past/upcoming split + source open fix`
  and `feat(atlas): underground EDM 3D star map (graph-ui fork + B2B layout projection)`.

## Next steps
1. **Multi-entity graph (P2)** — VENUES DONE (commit `53566fc`): `export_starmap_layout.py`
   now merges `dj_venue_rollup` into 250 venue anchor nodes (centroid of their DJs) +
   `resident_at` edges; `NodeDetailPanel`/`EdgeLines` are venue-aware. Layout is now
   1546 nodes / 10450 edges. **Org/label (厂牌) is the quick repeat**: same pattern on
   `dj_org_rollup` → org nodes + `signed_to` edges + a 厂牌 chip in the detail panel.
2. **Lens switcher** in the web app (B2B / 驻场(geo) / 厂牌 / 城市场景). geo exists in schema.
3. **Per-pair evidence**: clicking a connection shows that edge's events (now aggregated at
   node level).
4. **Refresh data off newer generation** once G5 completes (`fleet_merge`→serving), then
   re-run the projection. Bump `--max-nodes/--max-edges` for richer fields.
5. Time scrubber (first_seen→last_seen), search-to-focus, neighborhood paging for perf.

## Using cbm (codebase-memory-mcp) for navigation
Its MCP server is NOT wired into this Claude Code session's tool registry (ToolSearch finds
no `trace_path`/`search_graph`). Use the **CLI** instead:
`C:/Users/pc/AppData/Local/Programs/codebase-memory-mcp/codebase-memory-mcp.exe cli <tool> '<json>'`
(strip the leading `level=info ...` log line before JSON-parsing). The whole repo is indexed
as project `C-code-githubstar-wechathtmldownload` (incl. `apps/atlas_starmap_web`). To make it
callable natively, add it to this session's MCP config.
