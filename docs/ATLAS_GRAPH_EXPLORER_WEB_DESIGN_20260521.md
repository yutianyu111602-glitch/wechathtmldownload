# Atlas Graph Explorer Web Design - 2026-05-21

Status: deployed to `https://atlas.huaidj.club/atlas/graph` behind Cloudflare + Turnstile session gate / active evidence

Scope: design and deploy a polished, searchable, clickable, roaming graph web surface for the China underground electronic music Atlas. This document is based on the current `weekly_activity_cloudrun` service and the local `atlas.sqlite` product database. It does not authorize production graph writes, Qdrant writes, CloudRun deploys, mini-program uploads, or PinMe publishing.

Security gate: public data access is blocked until a visitor passes Cloudflare Turnstile and receives the httpOnly `atlas_session` cookie. The Atlas graph site must not expose bulk data, full graph export, direct SQLite files, or ungated graph APIs.

## Decision

Build a custom Atlas graph explorer rather than importing a generic no-code graph application wholesale.

Reference project to borrow from: [`cylynx/motif.gl`](https://github.com/cylynx/motif.gl). It is an MIT open-source graph explorer inspired by Kepler.gl and Neo4j Bloom, with visual graph UI, multiple imports, multiple layouts, styling, time-series analysis, and a widget system. It is the best product-pattern reference for the target "高级图谱工作台" feeling.

Rendering core now used in the implementation: [`3d-force-graph`](https://github.com/vasturiano/3d-force-graph) on Three.js/WebGL. This gives the Atlas page a high-energy 3D relation-map surface with orbit controls, focus camera moves, directional particles, roam mode, and much better visual separation than the first flat force canvas.

Fallback / secondary references: Sigma.js + Graphology remain the 2D WebGL fallback path; [`Cytoscape.js`](https://js.cytoscape.org/) remains a future graph-analysis/layout option for selectors, algorithms, and mature interaction patterns.

Reason not to directly embed Motif as the implementation:

- Motif is a broad no-code product and brings React/BaseWeb/Redux/Styletron assumptions that do not match the existing server-rendered `*.mjs` CloudRun service.
- Atlas needs domain-specific objects: DJ, club, venue, label, event, city, article, source evidence, identity review, accepted-for-graph gates.
- The existing service already exposes the exact Atlas API/data layer; a custom explorer keeps the surface compact, fast, and aligned with current safety rules.

## Existing Code Facts

Current service entrypoints:

- `services/weekly_activity_cloudrun/src/server.mjs`
- `services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs`
- `services/weekly_activity_cloudrun/src/atlasPage.mjs`
- `services/weekly_activity_cloudrun/src/atlasDetailPage.mjs`
- `services/weekly_activity_cloudrun/src/atlasIdentityPage.mjs`
- `services/weekly_activity_cloudrun/src/atlasLocalPage.mjs`

Current pages:

- `/atlas`
- `/atlas/identity`
- `/atlas/local`
- `/atlas/articles/:id`
- `/atlas/entities/:id`
- `/atlas/events/:id`

Current APIs:

- `/api/v1/stage7/manifest`
- `/api/v1/stage7/overview`
- `/api/v1/stage7/search?q=...&kind=...`
- `/api/v1/stage7/articles`, `/entities`, `/events`
- `/api/v1/stage7/articles/:id`, `/entities/:id`, `/events/:id`
- `/api/v1/stage7/local/status`
- `/api/v1/stage7/local/map`
- `/api/v1/stage7/local/geocode-review`
- `/api/v1/stage7/identity-review`
- `/api/v1/stage7/recommendations`
- `/api/v1/stage7/graph-rag/answers`
- `/api/v1/stage7/vector-router/status`

Current DB facts from `tools/stage7_rewrite/reports/atlas_local_sqlite_db_138102_20260521/atlas.sqlite`:

- `articles`: 138,102
- `entities`: 1,510,787
- `events`: 608,678
- `map_geocode_places`: 22,109
- `identity_review_items`: 155
- `recommendations`: 20
- `graph_rag_answers`: 10
- FTS5 tables exist for articles, entities, and events.

2026-05-21 23:20 ID/search correction:

- `eid` / `evid` values such as `local:e4` and `local:ev1` are local extraction IDs, not global IDs.
- Public graph node IDs now scope these local IDs by `source_article_uid`, preventing collisions like `MaFoL` and unrelated product rows resolving to the same detail key.
- Search ranking now prioritizes exact `name` / alias / local-id matches before same-article or vector-text mentions.
- The graph page auto-focuses the best exact visible node after search, so searching `MaFoL` opens the `MaFoL` inspector instead of the first co-mentioned lineup entity.
- Full-load architecture and open-source stack research are recorded in `docs/ATLAS_FULL_GRAPH_HIGH_PERFORMANCE_ARCHITECTURE_20260521.md`.

Most important data fields:

- Article node: `article_uid`, `title`, `source_account`, `publish_time_status`, `entity_count`, `event_count`, `quality_grade`, `vector_text_preview`
- Entity node: `eid`, `name`, `type`, `city`, `source_article_uid`, `aliases_json`, `bio`, `evidence_quote`, `vector_text_preview`
- Event node: `evid`, `name`, `place`, `city`, `time_iso`, `time_text`, `participants_json`, `organizers_json`, `source_article_uid`
- Place node: `place_id`, `label`, `normalized_place`, `city`, `lat`, `lon`, `event_count`, `entity_count`, `article_count`
- Identity candidate node/edge: `item_id`, `subject_name`, `subject_type`, `url`, `domain`, `source_article_uid`, `identity_signal_score`, `accepted_for_graph`, `identity_proof`, `graph_write_allowed`

## Product Shape

New page:

- `/atlas/graph`

The first screen should be the tool, not a landing page.

Layout:

- Top command bar: global search, search type, depth, layout mode, roam mode, reset, export snapshot.
- Left rail: saved searches, node-type filters, edge-type filters, exploration queue, breadcrumbs.
- Center: full-bleed graph canvas, not inside a card.
- Right inspector: selected entity, evidence, source article, related events, profile candidates, Graph RAG answers.
- Bottom strip: status, loaded node/edge count, API latency, safety flags, current DB/build identity.

Visual direction:

- Dense desktop workbench, closer to FinAgent Beta / VS Code than marketing SaaS.
- Dark graphite canvas, off-white panels, restrained cyan/green/amber accents.
- Node palette by domain role, not a one-hue AI gradient:
  - DJ/person: cyan
  - Club/venue/place: warm amber
  - Label/organization/brand/group: green
  - Event: red-orange
  - Article/source: muted graphite
  - Identity candidate/profile URL: violet-gray dashed outline only, because it is not accepted graph proof.
- Edges are visually typed:
  - `MENTIONED_IN`: thin gray
  - `HAS_EVENT`: orange
  - `AT_PLACE`: amber
  - `PARTICIPATED_IN`: cyan
  - `ORGANIZED_BY`: green
  - `SAME_ARTICLE`: gray dotted
  - `PROFILE_CANDIDATE`: dashed, warning color, never solid accepted edge

## Core Workflows

### Search

User enters `DADA`, `OIL`, `TAG`, `Dada Kunming`, `Howie Lee`, `Do Hits`, `北京`.

Flow:

1. Call `/api/v1/stage7/search?q=...&kind=...&limit=30`.
2. Show ranked mixed results in a command palette.
3. Press Enter or click a result.
4. Load `/api/v1/stage7/graph/subgraph?kind=entities&id=...&depth=1&limit=120`.
5. Fit graph to selected node, pin it, open inspector.

### Click

Single click:

- highlight one-hop neighborhood
- open right inspector
- show source article, city/place, aliases, related events, confidence, evidence quote

Double click:

- expand one step from clicked node
- preserve existing pinned nodes

Shift click:

- pin/unpin node
- pinned nodes remain visible through roam operations

Edge click:

- open evidence drawer showing why the edge exists: source article uid, shared event/place/article, participants list, candidate profile source, or review state.

### Exploration Roam

Roam is not random animation. It is guided graph traversal with domain presets.

Modes:

- `Scene Walk`: DJ -> event -> club -> city -> nearby clubs/events.
- `Label Orbit`: label/organization -> artists -> events -> articles.
- `Venue Nights`: venue -> recurring events -> participants -> source accounts.
- `City Pulse`: city -> clubs -> events -> DJs.
- `Evidence Trail`: identity candidate -> source article -> subject entity -> corroborating events, with all graph-write flags visible.

Each roam step:

1. Chooses 5-15 next nodes by score.
2. Adds only bounded nodes/edges.
3. Animates camera to the next anchor.
4. Appends breadcrumb and allows undo.

### Exploration Queue

The left rail maintains a queue:

- searched seeds
- clicked nodes
- expanded nodes
- pinned nodes
- hidden/quarantined nodes

The queue makes exploration reproducible and prevents the user from losing their path in a large graph.

## Required API Additions

All API additions are read-only.

### `GET /api/v1/stage7/graph/seed`

Purpose: convert search results into graph seed nodes.

Query:

- `q`: text
- `kind`: optional `articles|entities|events|places`
- `limit`: default 20, max 100

Response:

```json
{
  "schemaVersion": "stage7_atlas_graph.seed_response.v1",
  "query": "DADA",
  "nodes": [],
  "safety": {
    "sqliteWriteExecuted": false,
    "neo4jWriteExecuted": false,
    "qdrantWriteExecuted": false,
    "modelCallExecuted": false
  }
}
```

### `GET /api/v1/stage7/graph/subgraph`

Purpose: get a bounded graph around one node.

Query:

- `kind`: `articles|entities|events|places|identity`
- `id`: primary id
- `depth`: default 1, max 2 for now
- `limit`: default 120, max 300
- `edgeTypes`: optional comma-separated allow list

Initial edge derivation from existing tables:

- Entity -> Article via `source_article_uid`
- Event -> Article via `source_article_uid`
- Event -> Place via normalized `place`
- Event -> Entity by names in `participants_json` / `organizers_json`, matched against entity names within the same source article first
- Entity -> Event by same `source_article_uid`
- Place -> Event by `events.place`
- Identity Candidate -> Entity by `subject_name` and `source_article_uid`, but only as `PROFILE_CANDIDATE`

### `GET /api/v1/stage7/graph/expand`

Purpose: expand one visible node during exploration.

Query:

- `nodeId`
- `direction`: `out|in|both`
- `limit`: default 80, max 200
- `exclude`: optional currently loaded node ids

### `GET /api/v1/stage7/graph/random-walk`

Purpose: guided roam, not arbitrary DB scan.

Query:

- `seedNodeId`
- `mode`: `scene|label|venue|city|evidence`
- `steps`: default 5, max 20
- `fanout`: default 8, max 20

### Graph Payload Contract

```json
{
  "schemaVersion": "stage7_atlas_graph.subgraph_response.v1",
  "center": {"id": "entity:...", "kind": "entities"},
  "nodes": [
    {
      "id": "entity:...",
      "kind": "entities",
      "label": "DADA",
      "type": "club",
      "city": "北京",
      "size": 12,
      "colorKey": "venue",
      "href": "/atlas/entities/...",
      "evidence": {"sourceArticleUid": "...", "confidence": 0.83}
    }
  ],
  "edges": [
    {
      "id": "edge:...",
      "source": "event:...",
      "target": "place:...",
      "kind": "AT_PLACE",
      "weight": 6,
      "label": "at place",
      "evidence": {"sourceArticleUid": "...", "articleCount": 3}
    }
  ],
  "facets": {
    "nodeKinds": [],
    "edgeKinds": [],
    "cities": []
  },
  "safety": {
    "sqliteWriteExecuted": false,
    "neo4jWriteExecuted": false,
    "qdrantWriteExecuted": false,
    "modelCallExecuted": false,
    "acceptedGraphPromotionExecuted": false
  }
}
```

## Frontend Implementation

Preferred implementation path:

1. Add `services/weekly_activity_cloudrun/src/atlasGraphPage.mjs`.
2. Add route `/atlas/graph` in `server.mjs`.
3. Add graph APIs in `stage7AtlasSqliteStore.mjs`.
4. Add a browser graph renderer asset. Current deployed slice uses CDN-loaded `3d-force-graph`/Three.js with Sigma.js/Graphology fallback; production hardening should vendor these assets under the service public tree if CDN dependence becomes unacceptable.

Long-term production preference: do not rely on a remote CDN unless CSP and availability risk are explicitly accepted. Either:

- introduce a minimal frontend build step for the graph page, or
- vendor a built ESM/UMD asset under `services/weekly_activity_cloudrun/public/vendor/`.

Initial graph layout:

- Start with server-provided `x/y` if cached later.
- First implementation can use client-side circular / radial / force layout on the returned bounded subgraph.
- Add ForceAtlas2 only after node count and performance are verified.

State model:

- `loadedGraph`: graphology graph
- `selectedNodeId`
- `pinnedNodeIds`
- `hiddenNodeIds`
- `breadcrumbs`
- `pendingExpandNodeId`
- `filters`: node kind, edge kind, city, confidence, source account
- `roamSession`: mode, current step, visited nodes

## Inspector

Tabs:

- `概况`: name, role/type, city, counts, confidence
- `证据`: source article, quote, vector text preview, extracted participants/organizers
- `关系`: visible edges grouped by type, weight, evidence source
- `来源`: article detail link, source account, publish status
- `身份候选`: profile candidates, domain, score, acceptance flags
- `推荐`: current recommendation rows and Graph RAG answers related to the selected node

Critical safety copy:

- For `PROFILE_CANDIDATE`, show `候选资料，未入图`.
- For `accepted_for_graph=false`, show a warning state.
- Never make candidate/profile edges visually indistinguishable from accepted Atlas relationships.

## Performance Constraints

Client-side graph viewport:

- Default subgraph: 80-120 nodes, 120-250 edges.
- Hard cap for one response: 300 nodes, 700 edges.
- Search result graph starts small, then expands on user action.
- Never send all `1,510,787` entities or `608,678` events to the browser.

API:

- Query by indexed ids and `source_article_uid`.
- FTS search remains the search front door.
- For participants/organizers name matching, start with same-article exact match only; later add normalized alias index.
- Return safety flags in every graph API response.

## Implementation Slices

### Slice 1 - Read-only Graph API

Files:

- `services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs`
- `services/weekly_activity_cloudrun/src/server.mjs`
- `services/weekly_activity_cloudrun/tests/stage7GraphExplorer.test.mjs`

Acceptance:

- `GET /api/v1/stage7/graph/subgraph?kind=entities&id=<eid>` returns bounded nodes/edges.
- Safety flags all false for writes/model calls.
- No graph/vector/DB promotion write.
- `npm run weekly-api:test` passes.

### Slice 2 - `/atlas/graph` Shell

Files:

- `services/weekly_activity_cloudrun/src/atlasGraphPage.mjs`
- `services/weekly_activity_cloudrun/src/server.mjs`
- optional bundled graph asset

Acceptance:

- Page opens without console errors.
- Search loads a graph.
- Click opens inspector.
- Double-click expands.
- Fit/reset works.
- Mobile does not overlap text or controls.

### Slice 3 - Roam Modes

Files:

- `stage7AtlasSqliteStore.mjs`
- `atlasGraphPage.mjs`
- tests for `random-walk`

Acceptance:

- `Scene Walk`, `Label Orbit`, `Venue Nights`, `City Pulse`, and `Evidence Trail` return deterministic bounded paths.
- Breadcrumb undo works.
- User can pin nodes across roam steps.

### Slice 4 - Polish And Deployment

Acceptance:

- Browser screenshot verification: desktop 1440, 2.5K, mobile 390.
- Canvas nonblank pixel check.
- Keyboard search, Escape close inspector, Enter search, arrow result selection.
- Nginx/VPS or CloudRun deploy only after explicit authorization.
- PinMe remains a front-end publishing candidate only; it must not host the full SQLite DB or graph data.
- Anti-scrape deploy gate passes: edge bot protection selected, Atlas session/CAPTCHA gate enabled, origin direct access locked, graph API limits active, honey endpoints active, and bot smoke tests return 403/429/challenge.

## Test Plan

Targeted tests:

```powershell
npm run weekly-api:test
node --test services\weekly_activity_cloudrun\tests\stage7GraphExplorer.test.mjs
```

Browser verification:

- `/atlas/graph` loads.
- `/api/v1/stage7/graph/subgraph` returns non-empty graph for a known entity/place/event.
- Search `DADA`, `OIL`, `TAG`, `Dada Kunming`, `北京`.
- Node click opens inspector.
- Double-click expands without duplicate node ids.
- Roam mode adds bounded nodes and updates breadcrumbs.
- Console errors/warnings: 0.
- Horizontal overflow on mobile: false.

Safety checks:

- `sqliteWriteExecuted=false`
- `neo4jWriteExecuted=false`
- `qdrantWriteExecuted=false`
- `modelCallExecuted=false`
- `acceptedGraphPromotionExecuted=false`

## Non-goals

- No production Neo4j/Qdrant promotion.
- No identity edge acceptance.
- No public-search restart or PID interruption.
- No D: root scan.
- No LLM/model calls.
- No PinMe upload or VPS deployment in this design step.
- No complete graph dump in the browser.

## Implementation Checkpoint - 2026-05-21

Implemented locally in `services/weekly_activity_cloudrun` and deployed to the Singapore origin:

- Page: `/atlas/graph`
- HTML renderer: `src/atlasGraphPage.mjs`
- Route wiring: `src/server.mjs`
- Read-only graph APIs:
  - `/api/v1/stage7/graph/seed`
  - `/api/v1/stage7/graph/subgraph`
  - `/api/v1/stage7/graph/expand`
  - `/api/v1/stage7/graph/random-walk`
- Data layer: bounded graph DTO methods in `src/stage7AtlasSqliteStore.mjs`
- Tests: `tests/stage7SqliteLocal.test.mjs`

Current behavior:

- Uses `3d-force-graph` + Three.js/WebGL as the primary renderer.
- Keeps Sigma.js + Graphology as the 2D fallback when the 3D renderer fails to load.
- Falls back to the built-in Canvas renderer if graph modules fail entirely.
- Search, node filters, edge filters, inspector, detail links, PNG snapshot, reset/fit, and roam are available.
- Click selects and focuses a node; right-click expands; roam mode auto-rotates and fetches bounded random-walk neighborhoods.
- Graph payloads are capped and do not expose raw JSON, SQLite files, bulk export, production graph writes, Qdrant writes, model calls, or mem0 writes.
- Public graph responses no longer expose the local SQLite path by default; they expose only a public read-model identity. Use `ATLAS_EXPOSE_INTERNAL_DB_PATH=1` only for local operator debugging.
- Application anti-scrape gate is enabled on `atlas.huaidj.club`:
  - `ATLAS_REQUIRE_SESSION=1` turns on fail-closed session enforcement for `/api/v1/stage7/*`.
  - `POST /api/v1/atlas/session` verifies Turnstile and sets an httpOnly Atlas session cookie.
  - `GET /api/v1/atlas/session/status` lets the frontend decide whether to show the Turnstile lock.
  - Per-session API rate limits apply when the gate is enabled.
  - honey endpoints such as `/atlas.sqlite` return 403 at the application layer as well as the Cloudflare/Nginx layers.
- Production SQLite is read-only at the driver layer with `ATLAS_SQLITE_READONLY=1`, and Node listens only on `127.0.0.1:8787` behind Nginx.
- The visual direction has been aligned to the existing `C:\Users\pc\code\huaidj-submit` BAD DJ/miniprogram archive style: black/grey dominant, restrained, cold, mobile-first compatible, with a small acid-green functional accent.
- Default empty-search seed uses a small article-neighborhood sample for fast first paint on the 138,102 / 1,510,787 / 608,678 local SQLite DB.
- Search-driven seed and subgraph still use SQLite FTS/detail neighborhoods.
- Random-walk uses bounded row_pk article-neighborhood roaming rather than full-table same-name scans.
- SQLite runtime now sets conservative read-performance pragmas (`cache_size`, `temp_store`, `mmap_size`) and creates id/source lookup indexes if a fixture or future DB misses them.
- Public read-model noise filtering now hides alcohol/menu/product rows and broader non-electronic noise from search, graph seed, graph expansion, random walk, source-article neighborhoods, and detail pages. Current filtered classes include wine/alcohol menus, food/drink/cafe/restaurant items, jobs/hiring, wellness/fitness/classes, art/film/theatre/reading-club items, retail/promotions/beauty, and accommodation recommendations. The underlying `atlas.sqlite` is not mutated.

Verification evidence:

- `node --check services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs`: passed.
- `node --check services/weekly_activity_cloudrun/src/atlasGraphPage.mjs`: passed.
- `node --check services/weekly_activity_cloudrun/src/server.mjs`: passed.
- `node --test services/weekly_activity_cloudrun/tests/stage7SqliteLocal.test.mjs`: 8 passed after Turnstile/session gate, read-only SQLite, alcohol/menu, and non-electronic noise tests were added.
- `npm run weekly-api:test`: 50 passed when run serially.
- `git diff --check` on touched graph files: passed.
- Local browser `http://127.0.0.1:18987/atlas/graph`:
  - Desktop snapshot: loaded with renderer `3d-force-graph`, 26 nodes / 87 edges.
  - Headless canvas pixel check: desktop `nonDark=158`, mobile `nonDark=201`, renderer status `3d-force-graph`, nonblank WebGL canvas on both viewports. Desktop emitted only WebGL `ReadPixels` performance warnings from the verification sampling.
  - `DADA` real-DB graph response at `limit=80`: 39 nodes / 190 edges, `safety.bulkExportEnabled=false`, no DB-path key, no noise-pattern terms in node labels.
  - Noise-search smokes for `葡萄酒`, `酒单`, `艺术展`, `读书会`, `课程表`, `咖啡`, `餐厅`, `招聘`, `瑜伽`, `电影`, `戏剧`, `菜单`, `酒店推荐`, `疗愈`: all returned 0 public results.
  - `工作坊` remains allowed only for music-adjacent results, such as DJ workshop rows; known wellness/read-club/class noise is filtered.
  - `/atlas.sqlite`: application-level `403`.

Deployment evidence:

- Remote service: `atlas-weekly-api.service` active on `sg-atlas-origin`.
- Remote DB: `/var/lib/atlas/atlas.sqlite`, `root:atlas`, mode `640`, size `3983425536`.
- Remote app port: `127.0.0.1:8787` only.
- Origin service smoke: `atlas-weekly-api.service` active, Node listening on `127.0.0.1:8787`.
- Public Cloudflare smoke: browser UA `/atlas/graph=200`, page contains 3D graph code and Turnstile gate, session status `requireSession=true`, `configured=true`, `hasSession=false`, `secretExposed=false`, `siteKeyPresent=true`.
- Public no-session API smoke: `/api/v1/stage7/search?q=DADA&limit=1=403`.
- Public honey/script smokes: `/atlas.sqlite=403`, scripted `curl` UA to `/atlas/graph=403`.
- Direct origin app-port smoke from workstation: `http://149.28.150.224:8787/healthz` timed out.

## Practical Next Step

Next hardening step: replace the self-signed origin certificate with a Cloudflare Origin Certificate and move SSL/TLS from `Full` to `Full (strict)`. Keep Graph/vector promotion out of this public read model unless a separate write gate is approved.
