<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# WeChat Super Night Watcher v3 PRD

Date: 2026-04-24

Workspace: `C:\code\githubstar\wechathtmldownload`

## Source Of Truth

This PRD is subordinate to the live production safety rules in:

- `SUPER_NIGHT_WATCHER_PLAN_2026-04-24.md`
- `NIGHT_WATCHER_HANDOFF_2026-04-22.md`
- `NIGHT_WATCHER_MAINTENANCE_MANUAL_2026-04-22.md`
- `NIGHT_WATCHER_LOG_2026-04-22.md`

## Problem

The WeChat archive pipeline has moved past the asset phase into export and downstream preparation. The watcher must now supervise a longer chain without duplicating active jobs, overwriting live artifacts, or silently switching model/OCR backends.

Two new production requirements changed the watcher contract:

- OCR must use PaddleOCR as the main engine and preserve the current `poster_ocr.json` contract.
- Downstream text LLM must use the local `Qwen3.6-27B` GGUF through the local OpenAI-compatible endpoint, with a calibration gate before the 20-50 downstream matrix.

## Goals

1. Continue current `export_llm` safely until completion.
2. Promote to OCR only after export output validation passes.
3. Use PaddleOCR GPU as the primary OCR engine while preserving `backend / plain_text / blocks`.
4. Use `qwen3-vl` only as OCR fallback for weak Paddle results or review/blocked samples.
5. Run `qwen3.6_calibration` before formal downstream evaluation.
6. Run only `downstream_matrix_50`, then stop at `checkpoint_stop`.
7. Keep every heartbeat user-visible while this watcher is active.
8. Preserve raw descriptive entity text exactly: entity bios, label/collective/organizer intros, and venue info must never be LLM-abstracted.
9. Treat Mac as a future light-task runner only, not as the control plane.

## Non-Goals

- Do not run global watermark removal.
- Do not rewrite normal image assets destructively.
- Do not run the 300-1000 checkpoint, full downstream batch, graph candidate pack, ignuke, or `D:\DJ_DATA` registry writes.
- Do not migrate, restart, prune, or clean Docker Desktop automatically.
- Do not kill, restart, delete, clean, or overwrite live-root artifacts.
- Do not generate synthetic bios, label introductions, or venue descriptions.
- Do not let Mac read, write, clean, or directly mutate `D:\DDownload` live root.
- Do not call Mac-local `127.0.0.1` from Windows; use a Mac host address or explicit tunnel only through runner packs.

## Current Facts

- Current live stage: `export_llm`.
- Previously accepted blockers remain accepted: `247` missing `raw.html` bundles and `4` residual failed assets.
- PaddleOCR GPU is repaired on this host.
- Main OCR wrapper: `tools\ocr-image-paddle.ps1`.
- Paddle runner: `tools\ocr_image_paddle_runner.py`.
- Qwen calibration runner: `tools\runQwenCalibrationSweep.mjs`.
- Local Qwen alias: `Qwen3.6-27B`.
- Local Qwen model file: `D:\AI\models\Qwen3.6-27B\Qwen3.6-27B-Q4_K_M.gguf`.
- Local Qwen endpoint: `http://127.0.0.1:11434/v1`.
- Router config: `C:\llama-cpp\config.yaml`.
- Qwen route uses `--reasoning off` so downstream reads `message.content`.
- Mac light-runner capability is verified but not part of the current live gate: Mac-local `bge-m3` embedding on `http://127.0.0.1:8091`, Mac-local Qwen2.5-Coder OpenAI-compatible on `http://127.0.0.1:8093`.

## Mac Runner Boundary

- Windows remains the live-root control plane.
- Mac is allowed only for later light tasks: embedding, schema repair, text cleanup, validator, and dedup/rerank assistance.
- Mac runner inputs must be runner job packs.
- Mac runner outputs must be runner result packs.
- Windows must validate schema, hashes, row counts, and error summaries before any result can affect the pipeline.
- Mac capability does not authorize OCR, final pack, downstream, graph, or registry work while export is active.

### Mac Raw Service Outputs

The verified Mac responses are capability evidence, not production artifacts:

- `GET /health` on `http://127.0.0.1:8091`: embedding service health passed.
- `POST /embed` on `http://127.0.0.1:8091`: returned `2` vectors, each with dimension `1024`.
- `GET /v1/models` on `http://127.0.0.1:8093`: exposed `qwen2.5-coder-7b-instruct-q4_k_m.gguf`.
- `POST /v1/chat/completions` on `http://127.0.0.1:8093`: returned a successful OpenAI-compatible chat completion.
- LaunchAgents are running: `com.masher.embedding.bge-m3`, `com.masher.llamacpp.qwen2.5-coder`.

### Mac Runner Result Pack Outputs

When Mac runner work is enabled later, Windows accepts only a result pack:

- `results.jsonl`: one row per task with `article_id`, `runner_id=mac-m3pro`, `status`, `model_id`, `input_hash`, `output_hash`, and `output_paths`.
- `errors.jsonl`: failed tasks and error details.
- `run_summary.json`: task counts, endpoint/model metadata, elapsed time, and error summary.
- `hashes.json`: checksums for output files.
- Embedding outputs must include `vector_count` and `dimension=1024`; vector data lives inside the result pack, not in live root.
- Schema repair, text cleanup, validator, and dedup/rerank outputs must preserve raw responses plus normalized JSON and must not overwrite input files.

## Functional Requirements

### Stage Supervision

- Detect the active stage from status files and matching processes.
- If the current stage is active, monitor only.
- Never start a duplicate batch for the same stage.
- Resume only when the stage is stale/stopped, work remains, and no matching process exists.

### Export Gate

- Treat `export-llm-status.json` as the source of truth.
- Promote only when export is completed and sample artifacts contain:
  - `llm_input.md`
  - `sidecar.json`
  - `quality_report.json`
  - `poster_ocr.json`

### OCR Gate

- Set `WECHAT_OCR_COMMAND` to `tools\ocr-image-paddle.ps1`.
- Require Paddle output JSON to include `backend`, `plain_text`, and `blocks`.
- Keep `tools\ocr-image-openai.ps1` only as qwen3-vl fallback.
- Do not silently switch qwen3-vl back to main OCR.

### Qwen Calibration Gate

- Before calibration, verify `/v1/models` contains `Qwen3.6-27B`.
- If missing, set `need_human=true` and stop.
- Run `tools\runQwenCalibrationSweep.mjs --modelAlias Qwen3.6-27B`.
- Treat raw entity info preservation as a scoring gate: entity bios, label/collective/organizer intros, and venue info must be exact source spans or empty with a warning.
- Compare at least:
  - `strict`: temperature `0.05`, top_p `0.80`, max_tokens `2048`
  - `stable`: temperature `0.10`, top_p `0.90`, max_tokens `2048`
  - `balanced`: temperature `0.20`, top_p `0.92`, max_tokens `2304`
  - `wide`: temperature `0.30`, top_p `0.95`, max_tokens `2304`
- Use fixed samples, fixed prompts, and at least `2` rounds per profile.
- Stop for human review if there is no clear recommended profile.
- Stop for human review if sampled outputs show those fields were summarized, paraphrased, abstracted, translated, shortened, merged, normalized, or invented.

### Downstream Matrix Gate

- Start `downstream_matrix_50` only after calibration produces a recommended params file.
- Use `Qwen3.6-27B` and `qwen3.6-recommended-params.json`.
- Stop after `checkpoint_stop`.

## Acceptance Criteria

- `/v1/models` exposes `Qwen3.6-27B`.
- A minimal chat request to `Qwen3.6-27B` returns non-empty `message.content`.
- The watcher plan names `Qwen3.6-27B` directly, not a placeholder alias.
- The watcher prompt treats missing alias as a future regression, not the current state.
- PaddleOCR remains the documented main OCR engine.
- Downstream prompts and runners include the raw entity info preservation guardrail.
- The watcher stops after `downstream_matrix_50`.

## Heartbeat Output Contract

Each heartbeat reports:

- `decision`
- `need_human`
- `current_stage`
- counts from current status file
- matching process presence
- current OCR and text-model policy
- next action
