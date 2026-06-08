# Weekly Mini-Program Atlas Evidence Provenance V2 Plan

Status: Design/Planning only. No production write, deploy, mini-program upload, or WeChat review submission.

Generated: 2026-05-21 23:35 CST

This plan replaces the earlier upgrade plan as the implementation blueprint for the weekly mini-program downstream evidence layer. It combines:

- `docs/CLAUDE_WEEKLY_MINIPROGRAM_ATLAS_CROSSCHECK_UPGRADE_PLAN_20260521.md`
- `tools/stage7_rewrite/reports/deep_research_plan_critique_20260521.json`
- current runtime truth in `docs/current-runtime.md`
- HUAIDJ Weekly Release Guardian boundaries

## 1. Current Truth Lock

Any implementation session must start by proving the current runtime truth. Do not trust counts embedded in older plans.

As of `docs/current-runtime.md` updated `2026-05-21 23:10 CST`:

- Remote-effective CloudRun service: `weekly-api-045`.
- Backend package: `D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260521_BACKEND_REFRESH_CURRENT`.
- Manifest/current count: `127`.
- Materialized LLM cache: `127/127`; CloudRun serves cached output and does not call LLM at request time.
- Release Guardian: `GateMode=current-package ok=true`, `remoteTotal=127`, `backendRawHits=0`, `visibleHits=0`, `missingSourceHash=0`, `missingSourceMapUrl=0`, mini-program tests `37 pass`.
- Mini-program developer version was not uploaded in the backend refresh slice.
- WeChat review was not submitted.
- Local frontend hardening exists but has not been uploaded.

Local schema snapshot from `services/weekly_activity_cloudrun/data/current_release/current.json`:

- `evidence`: `127/127` non-empty.
- `field_evidence_refs`: `0/127` non-empty.
- `entity_links`: `0/127` non-empty.
- `description_original_lines`: `126/127` non-empty.
- `merge_provenance`: `10/127` non-empty.
- `time_verification`: `64/127` non-empty.

Interpretation: coarse item evidence exists, but field-level evidence and entity link evidence are not implemented in the current package.

## 2. Scope

This V2 plan is for the weekly mini-program downstream consumer:

```text
source article / OCR artifacts
  -> local LLM materialization
  -> field-level evidence refs
  -> read-only Atlas resolver
  -> API resource package
  -> release guardian
  -> mini-program display compatibility
```

Atlas remains read-only enrichment in this thread. The goal is to prevent duplicate uploads, preserve source-article context, and make extracted event fields auditable.

## 3. Non-Goals And Hard Boundaries

- Do not deploy CloudRun from this plan.
- Do not upload or submit the mini-program from this plan.
- Do not write Neo4j, Qdrant, production SQLite, or Atlas production graph state.
- Do not run OpenCLI, Maigret, Camofox, Scrapling, or broad public-search work from raw Atlas telemetry.
- Do not kill unrelated Atlas/search PIDs.
- Do not call LLM at CloudRun request time.
- Do not use local `9router`.
- Do not read, print, or export secrets, cookies, tokens, or `.env` values.
- Do not scan unbounded `D:\` roots.
- Do not make `backendRawHits` a release blocker unless a specific raw-payload cleanup task declares that scope. `visibleHits=0` remains the user-visible hard gate.

## 4. Design Principles

1. Runtime truth before plan truth.
   Every run first locks the current remote-effective service, local package path, mini-program upload state, and review state.

2. Additive schema before breaking schema.
   Preserve current mini-program fields while adding structured evidence fields. No frontend upload should be required just to keep old screens working.

3. Source evidence beats LLM text.
   LLM output is a proposal. Source article lines, OCR spans, registry entries, and explicit review records decide publishability.

4. Atlas is a verifier, not a generator.
   Atlas can confirm known entities and provide verified profile evidence. It must not invent event facts or biographies.

5. Deterministic gates first, probabilistic calibration later.
   Use explicit confidence rules and Golden eval before Bayesian networks or model-heavy calibration.

6. Internal review UI before public correction UX.
   `Did you mean?` style flows belong in an internal review panel first. Public mini-program UX should not expose ambiguous IDs or low-confidence candidates.

## 5. Architecture

```text
RuntimeTruthLock
  -> SourceEvidenceIndex
  -> OCRSpanRegistry
  -> LLMInputBuilder
  -> LLMMaterialization
  -> EvidenceRefAssembler
  -> ConflictResolver
  -> AtlasReadOnlyResolver
  -> CurrentPackageBuilder
  -> ReleaseGuardian
  -> MiniProgramCompatLayer
```

### 5.1 RuntimeTruthLock

Produces a small JSON record before every implementation or publish-like run:

```json
{
  "schema_version": "weekly.runtime_truth_lock.v1",
  "checked_at": "2026-05-21T23:35:00+08:00",
  "remote_effective_service": "weekly-api-045",
  "local_package_dir": "D:\\downstream_results\\stage7_rewrite\\longrun\\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260521_BACKEND_REFRESH_CURRENT",
  "manifest_count": 127,
  "current_count": 127,
  "materialized_llm_count": 127,
  "miniprogram_uploaded_version": "2026.05.21.2",
  "frontend_local_changes_uploaded": false,
  "wechat_review_submitted": false,
  "visible_hits": 0,
  "backend_raw_hits": 0
}
```

Hard stop conditions:

- local package count differs from declared runtime truth and no explanation report is attached;
- remote-effective service differs from plan assumptions;
- mini-program upload or review state is inferred instead of verified;
- target package lacks `current.json`, `manifest.json`, source map, or materialized LLM index.

### 5.2 EvidenceRef v1.1

Replace ad hoc string refs with structured objects while retaining backward compatibility.

Public `current.json` may keep compact refs. Internal review artifacts should store full refs.

```json
{
  "schema_version": "weekly.evidence_ref.v1.1",
  "field_path": "event_time_text",
  "support_type": "article_line",
  "source_hash": "sha256:...",
  "source_url_hash": "sha256:...",
  "text_sha256": "sha256:...",
  "char_range": [120, 148],
  "quote_policy": "hash_only",
  "ocr": null,
  "atlas": null,
  "registry": null,
  "review": null,
  "transform_id": "prov:activity:merge_current:..."
}
```

OCR-backed fields use an `ocr` block:

```json
{
  "schema_version": "weekly.evidence_ref.v1.1",
  "field_path": "lineup_artists[0]",
  "support_type": "ocr_span",
  "source_hash": "sha256:...",
  "text_sha256": "sha256:...",
  "ocr": {
    "image_id": "img_001",
    "span_id": "ocrspan:img_001:00042",
    "engine": "tesseract",
    "layout_format": "hocr",
    "bbox": [124, 330, 412, 371],
    "confidence": 91.4,
    "reading_order": 42
  },
  "transform_id": "prov:activity:ocr_extract:..."
}
```

Rules:

- No raw long OCR text in reports. Store SHA-256 and short local-only snippets only when needed for manual review.
- Every retained critical field should eventually have at least one evidence ref.
- P0 only requires canary coverage and validator correctness. Do not make `>=80%` coverage a first-run blocker.
- P1 raises coverage targets after compatibility and parse stability are proven.

### 5.3 OCRSpanRegistry

Add a local registry that normalizes OCR output from current artifacts.

Preferred inputs:

- existing `poster_ocr.json`;
- Tesseract hOCR or TSV when available;
- ALTO XML if a future OCR engine emits it;
- existing static-frame output under `.poster_ocr_frames`.

Registry shape:

```json
{
  "schema_version": "weekly.ocr_span_registry.v1",
  "source_hash": "sha256:...",
  "image_id": "img_001",
  "span_id": "ocrspan:img_001:00042",
  "text_sha256": "sha256:...",
  "bbox": [124, 330, 412, 371],
  "confidence": 91.4,
  "engine": "tesseract",
  "layout_format": "hocr",
  "reading_order": 42,
  "page_or_frame": 0,
  "source_artifact": "poster_ocr.json"
}
```

Initial thresholds:

| Band | OCR confidence | Default action |
|---|---:|---|
| high | `>= 85` | can support retained fields |
| medium | `60..84.99` | can support fields only with article or LLM corroboration |
| low | `< 60` | review only; cannot be the sole support for critical fields |
| unknown | missing confidence | review unless article text independently supports the field |

These are initial engineering thresholds, not statistical truth. They must be recalibrated with Golden eval.

### 5.4 PROV-lite Audit Ledger

Adopt W3C PROV concepts without importing a heavy graph stack.

Store one JSONL ledger per package:

`tools/stage7_rewrite/reports/prov_weekly_package_<timestamp>/prov_ledger.jsonl`

Object types:

- Entity: source article, OCR image, OCR span, LLM input, LLM enrichment, Atlas snapshot row, current item.
- Activity: OCR extract, build LLM input, LLM materialize, repair, dedupe, conflict resolve, Atlas resolve, package build, release gate.
- Agent: script, model, local operator, review tool.

Example:

```json
{
  "schema_version": "weekly.prov_lite.v1",
  "type": "activity",
  "id": "prov:activity:atlas_resolve:weekly-api-045:lineup:63",
  "used": [
    "prov:entity:current_item:loopy_club:7612fb974256bde9",
    "prov:entity:atlas_snapshot:alias_export_v1"
  ],
  "generated": [
    "prov:entity:entity_link:loopy_club:7612fb974256bde9:artist:0"
  ],
  "agent": "prov:agent:weekly_atlas_bridge.resolver.py",
  "started_at": "2026-05-21T23:35:00+08:00",
  "ended_at": "2026-05-21T23:35:01+08:00"
}
```

The ledger is local/package evidence. It does not write Atlas production graph state.

### 5.5 Confidence Model v1

Use a deterministic, inspectable model first:

```text
final_confidence =
  (
    0.35 * source_support
  + 0.25 * ocr_support
  + 0.15 * llm_consistency
  + 0.15 * atlas_identity
  + 0.10 * registry_support
  - 0.20 * conflict_penalty
  )
  * source_health
```

Component definitions:

| Component | Values | Notes |
|---|---|---|
| `source_support` | `0, 0.5, 1.0` | direct article/source line support is strongest |
| `ocr_support` | `0, 0.4, 0.7, 1.0` | depends on confidence band and span match |
| `llm_consistency` | `0, 0.5, 1.0` | single materialization starts at `0.5`; multi-run agreement can raise it |
| `atlas_identity` | `0, 0.5, 0.8, 1.0` | alias exact verified > alias exact unverified > fuzzy multiple |
| `registry_support` | `0, 0.5, 1.0` | venue/organizer registry support |
| `conflict_penalty` | `0, 0.25, 0.5, 1.0` | depends on unresolved conflicts |
| `source_health` | `0, 0.5, 1.0` | deleted/unavailable source reduces final confidence |

Display decision:

| Condition | Decision |
|---|---|
| critical field has no source/article/OCR/registry/review evidence | `hide_or_review` |
| `final_confidence >= 0.70` and has source/OCR support | `show` |
| `0.40 <= final_confidence < 0.70` and has source/OCR/Atlas hint | `show_with_hint` |
| unresolved conflict on critical field | `review` |
| `vector_candidate` only | `hide` |
| `final_confidence < 0.40` | `hide` |

Bayesian networks are explicitly deferred until enough labeled package history exists.

### 5.6 Conflict Evidence Model

Each conflicted field gets alternatives, not just a text flag.

```json
{
  "field_path": "event_time_text",
  "selected_value": "23:00-03:00",
  "decision": "show_with_hint",
  "alternatives": [
    {
      "value": "23:00",
      "source": "article_line",
      "evidence_ref": "eref:...",
      "confidence": 0.8
    },
    {
      "value": "03:00",
      "source": "ocr_span",
      "evidence_ref": "eref:...",
      "confidence": 0.65
    }
  ],
  "review_reason": "article and OCR describe different parts of the same time window",
  "review_status": "auto_resolved"
}
```

Rules:

- No silent overwrite of date, time, venue, address, price, or lineup.
- Every auto-resolved conflict must record `review_reason`.
- Golden eval must include a conflict-specific metric.

### 5.7 Description And Bio Policy

Do not use ROUGE-L or BLEURT as P0 gates. They are model-heavy and do not prove source faithfulness for short Chinese event copy.

Use deterministic fidelity checks first:

- normalized substring containment;
- SHA-256 of original source line or OCR span;
- Levenshtein ratio for whitespace/punctuation-only changes;
- CDN/qpic/URL visible-hit scan;
- source-ref existence validation.

`description_original_lines` compatibility strategy:

```json
{
  "description_original_lines": ["old public string line"],
  "description_original_line_refs": [
    {
      "text_sha256": "sha256:...",
      "source_ref": "eref:..."
    }
  ]
}
```

Bio remains three-tier:

1. `event_article_intro`: source article explicitly introduces the artist.
2. `atlas_verified_profile`: Atlas verified profile has non-empty manual bio.
3. `no_source`: hide bio; do not generate.

No LLM-written generic artist bio enters public payload.

### 5.8 Entity Link Policy

Add entity links as an additive field. Keep old `lineup` and `lineup_artists` stable.

```json
{
  "entity_links": [
    {
      "type": "artist",
      "raw_name": "DJ A",
      "display_tier": "show_with_hint",
      "resolved": {
        "atlas_id": "atlas:entity:ceid:person:...",
        "canonical_name": "DJ A",
        "match_method": "fuzzy_multiple",
        "confidence": 0.62
      },
      "evidence_refs": ["eref:...", "atlas:alias:fuzzy_multiple:..."],
      "public_candidate_ids_exposed": false
    }
  ]
}
```

Public rules:

- `alias_exact + verified=true`: show link.
- `alias_exact + verified=false`: show name with hint, no strong claim.
- `fuzzy_multiple`: show hint only; no public candidate IDs.
- `vector_candidate`: hide; review queue only.
- `no_match`: keep raw lineup text, no entity link.

Internal review UI may later add a `Did you mean?` panel. Public user correction is not P0.

## 6. Implementation Phases

### Phase 0: Runtime And Safety Foundation

Task 0.1: Runtime truth lock

- Files: new `tools/stage7_rewrite/scripts/check_weekly_runtime_truth.py`
- Acceptance:
  - reads local `current.json`, `manifest.json`, materialized summary/index, and current runtime doc;
  - emits `weekly.runtime_truth_lock.v1`;
  - fails on count/path/service mismatch unless an explicit override report is passed.
- Verification:
  - run against `weekly-api-045` package;
  - confirm manifest/current/materialized count `127`.

Task 0.2: Evidence coverage inventory

- Files: new `tools/stage7_rewrite/scripts/audit_weekly_evidence_coverage.py`
- Acceptance:
  - reports per-field evidence coverage;
  - reports current `field_evidence_refs=0/127` and `entity_links=0/127` as baseline;
  - does not print raw OCR or secrets.

Checkpoint 0:

- Runtime truth lock passes.
- Evidence coverage baseline captured.
- No package rebuild, deploy, upload, or review.

### Phase 1: Field Evidence Foundation

Task 1.1: OCR span registry from existing artifacts

- Files:
  - new `tools/stage7_rewrite/scripts/build_ocr_span_registry.py`
  - tests under `tools/stage7_rewrite/tests/`
- Acceptance:
  - reads existing `poster_ocr.json`, hOCR/TSV/ALTO if present;
  - writes local `ocr_span_registry.jsonl`;
  - preserves bbox/confidence when available;
  - marks confidence as `unknown` when absent.

Task 1.2: EvidenceRef object parser and validator

- Files:
  - new `tools/stage7_rewrite/scripts/weekly_evidence_refs.py`
  - tests under `tools/stage7_rewrite/tests/`
- Acceptance:
  - validates source hash, OCR span id, field path, and support type;
  - supports legacy string refs for backward compatibility;
  - rejects refs pointing to missing OCR spans or missing source hash.

Task 1.3: LLM prompt and sanitizer upgrade

- Files:
  - `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_deepseek.py`
- Acceptance:
  - critical retained fields request `field_evidence_refs`;
  - parser retries malformed evidence JSON once;
  - fallback keeps old safe payload without blocking package materialization;
  - logs parse success rate.

Task 1.4: Description source refs without frontend breakage

- Files:
  - `tools/stage7_rewrite/scripts/enrich_weekly_activity_pack_with_deepseek.py`
  - package builder/materializer if needed
- Acceptance:
  - keeps `description_original_lines` as public string array;
  - adds `description_original_line_refs` as structured metadata;
  - visible URL/CDN hits remain `0`.

Checkpoint 1:

- Canary package has non-empty `field_evidence_refs` for at least 10 events or all available canary rows.
- Validators reject bad refs.
- Old mini-program payload fields remain readable.

### Phase 2: PROV-lite And Confidence

Task 2.1: PROV-lite ledger writer

- Files:
  - new `tools/stage7_rewrite/scripts/write_weekly_prov_ledger.py`
- Acceptance:
  - emits Entity/Activity/Agent records for OCR, LLM input, LLM materialization, merge, Atlas resolve, package build, and release gate;
  - references package version and runtime truth lock;
  - does not write Atlas production stores.

Task 2.2: Confidence aggregator

- Files:
  - new `tools/stage7_rewrite/scripts/weekly_confidence.py`
- Acceptance:
  - outputs component scores and final score per critical field;
  - supports deterministic config;
  - records `hide`, `review`, `show_with_hint`, or `show`.

Task 2.3: Conflict alternatives model

- Files:
  - `tools/stage7_rewrite/scripts/repair_weekly_release_conflicts.py`
- Acceptance:
  - records alternatives for date/time/venue/address/price/lineup conflicts;
  - every auto-selected value has `review_reason`;
  - Golden eval includes conflict-specific counters.

Checkpoint 2:

- Cross-source audit reports per-field confidence and conflicts.
- No regression in duplicate/effective/conflict release gates.

### Phase 3: Atlas Read-Only Entity Links

Task 3.1: Snapshot path discovery

- Files:
  - `tools/stage7_rewrite/weekly_atlas_bridge/snapshot.py`
- Acceptance:
  - does not hardcode only `current_release`;
  - discovers snapshot from deploy context, current package, or declared runtime path;
  - fails clearly if snapshot and observations are absent.

Task 3.2: Entity link schema

- Files:
  - `tools/stage7_rewrite/weekly_atlas_bridge/resolver.py`
  - `tools/stage7_rewrite/weekly_atlas_bridge/snapshot.py`
- Acceptance:
  - emits additive `entity_links`;
  - no public candidate IDs for `fuzzy_multiple`;
  - `vector_candidate` never becomes public `show`.

Task 3.3: Internal no-match review queue

- Files:
  - local review API/page only if already in scope
- Acceptance:
  - no production graph/vector/SQLite writes;
  - review actions are local ledger records;
  - public payload remains stable.

Checkpoint 3:

- Entity link audit proves `alias_exact`, `fuzzy_multiple`, `no_match`, and `vector_candidate` policy behavior.
- Mini-program old views still load without `entity_links`.

### Phase 4: API And Frontend Compatibility

Task 4.1: API compatibility layer

- Files:
  - `services/weekly_activity_cloudrun/src/dataStore.mjs`
  - related API tests
- Acceptance:
  - old fields remain unchanged;
  - new evidence fields are available behind detail/debug/internal paths or additive fields;
  - CloudRun does not call LLM at request time.

Task 4.2: Mini-program evidence display, internal first

- Files:
  - `apps/weekly_activity_miniprogram/pages/detail/*`
  - tests
- Acceptance:
  - field confidence hints are optional and do not block core browsing;
  - public UI does not expose low-confidence candidate IDs;
  - new upload is required only when frontend display changes are intentionally selected.

Checkpoint 4:

- Frontend tests pass.
- Forced public API fallback still works.
- No mini-program upload unless explicitly requested.

### Phase 5: Release Guardian Integration

Task 5.1: Evidence gates in Release Guardian

- Files:
  - `C:\Users\pc\.codex\skills\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1`
  - project wrapper if needed
- Acceptance:
  - checks runtime truth lock;
  - checks materialized LLM completeness;
  - checks OCR provenance availability;
  - checks `visibleHits=0`;
  - treats `backendRawHits` as diagnostic unless raw cleanup mode is enabled.

Task 5.2: Publish-like dry run

- Acceptance:
  - `GateMode=current-package` passes on current known-good package;
  - canary bad package fails for missing OCR span, bad source hash, or broken materialization count;
  - no deploy/upload/review.

Checkpoint 5:

- Release Guardian can distinguish current-package verification from release/deploy readiness.
- The guard has no false positive against the known current package.

### Phase 6: Evaluation And Calibration

Task 6.1: Golden eval expansion

- Files:
  - `tools/stage7_rewrite/scripts/evaluate_weekly_golden_baseline.py`
- Acceptance:
  - reports per-field precision/recall for date/time/venue/address/price/lineup;
  - reports conflict-specific accuracy;
  - reports evidence coverage per critical field.

Task 6.2: Threshold calibration

- Acceptance:
  - updates OCR confidence bands only after Golden eval evidence;
  - logs before/after false block and false pass counts;
  - does not introduce Bayesian models until labeled history is sufficient.

## 7. Gate Matrix

| Gate | P0 behavior | P1/P2 behavior |
|---|---|---|
| Runtime truth lock | hard block on mismatch | hard block |
| Materialized LLM completeness | hard block | hard block |
| Source map missing | hard block | hard block |
| Visible URL/CDN hits | hard block | hard block |
| Backend raw hits | diagnostic | optional hard block in raw-clean mode |
| Field evidence coverage | canary threshold | target `>=80%` retained critical fields |
| OCR span missing for OCR refs | hard block | hard block |
| Low-confidence OCR sole support | review/block for critical fields | calibrated by Golden eval |
| Entity fuzzy candidates exposed | hard block | hard block |
| `vector_candidate` public show | hard block | hard block |
| Conflict without reason | hard block | hard block |
| Mini-program tests | required before upload only | required before upload |

## 8. Test Matrix

| Layer | Test file | Coverage |
|---|---|---|
| Runtime truth | `test_check_weekly_runtime_truth.py` | service/package/count mismatch |
| OCR span registry | `test_build_ocr_span_registry.py` | hOCR/TSV/legacy JSON parsing, bbox/confidence |
| EvidenceRef | `test_weekly_evidence_refs.py` | ref format, missing source, missing OCR span, legacy string |
| Description refs | `test_description_line_refs.py` | string compatibility, source_ref metadata, URL/CDN filter |
| Confidence | `test_weekly_confidence.py` | score bands, conflict penalty, source health |
| Conflict alternatives | `test_repair_weekly_release_conflicts.py` | alternatives, review_reason, selected value |
| Atlas entity policy | `weekly_atlas_bridge/tests/` | alias exact, fuzzy multiple, no match, vector candidate |
| API compatibility | `services/weekly_activity_cloudrun/tests/` | old fields preserved, new fields additive |
| Mini-program fallback | `apps/weekly_activity_miniprogram/tests/` | CloudRun fallback, display formatting |
| Release Guardian | guard script fixture tests | good current package passes; bad package blocks |

## 9. Rollout Strategy

1. Read-only baseline:
   - runtime truth lock;
   - evidence coverage audit;
   - no package mutation.

2. Canary package:
   - add EvidenceRef objects and OCR span registry for a small bounded subset;
   - validate no old field breaks.

3. Full local package:
   - run field evidence refs across current feed;
   - run PROV-lite ledger;
   - run confidence and conflict audit.

4. Current-package guardian:
   - verify local package with no deploy;
   - verify public API fallback if remote package is unchanged.

5. Backend deploy:
   - only after explicit deploy scope;
   - keep mini-program upload separate.

6. Frontend upload:
   - only after explicit frontend/schema display scope;
   - record exact developer version.

7. WeChat review:
   - separate guarded action only when explicitly requested.

## 10. Adopt / Adapt / Reject From Deep Research

Adopt:

- OCR span/bbox/confidence preservation.
- OCR confidence gates.
- W3C PROV concepts for auditability.
- Field-level source verification as an internal review capability.

Adapt:

- Use PROV-lite JSONL rather than a full RDF/ontology stack.
- Use deterministic confidence scoring before Bayesian networks.
- Use internal review UI before public `Did you mean?`.
- Use source-line hash and containment checks before ROUGE/BLEURT.

Reject for P0:

- Bayesian network confidence scoring.
- BLEURT/ROUGE as hard source-faithfulness gates.
- Domain-tuned OCR model fine-tuning as an immediate dependency.
- Public user correction loop before internal review quality exists.

## 11. Open Decisions

1. Should G0 alias export be regenerated before every weekly publish, or only when Atlas alias/profile source changes?
2. Which OCR formats are present in the latest source artifacts: legacy JSON only, Tesseract hOCR, TSV, ALTO, or mixed?
3. What is the first field coverage target after canary: `50%` critical fields or `80%` retained critical fields?
4. Should `description_original_line_refs` be exposed in public detail API or only internal/debug API?
5. Should no-match entity review stay local-only or become part of a broader Atlas local workbench?
6. Which package path is canonical when `current_release` and CloudRun deploy context diverge?

## 12. Reference Standards

- W3C PROV Overview: https://www.w3.org/TR/2013/NOTE-prov-overview-20130430/
- W3C PROV-O: https://www.w3.org/TR/prov-o/
- hOCR 1.2: https://kba.github.io/hocr-spec/1.2/
- Tesseract command line hOCR/TSV output: https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html
- ALTO XML overview: https://www.loc.gov/standards/alto/description.html
- ALTO layout attributes: https://www.loc.gov/standards/alto/techcenter/layout.html
