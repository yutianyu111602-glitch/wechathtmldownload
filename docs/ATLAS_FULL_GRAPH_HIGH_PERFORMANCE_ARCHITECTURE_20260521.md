# Atlas Full Graph High-Performance Architecture - 2026-05-21

Status: design / next implementation plan

Scope: full-load the Atlas SQLite database into a high-performance graph exploration stack without inventing the core graph engine or renderer from scratch. This plan keeps the public site anti-scrape by design: the full database is loaded only into private/offline/server-side stores, never into the browser as a raw graph dump.

## Source Research

- Frontend large-graph renderer: [`cosmosgl/graph`](https://github.com/cosmosgl/graph) / Cosmograph. Its README describes a GPU WebGL force graph engine where computation and drawing happen on the GPU and targets hundreds of thousands of points/links on modern hardware.
- Product-grade browser graph workbench: [Cosmograph](https://cosmograph.app/) for fast web-based force graph layout, search/filtering, local-first analysis, and DuckDB-backed analytics patterns.
- Production graph database candidate: [`ArcadeData/arcadedb`](https://github.com/ArcadeData/arcadedb). It is Apache 2.0, supports graph/document/key-value/search/time-series/vector/geospatial models, Cypher/Gremlin/SQL/HTTP, ACID, built-in graph algorithms, and Docker/server mode.
- ArcadeDB benchmark evidence: [ArcadeDB benchmarks](https://arcadedb.com/benchmarks.html) use LDBC Graphalytics and LSQB, and describe an OLAP Graph Analytical View using CSR encoding and lower memory layout for graph analytics.
- Low-latency alternative: [`FalkorDB/FalkorDB`](https://github.com/FalkorDB/FalkorDB), GraphBLAS/sparse-matrix property graph with OpenCypher and bulk loader. Risk: SSPL license, so it is a benchmark/alternative, not the default public production choice.
- Distributed future option: [`vesoft-inc/nebula`](https://github.com/vesoft-inc/nebula), Apache 2.0 distributed graph DB with RAFT, horizontal scale, OpenCypher, and large-volume graph support. It is too operationally heavy for the current single Singapore VPS, but valid if the project grows into a cluster.
- Offline large-scale analytics option: [`alibaba/GraphScope`](https://github.com/alibaba/GraphScope), a distributed graph computing platform combining analytics, interactive, GNN, and Vineyard memory transfer. Use only for offline batch analytics if local/server hardware becomes insufficient.
- Embedded prototype caveat: [`kuzudb/kuzu`](https://github.com/kuzudb/kuzu) has the right embedded/Cypher/columnar design, but the repository is archived as of 2025-10-10. It can be used for experiments only; do not make it the production base.

## Decision

Use a layered stack:

1. **Private full graph store:** benchmark ArcadeDB first. Keep FalkorDB and NebulaGraph as alternatives.
2. **Offline analytics:** use ArcadeDB built-in algorithms first; use NetworKit/igraph/GraphScope only if ArcadeDB cannot finish PageRank/community/k-core jobs fast enough.
3. **Public visualization:** add a Cosmograph/cosmos.gl "Galaxy mode" for dense GPU 2D exploration, while keeping the current `3d-force-graph` page as the cinematic focus/ego-neighborhood mode.
4. **Public API:** never expose the full graph. Serve signed, capped, level-of-detail graph windows.

## Why Browser Full Load Is Rejected

The current Atlas base is roughly:

- `articles`: 138,102
- `entities`: 1,510,787
- `events`: 608,678

If every mention/entity/event/article becomes a browser node, the raw node count is already above 2.2M before edges, outlinks, assets, places, accounts, and canonical merged entities. Loading that directly into a public browser page would be slow, visually useless, and a scrape-friendly bulk export.

The right architecture is **full-load privately, explore publicly by layers**.

## Data Model Fix

Do not treat `eid` like `local:e4` or `evid` like `local:ev1` as global IDs. They are local extraction IDs scoped to a source article.

Public graph IDs must be source-scoped:

- Entity mention key: `source_article_uid + eid`
- Event mention key: `source_article_uid + evid`
- Article key: `article_uid`
- Future canonical entity key: `ceid:{type}:{hash(normalized_name + evidence_cluster)}`

This prevents collisions such as `MaFoL` and an unrelated wine/product row both resolving as `local:e4`.

## Atlas Galaxy LOD Algorithm

### 1. Private Full Ingest

Export from `atlas.sqlite` into typed node/edge files:

- `article_nodes`
- `entity_mention_nodes`
- `event_mention_nodes`
- `source_account_nodes`
- `place_nodes`
- `canonical_entity_nodes` after clustering
- `outlink_nodes` and `asset_nodes` when avatar/outlink work completes

Edges:

- `ARTICLE_MENTIONS_ENTITY`
- `ARTICLE_HAS_EVENT`
- `EVENT_HAS_PARTICIPANT`
- `ENTITY_SAME_SOURCE_ARTICLE`
- `ENTITY_SAME_NAME`
- `EVENT_SAME_PLACE_TIME`
- `ENTITY_PROFILE_CANDIDATE`
- `ENTITY_HAS_ASSET`
- `ENTITY_HAS_OUTLINK`

Bulk-load via CSV/Parquet import. The import path must be batch-based, not one Cypher insert per row.

### 2. Noise And Safety Gate Before Graph Promotion

Filter public graph surfaces before community detection:

- Reject alcohol/menu/product noise.
- Reject non-electronic rows: generic food/drink/cafe/restaurant, hiring, wellness/classes, art/film/theatre/reading, retail/beauty/accommodation.
- Keep music-adjacent workshops and real electronic music concepts.
- Keep candidate social/outlink evidence as dashed candidate edges only until accepted.

### 3. Weighting

Base edge score:

```text
weight =
  relation_base
  * confidence
  * source_quality
  * type_priority
  * evidence_strength
  * noise_penalty
```

Priority examples:

- `EVENT_HAS_PARTICIPANT`: high
- `ARTICLE_MENTIONS_ENTITY`: medium
- `ENTITY_SAME_SOURCE_ARTICLE`: low
- `ENTITY_PROFILE_CANDIDATE`: low and dashed unless accepted

### 4. Offline Metrics

Precompute and store:

- connected components
- Leiden/Louvain community id
- PageRank
- weighted degree
- k-core
- source diversity count
- recent-event count
- representative score
- optional 2D layout coordinates for Cosmograph

### 5. Level Of Detail

Serve the public graph in layers:

- `L0 Galaxy`: community/meta graph, max 1,000-3,000 nodes.
- `L1 Community`: selected community, max 2,000-10,000 visible nodes depending on device.
- `L2 Ego`: selected DJ/club/label/event neighborhood, max 500-5,000 nodes.
- `L3 Evidence`: detail rows, source snippets, avatars, outlinks, identity candidates; lazy-loaded only after click/hover.

No endpoint should return "all nodes" or "all edges".

## Public API Shape

New routes:

- `GET /api/v1/stage7/graph/galaxy?q=&level=0&limit=2000`
- `GET /api/v1/stage7/graph/community?id=...&limit=5000`
- `GET /api/v1/stage7/graph/window?token=...`
- `GET /api/v1/stage7/graph/node/:publicId`
- `GET /api/v1/stage7/graph/assets?ids=...`

All routes require:

- Turnstile-backed `atlas_session`
- signed opaque cursor/window token
- hard node/edge caps
- per-session budget
- no raw database path
- no sequential ID enumeration
- no bulk export

## Public Frontend Shape

Keep current `/atlas/graph` as focus mode:

- 3D force graph
- click/expand/roam/inspector
- small bounded neighborhoods

Add a new "Galaxy" mode:

- Cosmograph/cosmos.gl canvas
- search + histogram filters + community filter
- WebGL point/edge rendering
- precomputed coordinates first, live force refinement second
- avatars and external links loaded only for selected/nearby nodes

## Server Fit

Current Singapore VPS should stay a **public serving node**, not the only full analytics machine.

Recommended split:

- PC/local/offline: full export, community detection, PageRank, layout, asset manifest generation.
- Singapore VPS: serve static/materialized LOD tables and optional ArcadeDB/FalkorDB query service only after benchmark.
- Cloudflare: Turnstile, WAF, rate limits, cache for HTML/assets, no cache for data windows unless signed and short-lived.

## Implementation Plan

1. Fix public IDs and exact-search ranking. Status: done for current service slice.
2. Build `atlas_graph_public_ids` materialized table and migration check for `source_article_uid + eid/evid` uniqueness.
3. Write `export_atlas_graph_lod.py`: SQLite -> Parquet/CSV nodes/edges.
4. Benchmark ArcadeDB import/query on local PC and Singapore VPS:
   - import time
   - disk size
   - 1-hop / 2-hop query latency
   - PageRank/community runtime
   - memory pressure
5. If ArcadeDB is too heavy on the VPS, keep it offline and deploy LOD JSON/SQLite/DuckDB artifacts only.
6. Add `/atlas/galaxy` with Cosmograph.
7. Add anti-scrape window-token API and per-session budget.
8. Only after local and remote smokes pass, route `/atlas/graph` to the new Galaxy/Focus dual-mode UI.

## Rejection List

- No browser-side full raw graph load.
- No direct public `atlas.sqlite`.
- No global `local:e4`-style IDs.
- No raw social/outlink candidate edge as accepted graph proof.
- No unauthenticated graph/search/detail API.
- No expensive cluster DB on the current VPS until a benchmark proves it is needed.
