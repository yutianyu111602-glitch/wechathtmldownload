# Atlas Full Production Final Goals Design

Generated: 2026-05-21 14:50 CST

Project: `C:\code\githubstar\wechathtmldownload`

Thread scope: Atlas graph full production only. Weekly mini-program release/upload/review, CloudRun weekly publish, CloudBase billing, FinAgent, and cross-project cleanup are out of scope.

## Current Gate

The active Atlas public-search run is still the first hard gate:

- Status file: `tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json`
- PID: `108336`
- Required state before Post-Filter: `status == "COMPLETE"` and `processed_review_rows == queue_entity_keys`
- Current decision while the run is `RUNNING`: monitor only, do not kill, restart, or run full Post-Filter over partial output.

No production Neo4j, Qdrant, production SQLite, mem0, agentmemory, deploy, upload, paid model, browser profile, cookie, token, or broad D: operation is part of this design.

## Goal

Finish the Atlas subsequent-search production loop from complete raw public-search telemetry to a staged, source-backed graph-promotion packet, while keeping every intermediate layer report-only until the final promotion gate is explicitly satisfied.

## Design Options

### Option A: Gate-Led Full Production Chain

Wait for the full `246,024` entity-key public-search run to complete, run strict Post-Filter, feed only the reduced review queue into Layer D content evidence, HTTP Fast, OpenCLI, Maigret, source-context decision, rule adjudication, bounded LLM dual-pass, human validation, and then a report-only staging promotion gate.

This is the selected design because it preserves raw telemetry, keeps noisy entities quarantined, and prevents false positive graph edges.

### Option B: Direct Tool Fanout

Run OpenCLI, Maigret, Camofox, or LLM directly against raw public-search candidates.

This is rejected. The deep-research reports identify raw SearXNG output as broad telemetry, not identity proof. Direct fanout would waste runtime and increase false-positive risk.

### Option C: Manual-Only Pause

Stop at Post-Filter and wait for human review before any evidence tools.

This is useful for small audits but rejected as the main production path because the project already has report-only evidence runners and adjudication scripts that can safely reduce review workload before human sign-off.

## Selected Architecture

The pipeline is a staged evidence chain:

`raw public search -> Post-Filter -> reduced review queue -> content evidence / HTTP Fast / OpenCLI / Maigret -> source-context decision -> rule adjudication -> bounded LLM dual-pass -> human validation -> report-only Neo4j staging gate -> explicit production promotion decision`

The important boundary is that each layer may enrich evidence, classify risk, and produce review rows, but it must not accept graph edges by default. Accepted edge files remain empty unless the relevant script requires an explicit write flag and the promotion gate has passed.

## Components

### Public-Search Monitor

Reads the run status JSON and PID state only. It is allowed to produce checkpoint reports. It must not write `STOP_ATLAS_ENTITY_PUBLIC_SEARCH`, kill PID `108336`, or restart SearXNG slices.

### Post-Filter

Uses `tools\stage7_rewrite\scripts\build_atlas_entity_public_search_post_filter_queue.py` after completion. It writes new derived files under a dated report directory and keeps raw JSONL untouched. Known noisy entities such as `TAG`, `house`, `DADA`, `CISCO`, `Watermelon`, and `All` must be quarantined or kept out of the review queue.

### Layer D Content Evidence

Uses `tools\stage7_rewrite\scripts\fetch_atlas_entity_public_search_content_evidence.py` on the reduced review queue. Dry-run is the first gate; bounded HTTP or `scrapling-get` is allowed only after dry-run and count checks. Outputs remain `accepted_for_graph=false`, `identity_proof=false`, and `graph_write_allowed=false`.

### External Evidence Stack

Uses bounded report-only tools only after Post-Filter:

- HTTP Fast: `tools\stage7_rewrite\scripts\run_graph_external_evidence_http_fast.py`
- OpenCLI: `tools\stage7_rewrite\scripts\opencli_social_profile_evidence.py`
- Maigret: `tools\stage7_rewrite\scripts\run_maigret_http_canary.py` against the current local Maigret service only after service availability is rechecked
- Review merger: `tools\stage7_rewrite\scripts\build_atlas_open_source_phase1_review_queue.py` when the inputs use its expected schema

If the full Post-Filter review queue is not schema-compatible with existing Phase 1 seed inputs, the execution plan adds a small adapter instead of bending existing scripts around the wrong shape.

### Adjudication

Rule adjudication runs before LLM adjudication. LLM adjudication stays bounded, evidence-backed, and report-only by default. `--enable-write` is forbidden until the human and staging gates are met.

### Promotion Gate

Promotion is a report-only readiness operation first. Any actual production write remains a separate explicit decision after the gate report proves source-backed acceptance, quarantines are clean, tests pass, and current docs are synced.

## Success Criteria

- Full public-search run reaches `COMPLETE`.
- Post-Filter full run completes from full raw output, with raw files untouched.
- Known noisy terms are not present in the strict review queue.
- Layer D content evidence emits bounded content rows only from reduced review rows.
- HTTP Fast / OpenCLI / Maigret are run only on reduced candidates and remain report-only.
- Rule adjudication and LLM dual-pass produce review outputs without default graph acceptance.
- Staging promotion readiness is generated without production writes.
- `docs\current-runtime.md` and `docs\DOCUMENTATION_INDEX.md` point to the final status and evidence artifacts.

## Self-Review

- Completeness scan: no unfinished sections or vague command stubs.
- Scope check: Atlas graph subsequent-search only; weekly and unrelated lanes are excluded.
- Safety check: no secret, browser credential, production write, broad D: scan, deploy, or 9router action is included.
- Ambiguity check: Post-Filter is blocked until public-search status is `COMPLETE`; production promotion is a separate explicit gate after report-only staging readiness.
