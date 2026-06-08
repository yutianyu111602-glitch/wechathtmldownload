# Configuration Reference

Updated: 2026-05-26

This repo uses package scripts, JSON profiles, prompt files, CLI flags, and status/manifest files rather than one single config file.

2026-05-26 T6 broader source-context recovery uses only file path CLI defaults and existing report artifacts. `build_atlas_social_broader_source_context_recovery_packet.py` adds no secret, provider, network, or runtime service config; it reads current T5 work-order JSONL files and writes report-only review slices.

2026-05-25 T5 venue acceptance uses only file path CLI defaults and existing report artifacts. `build_atlas_dj_venue_acceptance_gate.py` adds no secret, provider, network, or runtime service config; it reads venue auto candidates plus source/serving SQLite files in read-only mode, then writes report-only review artifacts.

2026-05-25 YYYY identity acceptance uses only file path CLI defaults and existing report artifacts. `build_atlas_social_yyyy_identity_acceptance_gate.py` adds no secret or provider config; it reads the accepted source-context JSONL and rendered public-profile evidence JSONL, then writes report-only review artifacts.

2026-05-24 T6 OpenCLI rendered-profile evidence uses script flags rather than secret config: `--opencli-bin`, `--profile`, `--session`, `--limit`, `--timeout-sec`, and `--wait-sec`. The default browser profile/session values are used only for bounded public profile rendering and must not be used to read or print cookies, tokens, browser credentials, or private account state.

## Runtime/package basics

- Node engine: `>=20`
- TypeScript target: `ES2022`
- Module system: `NodeNext` / ESM
- Electron main: `desktop/main.mjs`
- Desktop app id: `com.githubstar.wechathtmldownload`
- Desktop product name: `WeChat History HTML Pipeline`

## mptext / Docker exporter auth

The mptext exporter login expires periodically. In this workspace, `ret=200003 invalid session` should be treated first as an expired Docker exporter login state, not as a dedupe or weekly extraction failure.

Current auth resolution:

- Default: discover the latest 32-hex filename under `.mptext-data\kv\cookie` and use that as the current exporter auth key.
- `MPTEXT_COOKIE_DIR`: optional override for the cookie directory.
- `MPTEXT_DATA_DIR`: optional override for the `.mptext-data` root.
- `MPTEXT_AUTH_KEY`: still supported as fallback or for manual override.
- `MPTEXT_AUTH_KEY_PREFER_ENV=1`: force environment key before Docker discovery.
- Diagnostic scripts print only `auth_source` and `auth_key_hash`; do not print key/cookie material.

Use this health check after relogin:

```powershell
python tools\stage7_rewrite\scripts\diagnose_weekly_exporter_session.py --auth-source auto --out <scoped-output-json>
```

Expected healthy state: `decision=exporter_session_ok`, `session_ok=true`, `auth_source=docker-data` or explicit override, and `ret=0`.

## Model/runtime profiles

- `profiles/qwen36_27b_4090_llama_specdec_winning_candidate.json`
- `profiles/qwen36_27b_4090_longctx_experimental.json`
- `profiles/qwen36_27b_4090_stage7_default.json`
- `profiles/qwen36_27b_4090_stage7_safe.json`

## Prompts

- `prompts/downstream/event_extract.compact-json.md`
- `prompts/downstream/event_extract.evidence-first.md`
- `prompts/downstream/event_extract.repair-json.md`
- `prompts/downstream/event_extract_v4_zh.md`
- `prompts/stage7/00_system_extractor_zh.md`
- `prompts/stage7/01_article_precheck_foreman_zh.md`
- `prompts/stage7/02_main_extract_graph_candidate_zh.md`
- `prompts/stage7/02_main_extract_graph_candidate_zh_v1.md`
- `prompts/stage7/02_main_extract_graph_candidate_zh_v2_bio_locked.md`
- `prompts/stage7/02_main_extract_graph_candidate_zh_v3_short.md`
- `prompts/stage7/03_json_repair_zh.md`
- `prompts/stage7/03_json_repair_zh_v1.md`
- `prompts/stage7/04_schema_validation_judge_zh.md`
- `prompts/stage7/05_empty_result_judge_zh.md`
- `prompts/stage7/06_event_relation_refine_zh.md`
- `prompts/stage7/07_entity_merge_candidate_zh.md`

## Important output/status patterns

- `--inputDir`, `--outDir`, `--mirrorDir`, `--statusPath`, `--resultLogPath`, `--manifestPath`, `--artifactRoot`, `--artifactListPath`, `--archiveRoot`, `--accountsPath`, `--queuePath` are accepted by `src/cli.ts`.
- Default command concurrency in `src/cli.ts` starts at `3`; account prefetch concurrency starts at `2` unless flags override it.
- `--resume`, `--once`, `--noFallback`, `--deferExistingPartialOnResume`, and `--requireSignedLongLink` are important runtime switches.
- For OCR recovery, set `WECHAT_OCR_COMMAND` to `powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\ocr-image-paddle.ps1` before running `ocr-poster-batch` if no OCR command is already configured.
- For no-local-image recovery, use `tools\stage7_rewrite\scripts\run-recapture-asset-chunks.ps1` with explicit `-QueuePath`, `-RunRoot`, `-ChunkSize`, `-DiskStopPercent`, and `-MinRemainMoney`. The script writes `chunk-runner-status.json` under the run root and can resume from `next_chunk`.
- `archive-batch`, Dajiala repair, and asset download now share stricter archive quality gates. Captcha/platform HTML, Dajiala reconstructed HTML without meaningful article content, partial/failed archives, and stale empty `assets_local.json` must not be treated as recovered assets.
- For 2026-05-06 unattended night recovery, use `tools\stage7_rewrite\scripts\run-night-watchdog.ps1`. Default heartbeat root is `D:\downstream_results\stage7_rewrite\longrun\NIGHT_WATCHDOG_20260506`; `-EnableDajialaCanary` only permits the latest-post blocked canary. Historical empty-link recovery is separately controlled by `FULL_EMPTY_LINK_RECOVERY_20260507` wave plans and audit gates.
- For historical empty-link recovery, use `tools\stage7_rewrite\scripts\build_full_empty_recovery_wave.py --wave-size N --out-dir ...` before paid short2long. The planner excludes prior intake and prior short2long attempts, including prior `FULL_EMPTY_LINK_RECOVERY_*\SHORT2LONG_WAVE_*` runs.
- For weekly activity recommendation intake, use `tools\stage7_rewrite\scripts\build_weekly_activity_queue.py --out-dir ...` after a successful bounded prefetch. If prefetch returns `ret 200003 invalid session`, refresh the Docker exporter login and rerun the diagnostic above; current scripts auto-discover the latest Docker cookie key after relogin.
- For the weekly activity mini-program MVP, use `tools\stage7_rewrite\weekly_activity_next_week_pipeline.ps1 -WindowDays 15 -MaxItems 10000`. The current publish lane runs queue -> pack -> OCR -> entity -> aggregate expansion -> API -> repair/audit -> release. Aggregate parents are blocked from direct publish; secondary `mp.weixin.qq.com` links are fetched through WeChat exporter/mptext first, with Dajiala `article_detail` as a bounded content fallback when configured.
- For DJ Interview local intake, use `npm run weekly:dj-interview:import -- --input <file-or-dir> --dry-run` first. Supported draft formats are Markdown front matter, JSON, and JSONL. Import requires explicit internal-processing consent and writes only to the private sidecar.
- Mini-program DJ Interview mixtape/Instagram links are original-platform links only. `apps\weekly_activity_miniprogram\utils\externalLinkAction.js` copies safe `http(s)` page links and rejects direct media file URLs before submit; do not configure audio/video cache/proxy/download hosting for this lane.
- Mini-program WXML event wiring is checked by `apps\weekly_activity_miniprogram\tests\page-event-handler-coverage.test.cjs`; share coverage is derived from `app.json` in `share-wiring.test.cjs`. Deploy/upload preflight dynamically includes every `apps\weekly_activity_miniprogram\tests\*.test.cjs` file; S30 evidence lives under `tools\stage7_rewrite\reports\weekly_deploy_upload_preflight_s30_20260531`.
- Before future Weekly CloudRun deploy or mini-program upload claims, run `npm run weekly:deploy-upload:preflight`. The preflight does not auto-discover or read private key material; Clean-CI quality is skipped unless an explicit `--clean-ci-private-key-path` is supplied.
- Dajiala supplement keys for the weekly aggregate lane are read only from runtime environment. `expand_weekly_aggregate_articles.py` accepts `DAJIALA_API_KEY` and falls back to `JZL_API_KEY`; `weekly_activity_next_week_pipeline.ps1` imports relevant Windows User/Machine env vars into the current process without logging values. Dajiala content is only evidence input and still must pass DeepSeek Pro source-grounded extraction plus duplicate/conflict/field audits.
- For bounded Stage7 canary release candidates, use `finalize-llm-pack --intakeManifestPath ... --intakeOnly --limit N` to skip the base artifact-root scan. The 2026-05-07 night orchestrator uses limit `200` to keep D: HDD IO below the watchdog threshold.
- Stage7 release inputs may be nested as `source/account/token`; `tools\stage7_rewrite\stage7\audit_inputs.py` discovers article dirs recursively by `llm_input.md`.
- Stage7 LLM extraction uses the llama-swap OpenAI-compatible route in `tools\stage7_rewrite\config\default.yaml`: `api_style: openai_compatible`, endpoint `http://192.168.128.1:11434`, model `Qwen3.6-27B`. Do not switch this lane back to Ollama `/api/chat`; that route returned HTTP 404 on 2026-05-07.
- `run-llm --resume` must retry `failed_retryable` rows. Treating retryable rows as already processed caused transient endpoint failures to survive after the model route was fixed.
- Historical empty-link recovery resumes disk-paused free processing via `run-full-empty-wave-supervisor.ps1`, which passes `-StartChunk` from `chunk-runner-status.json.next_chunk`.
- Stage8 vector routing uses `tools\stage7_rewrite\config\vector_endpoints.yaml`. The default 93k WeChat entity/event/relation endpoint is `local_mac_vector_endpoint_11437`, model `stella-large-zh-v2`, dimension `1024`. The config keeps both `canonical_url` (`http://127.0.0.1:11437`, Mac-local) and `pc_call_url` (`http://192.168.8.234:11437`, PC runtime call path).
- Stage8 vector jobs produced by `stage7.cli build-vector-jobs` carry route metadata in each row: `endpoint_id`, `endpoint_port`, `canonical_url`, `pc_call_url`, `route_role`, and `dim_expected`. This is required so fallback usage and dimension mixing can be audited later.
- `tools\stage7_rewrite\scripts\build_atlas_full_source_lineage.py` is the current read-only atlas source-lineage builder. It scans bounded project script/config roots, records D:/mnt/d path references without opening or scanning D:, and writes the 47k/93k/FULL_MAP/V6/OCR/Dajiala/vector/network production decision table under `tools\stage7_rewrite\reports\atlas_full_source_lineage_47k_93k_gap_20260519`.
- `tools\stage7_rewrite\scripts\build_atlas_gap_backfill_execution_packet.py` is the current read-only residual gap/backfill decision builder. It consumes the source-lineage packet, gap ledger, and Dajiala ROI gate packet, then writes the no-rerun / hold / gated-backfill action table under `tools\stage7_rewrite\reports\atlas_gap_backfill_execution_packet_20260519`.
- `tools\stage7_rewrite\scripts\build_external_identity_source_context_decision_packet.py` is the current read-only P3 source-context decision builder. It consumes recovered source-context candidates and writes future-direct-proof, review-only, and rejected-for-now queues under `tools\stage7_rewrite\reports\external_identity_source_context_decision_47k_delta375_20260519`, with accepted graph edges forced to `0`.

## Safety

- Do not store real secrets in this repo.
- Do not read unscoped account/cookie/key material.
- Treat `tmp-*`, `.mptext-data`, `.omc`, `runs/`, `reports/`, and `artifacts/` as generated/runtime evidence unless explicitly promoted.
