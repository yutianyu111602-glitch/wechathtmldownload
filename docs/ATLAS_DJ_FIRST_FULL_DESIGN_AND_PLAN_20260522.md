# Atlas DJ-First Full Design And Execution Plan

Date: 2026-05-22

Status: CURRENT_AUTHORITY for the Atlas graph product model and next implementation plan. This is a design / planning artifact only. It does not authorize production graph writes, Qdrant writes, Neo4j writes, CloudRun deploys, mini-program uploads, paid API calls, secret reads, or server mutation.

Project: `C:\code\githubstar\wechathtmldownload`

## Executive Decision

Atlas is not a generic entity graph, event list, or article browser.

Atlas is a **DJ-first China underground electronic music relationship network and historical scene memory system**:

- The primary node is `DJ / artist / producer / performer`.
- The strongest facts come from historical and future `event / performance` records.
- Clubs, venues, labels, crews, cities, works, social profiles, and source articles exist to explain a DJ's scene position.
- Relation strength must be evidence-weighted: same event and same label matter; same article is only weak context.
- The browser never receives the full database. It receives capped search results, profile cards, LOD graph windows, and evidence summaries.

This corrects the earlier generic graph bias. Future Atlas graph work should optimize for questions such as:

- Search a DJ: where did this person play, who did they often play with, what labels/crews are they linked to, what clubs recur, what public accounts/mixtapes are known?
- Search a club: which DJs recur there, which historical events happened there, which labels/organizers are close to it, what city scene does it anchor?
- Search a label/crew: which artists, events, venues, works, and social profiles define the crew?
- Search an event: lineup, venue, organizer, source article, related past/future events, and later graph traversal.

## Current Data Reality

Current local Atlas SQLite read model:

- `articles`: `138,102`
- `entities`: `1,510,787`
- `events`: `608,678`

2026-05-22 quality audit correction:

- The full LLM run is not the same as a complete DJ-first graph. It created a broad article/entity/event surface.
- `reports\atlas_dj_product_loss_chain_20260522\audit.md` is the current loss-chain evidence for this gap.
- Event field completeness is the critical blocker for DJ history: `206,121 / 608,678` event rows have no participants, `141,601` have no place, `246,086` have no organizers, and all `608,678` rows have empty `time_iso`.
- Date evidence is present only as raw `time_text` for most rows; release-pack mapping did not normalize it into indexed historical/future dates.
- Non-music/product noise is real but smaller than the event-field gap: product rows `5,284`, noise-like entity rows `12,343`, noise-without-DJ articles `1,653`.
- Graph/API materialization can still under-serve the local release surface: release events `608,678`, graph unique events `158,490`, release-minus-graph events `450,188`; DJ collaboration usable events `191,100`, unusable events `417,578`.
- Therefore the next repair order is DJ-first: repair DJ-like entities with zero events, image/poster rows with zero events, participant-empty music rows, date normalization, and domain gating for wine/menu/product rows.

Important fields:

- `articles`: `article_uid`, `title`, `source_account`, `publish_time`, `city_label`, `entity_count`, `event_count`, `quality_grade`, `vector_text_preview`, `raw_json`
- `entities`: `eid`, `name`, `type`, `city`, `source_article_uid`, `confidence`, `aliases_json`, `bio`, `evidence_quote`, `vector_text_preview`, `raw_json`
- `events`: `evid`, `name`, `place`, `city`, `time_iso`, `time_text`, `source_article_uid`, `confidence`, `participants_json`, `organizers_json`, `vector_text_preview`, `raw_json`
- `identity_review_items`: `subject_name`, `subject_type`, `url`, `domain`, `source_account`, `source_article_uid`, `support_count`, `identity_signal_score`, `accepted_for_graph`, `identity_proof`, `graph_write_allowed`

Source interpretation:

- `articles` are evidence snapshots. They should not dominate the public graph as first-class product nodes.
- `events` are performance facts. They are the core bridge between DJ, venue, city, organizer, label, and source.
- `entities` are raw mention rows. They are not final canonical graph identities until merged.
- `identity_review_items` are public identity candidates. They are useful for social/profile cards only after strict acceptance.

Critical ID rule:

- `eid` and `evid` values such as `local:e4` and `local:ev1` are local to one article.
- Public IDs must be source-scoped by `source_article_uid + eid/evid` until a canonical ID exists.
- Final product IDs must use canonical IDs such as `dj:{hash}`, `venue:{hash}`, `label:{hash}`, `event:{hash}`.

## Product Ontology

### Node Classes

| Node class | Chinese label | Product role | Public priority |
| --- | --- | --- | --- |
| `canonical_dj` | DJ / 艺人 | Core identity and default search target | P0 |
| `performance_event` | 历史演出 / 活动 | Evidence fact layer connecting people and spaces | P0 |
| `canonical_venue` | 俱乐部 / 场地 | Scene anchor and event host | P0 |
| `canonical_label_org` | 厂牌 / Crew / 组织 | Affiliation and organizer network | P0 |
| `canonical_media_channel` | 电台 / 媒体 / 播客 | Radio, media, and mix channels such as SHCR, BYYB, baihui, CDCR | P1 |
| `city_scene` | 城市 / 场景 | Geography and community partition | P1 |
| `work_item` | Mixtape / 作品 / Set | Artist output and media identity | P1 |
| `public_profile` | 公开主页 / 外链 | Social identity proof and avatars | P1 |
| `source_article` | 来源文章 | Evidence and provenance only | P0 hidden-detail |
| `source_account` | 来源账号 / 公众号 | Source credibility and venue/account clue | P1 |

### Darwin-Style Taxonomy

Use a domain taxonomy to avoid flattening all entities:

| Level | Field | Example | Use |
| --- | --- | --- | --- |
| Realm | `realm` | 音乐场景 / 证据来源 / 地理空间 | Separate music graph from source/evidence graph |
| Kingdom | `kingdom` | 人与团体 / 空间 / 活动 / 作品 / 账号 / 文章 | Top-level UI families |
| Phylum | `phylum` | 艺人 / 场地 / 厂牌 / 演出 / 社交主页 | Default detail template |
| Class | `class` | DJ / Producer / Club / Label / Mixtape | Color, icon, relation template |
| Order | `order` | Techno / House / Bass / Ambient / Live set | Future style filters |
| Family | `family` | 城市社群 / 厂牌网络 / 驻场网络 | Community partition |
| Genus | `genus` | 同厂牌 / 常驻场地 / 系列活动 | Relation aggregation |
| Species | `species` | DJ+Producer, LabelMember, Resident-like | Ranking and badges |
| Individual | `individual` | MaFoL, OIL, DADA昆明, Do Hits | Search/click target |

## Relationship Ontology

Edges must represent music-scene meaning. `SAME_SOURCE_CONTEXT` is not enough.

| Edge | Direction | Evidence source | Chinese UI label | Strength |
| --- | --- | --- | --- | --- |
| `DJ_PLAYED_EVENT` | DJ -> Event | `events.participants_json`, lineup, OCR, article | 历史演出 | Strong |
| `EVENT_AT_VENUE` | Event -> Venue | `events.place`, address, source account | 活动场地 | Strong |
| `EVENT_IN_CITY` | Event -> City | `events.city`, article city | 所在城市 | Medium |
| `DJ_CO_PERFORMED_WITH_DJ` | DJ -> DJ | Same accepted event | 经常同台 | Strong |
| `DJ_AFFILIATED_WITH_LABEL` | DJ -> Label/Crew | bio, source text, social cross-link, organizer evidence | 关联厂牌 | Strong after gate |
| `LABEL_ORGANIZED_EVENT` | Label/Crew -> Event | `organizers_json`, title, source account | 主办活动 | Medium/Strong |
| `DJ_FEATURED_ON_MEDIA` | DJ -> MediaChannel | radio/podcast/mixtape article, public channel evidence | 电台 / 媒体出现 | Medium/Strong |
| `DJ_REGULAR_AT_VENUE` | DJ -> Venue | Repeated event participation | 常去场地 | Derived strong |
| `VENUE_REGULAR_DJ` | Venue -> DJ | Reverse rollup | 常见 DJ | Derived strong |
| `DJ_RELEASED_WORK` | DJ -> Work | public platform, article, source account | 作品 / Mixtape | Medium/Strong |
| `DJ_HAS_PUBLIC_PROFILE` | DJ -> PublicProfile | accepted identity evidence | 公开主页 | Strong after gate |
| `ENTITY_SAME_SOURCE_CONTEXT` | Any -> Any | same article only | 同文共现 | Weak context |
| `SOURCE_SUPPORTS_FACT` | SourceArticle -> Fact | article UID and quote | 证据来源 | Evidence edge |

Rule: a public UI must not label a same-article co-mention as "collaboration" unless event, label, work, or repeated-scene evidence supports it.

## Canonicalization Plan

Raw mentions must become canonical scene identities.

### Canonical DJ Identity

Table target: `canonical_dj`

Required fields:

```sql
canonical_dj(
  dj_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  aliases_json TEXT NOT NULL DEFAULT '[]',
  handles_json TEXT NOT NULL DEFAULT '[]',
  city_primary TEXT,
  city_candidates_json TEXT NOT NULL DEFAULT '[]',
  activity_start_at TEXT,
  activity_end_at TEXT,
  avatar_asset_id TEXT,
  public_profile_count INTEGER NOT NULL DEFAULT 0,
  source_article_count INTEGER NOT NULL DEFAULT 0,
  event_count INTEGER NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Merge signals:

- Exact normalized name, case-insensitive English match, Chinese simplified/traditional normalization.
- Alias JSON overlap.
- Same source account and repeated event co-occurrence.
- Social handle equality after strict accepted profile review.
- City/venue consistency.
- Avoid over-merging common names, city names, generic roles, brands, and product rows.

### Canonical Venue

Table target: `canonical_venue`

Fields: `venue_id`, `display_name`, `normalized_name`, `aliases_json`, `city`, `address`, `source_accounts_json`, `geo_lat`, `geo_lon`, `event_count`, `regular_dj_count`, `confidence`, `status`.

Venue merge signals:

- `events.place` variants.
- Source account name such as `OIL油`, `Dada Kunming`, `All俱乐部`.
- City and address/geocode consistency.
- Repeated event hosting.

### Canonical Label / Crew / Organization

Table target: `canonical_label_org`

Fields: `org_id`, `display_name`, `normalized_name`, `aliases_json`, `org_type`, `city`, `source_accounts_json`, `artist_count`, `event_count`, `confidence`, `status`.

Org merge signals:

- Entity type `organization`, `brand`, known label/crew keywords.
- Event organizer fields.
- Repeated same lineup around one name.
- Accepted public profile links only after review.

### Canonical Media Channel / Radio

Table target: `canonical_media_channel`

Fields: `channel_id`, `display_name`, `normalized_name`, `aliases_json`, `channel_type`, `source_accounts_json`, `featured_dj_count`, `work_count`, `confidence`, `status`.

Radio/media channels are music-relevant scene nodes, not noise. Confirmed or candidate seeds include `SHCR`, `BYYB`, `baihui`, and `CDCR`.

2026-05-22 public web spot-check:

- `SHCR` is publicly described as Shanghai Community Radio / a live-streaming platform for Shanghai underground arts and music.
- `BYYB` / `byyb.radio` is publicly described as a Shanghai community / neighborhood radio music platform.
- `BAIHUI` / `baihui` is publicly described by RA and DJ Mag as an online / independent radio station focused on Chinese underground/electronic music communities.
- `CDCR` is confirmed as Chengdu Community Radio / CDCR.live after user confirmation plus public evidence from The China Project and RNZ.
- `c1tyA1d2er` is confirmed as a DJ/artist by public RA lineup evidence. If it appears in `events.place`, treat that row as field noise / misfielded performer, not as a venue.

Unknown short acronyms or channel names should be verified through public web evidence before being promoted into this rule set. Use the local open-source verification stack recorded in `C:\code\githubstar\LOCAL_OPEN_SOURCE_INDEX.md`: SearXNG / ordinary public search first, then OpenCLI, Scrapling, Lightpanda, Maigret, or Camofox as bounded report-only evidence tools when needed.

## Materialized Relation Model

Do not compute all relation logic at request time. Build read-optimized sidecar tables.

2026-05-22 implementation update:

- `tools/stage7_rewrite/scripts/build_atlas_dj_history_rollup.py` is the current report-only implementation seam for this model.
- It treats DJ as the primary subject and materializes full DJ historical performance facts first: `dj_profile`, `dj_event`, `dj_collaborator`, `dj_venue`, `dj_organization`, `dj_media`, and `evidence_ref`.
- The builder reads source `atlas.sqlite` read-only and writes only sidecar JSONL / Markdown / SQLite artifacts under `reports/`.
- Initial real proof:
  - Focus run over `MaFoL`, `c1tyA1d2er`, `DaRou`, `GuangYu`, `MUYANG`: `270` DJ-event facts, `322` collaborator rollups, `48` venue rollups.
  - Top-25 DJ batch: `22,521` DJ-event facts, `9,401` collaborator rollups, `1,157` venue rollups.
- `SHCR` and `c1tyA1d2er` field-noise cases are resolved through curated public rules instead of polluting venue rollups.

### Core Tables

```sql
dj_event_edge(
  dj_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  role TEXT NOT NULL,
  confidence REAL NOT NULL,
  source_article_uid TEXT NOT NULL,
  evidence_quote TEXT,
  PRIMARY KEY(dj_id, event_id, source_article_uid)
);

event_venue_edge(
  event_id TEXT PRIMARY KEY,
  venue_id TEXT,
  city_id TEXT,
  place_text TEXT,
  confidence REAL NOT NULL,
  source_article_uid TEXT NOT NULL
);

dj_dj_relation_rollup(
  src_dj_id TEXT NOT NULL,
  dst_dj_id TEXT NOT NULL,
  same_event_count INTEGER NOT NULL DEFAULT 0,
  same_label_count INTEGER NOT NULL DEFAULT 0,
  same_work_count INTEGER NOT NULL DEFAULT 0,
  same_venue_count INTEGER NOT NULL DEFAULT 0,
  same_source_context_count INTEGER NOT NULL DEFAULT 0,
  source_diversity INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT,
  last_seen_at TEXT,
  relation_score REAL NOT NULL,
  relation_label_zh TEXT NOT NULL,
  sample_evidence_json TEXT NOT NULL,
  public_state TEXT NOT NULL,
  PRIMARY KEY(src_dj_id, dst_dj_id)
);

dj_venue_rollup(
  dj_id TEXT NOT NULL,
  venue_id TEXT NOT NULL,
  played_event_count INTEGER NOT NULL DEFAULT 0,
  source_diversity INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT,
  last_seen_at TEXT,
  affinity_score REAL NOT NULL,
  sample_evidence_json TEXT NOT NULL,
  PRIMARY KEY(dj_id, venue_id)
);

dj_label_rollup(
  dj_id TEXT NOT NULL,
  org_id TEXT NOT NULL,
  explicit_member_evidence_count INTEGER NOT NULL DEFAULT 0,
  organized_event_participation_count INTEGER NOT NULL DEFAULT 0,
  shared_release_count INTEGER NOT NULL DEFAULT 0,
  official_crosslink_count INTEGER NOT NULL DEFAULT 0,
  label_score REAL NOT NULL,
  public_state TEXT NOT NULL,
  sample_evidence_json TEXT NOT NULL,
  PRIMARY KEY(dj_id, org_id)
);

dj_work_rollup(
  dj_id TEXT NOT NULL,
  work_id TEXT NOT NULL,
  work_type TEXT NOT NULL,
  title TEXT NOT NULL,
  platform TEXT,
  public_url TEXT,
  confidence REAL NOT NULL,
  sample_evidence_json TEXT NOT NULL,
  PRIMARY KEY(dj_id, work_id)
);

dj_media_rollup(
  dj_id TEXT NOT NULL,
  channel_id TEXT NOT NULL,
  mention_count INTEGER NOT NULL DEFAULT 0,
  featured_work_count INTEGER NOT NULL DEFAULT 0,
  source_diversity INTEGER NOT NULL DEFAULT 0,
  media_score REAL NOT NULL,
  sample_evidence_json TEXT NOT NULL,
  PRIMARY KEY(dj_id, channel_id)
);
```

### Evidence Table

```sql
evidence_ref(
  evidence_id TEXT PRIMARY KEY,
  fact_id TEXT NOT NULL,
  fact_type TEXT NOT NULL,
  source_article_uid TEXT,
  source_title TEXT,
  source_account TEXT,
  publish_time TEXT,
  quote TEXT,
  url_hash TEXT,
  evidence_strength TEXT NOT NULL,
  visible_excerpt TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
```

Public APIs return evidence summaries and short excerpts, not raw full articles or raw database paths.

## Relation Scoring

### DJ-DJ Relation

```text
dj_relation_score =
  3.0 * exact_same_event_count
+ 2.2 * same_label_count
+ 1.8 * same_work_count
+ 1.4 * recurring_same_venue_count
+ 0.6 * same_source_music_context_count
+ recency_bonus
+ source_diversity_bonus
+ identity_confidence_bonus
- ambiguity_penalty
- noise_penalty
```

Labels:

- `经常同台`: same event count >= 2, or one high-confidence event plus multiple source confirmations.
- `同厂牌 / 同组织`: label score passes gate.
- `同场景高频出现`: same venue / same city / same source account recurrence, but not enough for collaboration.
- `同文共现`: same article only; weak gray edge.

### DJ-Venue Affinity

```text
venue_affinity_score =
  2.5 * played_event_count
+ 1.2 * future_event_count
+ 1.0 * distinct_series_count
+ recency_bonus
+ source_diversity_bonus
- low_confidence_penalty
```

Output:

- `常去场地`: high affinity.
- `历史演出场地`: event evidence exists, lower frequency.
- `来源账号上下文`: only source account match, no event fact.

### DJ-Label Affiliation

```text
label_affinity_score =
  3.0 * explicit_label_member_evidence
+ 2.0 * organized_event_participation
+ 1.5 * shared_release_or_mixtape
+ 1.0 * official_social_crosslink
+ source_diversity_bonus
- candidate_only_penalty
```

Only `public_state=accepted` can appear as a solid affiliation edge. Candidate-only links must be dashed and shown under `候选证据`.

### Work / Mixtape Evidence

Accept a `work_item` when at least one of these holds:

- official platform link plus artist name match;
- article title/body explicitly names artist and work;
- source account is a known radio/label/club account and the page contains a music platform URL;
- multiple weak sources jointly pass a review gate.

Do not treat generic article titles as works.

## Search Architecture

Public UX uses one Chinese omnibox. No visible entity type selector.

Search stages:

1. Normalize query: case fold, width fold, whitespace, punctuation, Chinese variants, handle cleanup.
2. Exact canonical hit: `canonical_dj`, `canonical_venue`, `canonical_label_org`, `canonical_media_channel`, `work_item`.
3. Alias/handle hit.
4. FTS hit over canonical search document.
5. Relation-backed boost: source count, event count, recent activity, graph degree, DJ-first priority.
6. Optional Meilisearch benchmark path for typo tolerance/facets.
7. Optional Qdrant hybrid retrieval for LLM context, not first exact search.

Search result order:

1. High-confidence DJ exact/alias matches.
2. Venue/club exact matches.
3. Label/crew exact matches.
4. Events and works.
5. Source articles only as evidence, never the default top result when an identity exists.

Serving table:

```sql
search_document(
  doc_id TEXT PRIMARY KEY,
  canonical_id TEXT NOT NULL,
  entity_kind TEXT NOT NULL,
  display_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  aliases_json TEXT NOT NULL,
  handles_json TEXT NOT NULL,
  taxon_path TEXT NOT NULL,
  cities_json TEXT NOT NULL,
  source_accounts_json TEXT NOT NULL,
  search_text TEXT NOT NULL,
  exact_boost INTEGER NOT NULL DEFAULT 0,
  dj_priority INTEGER NOT NULL DEFAULT 0,
  event_count INTEGER NOT NULL DEFAULT 0,
  source_count INTEGER NOT NULL DEFAULT 0,
  relation_degree INTEGER NOT NULL DEFAULT 0,
  recent_activity_at TEXT,
  quality_score REAL NOT NULL DEFAULT 0
);
```

## Graph Visualization Plan

Use two graph modes instead of one universal renderer.

### Focus Mode

Path: `/atlas/graph`

Renderer: current `3d-force-graph` / Three.js WebGL.

Purpose:

- DJ-centered ego network.
- Click / double-click expand.
- Inspector evidence.
- Roam mode over bounded neighborhoods.

Caps:

- Desktop: default 300 nodes / 900 edges, hard cap 1,200 nodes / 4,000 edges.
- Mobile: default 120 nodes / 300 edges, hard cap 300 nodes / 800 edges.

### Galaxy Mode

Future path: `/atlas/galaxy`

Renderer: Cosmograph / `@cosmos.gl/graph`.

Purpose:

- Dense overview of scenes, cities, labels, and communities.
- Precomputed 2D coordinates.
- Histogram filters and community filters.
- Click into Focus Mode for detail.

Caps:

- Public Galaxy L0: 1,000-3,000 community/meta nodes.
- Authenticated operator Galaxy L1: larger community windows after local benchmark.
- No full raw graph dump.

### UI Rules

Chinese labels only:

- 顶部: 搜索, 深度, 关系镜头, 漫游, 适配画布, 重置, 截图
- 左栏: 常用入口, 节点过滤, 关系过滤, 搜索结果, 探索记录
- 右栏: 身份档案, 历史演出, 常去场地, 常合作, 厂牌组织, 作品/mixtape, 公开主页, 证据来源
- 底栏: 节点数, 关系数, 延迟, 数据库版本, 反爬状态

Visual direction:

- Dense desktop workbench, not landing page.
- Dark graphite canvas, compact panels, 12-14px text, 4/8/12/16 spacing.
- DJ/person cyan, venue amber, label green, event orange/red, work blue-gray, source muted gray.
- Candidate social edges are dashed and visually secondary.

## Public API Shape

All routes are read-only, session-gated, rate-limited, and capped.

```text
GET /api/v1/atlas/search?q=...
GET /api/v1/atlas/entities/:canonicalId/profile
GET /api/v1/atlas/djs/:djId/network?lens=dj-career&depth=1
GET /api/v1/atlas/venues/:venueId/network?lens=venue-ecosystem
GET /api/v1/atlas/labels/:orgId/network?lens=label-network
GET /api/v1/atlas/events/:eventId/network
GET /api/v1/atlas/graph/window?token=...
GET /api/v1/atlas/evidence/:factId
```

Compatibility wrappers can keep the current `/api/v1/stage7/graph/*` paths during migration.

Response rules:

- include `schemaVersion`;
- include `safety.bulkExportEnabled=false`;
- include `limits` and `remainingBudget`;
- include `evidenceRefs` only as samples;
- hide raw file paths, raw DB paths, internal row IDs, and full article bodies;
- reject `limit` above hard caps;
- reject missing/invalid session for graph/data endpoints.

## Database / Storage Architecture

Use layered stores:

1. `atlas_source.sqlite`: current private immutable-ish source read model.
2. `atlas_canonical.sqlite`: canonical DJs, venues, labels, events, works, and evidence refs.
3. `atlas_serving.sqlite`: public read model for search/profile/graph windows.
4. `atlas_layout.duckdb` or Parquet: offline analytics, community metrics, layout coordinates.
5. Private graph benchmark store: ArcadeDB first; FalkorDB and NebulaGraph only as benchmarks/future options.

Public serving should start with SQLite sidecars because the current server already runs SQLite successfully and the anti-scrape model prefers small read models over exposing a live graph DB.

## Open-Source Wheel Decisions

GitHub metadata checked on 2026-05-22 via GitHub API.

| Project | Stars | License | Decision | Role |
| --- | ---: | --- | --- | --- |
| `vasturiano/3d-force-graph` | 6,049 | MIT | Keep | Current cinematic Focus Mode |
| `cosmosgl/graph` | 1,153 | MIT | Adopt next | GPU dense Galaxy Mode |
| `jacomyal/sigma.js` | 12,030 | MIT | Keep fallback | 2D graph fallback / simpler canvases |
| `graphology/graphology` | 1,669 | MIT | Keep fallback | JS graph model and algorithms |
| `meilisearch/meilisearch` | 57,667 | noassertion in GitHub API | Benchmark | Typo-tolerant one-box search and facets |
| `qdrant/qdrant` | 31,464 | Apache-2.0 | Keep sidecar | Hybrid/semantic LLM context, not exact search first |
| `duckdb/duckdb` | 38,343 | MIT | Use offline | Analytics/layout/materialization over Parquet |
| `ArcadeData/arcadedb` | 892 | Apache-2.0 | Benchmark first graph DB | Private graph store, Cypher/Gremlin/SQL, multi-model |
| `FalkorDB/FalkorDB` | 4,437 | noassertion in GitHub API | Benchmark only | Sparse-matrix graph alternative; license risk blocks default |
| `vesoft-inc/nebula` | 12,177 | Apache-2.0 | Future scale only | Distributed graph if single-node stack outgrows |
| `cylynx/motif.gl` | 139 | MIT | Product-reference only | High-level graph workbench inspiration |
| `kuzudb/kuzu` | 3,915 | MIT | Reject for production | Archived repository as checked 2026-05-22 |

Official source notes:

- `cosmosgl/graph` states GPU force layout and rendering happen on WebGL shaders and target hundreds of thousands of points/links on modern hardware.
- Cosmograph positions itself as browser graph analytics with filtering/search and DuckDB-backed local analysis.
- Meilisearch requires filterable/sortable attributes to build optimized structures for filtering/faceting/sorting.
- ArcadeDB official docs describe a multi-model graph/document/key-value/search/vector/time-series DB with SQL/Cypher/Gremlin and Apache 2.0 Community Edition.
- Qdrant hybrid queries are useful for dense+sparse context retrieval, but should not replace exact canonical search.

Media/radio and misfielded-artist public verification links used in the 2026-05-22 spot-check:

- SHCR: https://www.mqw.at/institutionen/kulturmieterinnen/frei-raum-q21-exhibition-space/no-dancing-allowed/shanghai-community-radio
- SHCR: https://soundcloud.com/shcradio
- BYYB: https://www.smartshanghai.com/event/e-fruity-x-byyb-radio-daytime-party-livestream-2026-03-08
- BYYB: https://ra.co/events/2037302
- BAIHUI: https://ra.co/news/75563
- BAIHUI: https://djmag.com/news/new-underground-music-station-baihui-launches-beijing
- CDCR: https://thechinaproject.com/2021/06/08/sleepless-in-chengdu/
- CDCR: https://www.rnz.co.nz/national/programmes/culture-101/audio/2018926356/kristen-ng-bridging-aotearoa-and-china-s-musical-undergrounds
- c1tyA1d2er: https://ja.ra.co/events/2198725

## Anti-Scrape Architecture

The dark database rule is non-negotiable.

Public users must not be able to reconstruct the full Atlas by crawling.

Required controls:

- Cloudflare proxied host and origin lock.
- Turnstile-backed `atlas_session`.
- HTTP-only, secure, short-lived session cookie.
- Separate rate limits for search, profile, graph window, expand, random walk, and evidence.
- No public list-all endpoints.
- No raw `atlas.sqlite`, `.db`, JSON dump, CSV export, or bulk graph export.
- Opaque graph window tokens; no predictable offset pagination.
- Honey endpoints: `/atlas.sqlite`, `/api/v1/stage7/export`, `/api/v1/stage7/full-graph`, `/atlas.json`.
- Per-session and per-IP budgets.
- Response watermark metadata for graph windows.
- Capped related lists and sampled evidence.
- Operator-only private APIs must stay behind server access, not public Cloudflare paths.

Default public caps:

| Surface | Default | Hard cap |
| --- | ---: | ---: |
| Search visible hits | 8 | 30 |
| Search API rows | 20 | 100 |
| DJ profile relation rows | 12 per section | 50 per section |
| Graph focus seed | 300 nodes / 900 edges | 1,200 nodes / 4,000 edges |
| Graph expand | 80 nodes | 200 nodes |
| Random walk | 5 steps | 20 steps |
| Evidence samples | 5 | 20 |

## Mini-Program / LLM Integration

Mini-program should not render a full graph. It should consume compact Atlas context cards:

- DJ card: aliases, city, upcoming events, frequent venues, frequent collaborators, labels, source confidence.
- Venue card: upcoming events, recurring DJs, common labels/organizers, city.
- Event card: lineup, venue, organizer, source article, related historical events.

LLM context API:

```text
GET /api/v1/atlas/context?name=MaFoL&intent=event_recommendation
```

Returns:

- top canonical match;
- compact facts;
- source citations;
- confidence;
- no raw full article body;
- no graph traversal beyond current budget.

## Implementation Roadmap

### P0 - Product Lock

Deliverables:

- This document as DJ-first design authority.
- Update documentation index and current-runtime.
- Keep previous generic graph docs as active evidence, not the top product model.

Acceptance:

- Future Atlas work can answer: "is this change DJ-first, evidence-backed, anti-scrape safe?"

### P1 - Canonical Identity Builder

Deliverables:

- `build_atlas_canonical_music_entities.py`
- tables: `canonical_dj`, `canonical_venue`, `canonical_label_org`, `canonical_media_channel`, `canonical_event`, `entity_mention_link`
- deterministic merge rules and review queue for ambiguous merges
- regression seeds: `MaFoL`, `OIL`, `DADA昆明`, `BO LIVE`, `TAG`, `ALL`, `DONG 洞`

Acceptance:

- exact DJ/venue/label searches map to canonical IDs;
- no `local:e4` collision class remains on public paths;
- known alcohol/product/noise rows do not become canonical music identities.

### P2 - DJ Relation Rollups

Deliverables:

- `build_dj_relation_rollups.py`
- tables: `dj_event_edge`, `event_venue_edge`, `dj_dj_relation_rollup`, `dj_venue_rollup`, `dj_label_rollup`, `dj_media_rollup`, `dj_work_rollup`, `evidence_ref`
- weighted scores and sampled evidence

Acceptance:

- `MaFoL` profile returns historical events, recurring venues, and collaborators from full source history;
- `OIL` profile returns recurring DJs and historical events without dumping all raw rows;
- profile p95 remains under `1200ms` before sidecar materialization and under `200ms` after sidecar.

### P3 - One-Box Search And Chinese Profiles

Deliverables:

- `search_document` materialization.
- FTS exact/alias/handle search.
- Optional Meilisearch benchmark pack.
- `/api/v1/atlas/search` compatibility layer.
- Chinese UI profile sections in `/atlas/graph`.

Acceptance:

- no visible type selector;
- `MaFoL`, `OIL`, `DADA昆明`, `BO LIVE`, `TAG`, `DONG 洞` top result accuracy >= 95% on golden set;
- source articles are not ranked above canonical DJ/venue when the query is an identity.

### P4 - Graph Window API And LOD Cache

Deliverables:

- `graph_lod_window` table.
- signed window token.
- `/api/v1/atlas/djs/:id/network`
- `/api/v1/atlas/venues/:id/network`
- `/api/v1/atlas/labels/:id/network`

Acceptance:

- no endpoint returns all nodes or all edges;
- graph payloads include caps and safety fields;
- desktop focus mode stays responsive under hard cap;
- mobile uses lower cap automatically.

### P5 - Galaxy Mode Benchmark

Deliverables:

- Cosmograph/cosmos.gl proof page under local-only path first.
- Precomputed coordinates in DuckDB/Parquet or SQLite sidecar.
- community/meta graph L0.

Acceptance:

- renders nonblank canvas on desktop and mobile;
- supports search/filter/click into Focus Mode;
- does not expose raw full graph.

### P6 - Private Graph DB Benchmark

Deliverables:

- ArcadeDB import benchmark with CSV/Parquet bulk load.
- FalkorDB benchmark only if license/ops risk is acceptable.
- NebulaGraph rejected unless single-node cannot satisfy private analytics.

Acceptance metrics:

- import time;
- disk size;
- memory pressure;
- 1-hop / 2-hop query p95;
- PageRank/community runtime;
- ops complexity on current Singapore VPS.

Decision rule:

- If ArcadeDB is heavy on VPS, keep it offline/local only and deploy only materialized serving artifacts.

### P7 - Anti-Scrape Hardening Before Public Scale

Deliverables:

- session budget ledger;
- opaque cursors;
- endpoint-specific limits;
- honey endpoint logging;
- response watermark;
- no-cache rules for data APIs;
- cache rules for static JS/CSS only.

Acceptance:

- no-session data API returns 403;
- scripted UA is challenged/blocked;
- `/atlas.sqlite` and export probes return 403;
- direct origin bypass stays blocked.

## Self-Test Matrix

Golden search seeds:

- DJs/persons: `MaFoL`, `Howie Lee`, `MIIIA`, `Difan`, `DaRou`, `GuangYu`, `MUYANG`
- Venues/clubs: `OIL`, `DADA昆明`, `Dada Beijing`, `TAG`, `ALL`, `BO LIVE`, `DONG 洞`
- Labels/crews/orgs: `Do Hits`, `SVBKVLT`, `Genome 6.66 Mbp`, `DIRTY HOUSE`
- Media/radio: `SHCR`, `BYYB`, `baihui`, `CDCR`
- Noise negatives: `葡萄酒`, `酒单`, `菜单`, `咖啡`, `餐厅`, `招聘`, `瑜伽`, `酒店推荐`, `课程表`

Required checks:

- exact top-1 or top-3;
- no noise promoted into public graph;
- DJ profile has events or clearly reports no events;
- collaborator edges are typed correctly;
- source/evidence samples exist for strong relations;
- API latency budgets pass;
- response does not include raw DB path or internal export controls;
- no model/vector/graph/database writes happen in read-only tests.

## Non-Goals

- Do not send the full graph to the browser.
- Do not expose all rows through pagination.
- Do not label weak co-mentions as collaboration.
- Do not accept public social/profile edges without strict evidence.
- Do not use archived Kuzu as production base.
- Do not turn the Atlas website into a crawler.
- Do not let mini-program needs override the Atlas DJ-first graph model.

## Immediate Next Engineering Slice

Recommended next slice after this plan:

1. Create `build_atlas_canonical_music_entities.py` over the current `atlas.sqlite`.
2. Produce a small `atlas_canonical_music_canary.sqlite` for golden seeds only.
3. Build `canonical_dj`, `canonical_venue`, `canonical_label_org`, and `canonical_media_channel`.
4. Run golden query tests and negative noise tests.
5. Only after canary passes, materialize `dj_dj_relation_rollup` and `dj_venue_rollup`.

This is the narrowest implementation path that changes the product from "raw entity graph" into "DJ-first underground scene graph" without exposing the raw database or inventing a new graph engine from scratch.
