# Weekly Activity Sanji Gap Audit - 2026-06-19

## Scope

This audit checks why Hangzhou `loopy Club` appears missing in the mini-program
city feed, and whether the new club overview feed caused it.

This document is for frontend/API-contract alignment. The daily backend
pipeline owner should use the concrete queue/package gap below; this thread did
not rebuild or deploy the daily package.

## Confirmed Facts

- Online API current package is healthy but stale relative to the latest Sanji
  queue:
  - API base: `https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com`
  - current package generated at: `2026-06-19T00:43:31+08:00`
  - `/api/v1/weekly/current?cityKey=hangzhou&lookbackDays=0` returns 6 items.
  - Hangzhou/loopy exists only as:
    - `loopy_club:6668978530f8a26c`
    - `2026-06-20`
    - `PRE呈现：失控阈值 / Threshold of Losing Control`
- `/api/v1/weekly/current?cityKey=hangzhou&date=2026-06-19` returns 4 Hangzhou
  items and 0 loopy items.
- `/api/v1/weekly/current?cityKey=hangzhou&date=2026-06-20` returns the loopy
  `PRE呈现` item.
- Local `services/weekly_activity_cloudrun/data/current_release/current.json`
  matches the online package.

## Loopy Breakpoint

Sanji has these recent loopy rows, but current_release only has `6668978530f8a26c`:

| Event date | Sanji title | Source hash | In latest Sanji queue | In current_release |
| --- | --- | --- | --- | --- |
| 2026-06-19 | 今晚，欢迎来到Jasmín的茉莉心房！ | `b8a487d2ad7c8c8f` | yes | no |
| 2026-06-21 | 6.21 周日｜loopy x Open M pres.夜游 / Off - duty 唱机龙舟 | `5331a3c6cb7d1d3f` | yes | no |
| 2026-06-27 | 6.27 周六｜「酸儿辣女·贵州厨房」全员贵州帮阵容，都别傻站着了！保持躁动！ | `39e8988f674671c1` | yes | no |
| 2026-06-20 | 6.20 周六｜PRE呈现：失控阈值 / Threshold of Losing Control | `6668978530f8a26c` | older Sanji row | yes |

Therefore the direct loss point is after Sanji article export and before the
published current_release package consumed by CloudRun.

## Not Caused By Club Overview UI

`apps/weekly_activity_miniprogram/data/club_overviews.js` is a separate
venue-page feed. Rows are emitted with:

```json
{
  "record_type": "club_overview_parent",
  "parent_aggregate": true,
  "include_in_activity_feed": false
}
```

The overview feed should not enter the ordinary city activity list, and it does
not explain missing single-event loopy source hashes.

## Similar Gap Count

Against `E:\公众号\sanji-daily-export\latest_queue.jsonl` generated at
`2026-06-19T16:03:44+08:00`:

- queue rows: 153
- current/future event-like rows detected: 73
- current/future rows absent from current_release by source hash: 46
- affected accounts: 29

Top affected accounts in this local audit:

- `电容DeepRoll`: 4
- `FLAT Club`: 3
- `loopy Club`: 3
- `POOLS`: 3
- `REACTOR Shanghai`: 3
- `莫须有工舍`: 2
- `Cs Bar`: 2
- `ILLUM Shanghai`: 2
- `OONOO`: 2
- `POTENT`: 2
- `VERVO国际独立电音俱乐部`: 2

This count is an audit heuristic, not an LLM extraction result. It is enough to
show the issue is not loopy-only.

## Frontend Fix Applied

To prevent similar frontend-side disappearance:

- static API fallback city filtering now matches backend semantics:
  `city_key == selected || city_keys includes selected`;
- dedupe city keys now prefer stable key fields before display city labels;
- changing the city filter clears the old date filter and reloads with
  `date: ""`, so `杭州 + stale 2026-06-19` does not hide loopy `2026-06-20+`
  rows and look like a city-filter failure.

## Daily Pipeline Requirement

The daily pipeline thread should ensure `SourceMode=sanji_desktop_rss` consumes
`E:\公众号\sanji-daily-export\latest_queue.jsonl` before building
current_release, and should add a gate that compares current/future Sanji queue
source hashes against the package output before deploy.

Thread: `codex://threads/019ed387-0945-7a72-9f9b-df013cfcc2cd`
