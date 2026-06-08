# Atlas Full Production Final Goals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the Atlas subsequent-search full-production evidence chain from complete public-search telemetry to a source-backed, report-only staging promotion gate.

**Architecture:** Run the chain as gated evidence layers: public-search completion -> strict Post-Filter -> reduced evidence fetches -> source-context review -> rule adjudication -> bounded LLM adjudication -> promotion readiness. Every layer writes new report artifacts and keeps graph/vector/production stores untouched until a later explicit promotion decision.

**Tech Stack:** PowerShell, Python 3.13, pytest, Stage7 report scripts under `tools\stage7_rewrite\scripts`, JSONL report artifacts, Neo4j/Qdrant promotion validators in report-only mode.

---

## Current Blocking Gate

As of 2026-05-21 14:43 CST, the public-search status is still `RUNNING`:

- Status JSON: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json`
- PID: `108336`
- Rows processed: `126,052 / 246,024`
- Required before Task 2: `status == "COMPLETE"` and `processed_review_rows == queue_entity_keys`

Do not run full Post-Filter while this gate is still `RUNNING`.

## File Structure

- Create: `C:\code\githubstar\wechathtmldownload\reports\ATLAS_FULL_PRODUCTION_FINAL_GOALS_STATUS_20260521.md`
- Modify: `C:\code\githubstar\wechathtmldownload\docs\current-runtime.md`
- Modify: `C:\code\githubstar\wechathtmldownload\docs\DOCUMENTATION_INDEX.md`
- Read: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json`
- Read: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_review.jsonl`
- Read: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_evidence.jsonl`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521\`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_content_evidence_full_138102_20260521\`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_subsequent_external_identity_review_full_138102_20260521\`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_subsequent_identity_adjudication_full_138102_20260521\`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_subsequent_llm_adjudication_full_138102_20260521\`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_subsequent_promotion_readiness_full_138102_20260521\`

## Task 1: Monitor Public-Search Completion

**Files:**
- Read: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json`
- Create or modify: `C:\code\githubstar\wechathtmldownload\reports\ATLAS_FULL_PRODUCTION_FINAL_GOALS_STATUS_20260521.md`

- [ ] **Step 1: Read the status JSON and PID state**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
$p = 'tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json'
$j = Get-Content -Raw -LiteralPath $p | ConvertFrom-Json
[pscustomobject]@{
  status = $j.status
  pid = $j.pid
  pidAlive = (Get-Process -Id $j.pid -ErrorAction SilentlyContinue) -ne $null
  processed = $j.processed_review_rows
  total = $j.queue_entity_keys
  generated_at = $j.generated_at
} | ConvertTo-Json -Compress
```

Expected while blocked: JSON with `status` equal to `RUNNING`, `pidAlive` equal to `true`, and `processed` lower than `total`.

Expected when ready: JSON with `status` equal to `COMPLETE` and `processed` equal to `total`.

- [ ] **Step 2: Write the checkpoint report**

Create or update `reports\ATLAS_FULL_PRODUCTION_FINAL_GOALS_STATUS_20260521.md` with these sections:

```markdown
# Atlas Full Production Final Goals Status 2026-05-21

## Scope

Atlas graph full-production subsequent-search lane only.

## Public-Search Gate

Record the exact `status`, `pid`, `processed_review_rows`, `queue_entity_keys`, and `generated_at` values printed by Step 1.

## Decision

If status is not COMPLETE, Post-Filter remains blocked.
If status is COMPLETE and processed_review_rows equals queue_entity_keys, Task 2 is allowed.

## Safety

No graph/vector/production SQLite write, deploy, upload, model call, secret read, browser profile read, broad D: scan, or 9router probe occurred.
```

Replace every angle-bracket value with the actual value from Step 1 before saving.

- [ ] **Step 3: Stop or continue based on the gate**

If the status is still `RUNNING`, stop the execution chain after updating the status report.

If the status is `COMPLETE`, continue to Task 2 in the same session.

## Task 2: Run Full Post-Filter After Completion

**Files:**
- Read: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_review.jsonl`
- Read: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_evidence.jsonl`
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_atlas_entity_public_search_post_filter_queue.py`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521\`
- Test: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_build_atlas_entity_public_search_post_filter_queue.py`

- [ ] **Step 1: Verify full input files exist**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
Get-Item `
  tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_review.jsonl,`
  tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_evidence.jsonl |
  Select-Object FullName,Length,LastWriteTime
```

Expected: both files exist and have non-zero `Length`.

- [ ] **Step 2: Run the full report-only Post-Filter**

Run only after Task 1 reports `COMPLETE`:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\build_atlas_entity_public_search_post_filter_queue.py `
  --review-jsonl tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_review.jsonl `
  --evidence-jsonl tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_evidence.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521 `
  --min-post-filter-score 35 `
  --review-score 45 `
  --validate-names TAG,house,DADA,CISCO,Watermelon,All `
  --emit-quarantine `
  --confirm-full-run
```

Expected: command exits `0` and prints a JSON summary containing `review_queue_rows`, `filtered_candidate_rows`, and `accepted_for_graph` equal to `0`.

- [ ] **Step 3: Confirm noisy entities are quarantined or excluded**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
$review = 'tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_review_queue.jsonl'
$audit = 'tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_post_filter_audit.jsonl'
$bad = 'TAG','house','DADA','CISCO','Watermelon','All'
foreach ($name in $bad) {
  $reviewHits = Select-String -LiteralPath $review -SimpleMatch ('"name": "' + $name + '"') -ErrorAction SilentlyContinue
  $auditHits = Select-String -LiteralPath $audit -SimpleMatch ('"name": "' + $name + '"') -ErrorAction SilentlyContinue
  [pscustomobject]@{name=$name; review_hits=($reviewHits | Measure-Object).Count; audit_hits=($auditHits | Measure-Object).Count}
}
```

Expected: `review_hits` is `0` for every listed noisy entity.

## Task 3: Verify Post-Filter and Public-Search Tests

**Files:**
- Test: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_build_atlas_entity_public_search_post_filter_queue.py`
- Test: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_run_atlas_entity_public_search.py`
- Test: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_fetch_atlas_entity_public_search_content_evidence.py`

- [ ] **Step 1: Compile relevant scripts**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
python -m py_compile `
  tools\stage7_rewrite\scripts\build_atlas_entity_public_search_post_filter_queue.py `
  tools\stage7_rewrite\scripts\run_atlas_entity_public_search.py `
  tools\stage7_rewrite\scripts\run_atlas_entity_public_search_full_slices.py `
  tools\stage7_rewrite\scripts\fetch_atlas_entity_public_search_content_evidence.py `
  tools\stage7_rewrite\scripts\llm_adjudicate_identity.py
```

Expected: exit code `0` and no Python traceback.

- [ ] **Step 2: Run targeted tests**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite
python -m pytest `
  tests\test_build_atlas_entity_public_search_post_filter_queue.py `
  tests\test_run_atlas_entity_public_search.py `
  tests\test_fetch_atlas_entity_public_search_content_evidence.py `
  tests\test_llm_adjudicate_identity.py `
  -q
```

Expected: exit code `0` and all selected tests pass.

## Task 4: Run Layer D Content Evidence on Reduced Queue

**Files:**
- Read: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_review_queue.jsonl`
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\fetch_atlas_entity_public_search_content_evidence.py`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_content_evidence_full_138102_20260521\`

- [ ] **Step 1: Dry-run the first 20 reduced rows**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\fetch_atlas_entity_public_search_content_evidence.py `
  --review-queue tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_review_queue.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_entity_public_search_content_evidence_full_138102_20260521 `
  --fetch-mode dry-run `
  --limit 20 `
  --sleep-sec 0
```

Expected: summary JSON reports selected rows and `fetch_status_counts` contains only `dry_run`; all output rows keep `accepted_for_graph=false`.

- [ ] **Step 2: Run bounded HTTP content evidence**

Run after Step 1 succeeds:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\fetch_atlas_entity_public_search_content_evidence.py `
  --review-queue tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_review_queue.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_entity_public_search_content_evidence_full_138102_20260521 `
  --fetch-mode http `
  --limit 200 `
  --timeout-sec 10 `
  --sleep-sec 0.25
```

Expected: summary JSON reports `accepted_for_graph=0`, `graph_write_allowed=false`, and content rows are written only under the output directory.

## Task 5: Build or Reuse a Schema-Compatible External Evidence Queue

**Files:**
- Read: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_review_queue.jsonl`
- Prefer existing scripts: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_atlas_open_source_phase1_seed_queue.py`, `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_graph_external_evidence_seed_queue.py`
- Create only if needed: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_atlas_public_search_followup_seed_queue.py`
- Test only if new adapter is needed: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\tests\test_build_atlas_public_search_followup_seed_queue.py`

- [ ] **Step 1: Check whether existing scripts accept the Post-Filter schema**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\build_atlas_open_source_phase1_seed_queue.py --help
python tools\stage7_rewrite\scripts\build_graph_external_evidence_seed_queue.py --help
```

Expected: help output confirms the required input paths. If neither script accepts `entity_public_search_review_queue.jsonl`, use Step 2.

- [ ] **Step 2: Add a narrow adapter if no existing script fits**

Create `tools\stage7_rewrite\scripts\build_atlas_public_search_followup_seed_queue.py` with one responsibility: convert Post-Filter review rows into report-only URL and handle seeds for HTTP Fast, OpenCLI, and Maigret.

The adapter must emit:

```json
{"seed_family":"url_evidence","subject_name":"...","url":"...","source":"atlas_entity_public_search_post_filter","accepted_for_graph":false,"graph_write_allowed":false}
{"seed_family":"handle_candidate","subject_name":"...","username":"...","source":"atlas_entity_public_search_post_filter","accepted_for_graph":false,"graph_write_allowed":false}
```

The adapter must reject rows without `best_url`, `url`, `canonical_url`, or a platform handle. It must not fetch URLs, call models, open browsers, or write graph/vector/database state.

- [ ] **Step 3: Test the adapter if it was created**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite
python -m pytest tests\test_build_atlas_public_search_followup_seed_queue.py -q
python -m py_compile scripts\build_atlas_public_search_followup_seed_queue.py
```

Expected: pytest exits `0`; py_compile exits `0`.

## Task 6: Run HTTP Fast, OpenCLI, and Maigret on Reduced Seeds

**Files:**
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\run_graph_external_evidence_http_fast.py`
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\opencli_social_profile_evidence.py`
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_graph_maigret_candidates_from_seed_queue.py`
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\run_maigret_http_canary.py`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\`

- [ ] **Step 1: Run HTTP Fast with a bounded limit**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\run_graph_external_evidence_http_fast.py `
  --seed-queue tools\stage7_rewrite\reports\atlas_public_search_followup_seed_queue_full_138102_20260521\external_evidence_seed_queue.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\http_fast `
  --limit 500 `
  --timeout-sec 10 `
  --max-bytes 65536
```

Expected: output rows describe reachability only; no graph acceptance file is created.

- [ ] **Step 2: Run OpenCLI dry-run first**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\opencli_social_profile_evidence.py `
  --identity-review tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_review_queue.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\opencli_dry_run `
  --platforms instagram,linktree,soundcloud,bandcamp,residentadvisor `
  --limit 50 `
  --per-platform 20 `
  --dry-run `
  --skip-profile-use
```

Expected: command exits `0`, writes candidate reports only, and does not use browser profile state.

- [ ] **Step 3: Build Maigret candidates**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\build_graph_maigret_candidates_from_seed_queue.py `
  --seed-queue tools\stage7_rewrite\reports\atlas_public_search_followup_seed_queue_full_138102_20260521\external_evidence_seed_queue.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\maigret_candidates `
  --limit 100
```

Expected: Maigret candidate JSONL is created with `accepted_for_graph=false`.

- [ ] **Step 4: Recheck Maigret service before use**

Run:

```powershell
try {
  Invoke-WebRequest -UseBasicParsing -Uri http://127.0.0.1:15051 -TimeoutSec 5 | Select-Object StatusCode
} catch {
  $_.Exception.Message
}
```

Expected if service is available: HTTP status output from `127.0.0.1:15051`. If unavailable, skip Step 5 and record `maigret_service_unavailable` in the status report.

- [ ] **Step 5: Run bounded Maigret canary only if Step 4 succeeds**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\run_maigret_http_canary.py `
  --candidates tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\maigret_candidates\maigret_candidates.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\maigret `
  --base-url http://127.0.0.1:15051 `
  --limit 50 `
  --top-sites 40 `
  --timeout 10 `
  --poll-timeout 60
```

Expected: Maigret results are breadth evidence only and remain outside graph writes.

## Task 7: Build Source-Context Decision and Rule Adjudication

**Files:**
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_external_identity_source_context_decision_packet.py`
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_atlas_open_source_phase1_review_queue.py`
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\adjudicate_graph_external_identity_queue.py`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_subsequent_external_identity_review_full_138102_20260521\`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_subsequent_identity_adjudication_full_138102_20260521\`

- [ ] **Step 1: Build the combined review queue**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\build_atlas_open_source_phase1_review_queue.py `
  --seed-queue tools\stage7_rewrite\reports\atlas_public_search_followup_seed_queue_full_138102_20260521\external_evidence_seed_queue.jsonl `
  --http-results tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\http_fast\http_fast_results.jsonl `
  --opencli-evidence tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\opencli_dry_run\social_profile_evidence.jsonl `
  --maigret-evidence tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\maigret\maigret_normalized_candidate_evidence.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_subsequent_external_identity_review_full_138102_20260521
```

Expected: `external_identity_review_queue.jsonl` is created and summary reports `accepted_for_graph=0`.

- [ ] **Step 2: Build source-context decision packet**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\build_external_identity_source_context_decision_packet.py `
  --input tools\stage7_rewrite\reports\atlas_subsequent_external_identity_review_full_138102_20260521\external_identity_review_queue.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_subsequent_source_context_decision_full_138102_20260521
```

Expected: decision packet is created and remains report-only.

- [ ] **Step 3: Run rule adjudication**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\adjudicate_graph_external_identity_queue.py `
  --review-queue tools\stage7_rewrite\reports\atlas_subsequent_external_identity_review_full_138102_20260521\external_identity_review_queue.jsonl `
  --seed-queue tools\stage7_rewrite\reports\atlas_public_search_followup_seed_queue_full_138102_20260521\external_evidence_seed_queue.jsonl `
  --maigret-candidates tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\maigret_candidates\maigret_candidates.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_subsequent_identity_adjudication_full_138102_20260521 `
  --report-only-exit-zero
```

Expected: rule adjudication summary is created; accepted graph edge output remains empty unless a later explicit acceptance gate changes the policy.

## Task 8: Run Bounded LLM Dual-Pass Adjudication in Report-Only Mode

**Files:**
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\llm_adjudicate_identity.py`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_subsequent_llm_adjudication_full_138102_20260521\`

- [ ] **Step 1: Verify no key is printed**

Run:

```powershell
if ($env:DEEPSEEK_API_KEY) { 'DEEPSEEK_API_KEY_PRESENT' } else { 'DEEPSEEK_API_KEY_MISSING' }
```

Expected: prints only presence or missing state, never the key value.

- [ ] **Step 2: Run report-only LLM adjudication**

Run only when key presence is confirmed and the rule adjudication output exists:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\llm_adjudicate_identity.py `
  --adjudication-dir tools\stage7_rewrite\reports\atlas_subsequent_identity_adjudication_full_138102_20260521 `
  --opencli-evidence tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\opencli_dry_run\social_profile_evidence.jsonl `
  --http-fast-dir tools\stage7_rewrite\reports\atlas_subsequent_external_evidence_full_138102_20260521\http_fast `
  --seed-queue tools\stage7_rewrite\reports\atlas_public_search_followup_seed_queue_full_138102_20260521\external_evidence_seed_queue.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_subsequent_llm_adjudication_full_138102_20260521 `
  --model deepseek-v4-pro `
  --api-key env:DEEPSEEK_API_KEY `
  --confidence-threshold 0.86 `
  --max-rows 200 `
  --spot-check 20 `
  --report-only-exit-zero
```

Expected: LLM report is created; because `--enable-write` is not present, accepted edge files remain empty or report-only.

## Task 9: Build Promotion Readiness Without Production Writes

**Files:**
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\validate_graph_promotion_readiness.py`
- Run: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\build_identity_neo4j_staging_gate_packet.py`
- Output: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_subsequent_promotion_readiness_full_138102_20260521\`

- [ ] **Step 1: Build the identity staging gate packet in dry-run mode**

Run only if strict accepted identity rows exist from prior gates:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\build_identity_neo4j_staging_gate_packet.py `
  --strict-social tools\stage7_rewrite\reports\atlas_subsequent_llm_adjudication_full_138102_20260521\strict_social_identity_acceptance.jsonl `
  --cdcr-strict tools\stage7_rewrite\reports\atlas_subsequent_llm_adjudication_full_138102_20260521\cdcr_strict_acceptance.jsonl `
  --out-dir tools\stage7_rewrite\reports\atlas_subsequent_promotion_readiness_full_138102_20260521\identity_staging_gate `
  --run-id atlas_subsequent_identity_138102_20260521
```

Expected: writer dry-run summary is produced; no Neo4j writes occur.

- [ ] **Step 2: Validate promotion readiness in report-only mode**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\validate_graph_promotion_readiness.py `
  --run-id stage7_all_full_llm_138102_prod_20260520 `
  --promotion-run-id atlas_subsequent_identity_138102_20260521 `
  --out-dir tools\stage7_rewrite\reports\atlas_subsequent_promotion_readiness_full_138102_20260521 `
  --strict-identity-acceptance tools\stage7_rewrite\reports\atlas_subsequent_llm_adjudication_full_138102_20260521\strict_social_identity_acceptance.jsonl `
  --skip-live-neo4j `
  --report-only-exit-zero
```

Expected: promotion readiness report is produced and records that production mutation has not occurred.

## Task 10: Sync Docs and Final Verification

**Files:**
- Modify: `C:\code\githubstar\wechathtmldownload\docs\current-runtime.md`
- Modify: `C:\code\githubstar\wechathtmldownload\docs\DOCUMENTATION_INDEX.md`
- Create or modify: `C:\code\githubstar\wechathtmldownload\reports\ATLAS_FULL_PRODUCTION_FINAL_GOALS_STATUS_20260521.md`

- [ ] **Step 1: Update current runtime**

Add a new top section to `docs\current-runtime.md` with:

```markdown
## 2026-05-21 Atlas Full Production Final Goals

- Plan: `docs\superpowers\plans\2026-05-21-atlas-full-production-final-goals.md`.
- Design: `docs\superpowers\specs\2026-05-21-atlas-full-production-final-goals-design.md`.
- Status report: `reports\ATLAS_FULL_PRODUCTION_FINAL_GOALS_STATUS_20260521.md`.
- Public-search gate: record the exact current state, including status and processed/total rows.
- Final decision: no production write unless the staging readiness gate explicitly passes and the user approves promotion.
```

Use the same status values recorded in `reports\ATLAS_FULL_PRODUCTION_FINAL_GOALS_STATUS_20260521.md`.

- [ ] **Step 2: Update documentation index**

Add these entries under `Current Entry And Useful Evidence`:

```markdown
- `docs/superpowers/specs/2026-05-21-atlas-full-production-final-goals-design.md` — `ACTIVE_EVIDENCE`; design for the Atlas subsequent-search full-production final-goal chain, selected gate-led approach, and safety boundaries.
- `docs/superpowers/plans/2026-05-21-atlas-full-production-final-goals.md` — `ACTIVE_EVIDENCE`; implementation plan for public-search completion, Post-Filter, Layer D, external evidence, adjudication, and report-only promotion readiness.
- `reports/ATLAS_FULL_PRODUCTION_FINAL_GOALS_STATUS_20260521.md` — `ACTIVE_EVIDENCE`; execution status for this plan, including whether the public-search completion gate is still blocking downstream work.
```

- [ ] **Step 3: Run safe handoff verification**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\stage7_safe_handoff_verify.ps1
```

Expected: exit code `0` and final output contains `PASS stage7 safe handoff verify`.

- [ ] **Step 4: Run Markdown whitespace check for touched docs**

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload
git diff --check -- `
  docs\superpowers\specs\2026-05-21-atlas-full-production-final-goals-design.md `
  docs\superpowers\plans\2026-05-21-atlas-full-production-final-goals.md `
  docs\current-runtime.md `
  docs\DOCUMENTATION_INDEX.md `
  reports\ATLAS_FULL_PRODUCTION_FINAL_GOALS_STATUS_20260521.md
```

Expected: exit code `0`; no whitespace errors.

## Self-Review

- Spec coverage: covers completion gate, Post-Filter, content evidence, HTTP Fast, OpenCLI, Maigret, source-context review, rule adjudication, LLM adjudication, promotion readiness, and docs sync.
- Completeness scan: no unfinished sections or vague command stubs remain.
- Type consistency: all script paths and output directories use the `tools\stage7_rewrite` Stage7 layout already present in this repo.
- Safety: production writes remain outside this plan unless a later explicit promotion decision is made after report-only readiness passes.
