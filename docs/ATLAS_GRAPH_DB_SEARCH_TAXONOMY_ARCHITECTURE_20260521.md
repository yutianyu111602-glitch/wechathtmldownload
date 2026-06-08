# Atlas Graph DB / Search / Taxonomy Architecture - 2026-05-21

Status: design / implementation blueprint

Target surfaces:

- Web: `https://atlas.huaidj.club/atlas/graph` and future `https://atlas.huaidj.club/atlas/galaxy`
- Mini-program backend: weekly activity LLM/materialized recommendation pipeline
- Private operator/API layer: full Atlas build, taxonomy, entity profile, social/outlink/mixtape evidence

Hard boundary: the full Atlas database is never sent to the browser or mini-program. Public clients receive capped, signed, level-of-detail windows and profile cards only.

Companion product-logic doc: `docs/ATLAS_MUSIC_GRAPH_RELATION_LOGIC_CHINESE_UI_20260521.md` defines the music-scene graph lenses, relation ontology, scoring rules, and full Chinese UI copy.

## Source Research Used

- [Cosmograph](https://cosmograph.app/) / [`cosmosgl/graph`](https://github.com/cosmosgl/graph): WebGL large-graph rendering and browser analytics reference.
- [Meilisearch filtering/faceting docs](https://www.meilisearch.com/docs/reference/features/filtering): search facets, filters, sortable/filterable attributes, and large-index optimized structures.
- [Typesense REST API](https://typesense.rest/): typo-tolerant instant search with filtering, faceting, geo-search, and vector search. Keep as benchmark alternative to Meilisearch.
- [Qdrant search docs](https://qdrant.tech/documentation/search/) and [hybrid queries](https://qdrant.tech/documentation/concepts/hybrid-queries/): semantic / hybrid search and payload filters for LLM context retrieval.
- [ArcadeDB](https://github.com/ArcadeData/arcadedb): Apache 2.0 multi-model graph database candidate for private graph store and graph algorithms.
- [ArcadeDB benchmarks](https://arcadedb.com/benchmarks.html): LDBC Graphalytics / LSQB benchmark reference and CSR analytical view direction.
- [FalkorDB](https://github.com/FalkorDB/FalkorDB): sparse-matrix / GraphBLAS graph DB alternative; useful benchmark candidate, but SSPL license makes it a non-default production choice.
- [NebulaGraph](https://github.com/vesoft-inc/nebula): distributed graph DB future option if Atlas outgrows one machine.
- [GraphScope](https://github.com/alibaba/GraphScope): offline distributed graph analytics option if local/VPS graph jobs become too large.

## Product Goal

The Atlas should feel like a fast underground electronic music intelligence system:

- Search any entity from one omnibox without choosing entity type.
- Open a DJ and immediately see labels, venues, future activities, past appearances, mixtapes, social profiles, articles, and evidence.
- Open a club/label and see affiliated DJs, events, locations, social/media links, and source provenance.
- Explore a 3D graph smoothly: zoom, drag, roam, click, expand, and inspect evidence.
- Feed the weekly mini-program and LLM with compact, source-cited Atlas context.
- Preserve anti-scrape: no raw database download, no bulk graph export, no ID enumeration.

## Core Decision

Do not use one database for everything.

Use a **multi-index serving architecture**:

1. **Source Layer**: immutable `atlas.sqlite` and source artifacts. Private only.
2. **Build / Analytics Layer**: full canonical graph, taxonomy classifier, entity resolution, metrics, LOD graph generation. Private/offline.
3. **Serving Layer**: small, read-optimized artifacts for public web and mini-program APIs.
4. **Public Client Layer**: capped search/profile/graph-window APIs behind Turnstile/session gates.

This is faster and safer than exposing a live full graph DB to the public website.

## Recommended Stack

### Current Minimum Viable Production

- **Source DB**: existing `atlas.sqlite`.
- **Serving DB**: generated read-only `atlas_serving.sqlite`.
- **Search**: materialized `search_document` table + SQLite FTS5/trigram first, benchmark Meilisearch as the next index.
- **Semantic retrieval**: existing Qdrant role/vector collections for LLM/context only, not as the first exact-search path.
- **Graph visual API**: generated `graph_lod_*` tables in SQLite.
- **Frontend**: current `3d-force-graph` focus mode, then add Cosmograph/cosmos.gl Galaxy mode.

### Target Production After Benchmark

- **Omnibox search**: Meilisearch primary if memory/latency benchmarks pass; Typesense as direct competitor benchmark.
- **Private graph store**: ArcadeDB benchmark first. Keep it behind internal APIs; do not expose it directly to the public.
- **Public graph payloads**: still served from materialized LOD tables, not raw ArcadeDB queries.
- **Vector/LLM context**: Qdrant hybrid search plus strict source-cited profile cards.

### Future Scale Option

- NebulaGraph only if the project grows beyond a single server and needs distributed graph serving.
- GraphScope only for heavy offline analytics, not for the public request path.

## Performance Budgets

API budgets:

- Omnibox search p95: `< 150 ms`, p99 `< 350 ms`
- Typeahead after debounce: `< 80 ms` server time for top 8
- Entity profile card p95: `< 120 ms`
- Graph seed p95: `< 250 ms` for 300 nodes / 900 edges
- Graph expand p95: `< 350 ms` for 1,000 nodes / 3,000 edges
- Mini-program Atlas context p95: `< 200 ms`

Client budgets:

- Desktop 3D focus mode: max `1,200` nodes / `4,000` edges live
- Desktop Galaxy mode: max `50,000` visible points, aggregate edges first
- Mobile web: max `300` nodes / `800` edges
- Mini-program: no large interactive graph by default; use profile cards and short relation lists
- Initial graph payload gzip/br: desktop `< 1.5 MB`, mobile `< 350 KB`

## Database Artifacts

### 1. `atlas_source.sqlite`

This is the current full data source. It remains private.

Current scale:

- `articles`: 138,102
- `entities`: 1,510,787
- `events`: 608,678

Rules:

- No direct public serving.
- No browser download.
- No `/atlas.sqlite`.
- No raw ID enumeration.

### 2. `atlas_canonical.sqlite`

Generated canonical graph facts.

Tables:

```sql
canonical_entity(
  ceid TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  primary_taxon TEXT NOT NULL,
  secondary_taxa_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL,
  confidence REAL NOT NULL,
  source_count INTEGER NOT NULL,
  first_seen_at TEXT,
  last_seen_at TEXT,
  avatar_asset_id TEXT,
  summary TEXT,
  updated_at TEXT NOT NULL
);

entity_mention(
  mention_id TEXT PRIMARY KEY,
  ceid TEXT,
  source_article_uid TEXT NOT NULL,
  local_eid TEXT NOT NULL,
  name TEXT NOT NULL,
  entity_type_raw TEXT,
  confidence REAL,
  evidence_quote TEXT,
  UNIQUE(source_article_uid, local_eid)
);

event_occurrence(
  event_id TEXT PRIMARY KEY,
  source_article_uid TEXT NOT NULL,
  local_evid TEXT NOT NULL,
  name TEXT NOT NULL,
  place_ceid TEXT,
  starts_at TEXT,
  ends_at TEXT,
  time_text TEXT,
  city TEXT,
  confidence REAL,
  UNIQUE(source_article_uid, local_evid)
);

edge_fact(
  edge_id TEXT PRIMARY KEY,
  src_id TEXT NOT NULL,
  dst_id TEXT NOT NULL,
  rel_type TEXT NOT NULL,
  weight REAL NOT NULL,
  evidence_count INTEGER NOT NULL,
  evidence_json TEXT NOT NULL,
  first_seen_at TEXT,
  last_seen_at TEXT,
  accepted_for_graph INTEGER NOT NULL DEFAULT 0
);
```

Required indexes:

```sql
CREATE INDEX idx_canonical_entity_norm ON canonical_entity(normalized_name);
CREATE INDEX idx_canonical_entity_taxon ON canonical_entity(primary_taxon);
CREATE INDEX idx_entity_mention_source_local ON entity_mention(source_article_uid, local_eid);
CREATE INDEX idx_entity_mention_ceid ON entity_mention(ceid);
CREATE INDEX idx_event_time ON event_occurrence(starts_at, ends_at);
CREATE INDEX idx_edge_src_type ON edge_fact(src_id, rel_type);
CREATE INDEX idx_edge_dst_type ON edge_fact(dst_id, rel_type);
CREATE INDEX idx_edge_type_weight ON edge_fact(rel_type, weight DESC);
```

### 3. `atlas_serving.sqlite`

Public-serving read model. It is safe to deploy because it contains only capped, curated, precomputed public fields.

Tables:

```sql
search_document(
  doc_id TEXT PRIMARY KEY,
  ceid TEXT NOT NULL,
  display_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  handles_json TEXT NOT NULL DEFAULT '[]',
  primary_taxon TEXT NOT NULL,
  taxon_path TEXT NOT NULL,
  cities_json TEXT NOT NULL DEFAULT '[]',
  genres_json TEXT NOT NULL DEFAULT '[]',
  source_accounts_json TEXT NOT NULL DEFAULT '[]',
  source_count INTEGER NOT NULL DEFAULT 0,
  pagerank REAL NOT NULL DEFAULT 0,
  graph_degree INTEGER NOT NULL DEFAULT 0,
  future_event_count INTEGER NOT NULL DEFAULT 0,
  work_count INTEGER NOT NULL DEFAULT 0,
  social_count INTEGER NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 0,
  quality_score REAL NOT NULL DEFAULT 0,
  last_active_at TEXT,
  search_text TEXT NOT NULL
);

entity_profile_card(
  ceid TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  primary_taxon TEXT NOT NULL,
  subtitle TEXT NOT NULL,
  summary TEXT NOT NULL,
  avatar_url TEXT NOT NULL DEFAULT '',
  stats_json TEXT NOT NULL,
  top_relations_json TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL
);

entity_future_event(
  ceid TEXT NOT NULL,
  event_id TEXT NOT NULL,
  starts_at TEXT,
  ends_at TEXT,
  title TEXT NOT NULL,
  venue_ceid TEXT,
  venue_name TEXT,
  city TEXT,
  evidence_refs_json TEXT NOT NULL,
  PRIMARY KEY(ceid, event_id)
);

entity_work(
  work_id TEXT PRIMARY KEY,
  ceid TEXT NOT NULL,
  work_type TEXT NOT NULL,
  title TEXT NOT NULL,
  published_at TEXT,
  platform TEXT,
  public_url TEXT,
  evidence_refs_json TEXT NOT NULL
);

entity_social_profile(
  profile_id TEXT PRIMARY KEY,
  ceid TEXT NOT NULL,
  platform TEXT NOT NULL,
  handle TEXT,
  public_url TEXT NOT NULL,
  accepted_for_graph INTEGER NOT NULL DEFAULT 0,
  evidence_refs_json TEXT NOT NULL
);

weekly_atlas_context(
  weekly_item_id TEXT NOT NULL,
  ceid TEXT NOT NULL,
  role TEXT NOT NULL,
  confidence REAL NOT NULL,
  context_json TEXT NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  PRIMARY KEY(weekly_item_id, ceid, role)
);
```

### 4. `atlas_graph_lod.sqlite`

Graph visualization serving artifact.

Tables:

```sql
graph_node_lod(
  node_id TEXT PRIMARY KEY,
  ceid TEXT,
  label TEXT NOT NULL,
  taxon TEXT NOT NULL,
  level INTEGER NOT NULL,
  community_id TEXT,
  x REAL NOT NULL,
  y REAL NOT NULL,
  z REAL NOT NULL,
  size REAL NOT NULL,
  color_key TEXT NOT NULL,
  rank_score REAL NOT NULL,
  payload_json TEXT NOT NULL
);

graph_edge_lod(
  edge_id TEXT PRIMARY KEY,
  src_node_id TEXT NOT NULL,
  dst_node_id TEXT NOT NULL,
  rel_type TEXT NOT NULL,
  level INTEGER NOT NULL,
  community_id TEXT,
  weight REAL NOT NULL,
  payload_json TEXT NOT NULL
);

graph_window_cache(
  window_key TEXT PRIMARY KEY,
  level INTEGER NOT NULL,
  center_node_id TEXT,
  community_id TEXT,
  node_count INTEGER NOT NULL,
  edge_count INTEGER NOT NULL,
  payload_json_gzip BLOB NOT NULL,
  generated_at TEXT NOT NULL
);
```

Indexes:

```sql
CREATE INDEX idx_graph_node_level_rank ON graph_node_lod(level, rank_score DESC);
CREATE INDEX idx_graph_node_community ON graph_node_lod(community_id, level, rank_score DESC);
CREATE INDEX idx_graph_edge_src ON graph_edge_lod(src_node_id, level);
CREATE INDEX idx_graph_edge_dst ON graph_edge_lod(dst_node_id, level);
CREATE INDEX idx_graph_window_level_center ON graph_window_cache(level, center_node_id);
```

## Unified Search Design

The UI should have one search box only:

```text
Search any DJ, label, club, venue, party, mixtape, genre, city, article, handle...
```

The user should not choose entity type. The backend infers and ranks.

### Search Pipeline

1. Normalize query:
   - trim, casefold, full/half width normalize
   - remove invisible punctuation
   - preserve CJK
   - derive latin, handle, and pinyin-like keys when available
2. Exact match lane:
   - `normalized_name`
   - aliases
   - social handles
   - source account names
3. Prefix / typo lane:
   - Meilisearch/Typesense or FTS5 fallback
4. Semantic lane:
   - Qdrant only after exact/prefix lane, mainly for concepts/genres/descriptions
5. Graph lane:
   - boost centrality, trusted source count, future-event count, social proof, and accepted external links
6. Noise gate:
   - hard reject known non-electronic categories
   - downrank generic places, products, menu rows, and weak OCR artifacts

### Ranking Formula

```text
score =
  exact_name * 1000
  + alias_exact * 900
  + handle_exact * 850
  + prefix_match * 650
  + bm25_or_typo_score * 220
  + semantic_score * 120
  + log(source_count + 1) * 45
  + pagerank * 40
  + future_event_count * 25
  + social_count * 20
  + confidence * 80
  + recency_boost
  - noise_penalty
```

Search results are displayed with inferred badges:

- `DJ / person`
- `label / org`
- `club / venue`
- `event`
- `mixtape`
- `source`
- `profile candidate`

Badges explain the result. They are not required filters.

## Darwin-Style Taxonomy

Use a biological-taxonomy-like hierarchy, but allow secondary roles because music-scene entities are multi-role.

Ranks:

```text
realm      AtlasObject
kingdom    Actor | Organization | Place | Event | Work | Concept | Evidence | Asset | Quarantine
phylum     HumanArtist | Collective | VenueOperator | CityPlace | PartyProgram | AudioWork | SocialProfile ...
class      DJ | Producer | Label | Club | Festival | Mixtape | Track | WeChatArticle ...
order      TechnoDJ | BassDJ | ExperimentalLabel | UndergroundClub | WeeklyParty ...
family     LocalSceneCluster / LabelFamily / VenueFamily / GenreFamily
genus      Canonical group or scene cluster
species    Canonical entity / actual profile / actual event series
individual Mention instance or evidence row
```

Taxon examples:

| Entity | Primary taxon | Secondary roles |
| --- | --- | --- |
| `MaFoL` | `Actor.HumanArtist.DJ` | `Producer`, `EventParticipant`, `ProfileCandidate` |
| `DONG 洞` | `Place.Venue.Club` | `Organization.Promoter`, `SourceAccount` |
| `Do Hits` | `Organization.Label` | `Collective`, `EventOrganizer` |
| `BLOODLINE 解构俱乐部` | `Event.Series.Party` | `Concept.SceneSeries` |
| `MaFoL SoundCloud` | `Evidence.SocialProfile.SoundCloud` | `ExternalPublicProfile` |
| `Mixtape title` | `Work.AudioWork.Mixtape` | `PublishedMedia` |
| `院吧夏日新酒单` | `Quarantine.NonMusic.MenuAlcohol` | not public graph |

### Taxonomy Storage

```sql
taxon(
  taxon_code TEXT PRIMARY KEY,
  rank TEXT NOT NULL,
  parent_code TEXT,
  label TEXT NOT NULL,
  label_zh TEXT NOT NULL,
  description TEXT NOT NULL,
  public_visible INTEGER NOT NULL DEFAULT 1
);

entity_taxon_assignment(
  ceid TEXT NOT NULL,
  taxon_code TEXT NOT NULL,
  role TEXT NOT NULL,
  confidence REAL NOT NULL,
  evidence_refs_json TEXT NOT NULL,
  assigned_by TEXT NOT NULL,
  PRIMARY KEY(ceid, taxon_code, role)
);
```

### Taxonomy Assignment Algorithm

Order:

1. Hard rules from structured fields: `type`, `participants_json`, `place`, `source_account`, `event_count`, social domain.
2. Source-context rules: if an entity appears in lineup/participants repeatedly, prefer Actor/DJ; if it is an article account or organizer, prefer Organization.
3. Lexical rules:
   - `club`, `bar`, `livehouse`, `space`, `room`, 地址 => Place/Venue
   - `records`, `label`, `厂牌`, `collective` => Organization/Label
   - `mix`, `mixtape`, `podcast`, `radio show`, `set` => Work/AudioWork
   - `instagram`, `soundcloud`, `bandcamp`, `ra.co` => Evidence/SocialProfile
4. Graph rules:
   - many `EVENT_HAS_PARTICIPANT` edges => Actor
   - many `ORGANIZED_BY` edges => Organization
   - many `AT_PLACE` edges => Venue/Place
5. Ambiguous rows go to review. LLM can propose, but not auto-accept public graph edges.

## Graph LOD Algorithm

### Offline Build

1. Build canonical weighted graph from accepted public facts.
2. Run connected components.
3. Run community detection: Leiden/Louvain first; GraphScope only if scale requires.
4. Run PageRank, weighted degree, k-core, source diversity, recency.
5. Generate 3D coordinates offline:
   - stable seed from `ceid`
   - community center from component/community id
   - local coordinate from force layout or deterministic spiral fallback
6. Generate LOD levels:
   - `L0`: community/meta graph
   - `L1`: community representatives
   - `L2`: selected entity ego graph
   - `L3`: evidence/profile/work/detail rows, lazy-loaded

### Runtime

The runtime never computes full graph layout. It only:

- searches entities
- fetches precomputed graph windows
- expands a selected node within a hard budget
- hydrates profile/evidence sections on click

## Web API Contract

Public session-gated API:

```http
GET /api/v1/atlas/search?q=mafol&limit=12
GET /api/v1/atlas/entities/{ceid}/profile
GET /api/v1/atlas/entities/{ceid}/future-events?limit=20
GET /api/v1/atlas/entities/{ceid}/works?type=mixtape&limit=20
GET /api/v1/atlas/entities/{ceid}/social?acceptedOnly=true
GET /api/v1/atlas/graph/seed?q=mafol&mode=focus&limit=300
GET /api/v1/atlas/graph/window?token=...
GET /api/v1/atlas/graph/expand?nodeId=...&budget=1000
```

Mini-program / LLM internal API:

```http
GET /api/v1/weekly/atlas-context?itemId=...&role=lineup
GET /api/v1/weekly/atlas-entity/{ceid}/compact
POST /api/v1/weekly/atlas-context/batch
```

Response shape:

```json
{
  "schemaVersion": "atlas_entity_profile.v1",
  "ceid": "atlas:entity:person:...",
  "displayName": "MaFoL",
  "taxon": {
    "primary": "Actor.HumanArtist.DJ",
    "secondary": ["Producer", "EventParticipant"]
  },
  "stats": {
    "sourceCount": 12,
    "futureEventCount": 2,
    "workCount": 4,
    "socialCount": 3
  },
  "relations": {
    "labels": [],
    "venues": [],
    "futureEvents": [],
    "works": [],
    "socialProfiles": []
  },
  "evidenceRefs": [],
  "safety": {
    "bulkExportEnabled": false,
    "sourceScopedIds": true,
    "rawDbPathExposed": false
  }
}
```

## Mini-Program / Daily LLM Linkage

The mini-program should not query the full graph DB at request time.

Daily build flow:

1. Weekly event ingestion creates event cards.
2. Lineup/venue/organizer names are normalized.
3. Atlas search resolves each name to `ceid` candidates.
4. Strict confidence gate chooses accepted links; ambiguous matches become review-only.
5. `weekly_atlas_context` is materialized:
   - DJ profile summary
   - affiliated labels/collectives
   - future events
   - recent appearances
   - mixtapes/audio works
   - accepted public social profiles
   - citations/source hashes
6. The LLM uses only this compact context, not raw Atlas rows.
7. Mini-program displays compact sections and can deep-link to the public web graph when appropriate.

LLM guard:

- Context must include citations.
- Candidate-only social links must be labeled as candidates.
- No request-time external crawling.
- No raw source article dump in user-facing output.

## Anti-Scrape And Dark Database

Public clients get capability-based windows:

- Turnstile + httpOnly `atlas_session`
- per-session search budget
- per-session graph expansion budget
- signed `windowToken`
- node/edge caps
- no sequential `ceid` enumeration
- no full export endpoint
- no public raw DB files
- no response with all neighbors when degree is huge; return ranked top window only
- honeypot endpoints and bot UA challenge stay active

Recommended public payload behavior:

- top search results: max `20`
- graph seed: max `300` nodes default
- graph expand: max `1,000` nodes desktop, `300` mobile
- social/outlink profile list: max accepted/candidate split, with evidence labels
- mini-program compact profile: max `8` relations per section

## Implementation Slices

### Phase 1 - Serving Schema And Taxonomy

- Create taxonomy table and initial taxon tree.
- Generate source-scoped mention IDs for all entity/event mention rows.
- Generate `search_document` and `entity_profile_card`.
- Keep current SQLite/FTS path as the first serving DB.

Acceptance:

- `MaFoL`, `DONG 洞`, `OIL`, `TAG`, `Do Hits`, `Howie Lee` search from one box without type choice.
- Exact/alias/handle matches outrank same-article mentions.
- Non-electronic noise stays hidden.

### Phase 2 - Mini-Program Context Bridge

- Generate `weekly_atlas_context`.
- Add compact batch API for weekly items.
- Make daily LLM materialization consume compact Atlas context.

Acceptance:

- Weekly card can show a DJ's label/venue/future-event context when confidently resolved.
- Ambiguous links are marked candidate/review-only.
- LLM output includes citations and does not invent social links.

### Phase 3 - Graph LOD

- Generate `graph_node_lod`, `graph_edge_lod`, and `graph_window_cache`.
- Add graph seed/window/expand endpoints.
- Keep 3D focus mode capped and fast.

Acceptance:

- 300-node graph opens under `250 ms` API p95.
- 1,000-node expand opens under `350 ms` API p95.
- Browser drag/zoom remains smooth.

### Phase 4 - Search Engine Benchmark

- Benchmark Meilisearch vs Typesense vs SQLite FTS5 on `search_document`.
- Metrics: index size, memory, import time, exact search latency, typo search latency, CJK/English mix, filter/facet latency.
- Promote only if it beats SQLite without unacceptable memory cost.

Acceptance:

- P95 search under `150 ms`.
- Typeahead under `80 ms` after debounce.
- Exact identity searches remain deterministic.

### Phase 5 - Galaxy Mode

- Add `/atlas/galaxy` using Cosmograph/cosmos.gl.
- Load L0/L1 graph windows first.
- Click opens 3D focus mode or inspector.

Acceptance:

- Desktop can view community graph with tens of thousands of points.
- Public payload remains capped and signed.
- No full graph export is possible from browser requests.

## Default Deployment Shape

On `huaidj.club`:

- `atlas.huaidj.club`: public web graph and search.
- `api.huaidj.club` or existing weekly API: compact Atlas context for mini-program.
- Cloudflare: WAF, Turnstile, bot challenge, static asset caching.
- Origin: only sees proxied traffic; direct app port remains locked down.

Data deployment:

- Build artifacts locally or on a private build host.
- Upload versioned `atlas_serving.sqlite`, `atlas_graph_lod.sqlite`, optional Meilisearch dump.
- Atomic symlink swap on server.
- Smoke test before making version active.

## Non-Negotiables

- No full graph in browser.
- No raw `atlas.sqlite` public access.
- No type selector required for search.
- No global `local:e4` IDs.
- No accepted social/profile edge without evidence gate.
- No request-time LLM for public search/profile pages.
- No crawler-friendly pagination over every entity.
- No weakening Turnstile/session/rate-limit gates.
