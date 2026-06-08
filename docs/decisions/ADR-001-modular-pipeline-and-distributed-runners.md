<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# ADR-001: Modular Pipeline and Distributed Runners

## Status

Accepted

## Date

2026-04-22

## Context

The current priority is to finish the WeChat HTML archive pipeline safely. After this line runs through, later stages will expand beyond the Windows PC:

- Mac M3 Pro 32GB should run smaller local tasks such as embeddings, text cleanup, metadata normalization, and lightweight validators.
- A cloud RTX 5090 runner can handle heavier OCR/VLM, larger downstream LLM extraction, checkpoint evaluation, and batch reruns.
- The Windows PC remains the archive control plane and owns live roots such as `D:\DDownload\_archive_mptext`, `D:\DDownload\_llm_artifacts`, and `D:\DDownload\_llm_release`.

The project must avoid large coupled changes where modifying one stage breaks the whole program.

## Decision

Use a contract-first, stage-based pipeline. Each stage reads an explicit input directory or manifest and writes to an explicit output directory or result log. Stages communicate through versioned files, not hidden process state.

Stable boundaries:

- Archive stage: `raw.html`, `archive_meta.json`, `mptext-archive-results.jsonl`, `mptext-archive-status.json`.
- Audit stage: `archive-audit-summary.json`, `archive-audit-items.jsonl`.
- Queue stage: incomplete queue and Dajiala signed long-link candidate queue.
- Asset stage: `assets_local.json`, `images/*`, `asset-retention-results.jsonl`.
- LLM artifact stage: `llm_input.md`, `sidecar.json`, `quality_report.json`, `poster_ocr.json`, `meta.json`, `assets.json`.
- OCR stage: only writes derived OCR fields/files. It must not overwrite raw HTML or original images.
- Final pack stage: `manifest.json`, `index.jsonl`, `articles/*`.
- Downstream evaluation stage: isolated `_eval/*` outputs, never inside archive root or final pack.

Runner placement is configuration, not business logic:

- Windows PC: control plane, archive/audit/final pack boundary, conservative local LLM smoke runs.
- Mac M3 Pro 32GB: embeddings, text cleanup, small schema repair, small validators, and resumable preprocessing jobs.
- Cloud RTX 5090: OCR/VLM, heavy downstream LLM extraction, 300-1000 article checkpoints, and larger batch evaluation.

All model-backed stages must support OpenAI-compatible endpoints through environment variables, with `OPENAI_BASE_URL`, model id, timeout, token limits, prompt hash, input hash, and params hash recorded in result logs.

## Rules

- Prefer adding a new stage or adapter over changing an existing stage contract.
- Do not make a downstream stage read private raw HTML, cookies, auth material, or private service state.
- Do not let a remote runner write directly into live roots. Remote runners should write isolated output that is imported or validated by a control-plane step.
- Keep resume keys variant-safe: model id, prompt hash, input hash, and params hash are part of the identity.
- Every stage must be restartable and idempotent where practical.
- A failed optional stage should produce a warning/result record instead of corrupting upstream output.

## Consequences

- Future Mac/cloud work can be added as adapters around existing stage contracts.
- The final pack remains the stable model-consumption boundary.
- The project can evolve toward distributed processing without rewriting the current archive pipeline.
- Some extra manifest and result-log plumbing is required, but this reduces the risk of whole-program breakage.

## Follow-up ADRs

- `ADR-002: Graph Candidate Pack And Runner Contracts` implements the first concrete v2 graph boundary and runner packet contracts.
- Canonical local handoff: `UNDERGROUND_ELECTRONIC_MUSIC_GRAPH_PIPELINE_V2_HANDOFF_2026-04-22.md`.
