<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Underground Electronic Music Graph Pipeline Design

Canonical local handoff:

- `HANDOFF.md`
- `UNDERGROUND_ELECTRONIC_MUSIC_GRAPH_PIPELINE_V2_HANDOFF_2026-04-22.md`

`HANDOFF.md` owns current path, variable, repair, and automation-boundary wording.

## Product Goal

Build a traceable, reviewable graph of Chinese underground electronic music entities from WeChat articles, posters, lineups, venues, labels, promoters, collectives, events, accounts, and related cross-platform clues.

## Architecture

```text
HTML archive
  -> final audit
  -> incomplete / Dajiala candidates
  -> automatic low-concurrency repair when signed candidates exist
  -> asset localization
  -> LLM export
  -> OCR/VLM enrichment
  -> final pack
  -> small LLM matrix
  -> stop before 300-1000 checkpoint unless confirmed
  -> graph candidate pack
  -> ignuke dry-run
  -> reviewed admission
```

External network evidence extension, 2026-05-17:

```text
graph/entity seed queue
  -> HTTP fast evidence
  -> OpenCLI public search / selected adapters
  -> Maigret public handle candidate scan
  -> Camofox browser fallback for JS/anti-bot/public authorized pages
  -> normalized evidence JSONL
  -> review queue
  -> graph candidate pack
  -> ignuke dry-run
  -> reviewed admission
```

This extension is report-only until a later gate accepts it. It does not replace archive/OCR/LLM/final-pack flow.

## Stable Boundaries

- Archive root is evidence storage and remains owned by Windows.
- Final pack is the only stable model input boundary.
- Runner job/result packs are the only cross-machine boundary.
- Graph candidate pack is the only graph import boundary.
- Network entity evidence is an input to graph candidate review, not a production graph write path.
- `ignuke` dry-run validates compatibility but does not admit facts.

## Implemented V2 Contracts

- `src/stage/contracts.ts`
  - `StageRunManifest`
  - `StageResultLogRow`
  - stable params hash
  - idempotency key validation
- `src/runners/runnerPack.ts`
  - create runner job pack
  - validate runner result pack
- `src/graph/graphCandidatePack.ts`
  - build entity/claim/relationship/event/alias/review/evidence/source outputs
- `src/ignuke/dryRunImport.ts`
  - validate entity, claim, relationship, and evidence consistency
- `src/packs/packRegistry.ts`
  - register final, graph, runner, and vector packs with checksums

## Runner Policy

- `windows-4090`: control plane, live archive owner, final pack owner, primary local compute.
- `mac-m3pro`: embeddings, cleanup, schema repair, validation, dedup, rerank.
- `cloud-5090`: OCR/VLM difficult samples and 300-1000 article checkpoints only.

Remote runners must not receive cookies, auth state, private service state, full raw archive roots, or write permissions to live roots.

Mac service readiness update, 2026-04-24: `mac-m3pro` now has a verified Mac-local `bge-m3` embedding service on `http://127.0.0.1:8091` (`GET /health`, `POST /embed`, 1024-dimensional vectors) and a verified Mac-local Qwen2.5-Coder llama.cpp OpenAI-compatible service on `http://127.0.0.1:8093` (`GET /v1/models`, `qwen2.5-coder-7b-instruct-q4_k_m.gguf`, small chat completion passed). These endpoints are Mac-local only; Windows must use a Mac host address or explicit tunnel and still exchange data through runner packs.

## Graph Policy

- Entities are candidates.
- Claims must include evidence.
- Relationships are derived from claims.
- Vectors are recall aids only.
- Low confidence or missing evidence goes to review.
- Public search results are leads only.
- Maigret positives are `profile_candidate` only, never direct `HAS_PROFILE`.
- Browser-rendered evidence must keep provenance and access mode; no raw cookies, tokens, or private content.

## Network Entity Evidence Policy

Source audit:

- `tools/stage7_rewrite/NETWORK_ENTITY_SEARCH_METHOD_AUDIT_20260517.md`
- `tools/stage7_rewrite/OPENCLI_EXTERNAL_EVIDENCE_PLAN_20260516.md`

Tool roles:

| Tool | Pipeline role | Hard boundary |
|---|---|---|
| HTTP fast evidence | first-pass known URL metadata/images/links | no login, no browser, no DB write |
| OpenCLI | bounded public search and adapter proof | no 93k/47k full-corpus crawl, no social write commands |
| Maigret | public handle candidate discovery | no private-person dossier; positive result still needs review |
| Camofox | browser fallback for JS/anti-bot/public authorized pages | no private content, no cookie/token output, cleanup session |

Normalized outputs:

```text
reports/entity_network_YYYYMMDD/seeds.jsonl
reports/entity_network_YYYYMMDD/http_fast_evidence.jsonl
reports/entity_network_YYYYMMDD/opencli_search_results.jsonl
reports/entity_network_YYYYMMDD/maigret_profile_candidates.ndjson
reports/entity_network_YYYYMMDD/camofox_browser_evidence.jsonl
reports/entity_network_YYYYMMDD/normalized_evidence.jsonl
reports/entity_network_YYYYMMDD/review_queue.jsonl
reports/entity_network_YYYYMMDD/summary.md
```

Admission rule:

- `search-result-only`, `maigret-only`, and `browser-rendered-only` evidence cannot create relationships by themselves.
- `HAS_PROFILE`, profile image, official external link, and source image claims need direct-source or manual-review acceptance.
- All accepted records must enter the normal `GraphCandidatePack -> ignuke dry-run -> reviewed admission` path.

## CLI Surface

```text
create-runner-job-pack
validate-runner-result-pack
build-graph-candidate-pack
ignuke-dry-run-import
register-pack
```

Existing commands remain the production path for audit, repair, assets, export, OCR, final pack, and downstream LLM.

## Production Gating

Do not run production graph pack, `ignuke` dry-run on real outputs, or `D:\DJ_DATA` registry writes until:

- HTML archive status is completed.
- Final audit has closed counts.
- Final pack exists and passes checksums/safety validation.
- The 20-50 article LLM matrix has produced accepted downstream outputs.
- The operator has explicitly moved past the 300-1000 checkpoint gate.

## Data Lake Policy

`D:\DJ_DATA` is the future pack registry and data lake, not the current live processing root. It should receive registered final, graph, runner, and vector packs only after the Windows control plane validates hashes, schemas, row counts, and error summaries.
