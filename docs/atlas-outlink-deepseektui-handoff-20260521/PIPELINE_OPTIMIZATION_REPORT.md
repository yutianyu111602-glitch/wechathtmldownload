# Pipeline Optimization Report — LLM Analysis

Generated: 2026-05-22 00:08 CST
Source: quality monitor (5 batches) + strategy test (16 strategies, 480 combinations)
+ cross-validation (192 entities, LLM-deduped to 137) + evidence audit (527k rows)

## 2026-05-23 做梦 lifecycle note

Status: `historical-or-evidence` / `reference` / `verify-before-use`.

This report is useful as 2026-05-22 optimization analysis for why raw public-search rows needed Post-Filter first, why generic platform/homepage URLs were noisy, and why graph writes and cookie export had to remain zero. It is not current execution authority for Atlas social-search or outlink/profile evidence work.

Current authority is `docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` plus `reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md`. Verified current state: public-search is `COMPLETE`, processed `246,024 / 246,024`, `missing_unique_entity_search_ids=0`, full Post-Filter was generated at `2026-05-22T10:36:47+08:00`, reduced review queue is `27`, filtered candidates `349`, quarantine `245,653`, and Layer D is dry-run only over `20 / 27` rows. `accepted_for_graph`, `identity_proof`, and `graph_write_allowed` remain blocked until human acceptance and separate staged-promotion authorization.

Historical caveats: the `137` / `~160` entity optimization counts, expected-yield table, OpenCLI daemon note, Instagram deep step, and `Avatar Download -> D:\DJ_DATA` line are old analysis context. They must not be copied as a current queue size, current runtime state, D-drive permission, browser/provider authorization, or graph/vector/database write plan.

## Root Cause Analysis

| Problem | Root Cause | Fix |
|---------|-----------|-----|
| Raw canary 0% high-value | Ran against unfiltered 144k rows | ✅ Post-Filter first (validated) |
| Linktree canary 99% Linktree links | Generic SoundCloud/Instagram homepages as input | ✅ Post-Filter provides specific profile URLs |
| Quality "degrading" | Based on stale canary, not real pipeline | ✅ Ignore pre-pipeline metrics |
| No music outlinks | Unfiltered data → generic platform URLs | ✅ Post-Filter entities have music-context URLs |
| OpenCLI daemon not connected | Browser profile needs manual connect | ✅ Auto-detect, skip gracefully |

## Optimized Pipeline Order

```
Phase 0: Cross-Validation (LLM dedup)
  → 137 unique entities, strategy-routed, searchability-classified

Phase 1: HTTP Outlink (always succeeds)
  → 500 entities, ~20 min
  → Target: direct_outlink_expansion + instagram_maigret_priority
  → Query per entity type:
      person/artist → "{name}" DJ
      Chinese entity → "{cn_name}" "{en_alias}"  
      generic name  → "{name}" DJ electronic music
      venue/place   → "{name}" {city} club

Phase 2: Fixed-Site Search
  → 100 entities, ~5 min
  → Platforms: RA, SoundCloud, Bandcamp, Mixcloud
  → Skip entities already found in Phase 1

Phase 3: Radio Crawl
  → baihui 18 hosts, ~15 min
  → cdcr/shcr/byyb → Atlas article extraction

Phase 4: Maigret (only for maigret_first entities)
  → 50 handles, ~45 min
  → candidate_only, not identity proof

Phase 5: Quality Monitor → adjust → re-run failing
Phase 6: Instagram Deep (daemon check first)
Phase 7: Avatar Download → D:\DJ_DATA
```

## LLM-Determined Entity Queries

For the 137 unique entities, these specific queries maximize yield:

| Entity | Type | Searchability | Best Query |
|--------|------|--------------|------------|
| Xhin | person | high | "Xhin" DJ |
| 3fungi | person | high | "3fungi" DJ |
| 4Tael | person | high | "4Tael" DJ |
| Nigls | person | high | "Nigls" DJ |
| Skrillex | person | high | "Skrillex" DJ |
| Diplo | person | high | "Diplo" DJ |
| Monk & Keys | person | high | "Monk & Keys" DJ |
| sound between | person | high | "sound between" DJ |
| Lucy | person | low | "Lucy" DJ electronic music |
| Jaya | person | low | "Jaya" DJ electronic music |
| Yellow | person | low | "Yellow" DJ electronic music club |
| RYAN | person | low | "RYAN" DJ electronic music |
| Sasha | person | low | "Sasha" DJ electronic music |
| 亞人類大逃杀 | event | cn | "亞人類大逃杀" |
| 极地大冲击 | event | cn | "极地大冲击" |

## Platform Priority After LLM Analysis

```
1. Instagram (bio external links → 30pts quality)
2. RA.co (DJ pages → direct identity evidence)
3. SoundCloud (tracks, followers → content evidence)
4. Bandcamp (releases → music identity proof)
5. baihui.live (host bios → social links)
6. Bilibili (DJ mixes → Chinese platform evidence)
7. Mixcloud (shows → content evidence)
8. YouTube (channels → supplementary)
9. Linktree (aggregator → second-hop only)
```

## Anticipated Yield (Post-Filter ~160 entities after LLM dedup)

| Method | Input | Expected Yield | Confidence |
|--------|-------|---------------|------------|
| HTTP Outlink | 160 | 30-50 high-value outlinks | High |
| Fixed-Site | 100 | 20-40 profile URLs | Medium |
| Radio Crawl | 18 | 10-15 with social links | Medium |
| Maigret | 60 | 15-30 usernames | Medium |
| Instagram Deep | 30 | 10-20 bio links | Low (needs daemon) |
| **Total** | — | **85-155 evidence items** | — |

## Success Definition

- ≥50 high-value outlinks (SoundCloud/Bandcamp/RA/Linktree with content)
- ≥30 verified profile URLs with content indicators
- ≥10 radio platform social links extracted
- 0 graph writes, 0 cookie exports
- All report-only
