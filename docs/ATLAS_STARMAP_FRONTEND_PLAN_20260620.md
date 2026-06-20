# ATLAS Starmap Frontend Plan 2026-06-20

Status: `CURRENT_PLAN / FRONTEND_LANE`

This is the execution plan for the current Codex thread's ATLAS star-map work. It is not the Sanji daily pipeline plan and not the full 140k article extraction plan.

## Scope

In scope:

- ATLAS Web 星图 P1: B2B / 高频同台合作网络宇宙.
- Mini-program entry that opens the full Web star map safely.
- Frontend display, interaction, static CloudRun route, build/bake/test/rendered proof.
- Documentation and handoff surfaces so Claude can resume without chat context.

Out of scope:

- Sanji daily package generation, `missing_geo`, poster review, deploy/upload decisions.
- Full 140k article extraction and Atlas DB rebuild execution.
- New production database writes.
- Replacing the native mini-program `pages/saved` lightweight starmap.
- WeChat review/public release.

Related threads:

- Sanji daily pipeline: `codex://threads/019ed387-0945-7a72-9f9b-df013cfcc2cd`
- Full 140k extraction: `codex://threads/019edb56-b898-7291-b92a-04c6d571f0bf`

## Current Confirmed State

- Web source: `apps/atlas_starmap_web`
- Data projector: `tools/atlas_rebuild/export_starmap_layout.py`
- Current layout: `apps/atlas_starmap_web/public/atlas_layout.json`
- Baked CloudRun static root: `services/weekly_activity_cloudrun/data/atlas_starmap`
- Web route: `GET /atlas/starmap`
- Asset route: `GET /atlas-starmap-assets/...`
- Mini-program entry: about page opens `/pages/source/source?url=https%3A%2F%2Fhuaidj.club%2Fatlas%2Fstarmap`
- Current layout proof: `1296` nodes, `8000` edges, `586` b2b, `7414` collab.
- Fresh rendered proof: `apps/atlas_starmap_web/test-artifacts/playwright-result.json`, `ok=true`, desktop/mobile canvas nonblank, node `NORA` search/click opens detail panel.

Current delivery risk:

- The star-map source/build artifacts are still mostly untracked in this dirty repo. A clean checkout will not contain this lane until these files are explicitly staged/committed or packed.

## Architecture Decisions

- Keep Web star map as a separate React/Three app under `apps/atlas_starmap_web`.
- Serve it through CloudRun as a static entry at `/atlas/starmap`, with dedicated `/atlas-starmap-assets` route and a narrow asset whitelist.
- Keep the native mini-program starmap as the lightweight in-app experience; the full 3D Web map is opened through the controlled source page.
- P1 remains one lens only: B2B / frequent co-appearance collaboration network.
- Future lenses are additive views over the same data contract, not replacements for P1.
- Visual target is a dense workbench/tool surface: command bar, filters, graph canvas, inspector. Avoid landing-page composition and decorative AI styling.

## P1 Closure Tasks

### Task 1: Delivery Inventory And Git Scope

Description: Identify every file required for P1 so the lane survives a clean checkout.

Acceptance criteria:

- [x] Required P1 source files are listed in one delivery manifest.
- [x] Untracked vs modified state is recorded.
- [x] No unrelated generated evidence or large artifacts are accidentally included.

Verification:

- [x] `git status --short -- apps\atlas_starmap_web services\weekly_activity_cloudrun\data\atlas_starmap tools\atlas_rebuild\export_starmap_layout.py docs\ATLAS_WEB_STARMAP_P1_20260620.md docs\ATLAS_STARMAP_FRONTEND_PLAN_20260620.md`
- [x] Delivery manifest references exact paths.

Delivery manifest:

- `docs/ATLAS_STARMAP_P1_DELIVERY_MANIFEST_20260620.md`

Likely files:

- `apps/atlas_starmap_web/**`
- `services/weekly_activity_cloudrun/data/atlas_starmap/**`
- `tools/atlas_rebuild/export_starmap_layout.py`
- `services/weekly_activity_cloudrun/src/server.mjs`
- `services/weekly_activity_cloudrun/tests/atlasStarmapStatic.test.mjs`
- `apps/weekly_activity_miniprogram/pages/about/*`
- `apps/weekly_activity_miniprogram/pages/source/*`
- `apps/weekly_activity_miniprogram/tests/about-atlas-link.test.cjs`
- `docs/ATLAS_WEB_STARMAP_P1_20260620.md`

Dependencies: none.

Scope: medium.

### Task 2: Reproducible Rendered Proof

Description: Keep a first-class smoke command that proves the 3D graph is visible and interactive on desktop/mobile.

Acceptance criteria:

- [x] `npm --prefix apps\atlas_starmap_web run test:rendered` exists.
- [x] The command starts Vite locally without fixed port assumptions.
- [x] It checks desktop and mobile viewports.
- [x] It verifies a nonblank canvas and a node detail interaction.
- [x] It writes `apps\atlas_starmap_web\test-artifacts\playwright-result.json`.

Verification:

- [x] `node --check apps\atlas_starmap_web\scripts\rendered-smoke.mjs`
- [x] `npm --prefix apps\atlas_starmap_web run test:rendered`

Dependencies: Task 1 helps with delivery, but the script already exists locally.

Scope: small.

### Task 3: P1 UI Tightening

Description: Make the P1 Web map feel like an operational star-map workbench, not a prototype shell.

Acceptance criteria:

- [x] Mobile side panels do not create awkward horizontal overflow.
- [x] Search, filters, graph canvas, HUD, and detail inspector remain usable at 390px and desktop width.
- [x] Detail panel uses ATLAS semantics: DJ name, city,演出数, B2B,同台, first/last seen, evidence titles/dates/source refs.
- [x] No card-in-card or landing-page style sections are introduced.

Verification:

- [x] `npm --prefix apps\atlas_starmap_web run build`
- [x] `npm --prefix apps\atlas_starmap_web run test:rendered`
- [x] Visual review of `desktop.png`, `desktop-detail.png`, `mobile.png`, `mobile-detail.png`.

Dependencies: Task 2.

Scope: medium.

### Task 4: P1 Data Contract Guard

Description: Protect the `atlas_layout.json` contract so future projector changes do not blank the Web map.

Acceptance criteria:

- [x] Layout validator checks required node fields: `id`, `name`, `x`, `y`, `z`, `label`, `size`, `color`.
- [x] Edge validator checks `source`, `target`, `type`, evidence shape, and dangling-node absence.
- [x] Validator records P1 lens metadata: total nodes/edges, b2b count, collab count.

Verification:

- [x] `python tools\atlas_rebuild\export_starmap_layout.py --selftest`
- [x] Real layout validation command or test passes against `apps\atlas_starmap_web/public/atlas_layout.json`.

Dependencies: none.

Scope: small-medium.

### Task 5: Mini-Program Entry Gate

Description: Keep mini-program integration narrow: native saved-page star map stays native; full Web map opens through a controlled huaidj.club link.

Acceptance criteria:

- [x] About page exposes "完整星图" only through `/pages/source/source?url=...`.
- [x] Source page direct web URL allowlist remains restricted to `huaidj.club` / `www.huaidj.club`.
- [x] No `navigateToMiniProgram`, no arbitrary web-view route, no mp.weixin.qq.com web-view assumption.

Verification:

- [x] `node --test apps\weekly_activity_miniprogram\tests\about-atlas-link.test.cjs`
- [x] `npm run test:miniprogram`

Dependencies: none.

Scope: small.

## P2 Lens Plan

P2 should add one lens at a time. Do not build all lenses in parallel.

Recommended order:

1. City slice lens
   - Why first: users naturally ask "this city has which DJs / clusters?"
   - Minimal UI: city selector + filtered graph + city-level summary.
   - Data dependency: existing `city` node field and current edges.

2. Time activity lens
   - Why second: helps explain first/last seen and recent activity.
   - Minimal UI: year/month filter and recent/legacy toggle.
   - Data dependency: `first_seen_at`, `last_seen_at`, evidence dates.

3. Venue / resident tendency lens
   - Why third: useful but needs clearer venue rollup, so higher risk.
   - Minimal UI: venue spotlight with frequent DJs and co-appearance edges.
   - Data dependency: Atlas serving profile/venue history, not just current layout.

4. Label / crew roster lens
   - Why later: affiliation data is noisier and should not be inferred from weak article prose.
   - Minimal UI: source-backed roster only, confidence-gated.
   - Data dependency: explicit source-backed affiliation fields.

P2 non-goal: do not turn the star map into a generic social graph or encyclopedia. Each lens must answer one inspection question.

## Verification Gates

Local source gate:

```powershell
python tools\atlas_rebuild\export_starmap_layout.py --selftest
npm --prefix apps\atlas_starmap_web run build
npm --prefix apps\atlas_starmap_web run test:rendered
node --test services\weekly_activity_cloudrun\tests\atlasStarmapStatic.test.mjs
node --test apps\weekly_activity_miniprogram\tests\about-atlas-link.test.cjs apps\weekly_activity_miniprogram\tests\atlas-starmap-runtime.test.cjs
npm run test:miniprogram
npm run weekly-api:test
npm run build
```

Rendered proof gate:

- `apps\atlas_starmap_web\test-artifacts\playwright-result.json` has `ok=true`.
- Desktop and mobile screenshots exist and show nonblank graph plus detail panel.

Release separation:

- Passing local tests does not mean CloudRun deployed.
- CloudRun deploy does not mean mini-program upload.
- Mini-program upload does not mean WeChat review.
- Review approval does not mean public release.

## Risks And Mitigations

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Star-map files stay untracked | Clean checkout loses the lane | Complete Task 1 delivery inventory before handoff or commit |
| WebGL blank screen on mobile | User sees empty map | Keep `test:rendered` canvas PNG pixel check and mobile viewport proof |
| Bundle stays large | Slow load in source page/browser | P1 accepts warning; P2 can split Three/R3F chunks if real load proof is poor |
| Lens creep | Work diffuses into 14w extraction / Atlas rebuild | One P2 lens at a time; data changes go to the proper backend/full-corpus thread |
| Weak relations shown as facts | Trust loss | Keep evidence titles/dates/source refs visible; confidence-gate future lenses |

## Immediate Next Step

Do Task 1 next: write a delivery manifest for P1 files and mark which are untracked/modified. This is the highest-value next action because current functionality is locally proven but not durable across checkout/agent handoff.
