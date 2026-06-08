# Loop 009: Poster Proxy And Detail Cleanup

Timestamp: 2026-05-09 03:22 CST

## Scope

Continue the HUAIDJ weekly mini-program lane without touching 93k, OCR, Stage7, vector, Dajiala, Qdrant, Neo4j, or PC DB production work.

This loop fixed the highest-impact display issue found in mobile screenshots: WeChat `mmbiz.qpic.cn` poster images were unreliable in browser preview and mini-program surfaces. It also cleaned detail-page copy so operational facts do not appear inside the description block.

## Changes

- Added CloudRun poster proxy route:
  - `/api/v1/weekly/poster/:id`
  - looks up the published item by id
  - fetches the selected WeChat cover/poster image server-side
  - streams it as image content with public cache headers
- Browser preview now renders event posters through the poster proxy instead of exposing direct `mmbiz.qpic.cn` image URLs.
- Mini-program `compactItem()` now maps `coverUrl` to the CloudBase public poster proxy through `publicBaseUrl`.
- Added `publicBaseUrl` to `apps/weekly_activity_miniprogram/app.js`.
- Detail/description formatting now filters operational lines such as:
  - time/date labels
  - address/location labels
  - ticket/pre-sale/on-site lines
  - account/venue/title duplicate lines
- Browser detail preview now includes poster art before description.
- DevTools upload `0.1.7` succeeded.

## Verification

- `npm test` in `services/weekly_activity_cloudrun`: `19/19` passed.
- `node --check services/weekly_activity_cloudrun/src/server.mjs`: passed.
- `node --check services/weekly_activity_cloudrun/src/previewPage.mjs`: passed.
- Mini-program formatter smoke import passed.
- Local 8787 `/healthz`: `ok=true`, local `llm.configured=true`.
- Local Playwright screenshot:
  - `docs/longrun-ui/weekly-miniapp/screenshots/loop-009-preview-mobile-after.png`
  - `docs/longrun-ui/weekly-miniapp/screenshots/loop-009-detail-mobile-after.png`
- Local poster proxy responses observed: HTTP `200`, `image/webp`.
- CloudBase deployed after retrying with an absolute `--source` path.
- Public preview verified:
  - `posterCount=22`
  - first title `电容俱乐部开放Open Deck`
  - no failed browser requests
  - screenshot `docs/longrun-ui/weekly-miniapp/screenshots/loop-009-preview-cloud-mobile.png`
- Public poster endpoint verified:
  - `/api/v1/weekly/poster/79503418e430520f903b932eb1f19da08d851295`
  - HTTP `200`
  - `image/webp`
  - `216290` bytes
- WeChat DevTools CLI upload:
  - AppID `wx0bc0a1d9d892af2d`
  - version `0.1.7`
  - package `97.5 KB / 99878 bytes`

## Known Gap

CloudBase public `/healthz` still reports `llm.configured=false`; the CloudRun service environment lacks `DEEPSEEK_API_KEY`. Static API, source jumps, current release, and poster proxy work. Cloud-side DeepSeek enrichment still needs service environment-variable configuration or a separate secure CLI/API setup.

## Next

Continue with `UI-002`:

- make mini-program detail page feel less like a table and more like an event product page;
- keep title tap as source action;
- keep address copy visible;
- keep poster first-class;
- do not add RA visual assets or RA red/corner marks.
