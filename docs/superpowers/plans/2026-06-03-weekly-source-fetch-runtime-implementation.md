# Weekly Source-Fetch Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement and run the explicitly released L2 source-fetch runtime so the 12 source-fetch rows produce summary/results/blockers for later no-coordinate-write acceptance.

**Architecture:** Keep the base OpenClaw Docker profile contract unchanged and network-disabled. Add a separate runtime override compose file that only affects `openclaw-source-queue-cache` under the controller release, and extend the container entrypoint to dispatch `source-fetch-runtime-dry-run`. The runtime reads the worker contract from the read-only `/workspace` mount, fetches only allowlisted `mp.weixin.qq.com` source URLs, writes report-local artifacts, redacts raw URLs/secrets, and never writes DB/coordinates/packages or invokes models/providers.

**Tech Stack:** Python standard library `argparse`/`json`/`urllib`, Docker Compose override, focused pytest coverage, existing npm script registry and release JSON artifacts.

---

### Task 1: Add Runtime Mode To Container Entrypoint

**Files:**
- Modify: `tools/stage7_rewrite/docker/openclaw-weekly/profile_report_entrypoint.py`

- [x] Add `--input-contract`, `--release-id`, `--runtime-run-id`, `--max-tasks`, and `--timeout-sec` arguments.
- [x] Dispatch `--mode source-fetch-runtime-dry-run` to a new source-fetch runtime path.
- [x] Validate every input task has `worker_layer=L2_SOURCE_EVIDENCE_FETCH`, profile/service `openclaw-source-queue-cache`, queue `openclaw.source_queue_cache`, and `https://mp.weixin.qq.com/` source URL.
- [x] Fetch only validated public source URLs with no cookies, tokens, browser profile, env file, model call, provider/geocode call, DB write, coordinate write, package mutation, CloudBase sync, upload, review, or release.
- [x] Write `weekly_current_missing_geo_source_fetch_runtime_summary.json`, `weekly_current_missing_geo_source_fetch_runtime_results.jsonl`, and `weekly_current_missing_geo_source_fetch_runtime_blockers.jsonl`.
- [x] Ensure output uses source URL hashes, sanitized evidence summaries, and leak counters; do not write raw source URLs.

### Task 2: Add Runtime Override Compose

**Files:**
- Create: `tools/stage7_rewrite/docker/openclaw-weekly/docker-compose.openclaw-weekly.source-fetch-runtime.yml`

- [x] Override only `openclaw-source-queue-cache`.
- [x] Set network policy for explicit L2 source-fetch release only.
- [x] Keep `/workspace` read-only and `/openclaw-reports` writable.
- [x] Do not add credential, browser profile, DB, CloudBase, package, or upload mounts.

### Task 3: Update Controller Release Command

**Files:**
- Modify: `tools/stage7_rewrite/scripts/build_weekly_current_missing_geo_source_fetch_controller_release.py`
- Modify: `tools/stage7_rewrite/tests/test_build_weekly_current_missing_geo_source_fetch_controller_release.py`

- [x] Include base compose and runtime override compose in the future runtime command.
- [x] Pass `--input-contract`, `--release-id`, `--runtime-run-id`, `--max-tasks 12`, and `--timeout-sec 20`.
- [x] Add checks that the runtime entrypoint contains source-fetch mode and the override compose exists.
- [x] Preserve `source_fetch_runtime_executed_by_this_packet=false`.

### Task 4: Test Locally Before Docker

- [x] Run focused pytest for entrypoint helpers and controller release.
- [x] Regenerate controller release.
- [x] Assert command uses the override compose and expected output directory.

### Task 5: Execute Bounded Runtime And Consume Result

- [x] Run the generated Docker Compose command once.
- [x] Verify expected summary/results/blockers exist.
- [x] Assert summary has `worker_task_count=12`, no raw URL/private path/secret leaks, no coordinate/DB/package/upload/release writes.
- [x] Generate or update source-fetch result acceptance packet before any provider/geocode or coordinate gate changes.

Result: runtime and acceptance are both report-local/no-coordinate-write. Runtime blocked all `12` rows with `wechat_environment_verification_required`; acceptance recorded `accepted_source_evidence_count=0`, so release/provider/coordinate gates remain closed.
