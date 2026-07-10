# ATLAS Starmap Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the WeChat Mini Program ATLAS page as a readable, full-screen universe exploration map whose node shapes, node mass, halos, evidence marks, and edge widths are grounded in ATLAS V2 fields.

**Architecture:** Keep the existing native 2D canvas and the existing graph/search/neighborhood/artist/path APIs. Extend the compact static bundle to carry the V2 metrics needed by the renderer, centralize visual encoding in small deterministic page helpers, and replace the oversized first-screen card with a three-state bottom sheet over a full-screen graph. City and time remain optional secondary lenses; structure is the default lens.

**Tech Stack:** WeChat Mini Program JavaScript/WXML/WXSS, Canvas 2D, Python 3 + SQLite read-only export, Node.js built-in test runner, WeChat DevTools automator.

## Global Constraints

- Work only in `C:\code\githubstar\wechathtmldownload` on the current `wip/rescue-20260605-160743` branch unless the user explicitly changes the target.
- Preserve the highly dirty worktree. Stage and commit only the files named in the current task; never use reset, clean, checkout-to-revert, or bulk staging.
- Keep all source and documentation writes in the primary controller. Repository policy permits subagents only as read-only scouts/reviewers unless the user explicitly authorizes a bounded exception.
- Open the ATLAS V2 SQLite source read-only. Do not migrate, seed, modify, vacuum, or replace any database.
- Use the authoritative source database at `tools\atlas_rebuild\_sandbox_entity_merge_apply_20260622_0045\atlas_serving_v2_enriched_merged.sqlite` for the final bundle regeneration.
- Do not add WebGL, Three.js, a graph library, or another dependency. Keep the base payload cap at 240 nodes and 640 edges and dynamic expansion at 18 nodes.
- Keep existing share URL compatibility: the query key remains `lens`, while page state uses `viewLens`.
- Preserve local/remote neighbor expansion, backtracking, related-type filters, shortest-path mode, share/focus restore, visited footprint, seed list, and artist detail navigation.
- No upload, deployment, review submission, release, production promotion, or database write is authorized by this plan.
- Local tests, rendered DevTools proof, developer upload, review, and public release are separate states and must be reported separately.

## File Structure

| Path | Role | Planned action |
|---|---|---|
| `tools/atlas_rebuild/export_mp_starmap_bundle.py` | Read-only V2-to-mini-bundle exporter | Add V2 metrics, edge weight, schema v2, paired JSON/JS writer, and stronger self-test |
| `apps/weekly_activity_miniprogram/data/atlas_starmap.json` | Inspectable compact bundle | Regenerate from the authoritative V2 database |
| `apps/weekly_activity_miniprogram/data/atlas_starmap.js` | Runtime bundle loaded by the mini program | Regenerate from the same serialized payload as JSON |
| `apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.js` | Graph state, interaction, and Canvas 2D rendering | Add deterministic visual helpers, semantic zoom, sheet/lens state, and integrate existing behavior |
| `apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.wxml` | Page composition | Replace large first-screen panels with command bar, tool rail, HUD, and progressive bottom sheet |
| `apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.wxss` | Page visual system | Implement dense mobile workbench styling and a maximum 45vh explore sheet |
| `apps/weekly_activity_miniprogram/tests/atlas-starmap-redesign.test.cjs` | Focused redesign contract tests | Create deterministic data, rendering, state, markup, and compatibility tests |
| `apps/weekly_activity_miniprogram/tests/atlas-search-and-starmap-l1.test.cjs` | Existing Atlas L1 regression | Update only assertions affected by the approved shell/state changes |
| `apps/weekly_activity_miniprogram/tests/devtools-atlas-neighborhood-rendered.cjs` | Real DevTools rendered proof | Assert the new state and capture the redesigned page |
| `docs/current-runtime.md` | Current runtime truth | Record only verified local source/test/render state after proof exists |

---

## Task 1: Upgrade the Compact Bundle to the ATLAS V2 Visual Contract

**Files:**

- Modify: `tools/atlas_rebuild/export_mp_starmap_bundle.py:157-286`
- Regenerate: `apps/weekly_activity_miniprogram/data/atlas_starmap.json`
- Regenerate: `apps/weekly_activity_miniprogram/data/atlas_starmap.js`

### 1.1 Write the failing exporter self-test

- [ ] Expand the temporary `subject` table with `relation_count`, `source_count`, `first_seen_at`, and `last_seen_at`.
- [ ] Insert deterministic metric values for all six retained subjects.
- [ ] Pass both the JSON output path and its `.js` sibling into `build`.
- [ ] Replace the v1 assertion with this contract:

```python
assert b["schemaVersion"] == "atlas.mp.starmap.v2"
assert b["counts"] == {"nodes": 6, "edges": 5}
assert all({"ec", "rc", "sc", "fs", "ls"} <= set(node) for node in b["nodes"])
assert all(len(edge) == 4 and isinstance(edge[3], (int, float)) for edge in b["edges"])
assert json.loads(Path(js_out).read_text(encoding="utf-8").removeprefix("module.exports = ").removesuffix(";\n")) == b
```

- [ ] Retain the synthetic B2B/TBA compound-subject exclusion and coordinate assertions.

### 1.2 Run the test and confirm it fails for the missing v2 contract

Run:

```powershell
python tools\atlas_rebuild\export_mp_starmap_bundle.py --selftest
```

Expected: non-zero exit caused by the v1 schema or missing `ec`/`rc`/`sc`/`fs`/`ls` fields. A database-open or import error is not the expected failure and must be fixed before continuing.

### 1.3 Implement paired bundle serialization

- [ ] Add one writer so JSON and runtime JavaScript cannot drift:

```python
def write_bundle_outputs(out_path, bundle, out_js_path=None):
    out = Path(out_path)
    js_out = Path(out_js_path) if out_js_path else out.with_suffix(".js")
    payload = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(payload + "\n", encoding="utf-8")
    js_out.write_text("module.exports = " + payload + ";\n", encoding="utf-8")
    return out, js_out
```

- [ ] Change `build` to accept `out_js_path=None` and call `write_bundle_outputs` instead of writing JSON directly.
- [ ] Add CLI option `--out-js`; default behavior must still derive the `.js` path from `--out`.

### 1.4 Export the required V2 node and edge fields

- [ ] Replace the subject query with:

```sql
SELECT subject_id, subject_type, display_name, city_primary,
       COALESCE(event_count, 0) AS event_count,
       COALESCE(relation_count, 0) AS relation_count,
       COALESCE(source_count, 0) AS source_count,
       first_seen_at, last_seen_at
FROM subject
```

- [ ] Add compact node keys without removing the legacy `s` fallback:

```python
"ec": int(m["event_count"] or 0),
"rc": int(m["relation_count"] or 0),
"sc": int(m["source_count"] or 0),
"fs": (m["first_seen_at"] or ""),
"ls": (m["last_seen_at"] or ""),
```

- [ ] Preserve the first three edge positions and append rounded relation weight:

```python
edges = [[ia, ib, relation_type, round(weight, 3)]
         for _, weight, ia, ib, relation_type in candidates[:max_edges]]
```

- [ ] Change only the schema version to `atlas.mp.starmap.v2`; keep `lens`, `generation`, and `counts` compatible.
- [ ] Update `_layout` edge unpacking so it accepts four-element edges without losing the existing layout behavior.

### 1.5 Run the exporter self-test and syntax check

Run:

```powershell
python tools\atlas_rebuild\export_mp_starmap_bundle.py --selftest
python -m py_compile tools\atlas_rebuild\export_mp_starmap_bundle.py
```

Expected: `selftest OK`; both commands exit 0.

### 1.6 Regenerate both runtime artifacts from the authoritative read-only DB

Run:

```powershell
python tools\atlas_rebuild\export_mp_starmap_bundle.py `
  --v2 tools\atlas_rebuild\_sandbox_entity_merge_apply_20260622_0045\atlas_serving_v2_enriched_merged.sqlite `
  --out apps\weekly_activity_miniprogram\data\atlas_starmap.json `
  --out-js apps\weekly_activity_miniprogram\data\atlas_starmap.js `
  --max-nodes 240 `
  --max-edges 640
```

Expected: exactly 240 nodes and at most 640 edges; both files are written from one payload.

### 1.7 Validate runtime and inspectable bundles are identical

Run:

```powershell
node -e "const fs=require('fs');const j=JSON.parse(fs.readFileSync('apps/weekly_activity_miniprogram/data/atlas_starmap.json','utf8'));const m=require('./apps/weekly_activity_miniprogram/data/atlas_starmap.js');if(JSON.stringify(j)!==JSON.stringify(m))throw Error('bundle drift');if(j.schemaVersion!=='atlas.mp.starmap.v2')throw Error('schema');if(j.nodes.length!==240||j.edges.length>640)throw Error('caps');if(!j.nodes.every(n=>['ec','rc','sc','fs','ls'].every(k=>k in n)))throw Error('node metrics');if(!j.edges.every(e=>e.length===4&&Number.isFinite(e[3])))throw Error('edge weights');console.log(j.counts)"
```

Expected: prints the node/edge counts and exits 0.

### 1.8 Commit only the exporter and generated pair

```powershell
git add tools/atlas_rebuild/export_mp_starmap_bundle.py apps/weekly_activity_miniprogram/data/atlas_starmap.json apps/weekly_activity_miniprogram/data/atlas_starmap.js
git diff --cached --check
git commit -m "feat(atlas): export v2 starmap metrics"
```

---

## Task 2: Encode V2 Metrics in Deterministic Canvas Visuals

**Files:**

- Create: `apps/weekly_activity_miniprogram/tests/atlas-starmap-redesign.test.cjs`
- Modify: `apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.js:120-1010`

### 2.1 Create a focused Page harness and failing visual tests

- [ ] Load the page by capturing the object passed to `global.Page`, matching the existing L1 harness.
- [ ] Stub only `wx.showToast`, `wx.navigateTo`, `wx.getStorageSync`, and `wx.setStorageSync` required during isolated method tests.
- [ ] Add assertions for these exact contracts:

```javascript
assert.equal(page._metricScore(0, 115), 0);
assert.equal(page._metricScore(115, 115), 1);
assert.equal(page._zoomTierForScale(0.8), "overview");
assert.equal(page._zoomTierForScale(1.5), "neighborhood");
assert.equal(page._zoomTierForScale(2.6), "detail");

const dj = page._nodeVisual({ t: "dj", ec: 115, rc: 284, sc: 101, s: 1 });
assert.equal(dj.shape, "circle");
assert.equal(dj.color, "#7FD4FF");
assert.equal(dj.radius, 9);
assert.equal(dj.haloGap, 7);
assert.equal(dj.haloRings, 3);
assert.equal(dj.evidenceTicks, 8);

assert.equal(page._nodeVisual({ t: "venue", ec: 1, rc: 1, sc: 1 }).shape, "hexagon");
assert.equal(page._nodeVisual({ t: "org", ec: 1, rc: 1, sc: 1 }).shape, "diamond");
assert.equal(page._nodeVisual({ t: "series", ec: 1, rc: 1, sc: 1 }).shape, "ring");

const edge = page._edgeVisual([0, 1, "collab", 585], true);
assert.equal(edge.lineWidth, 2.45);
assert.equal(edge.color, "rgba(127,212,255,0.68)");
assert.deepEqual(page._edgeVisual([0, 1, "signed_to", 10], true).dash, [3, 2]);
```

- [ ] Add a compatibility assertion showing a node with only legacy `s` still gets a finite radius between 3.5 and 9.
- [ ] Add a ranking assertion that event and relation metrics both affect `_labelRank`.
- [ ] Add a duplicate-name assertion showing `OIL` DJ and `OIL` venue labels include their entity types.

### 2.2 Run the focused test and confirm the helpers are absent

Run:

```powershell
node --test apps\weekly_activity_miniprogram\tests\atlas-starmap-redesign.test.cjs
```

Expected: non-zero exit because `_metricScore`, `_nodeVisual`, `_edgeVisual`, and `_zoomTierForScale` do not exist.

### 2.3 Add visual constants and pure helpers

- [ ] Add explicit constants near the current type/relation constants:

```javascript
var TYPE_VISUAL = {
  dj: { shape: "circle", color: "#7FD4FF" },
  venue: { shape: "hexagon", color: "#FFCF6B" },
  org: { shape: "diamond", color: "#B794F6" },
  series: { shape: "ring", color: "#2DD4BF" },
};
var EVENT_P99 = 115;
var RELATION_P99 = 284;
var SOURCE_THRESHOLDS = [1, 8, 101];
var EDGE_WEIGHT_P99 = 585;
var RELATION_VISUAL = {
  b2b: { color: "255,207,107", dash: [] },
  collab: { color: "127,212,255", dash: [] },
  resident_at: { color: "45,212,191", dash: [] },
  held_at: { color: "45,212,191", dash: [] },
  signed_to: { color: "183,148,246", dash: [3, 2] },
  presented_by: { color: "183,148,246", dash: [3, 2] },
};
```

- [ ] Implement `_metricScore(value, p99)` as `clamp(log1p(value) / log1p(p99), 0, 1)`.
- [ ] Implement `_nodeVisual(node)` with:
  - radius `3.5 + 5.5 * eventScore`, rounded to three decimals;
  - halo gap `3 + 4 * relationScore`, rounded to three decimals;
  - one base halo, a second ring at `rc >= 36`, and a third ring at `rc >= 284`;
  - evidence ticks `0`, `2`, `4`, or `8` at source counts `0`, `1`, `8`, and `101`;
  - legacy radius fallback derived from `s` when `ec` is absent.
- [ ] Implement `_edgeVisual(edge, highlighted)` with weight score `log1p(weight) / log1p(585)`, base width `0.35 + 1.65 * score`, and `+0.45` only for highlighted one-hop edges. It returns relation-specific color and dash values from `RELATION_VISUAL`, using a restrained slate fallback for unknown relation types.
- [ ] Implement `_labelRank(node)` as `0.55 * eventScore + 0.45 * relationScore`.
- [ ] Implement `_zoomTierForScale(scale)` with thresholds `<1.2`, `<2.2`, and `>=2.2`.
- [ ] Build a normalized-name-to-types index once during `onLoad`. Implement `_nodeLabel(node)` so only cross-type duplicate names append ` · DJ`, ` · 场地`, ` · 厂牌`, or ` · 系列`.
- [ ] Do not read or encode `confidence` as a global visual dimension.

### 2.4 Draw entity shapes, metric halos, evidence ticks, weighted edges, and ranked labels

- [ ] Preserve the static deep-space background, but remove time-based twinkling from normal drawing.
- [ ] Draw city halos only when the city lens is active.
- [ ] Replace hardcoded relation widths with `_edgeVisual` and use the fourth edge item as weight; default missing weight to `1`.
- [ ] Add one small shape-path helper used by both fill and stroke operations:
  - circle for DJ;
  - six-point polygon for venue;
  - four-point diamond for org;
  - hollow circular ring for series.
- [ ] Render relation halos outside the core and evidence ticks only for the selected node or in detail zoom.
- [ ] Use `#A7FF26` only for the selected static ring and actionable focus marks.
- [ ] Select overview labels by descending `_labelRank`, then reject screen-space overlaps with a small bounding-box test. Always show the selected label.
- [ ] Draw accepted labels on an opaque near-black background with a one-pixel border, using `_nodeLabel` so cross-type duplicates never appear as a bare name.
- [ ] Keep off-neighborhood nodes and edges subdued but visible enough to preserve global structure.

### 2.5 Preserve edge weights during page initialization and expansion

- [ ] Change base edge copying from three items to four:

```javascript
this._edges = ((bundle && bundle.edges) || []).map(function (edge) {
  return [edge[0], edge[1], edge[2], Number(edge[3]) || 1];
});
```

- [ ] Ensure `_appendEdge` stores remote neighbor weight in the same fourth position.
- [ ] Keep dynamic neighbors without `ec`/`rc`/`sc` on the explicit legacy `s` and neighbor `w`/`rs` fallback path; do not synthesize V2 counts for them.
- [ ] Keep `_rebuildAdj`, path highlighting, and existing relation-type behavior compatible with the first three positions.
- [ ] Add `_scheduleDraw` to coalesce touch-pan and pinch redraws into one `requestAnimationFrame`; `onTouchMove` must update scalar transform state and schedule a draw without allocating replacement node/edge arrays.

### 2.6 Run focused tests and JavaScript syntax validation

```powershell
node --test apps\weekly_activity_miniprogram\tests\atlas-starmap-redesign.test.cjs
node --check apps\weekly_activity_miniprogram\pages\atlas-starmap\atlas-starmap.js
```

Expected: both commands exit 0.

### 2.7 Commit the focused tests and canvas encoding

```powershell
git add apps/weekly_activity_miniprogram/tests/atlas-starmap-redesign.test.cjs apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.js
git diff --cached --check
git commit -m "feat(atlas): encode v2 graph visuals"
```

---

## Task 3: Replace the Oversized Card with a Progressive Exploration Shell

**Files:**

- Modify: `apps/weekly_activity_miniprogram/tests/atlas-starmap-redesign.test.cjs`
- Modify: `apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.js:120-1168`
- Modify: `apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.wxml:1-145`
- Modify: `apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.wxss:1-106`

### 3.1 Add failing shell and state tests

- [ ] Assert initial page data contains:

```javascript
assert.equal(page.data.sheetState, "hidden");
assert.equal(page.data.viewLens, "structure");
assert.equal(page.data.zoomTier, "overview");
assert.equal(page.data.toolPanel, "");
```

- [ ] Assert valid sheet transitions `hidden -> peek -> explore -> peek` and reject unknown states by normalizing them to `hidden`.
- [ ] Assert selecting a node sets `sheetState` to `peek`, clearing selection sets it to `hidden`, and starting path mode hides the sheet.
- [ ] Assert `_updateSelected` exposes real `eventCount`, `relationCount`, `sourceCount`, `firstSeen`, and `lastSeen` values plus presence flags, while dynamic nodes with missing fields keep those rows hidden.
- [ ] Add static WXML assertions for `sm-command`, `sm-tool-rail`, `sm-hud`, and `sm-sheet-{{sheetState}}`.
- [ ] Assert the old `data-lens="future"` and `data-lens="dj_traj"` controls are absent.
- [ ] Add WXSS assertions for `.sm-sheet-explore` and `max-height:45vh`.

### 3.2 Run the focused test and confirm shell contracts fail

```powershell
node --test apps\weekly_activity_miniprogram\tests\atlas-starmap-redesign.test.cjs
```

Expected: non-zero exit because the new state and shell classes are absent.

### 3.3 Add the four explicit UI state fields and handlers

- [ ] Add `sheetState`, `viewLens`, `zoomTier`, and `toolPanel` to page data.
- [ ] Implement:

```javascript
setSheetState: function (state) {
  var next = state === "peek" || state === "explore" ? state : "hidden";
  this.setData({ sheetState: next });
},
toggleExploreSheet: function () {
  this.setSheetState(this.data.sheetState === "explore" ? "peek" : "explore");
},
toggleToolPanel: function (event) {
  var panel = event.currentTarget.dataset.panel || "";
  this.setData({ toolPanel: this.data.toolPanel === panel ? "" : panel });
},
```

- [ ] Integrate transitions into existing methods:
  - `selectNode` -> `peek`;
  - `clearSel` -> `hidden`;
  - `startPathMode` -> `hidden`;
  - path result completion -> `peek` when a selected node still exists;
  - related-node focus and trail-back -> `peek`;
  - reset/fit-all -> `hidden`.
- [ ] Update `zoomTier` only after scale changes in pinch, fly-to ticks, and fit-all.

### 3.4 Recompose WXML into four layers

- [ ] Keep the canvas first and full-screen.
- [ ] Add a compact top command bar with ATLAS title/status, search input, search action, and a clear focus action.
- [ ] Add a right tool rail for structure/city/time lenses, entity filters, random hop, fit-all, and path mode status.
- [ ] Move type and city legends into conditional tool panels rather than occupying the first screen.
- [ ] Keep a compact HUD for visible node count, visited count, current lens, zoom tier, and path hint.
- [ ] Replace the current large selected card with one bottom sheet:
  - `hidden`: not rendered into the interaction surface;
  - `peek`: name, type, city, event/relation/source metrics, trail summary, and one expand affordance;
  - `explore`: maximum 45vh, scrollable related entities, filters, inspector summary, share/path/artist actions;
  - detailed neighbor and inspector blocks render only in `explore`.
- [ ] In `_updateSelected`, map `ec`/`rc`/`sc`/`fs`/`ls` into the selected view model with `hasEventCount`, `hasRelationCount`, `hasSourceCount`, and `hasTimeRange` flags. Do not display missing fields as zero.
- [ ] Keep relation evidence summaries such as relation score/count in explore rows when the existing neighbor/inspector payload provides them; do not print evidence across the canvas.
- [ ] Keep existing action handler names where possible so existing behavior remains wired.

### 3.5 Implement the approved mobile workbench visual system

- [ ] Use a near-black opaque surface and restrained one-pixel borders; no glass blur, gradient cards, or heavy shadows.
- [ ] Use 8/12/16rpx spacing rhythm, 22-24rpx body text, 28-30rpx key entity names, 18-20rpx supporting text, and 8-14rpx control radii.
- [ ] Keep every primary touch target at least 72rpx in both dimensions; the explore sheet may use an 18-24rpx top radius.
- [ ] Give the command bar and tool rail safe-area-aware positioning.
- [ ] Set `.sm-sheet-explore { max-height: 45vh; }` and make only its detail body scroll.
- [ ] Use `#A7FF26` for active controls and selection; preserve type colors for data meaning.
- [ ] Add explicit pressed, disabled, and selected states for touch clarity.

### 3.6 Run focused tests and syntax validation

```powershell
node --test apps\weekly_activity_miniprogram\tests\atlas-starmap-redesign.test.cjs
node --check apps\weekly_activity_miniprogram\pages\atlas-starmap\atlas-starmap.js
```

Expected: both commands exit 0.

### 3.7 Commit the interaction shell

```powershell
git add apps/weekly_activity_miniprogram/tests/atlas-starmap-redesign.test.cjs apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.js apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.wxml apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.wxss
git diff --cached --check
git commit -m "feat(atlas): add progressive exploration shell"
```

---

## Task 4: Add Secondary City and Time Lenses Without Weakening Structure

**Files:**

- Modify: `apps/weekly_activity_miniprogram/tests/atlas-starmap-redesign.test.cjs`
- Modify: `apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.js:760-1168`
- Modify: `apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.wxml:1-145`

### 4.1 Add failing lens, time, and share compatibility tests

- [ ] Assert `setViewLens` accepts only `structure`, `city`, and `time`; all other inputs resolve to `structure`.
- [ ] Assert city emphasis is false when `node.c` is empty and true only in the city lens for a known city.
- [ ] Assert time metadata is empty if both `fs` and `ls` are empty and returns a bounded year range for valid timestamps.
- [ ] Assert time alpha is finite and clamped to `[0.25, 1]`.
- [ ] Assert missing city/time values are omitted from peek/explore markup instead of rendering `0`, `未知城市`, or a guessed city.
- [ ] Assert `_shareQueryParts()` serializes the internal `viewLens` as the existing URL query key `lens`.
- [ ] Assert `onLoad({ lens: "city" })` restores `viewLens: "city"` while an old value such as `entity` restores `structure`.
- [ ] Assert selecting and sharing by `focusId` remains unchanged.

### 4.2 Run the focused test and confirm missing lens behavior

```powershell
node --test apps\weekly_activity_miniprogram\tests\atlas-starmap-redesign.test.cjs
```

Expected: non-zero exit because the view-lens helpers and compatibility mapping do not exist.

### 4.3 Implement bounded secondary-lens helpers

- [ ] Implement `setViewLens(event)` and `_normalizeViewLens(value)`.
- [ ] Implement `_cityHaloVisible(node)` so an unknown city never gets a guessed city or halo.
- [ ] Implement `_timeRangeLabel(node)` from `fs` and `ls`, using years only in the canvas/HUD and leaving full timestamps to inspector data.
- [ ] Implement `_nodeAlphaForLens(node)`:
  - structure: `1`;
  - city: `1` for nodes with a known city and `0.28` for unknown city;
  - time: map valid `ls` recency into `[0.35, 1]`, use `0.25` when time is absent.
- [ ] Keep node shape, node size, relation halo, and edge width unchanged across lenses.

### 4.4 Integrate semantic zoom and lens drawing

- [ ] Overview: cap ranked labels, hide evidence ticks, show the global structure.
- [ ] Neighborhood: show selected one-hop labels, type shapes, and selected metric summary.
- [ ] Detail: show evidence ticks and more labels without allowing labels to overlap the selected sheet.
- [ ] City lens: render only evidence-backed city halos and the current city legend panel.
- [ ] Time lens: vary node opacity by last-seen recency and show first/last year in the peek/explore sheet; do not add continuous blinking.
- [ ] Z2 detail labels may add a short relation type, known city, or time range, but never show missing data or cover the active bottom sheet.
- [ ] Remove the always-running `_startAnim` call from node selection. Keep requestAnimationFrame only for bounded fly-to transitions.

### 4.5 Preserve URL compatibility and load restoration

- [ ] Parse `query.lens` during `onLoad` and map legacy `entity` to `structure`.
- [ ] Change `_shareQueryParts` to read `this.data.viewLens` while continuing to emit `lens=<value>`.
- [ ] Keep `q` and `focusId` serialization/restoration unchanged.

### 4.6 Run focused tests and syntax validation

```powershell
node --test apps\weekly_activity_miniprogram\tests\atlas-starmap-redesign.test.cjs
node --check apps\weekly_activity_miniprogram\pages\atlas-starmap\atlas-starmap.js
```

Expected: both commands exit 0.

### 4.7 Commit secondary lenses and semantic zoom

```powershell
git add apps/weekly_activity_miniprogram/tests/atlas-starmap-redesign.test.cjs apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.js apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.wxml
git diff --cached --check
git commit -m "feat(atlas): add semantic graph lenses"
```

---

## Task 5: Reconcile Existing Atlas Contracts and Run the Full Local Regression

**Files:**

- Modify: `apps/weekly_activity_miniprogram/tests/atlas-search-and-starmap-l1.test.cjs:63-334`
- Modify only if a real regression requires it: `apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.js`
- Modify only if a real regression requires it: `apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.wxml`

### 5.1 Update only obsolete L1 expectations

- [ ] Replace assertions tied to the old `entity/future/dj_traj` tab strip with `structure/city/time` and progressive-sheet assertions.
- [ ] Update harness page data to include `viewLens`, `sheetState`, `zoomTier`, and `toolPanel` where a called method reads them.
- [ ] Keep all existing assertions for:
  - local and remote neighbor expansion;
  - exactly bounded related previews;
  - related entity filtering;
  - trail forward/back navigation;
  - artist inspector loading/fallback;
  - path mode and path result;
  - focusId share/restore;
  - artist navigation with `subjectId`.
- [ ] Add explicit failure-path assertions that a remote neighborhood failure preserves local rows, an inspector failure preserves node metrics/actions, and a path API failure preserves the current selection and camera state.
- [ ] Add a static performance assertion that `onTouchMove` schedules a coalesced draw and does not start the retired ambient animation loop.

### 5.2 Run focused and existing Atlas tests

```powershell
node --test apps\weekly_activity_miniprogram\tests\atlas-starmap-redesign.test.cjs
node --test apps\weekly_activity_miniprogram\tests\atlas-search-and-starmap-l1.test.cjs
```

Expected: both suites exit 0. Fix only regressions attributable to the redesign.

### 5.3 Run syntax and package-level no-DevTools regression

```powershell
node --check apps\weekly_activity_miniprogram\pages\atlas-starmap\atlas-starmap.js
node --check apps\weekly_activity_miniprogram\tests\devtools-atlas-neighborhood-rendered.cjs
npm run test:miniprogram
```

Expected: all mini-program tests pass. If an unrelated pre-existing failure appears, record the exact test and evidence without changing unrelated modules.

### 5.4 Inspect the bounded diff

```powershell
git diff --check -- tools/atlas_rebuild/export_mp_starmap_bundle.py apps/weekly_activity_miniprogram/data/atlas_starmap.json apps/weekly_activity_miniprogram/data/atlas_starmap.js apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.js apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.wxml apps/weekly_activity_miniprogram/pages/atlas-starmap/atlas-starmap.wxss apps/weekly_activity_miniprogram/tests/atlas-starmap-redesign.test.cjs apps/weekly_activity_miniprogram/tests/atlas-search-and-starmap-l1.test.cjs
git diff --stat -- tools/atlas_rebuild/export_mp_starmap_bundle.py apps/weekly_activity_miniprogram/data/atlas_starmap.json apps/weekly_activity_miniprogram/data/atlas_starmap.js apps/weekly_activity_miniprogram/pages/atlas-starmap apps/weekly_activity_miniprogram/tests/atlas-starmap-redesign.test.cjs apps/weekly_activity_miniprogram/tests/atlas-search-and-starmap-l1.test.cjs
```

Expected: no whitespace errors; no unrelated file appears in the bounded stat.

### 5.5 Commit the reconciled regression contracts if they changed

```powershell
git add apps/weekly_activity_miniprogram/tests/atlas-search-and-starmap-l1.test.cjs
git diff --cached --check
git commit -m "test(atlas): reconcile starmap redesign contracts"
```

If that file has no diff, skip this commit.

---

## Task 6: Produce Real DevTools Rendered Proof and Record Runtime Truth

**Files:**

- Modify: `apps/weekly_activity_miniprogram/tests/devtools-atlas-neighborhood-rendered.cjs:250-492`
- Modify: `docs/current-runtime.md`
- Generated, do not commit unless repository policy already tracks the exact artifact lane: `apps/weekly_activity_miniprogram/test-artifacts/atlas-neighborhood-rendered-*/`

### 6.1 Extend the rendered-state probe before running DevTools

- [ ] Add these fields to the current page-state extraction:

```javascript
sheetState: page && page.data && page.data.sheetState,
viewLens: page && page.data && page.data.viewLens,
zoomTier: page && page.data && page.data.zoomTier,
toolPanel: page && page.data && page.data.toolPanel,
typeShapes: page && page._nodes ? Array.from(new Set(page._nodes.map(function (node) {
  return page._nodeVisual(node).shape;
}))).sort() : [],
selectedMetrics: page && page.data && page.data.selected ? {
  eventCount: page.data.selected.eventCount,
  relationCount: page.data.selected.relationCount,
  sourceCount: page.data.selected.sourceCount,
} : null,
```

- [ ] Assert initial `viewLens === "structure"` and `sheetState === "hidden"`.
- [ ] After selecting the center entity, assert `sheetState === "peek"` and all three selected metrics are finite non-negative numbers.
- [ ] Assert the rendered base data resolves all four shapes: `circle`, `diamond`, `hexagon`, and `ring`.
- [ ] Trigger the explore handler and assert `sheetState === "explore"` while the existing 40-neighbor and inspector checks still pass.
- [ ] Switch to city and time lenses and assert the data state changes without changing selected entity or node count.
- [ ] Return to structure lens before the final screenshot.

### 6.2 Run the DevTools stop gate and discover the current websocket

- [ ] Run the existing stop-gate script before using the live DevTools connection:

```powershell
node apps\weekly_activity_miniprogram\tests\devtools-automator-live-stop-gate.cjs
```

- [ ] Read the current Windows WeChat DevTools automator listener from the validated local runtime. Do not reuse a stale port from an old report.
- [ ] If no listener exists, start/open the project with the Windows WeChat DevTools CLI according to the repository SOP; do not retry through WSL.

Expected: one current `ws://` endpoint is known and the stop gate does not report a conflicting active automation run.

### 6.3 Run the rendered proof with screenshots enabled

Read the endpoint selected by the newly generated green stop-gate report and run with it:

```powershell
$gateReport = Get-ChildItem apps\weekly_activity_miniprogram\test-artifacts -Directory -Filter 'devtools-automator-live-stop-gate-*' |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1 |
  ForEach-Object { Join-Path $_.FullName 'report.json' }
$gate = Get-Content -Raw $gateReport | ConvertFrom-Json
if (-not $gate.ok -or -not $gate.selectedEndpoint) { throw "DevTools stop gate is not green: $gateReport" }
$env:MINIPROGRAM_AUTOMATOR_WS = $gate.selectedEndpoint
$env:MINIPROGRAM_SCREENSHOTS = '1'
node apps\weekly_activity_miniprogram\tests\devtools-atlas-neighborhood-rendered.cjs
```

Expected:

- route is `pages/atlas-starmap/atlas-starmap`;
- `loading=false` and `canvasError=false`;
- base graph is visible and node count remains bounded;
- selected entity has metrics, 40-neighbor preview, and inspector data;
- peek/explore transitions and structure/city/time lens transitions pass;
- share, filters, trail, path, and artist navigation checks remain green;
- `starmap-neighborhood.png` is non-empty.

### 6.4 Inspect the screenshot as visual evidence

- [ ] Open the generated PNG with the local image viewer.
- [ ] Verify at phone dimensions:
  - graph remains the primary visual surface;
  - top command bar is compact and unobstructed;
  - right tool rail is reachable and does not cover the selected node;
  - peek sheet is compact;
  - explore sheet does not exceed 45% of viewport height;
  - node shapes and colors are distinguishable;
  - labels do not visibly collide around the selected neighborhood;
  - no old future/DJ-trajectory tabs or oversized first-screen card remain.
- [ ] If visual proof fails, change one scoped cause at a time and rerun the focused test plus rendered proof.

### 6.5 Record verified runtime state without making release claims

- [ ] Add a dated Atlas starmap entry to `docs/current-runtime.md` containing:
  - approved design spec path;
  - bundle schema v2 and 240/640 caps;
  - focused, L1, and package test results;
  - DevTools artifact directory and screenshot path;
  - explicit state: local source and rendered proof complete; developer upload, review, and public release not performed.

### 6.6 Run final verification

```powershell
python tools\atlas_rebuild\export_mp_starmap_bundle.py --selftest
node --test apps\weekly_activity_miniprogram\tests\atlas-starmap-redesign.test.cjs
node --test apps\weekly_activity_miniprogram\tests\atlas-search-and-starmap-l1.test.cjs
npm run test:miniprogram
git diff --check -- tools/atlas_rebuild/export_mp_starmap_bundle.py apps/weekly_activity_miniprogram/data/atlas_starmap.json apps/weekly_activity_miniprogram/data/atlas_starmap.js apps/weekly_activity_miniprogram/pages/atlas-starmap apps/weekly_activity_miniprogram/tests/atlas-starmap-redesign.test.cjs apps/weekly_activity_miniprogram/tests/atlas-search-and-starmap-l1.test.cjs apps/weekly_activity_miniprogram/tests/devtools-atlas-neighborhood-rendered.cjs docs/current-runtime.md
```

Expected: all commands exit 0, except an unrelated package-suite failure may be reported separately with exact evidence and must not be hidden.

### 6.7 Commit rendered proof contracts and runtime documentation

```powershell
git add apps/weekly_activity_miniprogram/tests/devtools-atlas-neighborhood-rendered.cjs docs/current-runtime.md
git diff --cached --check
git commit -m "test(atlas): verify redesigned starmap rendering"
```

### 6.8 Final handoff checklist

- [ ] Report changed files and commit IDs.
- [ ] Report exact test commands and pass/fail counts.
- [ ] Link the rendered screenshot and runtime note with absolute Windows paths.
- [ ] State that the V2 database was opened read-only and remained unchanged.
- [ ] State separately whether local source, local rendered proof, developer upload, review, and public release are complete.
- [ ] Do not stage or commit `.superpowers/`, unrelated dirty files, databases, credentials, environment files, or old test artifacts.
