# Screenshots session — non-electronic filter + rich DJ card — 2026-06-20

Driven by 3 user screenshots (no text): ① a rich DJ card (96 Back — bio + 外媒 RA/NTS/Mixcloud +
SoundCloud/Mixcloud/RA/Instagram/演出原文 link rows + 资料来源 chips), ②③ non-electronic content
(张学友/亚洲爵士长笛, 喜剧脱口秀, 重庆首届鸡尾酒节) leaking into the weekly feed. Confirmed scope =
全做, DJ card on **both** the mini-program artist page and the star-map detail panel.
Plan file: `~/.claude/plans/misty-gliding-stardust.md`.

Lane split (Codex concurrently owns the atlas/star-map files): **mini-program done here; star-map
handed to Codex.**

## Done (committed — mini-program lane)
- **A — non-electronic feed filter** (`e92ced8`): `apps/weekly_activity_miniprogram/utils/genreFilter.js`
  (ES5 JS mirror of `tools/atlas_rebuild/genre_filter.py`: `genreOf`/`filterItemsByElectronic`).
  `pages/index/index.js` drops `non_electronic` at the item source (feeds posters + city/date facets
  + display); keeps `electronic` + `unknown` (no over-drop). Extended `NON_ELECTRONIC` in **both** the
  py and the js with the non-music-event class that leaked: 鸡尾酒/cocktail/酒节/喜剧/comedy/长笛/
  flute/话剧/音乐剧/市集/漫展. Test `tests/genre-filter.test.cjs` (screenshot cases dropped).
- **B — rich DJ card on the artist page** (`b66e284`): `utils/djLinks.js`
  (`socialToLinkItems` maps `dj_profile.social_json` → external-link items: display-allowed,
  high-confidence, categorized) + `pages/artist/artist.{js,wxml}` "外媒 · 资料来源" section reusing
  `publicExternalLinks.normalizeDjDiscoverySectionsForDisplay` (links + verbatim bio atoms) and
  `externalLinkAction.copyOriginalExternalLink` (mini-program copies external links). i18n
  `externalMedia`. Test `tests/dj-links.test.cjs`. `test:miniprogram` 172/172.

## Remaining

### C — rich DJ card on the star map (Codex's lane; files it just restructured)
- Data: `tools/atlas_rebuild/export_starmap_layout.py` (v2 path) — for DJ nodes, attach
  `node.social` (from `dj_profile.social_json`), `node.bio` (`bio_snippet` or top `dj_bio_atom`),
  `node.sources` (from `dj_bio_atom` source refs). `apps/atlas_starmap_web/src/lib/types.ts` add
  `social?`, `bio?`, `sources?` to `GraphNode`.
- Render: `src/components/NodeDetailPanel.tsx` add a **Bio** section + **social link rows**
  (`<a href target="_blank">` — the web app opens external links directly, unlike the mini-program)
  + sources chips. Reuse the social→category map (`utils/djLinks.js` `CATEGORY_BY_KEY`) for parity
  with the mp card.

### A3 — non-electronic gate in the pipeline (so it never reaches serving)
- Wire `genre_filter.genre_of` into `tools/stage7_rewrite/scripts/convert_atlas_events_to_weekly_incremental.py`
  (drop/flag `non_electronic` at build). Gate `non_electronic_in_head` already audits. Needs
  pipeline rebuild + deploy (release thread). The frontend filter (A) is the immediate safety net.

### B3 — data for the mp card (release thread)
- Re-bake `atlas_index.json.gz` (`tools/stage7_rewrite/scripts/export_atlas_core_to_miniapp_index.py`)
  to add `profiles[dj].social` (from v2 `social_json`) + `bio_atoms` (from `dj_bio_atom`); then
  `services/weekly_activity_cloudrun/src/miniappAtlasApi.mjs` `getArtist`/`getArtistById` return them.
  The mp card (B) renders empty-safe until then.

## atlas.v2 contract additions (for `ATLAS_NEXTGEN_DESIGN_20260620.md` §3)
`subject/{urn}` profile gains `socialLinks[]` (`{category,url,platform}`, display-gated),
`bioAtoms[]` (`{text,language,sourceRef}` verbatim), `discoverySections[]`; and a serving rule
`isElectronic` (from `genre_of`) so non-electronic items never enter the weekly feed.

## Boundary
Mini-program external links = copy-to-clipboard (can't open arbitrary URLs). candidate-only; no
deploy/upload; `same_label` withdrawn / `b2b` kept; UI style unchanged. C edits files Codex is
actively maintaining — coordinate before touching `export_starmap_layout.py` / `NodeDetailPanel.tsx`.
