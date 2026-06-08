# 去重算法与推文来源整合逻辑 — 2026-05-21

Scope: HUAIDJ weekly mini-program + Atlas read-only cross-reference boundary.

This thread owns the mini-program event feed and its Atlas read-only enrichment surface. It does not take over the Atlas graph mainline.

Operational boundary: the Singapore server / Singapore VPS belongs to the stock-trading beta line. It is not part of the HUAIDJ weekly mini-program, Atlas read-only bridge, Docker exporter, CloudRun `weekly-api`, or mini-program upload/review workflow.

## Goal

When AI整理活动推文信息:

- do not publish duplicate event cards
- do not lose source article information when several posts point to one event
- do not merge conflicts just because titles look similar
- keep deploy, mini-program upload, and WeChat review as explicit separate states
- do not route mini-program debugging or scripts through the Singapore stock beta server

## Layering

| Layer | Responsibility |
|------|----------------|
| L2 Python release repair | SSOT dedupe/conflict decision |
| L2 source-map repair | Preserve/remap merged source articles |
| L3 CloudRun dataStore | Runtime idempotent dedupe with L2-compatible rules |
| L3 mini-program `format.js` | Display fallback dedupe, must not be wider than L2 |
| L3 mini-program `sourceArticles.js` | Display source refs by source hash; merged sources are links, not duplicate event cards |
| L3 Club Profile | `organizer_key` / `club_profile` aligns weekly venue pages with Atlas read-only references |
| Atlas bridge | Read-only artist/entity enrichment only; no vector/graph write from this thread |

## Event Dedup Decision

The current SSOT is `audit_weekly_cross_source_conflicts.are_likely_duplicates`.

Decision order:

1. Same `event_date_start` / `event_date_iso_guess`.
2. Same city.
3. Venue scope must match:
   - exact venue label, or
   - same address, or
   - short/long venue alias with same owner.
4. Title date conflict veto:
   - if title tokens mention different month/day, do not merge.
5. Strong duplicate evidence:
   - same cover with title similarity >= 0.5
   - same source hash with title similarity >= 0.5
   - exact dedupe key
   - title similarity >= 0.86
6. Weak evidence only merges when supported by trusted time, address, owner, or shared title anchors.

Conflict rule:

- same date/city/title-ish but different venue/address is conflict or separate event, not duplicate.

## Source Article Integration

Before this slice, duplicate repair removed duplicate rows and filtered out source map entries for removed event IDs. That kept the list clean but could drop information about uploaded/collected posts.

Now duplicate repair keeps one event card and preserves source provenance:

```json
"merge_provenance": {
  "schema_version": "weekly_merge_provenance.v1",
  "reason": "duplicate_cluster",
  "retained_id": "event:id",
  "retained_source_hash": "hash",
  "merged_from": ["old:event", "event:id"],
  "merged_source_hashes": ["oldhash", "hash"],
  "source_count": 2,
  "sources": []
}
```

Source map repair now redirects duplicate source entries to the retained event:

- `event_id` becomes the retained event id
- `merged_into_event_id` records the retained event id
- `merged_into_source_hash` records the retained source hash
- `merge_reason=duplicate_cluster`

Conflict-quarantined source entries are still removed; they are not folded into a retained event because the event identity is unsafe.

## Source Availability Gate

Source provenance is only useful when the source can still support the event. If the original WeChat article has been deleted or is unavailable, that row must not update the published mini-program feed.

Current static API publication gate:

- skip rows with deletion/unavailable fields such as `source_deleted`, `article_deleted`, `source_available=false`, `source_status=deleted/unavailable/not_found`, or HTTP `404/410`
- skip rows whose error/message text indicates the article was deleted, unavailable, gone, or not found
- skip rows matching optional `--deleted-source-registry` JSON/JSONL values by source URL or `url_hash`
- count these rows as `filtered_counts.source_unavailable`

This is a publish/update blocker, not a UI hiding rule. Deleted source rows should be excluded before `source_url_map.json`, so stale original links do not remain reachable as if they were valid evidence.

## Multi-day Schedule Articles

Ping常 exposed a common failure mode: one source article title can carry a broad range like `5.20-23`, while the body contains separate schedule sections such as `5.22 周五｜白X3` and `5.23 周六｜Kchen`.

Current rule:

- The title range is routing context, not the final event identity when body date sections exist.
- Each body date section becomes a child event with the same source URL/hash.
- The aggregate parent is not published as a city-feed event card.
- Time, lineup, and ticketing fields are extracted from the nearest date section first.
- Source audit must still see the same parent article as evidence for each child event, so no source information is lost.

This prevents both failure modes: repeating the parent schedule as a duplicate card, and losing child events hidden inside the article body.

## Current-Date Display Gate

Publication packages can cover a broad window, for example `2026-05-20..2026-06-03`. The default discovery feed must still be "today onward", not "everything in the package".

Current runtime rule:

- default `current` feed with no explicit date hides ended past single-day events
- a multi-day event stays visible while `event_date_end` or the latest known event date is today or later
- date chips hide past dates by default
- explicit date filters still work for direct lookup/debugging, so `date=2026-05-20` can intentionally show a past date even on `2026-05-21`
- CloudRun computes "today" in Asia/Shanghai; mini-program static fallback uses local device date

This fixes the 2026-05-21 symptom where 5.20 single-day activities were still shown because both CloudRun and static fallback treated missing `date` as no date filter.

## Mini-program Display Rule

The UI now separates event identity from source article identity:

- City/home list shows one event card per retained event.
- Detail page shows merged source refs in `SOURCE ARTICLES` only when one retained event has multiple source hashes.
- Venue/club page groups source refs by `source_hash`, so one aggregate parent or repeated promotion article appears once.
- Source rows use `fallbackDetailId` only as a fallback; the primary source identity is the URL hash.
- Venue navigation uses `organizer_key` before fuzzy name matching.

This means repeated uploaded posts should not create repeated event cards, but their source articles remain reachable for audit and user fallback.

## Ticketing / OCR Extraction Guard

Ticketing text is part of source integrity. A source article can be deduped correctly and still be misleading if OCR ticketing lines are split incorrectly.

Current guard:

- `3am` / `3 AM` / `凌晨3点` are time conditions, not prices.
- `3am 后免费入场` must stay as one entry rule, not `￥3` plus `免费入场`.
- Amounts written after the number, such as `预售 70￥ / 双人 128￥ / 现场 100￥`, are supported by upstream pack extraction.
- Static API and mini-program formatting both sanitize legacy polluted values before publishing/displaying.
- Prompt contracts for DeepSeek and CloudRun tell the LLM not to infer prices from time strings.

## Current Package Impact

Dry-run/write against a temporary copy of current 158-item package:

| Metric | Result |
|------|------|
| raw_item_count | 158 |
| repaired_item_count | 158 |
| removed_duplicate_count | 0 |
| quarantined_conflict_item_count | 0 |
| missing_lineup_after | 58 |
| hard_fail_after | 0 |
| soft lineup retained actions | 0 |
| lineup cleared actions | 0 |

Interpretation: current package already has duplicate/conflict gates clean. The new source integration mainly protects future packages where repeated uploaded posts or aggregate/direct pairs collapse into one event.

## Tests Covering The Contract

- `tools/stage7_rewrite/tests/test_weekly_dedup_spec_parity.py`
- `apps/weekly_activity_miniprogram/tests/dedup-parity.test.cjs`
- `apps/weekly_activity_miniprogram/tests/source-articles.test.cjs`
- `apps/weekly_activity_miniprogram/tests/page-source-routing.test.cjs`
- `services/weekly_activity_cloudrun/tests/dedupParity.test.mjs`
- `tools/stage7_rewrite/tests/test_repair_weekly_release_conflicts.py`
- `tools/stage7_rewrite/tests/test_weekly_activity_exporter_queue_pack.py`
- `tools/stage7_rewrite/tests/test_weekly_activity_recommendation_pack.py`
- `tools/stage7_rewrite/tests/test_weekly_activity_miniprogram_api.py`
- `apps/weekly_activity_miniprogram/tests/format-quality.test.cjs`
- `apps/weekly_activity_miniprogram/tests/api-static-fallback.test.cjs`
- `services/weekly_activity_cloudrun/tests/weeklyApi.test.mjs`

Key assertions:

- `frontend_extra_merge=0`
- Python/JS/CloudRun all obey `weekly_dedup_spec.v1.json`
- duplicate source-map entries are redirected to retained event instead of being dropped
- retained event receives `merge_provenance`
- detail/venue source article rows expose merged sources once per source hash
- `organizer_key` is present on API current/detail/batch items and preserved by mini-program formatting
- deleted/unavailable source rows are excluded before publication and source-map output
- default current/date fallback hides ended past dates while preserving explicit date lookup and active multi-day ranges
