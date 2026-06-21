# ATLAS 全量地下电子音乐图书馆 — 数据库构造 · 前后端契约 · 日更管线 · 小程序 · iOS App 设计 — 2026-06-21

Grounded in the **accepted full-union 14w** candidate
(`_fleet_14w_g1_g7_full_union_fast2_retry_20260621/merged`) and the v2 serving built on it:
**87,169 subjects** (dj 45483 / venue 5760 / org 12092 / series 23834) + **845,192 relations**
(collab 378782 / signed_to 283719 / resident_at 129971 / held_at 22448 / presented_by 21337 / b2b 8935),
events 97,750, bio atoms 263,999. Companion: `ATLAS_NEXTGEN_DESIGN_20260620.md` (v2 schema),
`CODEX_HANDOFF_ATLAS_NEXTGEN_EXECUTION_20260620.md`. Candidate-only; no auto-deploy.

Primary surface = **WeChat mini-program**. Star map (web 3D) + iOS app are companions on the same contract.

## Guiding principle — this is a 图鉴 (reference atlas), NOT a game
Optimize for **readability + explorability**, never playability/spectacle. This is a strong **tool**:
- **Readable:** legible labels, clear structure, identifiable distinct nodes. You must be able to *read*
  who/what a node is, not just admire lights. Semantic zoom (labels appear as you focus; hub names always
  on). Restrained glow **in service of legibility** — never glare, never motion (twinkle/heavy bloom) that
  obscures reading. If a viewer can't tell two nodes apart or read a name, the effect is wrong.
- **Explorable:** search → jump, filter by type/lens/style/city, click → drill neighborhood, click → see
  evidence/source. Every fact traceable. The point is *finding and understanding*, not playing.
- Visual polish exists only to make structure clearer (color = type/scene, size = significance,
  proximity = relation). Cut anything decorative that doesn't aid reading or navigation.

---

## 0. The "节点太少" problem → the core design decision
The star map caps at ~1,339 nodes because it dumps one precomputed layout. With 87k subjects you
**cannot and should not render everything at once** (WebGL/phone budget, and it'd be noise). The library
is explored by **overview + drill**, not a single mega-dump:

- **L0 overview (precomputed):** per lens, the top-N backbone (~1.5–3k strongest subjects by
  relation strength / event_count) — the "galaxy you land in".
- **L1 neighborhood (on-demand):** click any node → fetch its k-hop neighborhood from the full DB and
  merge into the scene. Every one of the 87k subjects is reachable this way.
- **Search → teleport:** search any subject → camera flies to it (loading its neighborhood if outside L0).
So the *full library* is explorable, but the frame is always ~a few thousand live nodes. This is the
fix for "节点太少": not a bigger dump, but **bottomless drill-down**.

---

## 1. Full library DB construction (`atlas_serving.v2`, full-scale)
Source of truth = the full-union candidate (`atlas_serving_candidate.sqlite` + `atlas_serving_v2.sqlite`
from `build_atlas_serving_v2.py`). v2 already has: `subject`, `{dj,venue,org,series}_profile`, `event`,
`participation`, unified typed `relation`, `style`/`subject_style`, `dj_bio_atom`, `source_ref`,
`search_document`+FTS, `meta`. Add the **serving/read-model layer** for scale:

```sql
-- ranking + LOD selection (precomputed once per build)
node_rank(subject_id PK, subject_type, rank_score, degree, event_count, lens_flags)  -- top-N per lens
neighbor_index(subject_id, neighbor_id, relation_type, weight)                        -- fast k-hop fetch (indexed)
lens_overview(lens, payload_json, node_count, edge_count, generation)                 -- precomputed L0 layouts
search_document + FTS5                                                                -- already exists; covers all types
meta(schema_version, generation, built_at, counts_json)                              -- generation = g1_g7_full + dailies
```
- `node_rank.rank_score` = blend(relation_count, event_count, source_diversity) → drives L0 selection +
  star size + search ranking. Per-lens flags so each lens's L0 is its own top-N.
- `neighbor_index` is `relation` indexed both directions → O(degree) neighborhood fetch for L1.
- `lens_overview` stores the 6 precomputed L0 layouts (what the star map loads first).
- Identity/dedup stays pipeline-owned (Stage3 + vector/pinyin merge; `subject.aliases_json`).
- Generation tracking: every subject/relation/observation carries `generation`; dailies append.

**Serving artifacts produced per build** (by `atlas:rebuild`, regenerable, not committed):
`atlas_serving_v2.sqlite` (full) → `atlas_index.json.gz` (mp API read-model, **+social/bio** = B3) →
`lens_overview` layouts (`apps/atlas_starmap_web/public/atlas_layout.<lens>.json`).

---

## 2. Front/back contract (`atlas.v2`, full-scale)
Versioned, additive, camelCase, cursor-paginated. Served as static read-model (current) and/or REST.

| Resource | Purpose / shape |
|---|---|
| `lens/{lens}/overview` | precomputed L0 galaxy: `{schemaVersion, lens, nodes[], edges[], facets, meta:{generation}}` |
| `subject/{urn}` | profile (type-specific) + counts (authoritative) + `socialLinks[]` + geo + spans |
| `subject/{urn}/neighborhood?depth=1&limit=` | L1 drill: `{nodes[], edges[]}` around the subject (from `neighbor_index`) |
| `subject/{urn}/relations?type=&cursor=` | paginated typed relations + per-edge evidence |
| `subject/{urn}/events?cursor=` | participations/events |
| `subject/{urn}/bio` | verbatim `dj_bio_atom` by language + source |
| `event/{id}` | full event (lineup/styles/price/ticketing/poster/series/venue/setTimes) |
| `search?q=&type=&cursor=` | FTS over all subjects → ranked hits `{urn,type,name,city,rank}` |
| `evidence/{sourceRefId}` | source title/account/date + `publicUrl: string\|null` |

Rules: URN identity (`urn:atlas:{type}:{id}`); counts from DB (frontend `atlasContract` = fallback only);
`socialLinks` filtered (drop VL placeholders 未提及/未明确说明/无/N/A via latin-token rule — already in
`export_starmap_layout._clean_social` + `utils/djLinks`); `publicUrl` only a real http(s) string;
mini-program external links = copy-to-clipboard.

---

## 3. Daily auto-import pipeline (import + rebuild side; Codex owns extraction)
Codex's daily Sanji extraction (marker-only: only new HTML-backed articles) produces an accepted delta
candidate. **My side = auto-import into serving + rebuild**, gated and idempotent:

```
[Codex] sanji daily delta → extract → merge → gate/audit → accepted delta candidate root
            │  (only if gate=GO and audits ACCEPT)
            ▼
[import] daily_atlas_import.py  (new orchestrator)
  1. detect newest accepted delta root (read its final_report + gate snapshot; bail if not accepted)
  2. union the delta into the full root  (fleet_merge_roots add-delta, or rebuild union)
  3. build_atlas_serving_v2.py  (refresh subjects+relations; meta.generation += daily tag)
  4. backfill_venue_geo + node_rank + neighbor_index + lens_overview regenerate (atlas:rebuild)
  5. rebake atlas_index.json.gz (+social/bio) for the mp API
  6. write an import report (counts delta, new subjects/relations); DO NOT deploy
```
- Triggered after Codex's daily chain (a marker file / report the import polls), or `npm run atlas:daily-import`.
- Candidate-only: produces refreshed serving artifacts; **deploy/upload stays manual** (release thread).
- Idempotent: keyed on delta generation token; re-runs are no-ops if already imported.
- Boundary: never re-run full paid extraction; never write production DB; never auto-deploy.

---

## 4. Mini-program (primary)
Consumes `atlas.v2` via the cloudrun API. Already shipped: feed non-electronic filter, rich DJ card
(external media + 资料来源 + bio), venue upcoming/past split, source-open fix. Remaining for full-library mp:
- **B3 (data):** rebake `atlas_index.json.gz` so artist/venue/org/series APIs return social/bio/profiles.
- **Search page:** `/search` over all subjects → entity pages.
- **Entity pages parity:** venue/org/series detail pages mirroring the DJ rich card (profile + relations + events + evidence).
- **Lens entry points:** "本周一览" + atlas entry; the 3D star map is a web link (not in mp).

---

## 5. iOS app design (native companion)
A native iOS app (SwiftUI + Metal/SceneKit) on the same `atlas.v2` contract. Dark underground-neon
aesthetic matching the star map.

**Information architecture (tab bar):**
1. **活动 Feed** — this-week electronic events (city/date filter), poster-forward cards → event detail.
2. **星图 Explore** — the 3D star map, **native Metal/SceneKit** (not a webview): L0 overview galaxy +
   tap-to-expand neighborhood + pinch/orbit + search-teleport. Lens switcher (B2B/驻场/厂牌/系列/城市/曲风).
3. **搜索 Search** — FTS over DJs/venues/orgs/series; recents; → entity pages.
4. **收藏 / Me** — saved DJs/venues/events, follow, offline cache.

**Key screens:** Event detail (lineup→DJ, poster, ticketing, source); DJ profile (bio atoms by language,
social links open in-app Safari, top venues/collabs, timeline, related events); Venue (geo map + resident
DJs + schedule); Org/label (roster); Series (editions + venue).

**Star map on iOS (native):** SceneKit `SCNNode` instanced points + additive/bloom (SCNTechnique or
RealityKit post) for the glowing-galaxy look; positions from `lens/{lens}/overview`; tap → fetch
`subject/{urn}/neighborhood` → animate-in; camera fly-to on search. Same L0+L1 model as web.

**Data/architecture:** Swift `AtlasClient` mirroring the contract; URLCache + on-disk cache of overview
layouts + visited neighborhoods/profiles (offline-friendly); `Codable` models matching atlas.v2;
generation-aware cache invalidation (`meta.generation`).

**Design language:** near-black space (#05070d), neon green accent (#A7FF26, matches mp tabbar), per-type
hues (DJ scene-color / venue amber / org violet / series teal), glow/bloom, copy-to-clipboard for
external links (App Store-safe), poster-forward imagery.

**Phasing:** P1 Feed + entity pages + search (reuse contract, fastest value). P2 native star map (Metal).
P3 follow/offline/notifications.

---

## Boundaries
candidate-only; no production DB write, no CloudRun deploy, no mini-program/App Store upload from this
work; `same_label` withdrawn, `b2b` preserved; daily import never triggers paid re-extraction; deploy is
the release thread's explicit step. Star map = web/iOS (not in the WeChat mini-program).
