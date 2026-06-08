<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# ADR-002: Graph Candidate Pack And Runner Contracts

## Status
Accepted

## Date
2026-04-22

## Context

The WeChat archive pipeline is moving from article preservation toward a Chinese underground electronic music entity graph. The graph cannot treat LLM output as truth. It needs stable evidence, replayable model jobs, cross-machine execution, and a dry-run boundary before `ignuke` admission.

The deployment shape is asymmetric:

- Windows PC with RTX 4090 owns the live archive roots and remains the control plane.
- Mac M3 Pro 32GB should run light jobs such as embeddings, schema repair, text cleanup, and validation.
- Cloud RTX 5090 can run heavy OCR/VLM/checkpoint jobs, but upload and download bandwidth are slow.

## Decision

Add three explicit contracts:

- `StageRunManifest` / `StageResultLogRow` for resumable stage identity and append-only result logging.
- `RunnerJobPack` / `RunnerResultPack` for isolated Mac/cloud work packets that never write live roots directly.
- `GraphCandidatePack` for evidence-first entity, claim, relationship, event, alias, review, evidence, and source article outputs.

Downstream LLM resume must be variant-safe. The resume key is based on:

```text
stage + article_id + input_sha256 + model_id + prompt_sha256 + params_hash + schema_version
```

`final pack` remains the stable model-consumption boundary. `graph candidate pack` is the stable graph-consumption boundary. `ignuke` integration starts with dry-run validation and keeps admission disabled by default.

The canonical local handoff and current operating entry for the whole v2 graph line is:

- `HANDOFF.md`
- `UNDERGROUND_ELECTRONIC_MUSIC_GRAPH_PIPELINE_V2_HANDOFF_2026-04-22.md`

`HANDOFF.md` owns current path, variable, automatic Dajiala repair, and automation-boundary wording. This ADR records the architectural contract and does not override live-operation gates.

## Alternatives Considered

### Direct LLM Result Import

- Pros: Fastest path to visible graph data.
- Cons: Makes hallucinations and parse errors look like facts.
- Rejected: The target graph must be evidence-first.

### Cloud 5090 As Primary Pipeline

- Pros: More compute headroom.
- Cons: Slow transfer, privacy risk, no live root ownership.
- Rejected: Cloud runner should process small heavy packets only.

### One Large Refactor Before New Outputs

- Pros: Cleaner final shape.
- Cons: Higher risk while long-running archive work is still active.
- Rejected: Additive contracts and tests are safer.

## Consequences

- New code can build runner packs, validate result packs, build graph candidate packs, dry-run `ignuke` imports, and register packs.
- Dajiala repair now has a unified result log.
- Final packs now include `checksums.sha256`.
- Downstream LLM batch resume reruns when model/prompt/params/schema changes.
- Remote runner output must pass schema/hash/count checks before Windows imports it into staging.
