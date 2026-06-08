# WeChat Mini-Program Poster Loading Notes 20260605

Status: `CURRENT_AUTHORITY` for HUAIDJ weekly mini-program poster loading.

## Official References

- Mini-program framework: https://developers.weixin.qq.com/miniprogram/dev/framework/
- Mini-program API reference: https://developers.weixin.qq.com/miniprogram/dev/api/
- Server API reference: https://developers.weixin.qq.com/miniprogram/dev/server/API/
- Server API signature guide: https://developers.weixin.qq.com/miniprogram/dev/server/getting_started/api_signature.html
- WeChat Cloud getting started: https://developers.weixin.qq.com/miniprogram/dev/wxcloudservice/wxcloud/basis/getting-started.html
- WeChat Cloud Run docs: https://developers.weixin.qq.com/miniprogram/dev/wxcloudservice/wxcloudrun/src/
- Cloud Storage temporary URL API: https://developers.weixin.qq.com/miniprogram/dev/wxcloud/reference-sdk-api/storage/Cloud.getTempFileURL.html
- Cloud Storage download API: https://developers.weixin.qq.com/miniprogram/dev/wxcloud/reference-sdk-api/storage/Cloud.downloadFile.html
- Cloud function call API: https://developers.weixin.qq.com/miniprogram/dev/wxcloud/reference-sdk-api/functions/Cloud.callFunction.html
- `image` component: https://developers.weixin.qq.com/miniprogram/dev/component/image.html
- Mini-program network rules: https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html

## Decisions

- Poster source fields in release packages and backend APIs must be CloudBase Storage file IDs, normally `cloud://huaidjweekly-d8g1go7-d0a07863e3e.../weekly-posters/...`.
- Do not publish public WeChat article image URLs such as `mmbiz.qpic.cn`, `mmecoa.qpic.cn`, or `mp.weixin.qq.com` as `poster_url`, `coverUrl`, or `posterFileId`.
- Front-end `<image src>` should render a CloudBase temp URL resolved by `wx.cloud.getTempFileURL`, while retaining the original `posterFileId` for fallback.
- `wx.cloud.getTempFileURL` accepts up to 50 file IDs per call; keep batching at 50 or lower.
- If image loading fails after temp URL resolution, retry in this order: `wx.cloud.downloadFile` local temp path, then original `cloud://` file ID once. Do not fall back to public WeChat/CDN URLs.
- Server API signature/AppSecret rules apply to server-side OpenAPI calls only. Do not move AppSecret or signed server calls into mini-program client code.
- Mini-program direct network APIs are domain-gated. CloudBase and Cloud Run internal calls are the preferred path for this poster lane.

## Current Runtime Chain

1. OpenClaw / pipeline selects the main poster, uploads it to CloudBase Storage, and writes internal file IDs into the release package.
2. CloudRun reads `services/weekly_activity_cloudrun/data/current_release` and returns `poster_file_id`, `posterFileId`, `poster_url`, `coverUrl` as `cloud://` file IDs.
3. `weeklyDataSync` cloud function syncs CloudRun current data into CloudBase hot DB and preserves poster fields.
4. `apps/weekly_activity_miniprogram/utils/api.js` reads CloudBase hot DB first for first-screen paths, then falls back to CloudRun/public/cache/snapshot.
5. `apps/weekly_activity_miniprogram/utils/format.js` canonicalizes snake/camel poster aliases without letting empty fields wipe valid file IDs.
6. `apps/weekly_activity_miniprogram/utils/cloudPosterUrls.js` resolves file IDs to temp URLs for rendering and preserves original file IDs.
7. `pages/index/index.js`, `pages/detail/detail.js`, and `utils/posterPool.js` render temp URLs but keep `posterFileId` as source truth.

## 2026-06-05 Proof

- Full acceptance: `tools/stage7_rewrite/reports/weekly_miniprogram_full_acceptance_20260605_202028/summary.json`, `ok=true`.
- CloudRun deploy: `tools/stage7_rewrite/reports/cloudrun_direct_api_deploy_20260605_poster_tempurl_frontend_fix/cloudrun_direct_api_deploy_report.json`, `weekly-api-029 -> weekly-api-030`.
- Public CloudRun readback after deploy: generatedAt `2026-06-05T18:01:29+08:00`, current page total `137`, first page cloud poster IDs `100/100`, public WeChat/qpic `0`, empty poster `0`.
- CloudBase hot DB sync: `syncId=weekly_1780662457013`, events `137`, cities `25`, AI summary `1`, source `cloudbase-database`.
- CloudBase hot DB poster readback: generatedAt `2026-06-05T18:01:29+08:00`, first page cloud poster IDs `100/100`, public WeChat/qpic `0`, empty poster `0`.
- DevTools rendered readback after sync/upload: `apps/weekly_activity_miniprogram/test-artifacts/devtools-current-package-rendered-2026-06-05T12-30-47-455Z/report.json`, first screen `137/137`, CloudBase temp poster covers `48`, retained source file IDs `48`, poster image loads `48`, poster errors `0`.
- Development upload: AppID `wx0bc0a1d9d892af2d`, version `2026.06.05.4`, desc `poster-tempurl-hotdb-137`, size `411275` bytes.

Boundary: no WeChat review submission and no public release were executed.
