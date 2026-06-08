# OpenClaw Docker Incremental Pack Constraint Prompt 20260605

Use this prompt for every HUAIDJ weekly mini-program incremental package run.

```text
You are building a HUAIDJ weekly mini-program incremental package. Follow these constraints exactly.

Poster storage and rendering contract:
- The package must never publish public WeChat article image URLs as poster fields. Reject `mmbiz.qpic.cn`, `mmecoa.qpic.cn`, `mp.weixin.qq.com`, and `/api/v1/weekly/poster/` proxy URLs in `poster_url`, `cover_url`, `coverUrl`, `posterFileId`, `poster_file_id`, `flyer_url`, or equivalent fields.
- Every current item must carry an internal CloudBase Storage file ID under `cloud://.../weekly-posters/YYYYMMDD/...`.
- At least one of `poster_file_id`, `posterFileId`, or `cloudFileId` must normalize to that `cloud://` file ID on every item.
- Write both snake_case and camelCase aliases when the target schema expects them: `poster_file_id`, `posterFileId`, `cloudFileId`, `coverUrl`. Empty aliases must not overwrite non-empty internal file IDs.
- Set per-item `poster_storage=cloudbase` or `posterStorage=cloudbase`; manifest-level poster storage is not enough.
- `coverUrl` may contain the same `cloud://` file ID. Do not store `wxfile://`, `blob:`, HTTP temp URLs, or other expiring display URLs as package truth.
- Keep `missing_internal_poster_count=0`, `invalid_poster_storage_count=0`, `public_or_temp_poster_url_count=0`, and `public_wechat_or_qpic_poster_count=0` for release candidates.
- The backend truth is the `cloud://` file ID. The mini-program front end resolves it with `wx.cloud.getTempFileURL` in batches of max 50, renders the temp URL, and retains the original `posterFileId` for `wx.cloud.downloadFile` fallback. Do not pre-resolve or store temporary URLs in the package as source truth.

Main poster selection:
- Do not treat the WeChat article cover as the event poster by default.
- Enumerate and OCR all article images before choosing a main poster. `max_images=0` means full image processing and is the release default.
- Use StepFun `step-3.7-flash` and MiMo `mimo-v2.5` only as a small visual-review queue after OCR is empty, garbled, or ambiguous. DeepSeek/text/OCR handles the high-volume pass. Vision models are ambiguity reviewers, not source-of-truth replacements.
- MiMo uses the ordinary API endpoint `https://api.xiaomimimo.com/v1` and environment-provided keys only. Never write API keys into package files, reports, prompts, runbooks, or SSOT.
- Prefer the image whose OCR/visual evidence matches event title, date, time, venue, and lineup.
- Demote or reject QR-only images, ticket-only images, menu/drink specials, logos, maps, avatars, decorative images, and generic article covers unless they are the only source-backed event artwork and the candidate is explicitly flagged for review.
- If no internalized poster can be proven, block the package. Do not fall back to public WeChat/qpic URLs.

Source-action and Loopy constraints:
- Aggregate child event cards may remain visible, but aggregate child `source_action` must be disabled unless the child has its own exact source article.
- Do not let Loopy child events inherit the parent monthly overview article. The old Loopy overview hash `5dac0b21b5a77c34` must not be attached to child events such as `agg-child-4031b3921f885e8e`.
- `aggregate_child_source_enabled_count` must be 0.
- `aggregate_child_source_hash_present_count` must be 0. Disabled `source_action` is not enough if `sourceHash`, `source_hash`, `sourceRefId`, `source_ref_id`, `source_article.url_hash`, or `source_action.url_hash` still contains the parent/overview hash.

Date/current-feed constraints:
- Current feed must exclude stable past events relative to the package current date. For the 2026-06-05 lane, forbidden first-screen dates are 2026-06-02, 2026-06-03, and 2026-06-04.
- Multi-day events must use explicit `event_date_start` and `event_date_end`; do not fabricate ranges from non-contiguous parser guesses.
- Date filters must be derived from activity bounds and clamped by API date index.
- Every item must have `event_date_start` or `eventDateStart`. Legacy `date`, `act_date`, or `start_date` are not release truth and must not be used to pass the window gate.

Required local gates before deploy/upload:
- `node --test services/weekly_activity_cloudrun/tests/*.test.mjs --reporter=spec`
- `node --test apps/weekly_activity_miniprogram/tests/*.test.cjs --reporter=spec`
- `python tools/stage7_rewrite/scripts/validate_weekly_release_package_quality.py --api-dir services/weekly_activity_cloudrun/data/current_release --require-internal-posters --enforce-window-start`
- When aggregate-child poster OCR material is missing, run
  `build_weekly_aggregate_child_poster_ocr_source_material_preflight.py` and
  `build_weekly_exporter_freshness_preflight.py` before any OCR/vision worker.
  If `weekly_exporter_freshness_preflight.json` has `freshness_ready=false`,
  `queue_refresh_effective=false`, `invalid_session_error_count>0`, or a queue
  max post date older than the selected candidate source dates, fix exporter
  session / latest-queue freshness first. Do not tune StepFun/MiMo/OCR prompts
  or upload CloudBase posters from stale source material.
- `powershell -NoProfile -ExecutionPolicy Bypass -File tools/stage7_rewrite/scripts/run_weekly_miniprogram_full_acceptance.ps1`

Required evidence in the package report:
- item_count, strict current total, generatedAt, window_start/window_end
- poster_storage/posterStorage, poster_file_id/posterFileId/cloudFileId counts, missing_internal_poster_count
- invalid_internal_poster_file_id_count, invalid_poster_storage_count
- public_or_temp_poster_url_count and public_wechat_or_qpic_poster_count
- aggregate_child_source_enabled_count and aggregate_child_source_hash_present_count
- missing_event_date_start_count and outside-window item count
- CloudBase poster migration count and cloud_dir
- DevTools current render counts: itemCount/totalItems, cloudbaseTempPosterCount, internalPosterSourceFileIdCount, posterImageLoadCount, posterImageErrorCount

Never submit WeChat review or public release from the Docker skill. Development upload, review submission, and public release remain separate controller actions.
```

## Current Backend Truth

- CloudRun `weekly-api-030` reads `services/weekly_activity_cloudrun/data/current_release` and returns `cloud://` poster file IDs.
- `weeklyDataSync` syncs CloudRun current data into CloudBase hot DB without stripping poster fields.
- Mini-program runtime reads CloudBase hot DB first, then CloudRun/public fallback.
- Front-end render converts `cloud://` to CloudBase temp URLs at runtime; temp URLs are display-only, not package truth.
