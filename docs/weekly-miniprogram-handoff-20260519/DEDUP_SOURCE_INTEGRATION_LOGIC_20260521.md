# 去重算法与推文来源整合逻辑 — 2026-05-21

Scope: HUAIDJ weekly mini-program + Atlas read-only cross-reference boundary.

This thread owns the mini-program event feed and its Atlas read-only enrichment surface. It does not take over the Atlas graph mainline.

## Goal

When AI整理活动推文信息:

- do not publish duplicate event cards
- do not lose source article information when several posts point to one event
- do not merge conflicts just because titles look similar
- keep deploy, mini-program upload, and WeChat review as explicit separate states

## Layering

| Layer | Responsibility |
|------|----------------|
| L2 Python release repair | SSOT dedupe/conflict decision |
| L2 source-map repair | Preserve/remap merged source articles |
| L3 CloudRun dataStore | Runtime idempotent dedupe with L2-compatible rules |
| L3 mini-program `format.js` | Display fallback dedupe, must not be wider than L2 |
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
- `services/weekly_activity_cloudrun/tests/dedupParity.test.mjs`
- `tools/stage7_rewrite/tests/test_repair_weekly_release_conflicts.py`

Key assertions:

- `frontend_extra_merge=0`
- Python/JS/CloudRun all obey `weekly_dedup_spec.v1.json`
- duplicate source-map entries are redirected to retained event instead of being dropped
- retained event receives `merge_provenance`
