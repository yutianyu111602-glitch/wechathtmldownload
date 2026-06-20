# ATLAS Next-Gen — DB Schema · Field Contract · Star Map Design — 2026-06-20

Design for the atlas serving DB + frontend contract + star map, grounded in the
**current full-extraction state** (G1–G5 accepted, G6 running, daily delta live).
Candidate-only; no production write/deploy implied by this doc.

Companion: [CLAUDE_HANDOFF_20260620.md](CLAUDE_HANDOFF_20260620.md) ·
[CLAUDE_STEPLOG_ATLAS_20260620.md](CLAUDE_STEPLOG_ATLAS_20260620.md) ·
G5 acceptance `assistant-handoff/54_*`, bio/delta `assistant-handoff/55_*`.

---

## 1. Where the data is now (G5 merged)

Stage3 entities: **dj 12262 · org 2888 · series 5666 · venue 1562**; events 20342;
participants 71661; b2b pairs 3156; vector/pinyin merge queue 9108 (ratio 0.41).
Stage4 candidate: `canonical_subject=11292` (**DJ only**), `dj_profile=11292`,
`performance_event=19053`, `dj_event=68032`, `dj_relation_rollup=199484`,
`dj_venue_rollup=29843`, `dj_org_rollup=65528`, `evidence_ref=23651`,
`activity_evidence_ref=112922`, `search_document=40526`, plus **`dj_bio_atom`=52671**
(verbatim bio spans, EN+ZH, attached to the serving DB).

Field coverage (G5 audit) — drives which fields are reliable vs sparse:
- **Core ≥0.9:** event title/date 1.0, venue 0.989, city 0.979, ticketing 0.969,
  lineup role 0.983 / perf_type 0.979, dj surface 1.0.
- **Mid 0.6–0.9:** lineup 0.905, organizer 0.878, time 0.877, dj name_en 0.895,
  dj social 0.845, styles 0.796/0.678, price 0.625, lineup name_en 0.608.
- **Sparse <0.2 (optional):** model `bio_snippet` 0.185, poster_credits, sponsors,
  age_policy, dress_theme → **verbatim bio comes from `dj_bio_atom`, not bio_snippet.**

**The gap:** venue/org/series are extracted but only live denormalized inside the
DJ rollups; they have no first-class identity, profile, geo, or relations. Series
has no serving table. Styles/social/geo/price/set_times/poster are captured but not
served as structured, queryable dimensions. The next-gen serving fixes this.

---

## 2. Next-gen serving DB (`atlas_serving.v2`)

Principle: **one unified subject model + typed relations + evidence-as-observations**,
all four entity types first-class, rich event attributes structured, bio verbatim.
Built by a new downstream `build_atlas_serving_v2.py` (Stage4.5) from the existing
Stage3/Stage4 candidate — additive, produced alongside v1 so the star map can switch.

### 2.1 Unified subject + per-type profiles
```sql
subject(                         -- replaces DJ-only canonical_subject
  subject_id TEXT PK,            -- canonical id; urn:atlas:{type}:{id}
  subject_type TEXT,             -- dj | venue | org | series | style | city
  display_name, normalized_name,
  aliases_json,                  -- resolved variants (cross-lang merged by pipeline)
  taxon_path,                    -- atlas/dj, atlas/venue, ...
  city_primary, geo_lat, geo_lng,
  event_count, relation_count, source_count,
  first_seen_at, last_seen_at, confidence, public_state)

subject_alias(alias_id, canonical_subject_id, reason)   -- merged-away ids -> canonical

dj_profile(subject_id PK, name_en, nationality, origin_city, roles_json,
  styles_json, social_json, gear, bio_snippet, avatar_asset_id,
  venue_count, collaborator_count, organization_count)
venue_profile(subject_id PK, name_en, district, address, geo_lat, geo_lng,
  venue_type, rooms, capacity, booth_gear_json, sound_brand_json, social_json,
  resident_dj_count, event_count)                       -- NEW (first-class)
org_profile(subject_id PK, org_type, city, social_json, roster_count, event_count)  -- NEW
series_profile(subject_id PK, venue_subject_id, organizer_subject_id, concept,
  edition_count)                                        -- NEW
```
`subject_type` enables one search/lookup/identity path for all entities. Profiles are
1:1 sparse side-tables (query-friendly; JSON only for genuinely list-shaped fields).

### 2.2 Events + participation (structured rich attrs)
```sql
event(event_id PK, title, title_display, date_start, date_end, time_text,
  set_times_json, city, venue_subject_id, address, room,
  organizer_subject_id, series_subject_id, presented_by_json,
  price_tiers_json, ticketing_json, styles_json, special_concept_json,
  age_policy, dress_theme, poster_asset_id, poster_credits_json,
  confidence, primary_source_ref_id)
participation(subject_id, event_id, role, performance_type, b2b_group,
  billing_order, source_ref_id, confidence)             -- generalizes dj_event
```

### 2.3 Unified typed relation (generalizes the 3 rollups)
```sql
relation(
  relation_id PK, src_subject_id, dst_subject_id, relation_type,
  -- b2b | collab | co_bill | resident_at | signed_to | affiliated
  --  | part_of_series | presents | in_city | plays_style
  weight, same_event_count, b2b_count, source_diversity,
  relation_label_zh, first_seen_at, last_seen_at,
  public_state, sample_evidence_json)
```
`same_label` stays withdrawn (not a type); `b2b` preserved. One table → the star map
reads every edge kind uniformly; lenses just filter `relation_type`.

### 2.4 Styles, bio, evidence/observations
```sql
style(style_id PK, name, parent_style_id)               -- light genre taxonomy
subject_style(subject_id, style_id, weight)             -- DJ/venue/event ↔ style
dj_bio_atom(...)            -- EXISTS: bio_text_raw, language, char span, section_heading,
                            --         source_ref_id, title/account, method, confidence, hash
source_ref(source_ref_id PK, source_hash, source_account, source_title,
  post_date, source_kind, public_url)                   -- ADD public_url (string|null)
observation(observation_id PK, target_kind, target_id,  -- NEW: provenance per fact/relation
  source_kind, source_ref_id, generation, extractor_version, confidence, observed_at)
search_document(... all subject types + events ...) + FTS5
meta(schema_version, generation, built_at, counts_json)
```
`observation` records *how* each relation/fact was learned (static extract vs vector
merge vs manual) across generations g1…g6+delta — supports confidence blending and
"why is this edge here" without stuffing JSON into the edge row.

### 2.5 Identity / dedup ownership
Cross-language + variant merging (Dada Beijing↔Dada Bar Beijing, OIL↔OIL油,
招待↔ZhaoDai, moon/Moon/MOON) is **owned by the pipeline** (Stage3 normalize + the
vector/pinyin merge queue), surfaced via `subject.aliases_json` + `subject_alias`.
→ The frontend's defensive `atlasContract` merge becomes a **fallback only**; counts
come authoritative from `subject.*_count`.

---

## 3. Frontend field contract (`atlas.v2`)

Versioned, additive (old clients ignore new fields; `schemaVersion` gates breaks).
Served either as REST (CloudRun) or precomputed static JSON (current model).

| Resource | Shape (camelCase) |
|---|---|
| `subject/{urn}` | `{ schemaVersion:"atlas.v2.subject", urn, type, displayName, aliases[], city, geo:{lat,lng}, counts:{events,relations,venues,collaborators,...}, profile:{...type-specific...}, firstSeenAt, lastSeenAt }` |
| `subject/{urn}/relations` | `[{ urn, type:b2b|collab|resident_at|signed_to|..., weight, sameEventCount, labelZh, peer:{urn,type,name}, evidence:[{title,date,sourceRefId}] }]` |
| `subject/{urn}/events` | `[{ eventId, title, dateStart, role, performanceType, venue:{urn,name}, city }]` |
| `subject/{urn}/bio` | `[{ text, language, sectionHeading, sourceRefId, sourceAccount, sourceTitle }]` (verbatim atoms) |
| `event/{id}` | full event: lineup[{urn,name,role,perfType,styles,b2bWith}], styles, priceTiers, ticketing, poster, series, organizer, venue, setTimes |
| `evidence/{sourceRefId}` | `{ sourceTitle, sourceAccount, postDate, publicUrl: string|null, sourceKind }` |
| `starmap/layout?lens=` | precomputed GraphData v2 (see §4.5) |

Rules: URN identity everywhere (`urn:atlas:{type}:{id}`); counts authoritative from DB;
`publicUrl` is a real http(s) string or `null` (null → evidence-only, no "open" button —
atlas history is `not_public` by design); bio rendered verbatim with language tag +
source; aliases exposed for display, never as separate nodes.

---

## 4. Star map v2

### 4.1 Nodes / edges
Node types: **dj · venue · org · series** (style + city are *facets*, not nodes, by
default). Edge types: b2b, collab, co_bill, resident_at, signed_to, affiliated,
part_of_series, presents.

### 4.2 Lenses (each = relation/node filter + layout + encoding)
| Lens | Nodes | Edges | Layout |
|---|---|---|---|
| **B2B 宇宙** (done) | dj | b2b, collab | Louvain constellations |
| **驻场地图** | dj, venue | resident_at | venue by real geo (lat/lng → projection), DJs orbit |
| **厂牌花名册** | org, dj | signed_to, affiliated | org-centric radial |
| **系列宇宙** | series, venue, org, dj | part_of_series, presents | hierarchical |
| **城市场景** | city facet → venue, dj | in_city + intra | city super-clusters |
| **曲风光谱** | dj/venue | (any) | color/cluster by dominant style |

### 4.3 Visual encoding
Color: by type (dj=scene/community hue, venue=amber #ffcf6b, org=violet #b794f6,
series=teal) OR by facet (city/style) in faceted lenses. Size: `event_count` /
`relation_count`. Edge: color by `relation_type`, width by `weight`. Bloom/additive
for the "星图" glow (already in the r3f graph-ui).

### 4.4 Interaction
Click node → type-aware profile card (DJ: bio atoms + social + top venues/collabs;
venue: geo/capacity/sound + resident DJs; org: roster; series: editions) + evidence.
Click edge → the events that created it (`sample_evidence_json`). Lens switcher;
search-to-focus; time scrubber (first_seen→last_seen) to animate scene growth.

### 4.5 Layout export contract (`atlas.starmap.v2`)
```json
{ "schemaVersion": "atlas.starmap.v2", "lens": "b2b_universe|residency_map|...",
  "nodes": [{ "id":int, "urn", "type", "x","y","z", "size", "color",
              "name", "city", "eventCount", "community",
              "geo": {"lat","lng"}|null, "styles": [..], "evidenceRef": "..." }],
  "edges": [{ "source":int, "target":int, "type", "weight", "labelZh",
              "evidence": [{title,date,sourceRefId}] }],
  "facets": { "cities": [...], "styles": [...], "types": [...] },
  "meta": { "generation", "counts": {...} } }
```
`export_starmap_layout.py` evolves to read `atlas_serving.v2` and emit **per-lens**
layouts. Current implementation reads `venue_profile.geo_*` for the residency lens and
projects matched venues from lat/lng; style taxonomy remains a pending dimension.
The current v1 (`atlas_starmap.layout.v1`, DJ+venue+org, 1746 nodes) stays valid until
v2 lands — the web app loads whichever `schemaVersion` is present.

---

## 5. Build path (phased, additive, non-breaking)

1. **Promote entities** — `build_atlas_serving_v2.py`: subject + venue/org/series
   profiles from existing Stage3 entities + rollups (data already there: 1562 venues,
   2888 orgs, 5666 series). Biggest unlock.
2. **Unify relations** — collapse the 3 rollups into `relation` + `observation`.
3. **Dimensions** — geo onto venues first slice is done via confirmed local registries;
   styles taxonomy and bio atoms + social into contract remain.
4. **Star map lenses** — per-lens layouts + lens switcher + geo/style/time.

Each phase: regenerate candidate v2, run the existing gate/field/artifact audits,
re-run the star map projection + web build, commit. Refresh off G6/delta as they land
(`subject.generation`/`meta.generation` tracks which ramp produced the data).

## Constraints
Candidate-only (no prod DB write/deploy/upload). `same_label` withdrawn; `b2b` kept.
Don't pause the paid fleet for local probes. cbm main = Codex's memory tool.
3D star map is a web app, not in the mini-program.
