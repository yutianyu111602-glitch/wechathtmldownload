<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Underground Electronic Music Graph Pipeline Implementation Plan

Canonical local handoff:

- `HANDOFF.md`
- `UNDERGROUND_ELECTRONIC_MUSIC_GRAPH_PIPELINE_V2_HANDOFF_2026-04-22.md`

`HANDOFF.md` owns current path, variable, repair, and automation-boundary wording.

## Phase 1: Contract Foundation

- [x] Add `StageRunManifest` and `StageResultLogRow`.
- [x] Add stable params hashing and idempotency validation.
- [x] Add checksums writer for pack outputs.
- [x] Add final pack `checksums.sha256`.

## Phase 2: Safer Resume And Repair Logs

- [x] Add downstream LLM manifest fields for model, prompt, params, schema, and idempotency.
- [x] Change downstream batch resume to skip only matching idempotency keys.
- [x] Add Dajiala repair append-only result log.

## Phase 3: Runner Isolation

- [x] Add runner job pack creation.
- [x] Copy lightweight article inputs and optional local image subset.
- [x] Add runner result pack validation.
- [x] Expose CLI commands for job pack creation and result validation.

## Phase 4: Graph Candidate Boundary

- [x] Add graph candidate pack builder.
- [x] Emit `entities.jsonl`, `claims.jsonl`, `relationships.jsonl`, `events.jsonl`, `aliases.jsonl`, `review_queue.jsonl`, `evidence_spans.jsonl`, and `source_articles.jsonl`.
- [x] Derive relationship edges from claims.
- [x] Add `ignuke` dry-run validator with admission disabled.

## Phase 5: Pack Registry

- [x] Add checksum-backed pack registry.
- [x] Expose `register-pack` CLI.

## Phase 6: Production Use After HTML Completed

- [ ] Wait for mptext HTML archive to reach completed.
- [ ] Run final audit to `D:\DDownload\_reports\archive-audit-final`.
- [ ] Generate `D:\DDownload\_queues\archive_incomplete_queue.jsonl` and `D:\DDownload\_queues\dajiala_signed_repair_candidates.jsonl`.
- [ ] Run Dajiala repair automatically with low concurrency and result log when signed candidates exist.
- [ ] Run assets, export, OCR, and final pack.
- [ ] Run 20-50 article LLM matrix.
- [ ] Stop before the 300-1000 article checkpoint unless confirmed.
- [ ] Build graph candidate pack from accepted downstream sample output.
- [ ] Dry-run `ignuke` import.
- [ ] Register final/graph packs under `D:\DJ_DATA` when ready.

## Phase 7: Documentation Sync

- [x] Save local v2 handoff.
- [x] Update `HANDOFF.md`.
- [x] Update `MASTER_HANDOFF_AND_FUTURE_PLAN_2026-04-22.md`.
- [x] Update `PIPELINE_NEXT_ACTION_TODOS_2026-04-22.md`.
- [x] Update ADR/spec/plan/Ralph PRD references.

## Verification

- [x] `npm run build`
- [x] `npm test`

## Notes

The implementation deliberately does not run live post-processing while `D:\DDownload\_archive_mptext` is still active. New commands are additive and safe to exercise on copied sample packs.
