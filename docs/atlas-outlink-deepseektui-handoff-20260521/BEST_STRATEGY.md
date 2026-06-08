# Atlas Outlink Search — Best Strategy (Definitive)

Generated: 2026-05-21 23:35 CST
Based on: 16-strategy test, 192-entity cross-validation, 527k evidence audit, radio platform probe

## 2026-05-22 Lifecycle / Current-Authority Boundary

Status: `historical-or-evidence` / `reference` / `verify-before-use`.

This file is a 2026-05-21 strategy synthesis for Atlas outlink and social-profile follow-up. It remains useful as query/platform strategy evidence, but it is not the current runtime authority and must not be used to start public-search, Post-Filter, avatar download, OpenCLI, Maigret, Camofox, Scrapling, browser, LLM/model, vector, graph, SQLite, CloudRun, or mini-program work.

Current authority is `docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md`, then `docs\current-runtime.md`, `tools\stage7_rewrite\SSOT.md`, and `tools\stage7_rewrite\STAGE7_SSOT_20260514.md`.

Current verified closeout from `reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md`:

- public-search is `COMPLETE`, `246,024 / 246,024`, `100.0%`.
- full Post-Filter completed at `2026-05-22T10:36:47+08:00`.
- current reduced review queue is `27`, not the older `~890` estimate below.
- filtered candidates are `349`; quarantine rows are `245,653`.
- reduced Layer D was verified only in dry-run mode over the first `20 / 27` review rows.
- `accepted_for_graph`, `identity_proof`, and `graph_write_allowed` remain `0` / false until explicit human acceptance and a separate staged-promotion authorization.

The execution-order and scale-estimate sections below are preserved as historical strategy context. Any future run must start from the reduced Post-Filter review queue and current gates in the SSOT, not from this file's old full-run estimates or avatar-download step.

## Strategy Per Entity Type

| Entity Type | Best Query | Best Method | Priority |
|-------------|-----------|-------------|----------|
| artist/person/band | `"{name}" DJ` | Instagram deep → HTTP outlink | HIGHEST |
| Chinese entity | `"{cn}" "{en}"` | Bilingual search → radio platforms | HIGH |
| label/organization | `"{name}" "electronic music"` | Fixed-site + radio | HIGH |
| venue/place | `"{name}" {city}` | Fixed-site + Instagram | MED |
| event | `"{name}"` exact | HTTP outlink | MED |
| concept/unknown | `"{name}"` | Maigret → fallback | LOW |

## Platform Priority (Historical Strategy Context)

```
1. Instagram       — bio external links → SC/BC/Linktree/RA (bio link=30pts)
                     following list → social graph discovery
2. Radio Platforms — baihui hosts (18 known: cod,knopha,zean...)
                     cdcr/shcr/byyb → Atlas article extraction
3. SoundCloud      — artist profiles, tracks, reposts
4. Bandcamp        — artist pages, releases
5. RA (Resident Advisor) — DJ pages, events
6. Maigret         — 600+ site username discovery (candidate_only)
7. Bilibili        — DJ mixes, live streams
8. Mixcloud        — mixes, shows
9. YouTube         — channels, live sets
10. Linktree       — aggregator → second-hop expansion
```

## Query Formulations (Tested, Ranked)

| Rank | Strategy | Avg Score | Use Case |
|------|----------|-----------|----------|
| 1 | `name_dj` — "{name}" DJ | 5.0 | Artists/persons |
| 1 | `multi_pass` — strict→alias→broad | 5.0 | Priority≥20 entities |
| 3 | `exact_name` — "{name}" | 2.0 | Generic baseline |
| 4 | `chinese_name_exact` | 2.0 | Chinese entities |
| 5 | `music_first_exact` | 2.0 | Music-first platforms |
| 6 | `radio_platforms` | NEW | Chinese radio |
| 7 | `bilibili_music` | NEW | Bilibili video |
| 8 | `radio_name_cn` | NEW | CN radio keyword |

## Multi-Pass Strategy (Priority≥20 Entities)

```
Pass 1: Exact name + DJ/electronic → music platforms
  → If ≥3 high-value outlinks found: STOP
Pass 2: Alias + city → social platforms
  → If ≥1 new outlink found: CONTINUE
Pass 3: Broad genre + radio → all platforms
  → Capture everything, sort by score
```

## Execution Order (Historical Strategy Context)

```
Phase 0: Cross-Validation → strategy routing
Phase 1: Instagram Deep (priority≥20) — OpenCLI Windows
Phase 2: Radio Crawl (baihui hosts) — OpenCLI/Scrapling
Phase 3: Maigret (maigret_first entities) — Docker :15051
Phase 4: HTTP Outlink (all entities) — HTTP first
Phase 5: Fixed-Site Search (remaining) — HTTP+Scrapling
Phase 6: Quality Monitor → adjust → re-run failing entities
Phase 7: Avatar Download → D:\DJ_DATA  [historical estimate only; not authorized by this file]
```

## Scale Estimates (Historical 2026-05-21 Estimate)

These estimates predate the 2026-05-22 full Post-Filter closeout. Current verified review queue size is `27`; the `~890` estimate below is not current planning truth.

| Method | Entities | Batch | Est. Time |
|--------|----------|-------|-----------|
| Instagram Deep | ~50 (priority≥20) | 20 | ~30 min |
| Radio Crawl | ~18 hosts | 18 | ~15 min |
| Maigret | ~350 (maigret_first) | 50 | ~45 min |
| HTTP Outlink | ~890 | 500 | ~20 min |
| Fixed-Site | ~45 | 100 | ~5 min |
| Quality Monitor | — | — | ~1 min |
| Avatar Download | ~50 confirmed | 50 | ~10 min |
| **Total** | — | — | **~2 hours** |
