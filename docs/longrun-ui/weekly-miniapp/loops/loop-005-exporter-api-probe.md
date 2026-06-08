# Loop 005 - Exporter API Probe

Date: 2026-05-09

## Scope

Use the local `wechat-article-exporter` public API in read-only mode to inspect current account/article metadata.

This loop did not click sync, start crawling, download article bodies, run OCR, run LLM extraction, start Stage7 production, write vectors, touch Qdrant/Neo4j, write PC production DB data, or use Dajiala/paid jobs.

## Inputs

- exporter dashboard: `http://127.0.0.1:17300/dashboard/api`
- API auth method: `X-Auth-Key`
- account export: `D:\DDownload\公众号 (5).json`
- API endpoints used:
  - `/api/public/v1/article?fakeid=...&begin=0&size=20`

## Result

- account export count: `126`
- API account probes OK: `126`
- API account probes failed: `0`
- accounts with articles since `2026-05-01`: `79`
- article metadata rows since `2026-05-01`: `430`

Generated artifacts:

- `tools\stage7_rewrite\reports\wechat_exporter_api_probe_20260509.json`
- `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_20260509\weekly_activity_queue.jsonl`
- `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_20260509\summary.json`

Top accounts by new article metadata volume:

- `Dada Kunming`: `16`
- `DIRTY HOUSE 得体`: `15`
- `Dada Bar Beijing`: `15`
- `ILLUM Shanghai`: `15`
- `院吧 Hakka Bar`: `14`
- `坚果NUTS`: `13`
- `OIL油`: `12`
- `wigwam`: `12`
- `loopy Club`: `12`
- `VERVO国际独立电音俱乐部`: `11`

## Interpretation

The Docker/exporter data source is not empty. The low mini-program publish count comes from the old extraction/recommendation pack still being used by the release builder.

The next data step is to feed `WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_20260509` into the weekly article body download and LLM extraction lane, then rebuild the recommendation pack and mini-program API from those new extracts.
