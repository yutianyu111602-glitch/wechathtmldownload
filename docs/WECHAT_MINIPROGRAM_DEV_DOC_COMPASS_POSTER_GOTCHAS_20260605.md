# WeChat Mini-Program Dev Doc Compass: Poster Loading Gotchas 20260605

Status: `CURRENT_AUTHORITY`

Audience: future Codex/OpenClaw agents debugging HUAIDJ weekly mini-program first-load, poster, CloudBase, and data-package issues.

## Official Doc Anchors

These links were verified reachable on 2026-06-05 and are the source set for the rules below:

- Mini-program framework: https://developers.weixin.qq.com/miniprogram/dev/framework/
- Mini-program API reference: https://developers.weixin.qq.com/miniprogram/dev/api/
- Mini-program network rules: https://developers.weixin.qq.com/miniprogram/dev/framework/ability/network.html
- `image` component: https://developers.weixin.qq.com/miniprogram/dev/component/image.html
- WeChat Cloud getting started: https://developers.weixin.qq.com/miniprogram/dev/wxcloudservice/wxcloud/basis/getting-started.html
- Cloud Run docs: https://developers.weixin.qq.com/miniprogram/dev/wxcloudservice/wxcloudrun/src/
- Cloud Storage `getTempFileURL`: https://developers.weixin.qq.com/miniprogram/dev/wxcloud/reference-sdk-api/storage/Cloud.getTempFileURL.html
- Cloud Storage `downloadFile`: https://developers.weixin.qq.com/miniprogram/dev/wxcloud/reference-sdk-api/storage/Cloud.downloadFile.html
- Cloud function `callFunction`: https://developers.weixin.qq.com/miniprogram/dev/wxcloud/reference-sdk-api/functions/Cloud.callFunction.html
- Server API and signature docs:
  - https://developers.weixin.qq.com/miniprogram/dev/server/API/
  - https://developers.weixin.qq.com/miniprogram/dev/server/getting_started/api_signature.html

## Compass Rules

1. Treat CloudBase Storage `cloud://...` as source truth, not as the final render URL.
   - Release packages, CloudRun API, and CloudBase hot DB should preserve internal file IDs.
   - The front end should resolve file IDs to display URLs at runtime with `wx.cloud.getTempFileURL`.
   - Temporary URLs are display artifacts. Do not store them as package truth because they can expire.

2. Do not solve WeChat article image blocking by adding public domains.
   - `mmbiz.qpic.cn`, `mmecoa.qpic.cn`, and `mp.weixin.qq.com` are source-acquisition evidence, not mini-program poster runtime truth.
   - Domain allowlisting does not make WeChat article media hotlink-safe.
   - The current poster lane must internalize images into CloudBase Storage before publication.

3. Keep server-side and client-side API boundaries separate.
   - Server OpenAPI signature/AppSecret rules belong in backend/server code only.
   - Mini-program client code must not carry AppSecret, signed server calls, cookies, or crawler credentials.
   - Client-side CloudBase calls use `wx.cloud` APIs after cloud initialization.

4. Render proof must come from the mini-program runtime.
   - Static code review can tell which path should run; it cannot prove images rendered.
   - The proof gate is DevTools output with positive `posterImageLoadCount` and zero `posterImageErrorCount`.
   - A passing public API readback alone only proves data exists, not that the `<image>` component displayed it.

5. Batch and fallback rules are part of correctness.
   - `wx.cloud.getTempFileURL` must be called in batches of 50 file IDs or fewer.
   - On image load failure, retry `wx.cloud.downloadFile` to a local `wxfile://` temp path.
   - Only after download fallback fails, retry the original `cloud://` file ID once.
   - Never overwrite the original `posterFileId` with a temporary URL or local file path.

## Current Project Poster Chain

The current HUAIDJ weekly mini-program poster chain is:

1. Source pipeline/OpenClaw identifies the main poster from article images.
2. The image is uploaded to CloudBase Storage under `weekly-posters/YYYYMMDD/...`.
3. The release package stores CloudBase file IDs in poster fields such as `poster_file_id`, `posterFileId`, `poster_url`, and `coverUrl`.
4. CloudRun reads `services/weekly_activity_cloudrun/data/current_release` and exposes the same internal poster fields.
5. `weeklyDataSync` syncs CloudRun current data into the CloudBase hot DB without stripping poster fields.
6. The mini-program reads CloudBase hot DB first, then CloudRun/public/cache fallback.
7. `apps/weekly_activity_miniprogram/utils/cloudPosterUrls.js` converts `cloud://` file IDs to temp URLs for display.
8. `pages/index/index.js`, `pages/detail/detail.js`, and `utils/posterPool.js` render the temp URL while preserving the original `posterFileId`.

## Why Posters Kept Loading Blank

The recurring blank-poster failure was a chain bug, not one isolated typo:

1. Public WeChat image URLs are not reliable poster runtime assets.
   - Earlier package and API shapes could expose `mmbiz.qpic.cn` / `qpic.cn` / article media URLs.
   - Those URLs can be blocked by anti-hotlinking and WeChat article access controls.
   - Adding them to download domains is not enough; the mini-program still needs a stable owned asset path.

2. The corrected backend/package truth became `cloud://`, but the front end still needed a render URL.
   - After internalization, the API and CloudBase DB correctly carried CloudBase file IDs.
   - A `cloud://` file ID is the storage reference. The robust display path is to resolve it with CloudBase APIs into a temp URL, then feed that temp URL into `<image src>`.
   - When the page treated the internal file ID as the final `coverUrl`, first render could show an empty poster or trigger `binderror`.

3. First-entry timing made the problem look random.
   - On the first entrance, home data, CloudBase initialization, cached fallback, filter metadata, and poster prewarm all compete.
   - If the data path wins before `wx.cloud` is available, `getTempFileURL` cannot run and the card keeps the unresolved `cloud://` value.
   - Re-entering the mini-program may appear to fix it because CloudBase initialization and caches are warm.

4. Fallback once corrupted the source ID.
   - When image error fallback replaced `posterFileId` with a `wxfile://` local temp path or a temp URL, later retry logic lost the original CloudBase file ID.
   - Losing the original file ID meant the next fallback could not call `downloadFile` or re-resolve temp URLs correctly.
   - The fixed state keeps `posterFileId=cloud://...` and changes only `coverUrl` for display.

5. Field aliases made false positives easy.
   - The same poster may appear as `poster_file_id`, `posterFileId`, `cover_file_id`, `coverFileId`, `poster_url`, `cover_url`, `cover_image_url`, or `coverUrl`.
   - Empty aliases must never overwrite non-empty internal file IDs.
   - Tests must check both snake_case and camelCase routes.

6. Stale cache/snapshot issues can mimic poster failure.
   - If a first-load fallback wins with old snapshot/cache rows, the UI may render old items with missing or public poster fields.
   - That is a loading-state bug, not proof that the current backend package has no poster fields.

## How To Diagnose The Next Blank Poster

Use this order. Do not skip directly to code edits.

1. Check CloudRun/public API data.
   - Expected: each current item has a non-empty `cloud://.../weekly-posters/...` poster file ID.
   - If missing here, it is a source package or backend packaging issue.

2. Check CloudBase hot DB readback.
   - Expected: hot DB current items preserve the same poster fields.
   - If CloudRun has posters but hot DB does not, the bug is in `weeklyDataSync` or DB projection.

3. Check front-end canonicalization.
   - Expected: `utils/format.js` and `utils/api.js` keep the internal file ID across aliases and do not let empty values wipe it.
   - If `posterFileId` disappears before render, the bug is front-end data normalization.

4. Check temp URL resolution.
   - Expected: `utils/cloudPosterUrls.js` calls `wx.cloud.getTempFileURL`, batches at 50 or below, sets `posterTempUrl`, and changes `coverUrl` to the temp URL.
   - If `cloudbaseTempPosterCount=0` while API has cloud file IDs, the bug is CloudBase init or resolver wiring.

5. Check `<image>` runtime events.
   - Expected: DevTools report has `posterImageLoadCount > 0` and `posterImageErrorCount = 0`.
   - If temp URLs exist but errors remain, inspect CloudBase permissions, temp URL expiry, and `downloadFile` fallback.

6. Check source-action separately.
   - Wrong click-through links such as jumping to a weekly overview are a `source_action` / aggregate-child routing issue.
   - Do not conflate that with poster image transport unless the same row also has missing poster file IDs.

## Current Proof Snapshot

As of 2026-06-05:

- CloudRun deployed version: `weekly-api-030`.
- Public API readback after deploy: generatedAt `2026-06-05T18:01:29+08:00`, first page poster file IDs `100/100`, public WeChat/qpic posters `0`, empty posters `0`.
- CloudBase sync: `syncId=weekly_1780662457013`, events `137`, CloudBase DB source readback `137`.
- DevTools rendered proof after sync/upload: `apps/weekly_activity_miniprogram/test-artifacts/devtools-current-package-rendered-2026-06-05T12-30-47-455Z/report.json`.
- DevTools poster result: `cloudbaseTempPosterCount=48`, `internalPosterSourceFileIdCount=48`, `posterImageLoadCount=48`, `posterImageErrorCount=0`.
- Development upload: version `2026.06.05.4`, desc `poster-tempurl-hotdb-137`.
- Boundary: no WeChat review submission and no public release were executed.

## Pitfalls To Remember

- A legal download domain is not the same as a renderable poster asset.
- A `cloud://` file ID is source truth; a temp URL is display truth; mixing them causes blanks and stale fallbacks.
- Temp URLs should not be persisted in release packages.
- Local `wxfile://` fallback must not overwrite the CloudBase source file ID.
- First-entry bugs often come from CloudBase initialization and cache/snapshot races, not from missing backend data.
- A passing API readback is necessary but insufficient. Always require DevTools image load evidence.
- `source_action` link bugs and poster image bugs share rows but are different contracts.
- Aggregate child rows are not normal events unless they have source-backed month/day evidence for their own `event_date_start`.
- Weekday-only or bare day-only evidence from a previous-month overview, such as `Sun` / `30` published on `2026-05-25`, must not be promoted into the next package window as `2026-06-06`.
- Aggregate child rows must not inherit the parent weekly/monthly overview poster. If no child-specific CloudBase poster exists, suppress the poster instead of showing the overview image.
- Aggregate child rows must not expose the parent weekly/monthly overview source link. Set `source_action.available=false`, clear source hashes, and keep `source_url_map.json` free of aggregate-child targets.
- Source-map rows for a current source hash must point to the current item `event_id`. Stale `merged_into_event_id` / `merge_reason=duplicate_cluster` metadata can make a valid URL open in the wrong event context.

## Related Maintained Docs

- `docs/WECHAT_MINIPROGRAM_POSTER_LOADING_OFFICIAL_NOTES_20260605.md`
- `docs/WEEKLY_MINIPROGRAM_DEBUG_UPLOAD_RUNBOOK_20260605.md`
- `docs/OPENCLAW_DOCKER_INCREMENTAL_PACK_CONSTRAINT_PROMPT_20260605.md`
