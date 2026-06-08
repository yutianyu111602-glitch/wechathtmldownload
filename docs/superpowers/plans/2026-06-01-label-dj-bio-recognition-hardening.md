# Label / DJ Bio Recognition Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a report-only workbench that strengthens music label / 厂牌 recognition and source-backed DJ bio extraction before DB2/DB3 projection or mini-program display.

**Architecture:** Add a bounded extraction contract between the S122 poster/lineup router and S125 DB2 projection smoke. The workbench separates people, labels, collectives, promoters, venues, radio shows, and events; every DJ bio or label claim must carry a source substring, role evidence, confidence, disposition, and no-write flags.

**Tech Stack:** Python report builder, read-only SQLite/JSON inputs, JSON/JSONL outputs, pytest fixtures, existing S121/S122/S124 artifacts, and later mini-program JS fixtures only after the report contract passes.

---

## Scope

This plan is inserted as `S125A`, before DB2 candidate projection. It does not write DB1/DB2/DB3, does not call models by itself, does not upload/release the mini-program, and does not read cookie/token values.

Primary risks to remove:

- Treating a label / 厂牌 / crew / promoter as a DJ.
- Losing DJ bio lines because the extraction prompt only returns one main DJ.
- Showing speculative label or bio text in the mini-program without source evidence.
- Merging label identity evidence into DB3 `dj_profile` before the S121 entity-id mapping gate is solved.

## Data Contract

Each extracted candidate row must expose:

- `candidate_id`
- `source_ref_id`
- `source_url_or_article_id`
- `evidence_text`
- `entity_name`
- `entity_kind`: `dj_person`, `label_org`, `collective_crew`, `promoter_org`, `venue`, `radio_show`, `event`, `unknown`
- `role_hint`: examples `founder`, `member`, `resident`, `presented_by`, `hosted_by`, `lineup_artist`, `label_artist`, `bio_claim`
- `bio_text`
- `bio_subject_name`
- `confidence`
- `disposition`: `accept_candidate`, `needs_review`, `reject_not_dj`, `reject_not_bio`, `blocked_no_source`
- `model_lane`: `deterministic`, `deepseek_flash`, `deepseek_pro`, `mimo_multimodal`, `hunyuan_summary_only`
- `write_allowed=false`
- `db2_projection_allowed=false`
- `db3_identity_write_allowed=false`
- `miniapp_public_display_allowed=false`

## Task 1: Taxonomy Fixture Gate

**Files:**
- Create: `tools/stage7_rewrite/scripts/build_label_dj_bio_recognition_workbench_s125a.py`
- Create: `tools/stage7_rewrite/tests/test_build_label_dj_bio_recognition_workbench_s125a.py`

- [ ] **Step 1: Write fixture tests for role separation**

Create pytest cases with Chinese and English evidence text:

```python
def test_rejects_label_as_dj():
    text = "厂牌 TRUST 相信电音 presents the night, lineup: DJ A / DJ B"
    rows = extract_fixture_rows(text)
    assert row_for(rows, "TRUST 相信电音")["entity_kind"] == "label_org"
    assert row_for(rows, "TRUST 相信电音")["disposition"] == "reject_not_dj"
    assert row_for(rows, "DJ A")["entity_kind"] == "dj_person"

def test_preserves_source_backed_bio():
    text = "DJ A 是来自杭州的制作人，也是某厂牌主理人。"
    row = row_for(extract_fixture_rows(text), "DJ A")
    assert row["bio_subject_name"] == "DJ A"
    assert "来自杭州的制作人" in row["bio_text"]
    assert row["evidence_text"] == text
```

- [ ] **Step 2: Implement deterministic role hints**

Use bounded regex/keyword extraction for `厂牌`, `label`, `crew`, `collective`, `主理`, `成员`, `resident`, `presents`, `presented by`, `hosted by`, `lineup`, and `阵容`.

- [ ] **Step 3: Verify**

Run:

```powershell
python -m pytest tools/stage7_rewrite/tests/test_build_label_dj_bio_recognition_workbench_s125a.py -q
python -m py_compile tools/stage7_rewrite/scripts/build_label_dj_bio_recognition_workbench_s125a.py
```

Expected: focused tests pass and no model/network/DB write occurs.

## Task 2: Real Input Workbench

**Files:**
- Modify: `tools/stage7_rewrite/scripts/build_label_dj_bio_recognition_workbench_s125a.py`
- Test: `tools/stage7_rewrite/tests/test_build_label_dj_bio_recognition_workbench_s125a.py`

- [ ] **Step 1: Read current report inputs**

Inputs should be read-only:

- S122 router: `tools/stage7_rewrite/reports/poster_lineup_extraction_router_s122_20260601/poster_lineup_extraction_tasks.jsonl`
- S121 audit: `tools/stage7_rewrite/reports/three_db_merge_performance_s121_20260601/three_db_merge_performance_audit.json`
- S124 canary: `tools/stage7_rewrite/reports/external_link_no_cookie_canary_s124_20260601/external_link_no_cookie_canary_results.jsonl`

- [ ] **Step 2: Produce report-local outputs**

Write:

- `tools/stage7_rewrite/reports/label_dj_bio_recognition_s125a_20260601/label_dj_bio_recognition_workbench.json`
- `tools/stage7_rewrite/reports/label_dj_bio_recognition_s125a_20260601/label_dj_bio_candidates.jsonl`
- `reports/WEEKLY_LABEL_DJ_BIO_RECOGNITION_S125A_20260601.md`

- [ ] **Step 3: Keep write gates closed**

The report summary must include:

```json
{
  "database_mutation": false,
  "db2_projection_allowed": false,
  "db3_identity_write_allowed": false,
  "miniapp_public_display_allowed": false,
  "model_call_performed": false,
  "cookie_values_read": false,
  "token_values_read": false
}
```

## Task 3: Model Lane Policy

**Files:**
- Modify: `tools/stage7_rewrite/scripts/build_label_dj_bio_recognition_workbench_s125a.py`
- Create output: `tools/stage7_rewrite/reports/label_dj_bio_recognition_s125a_20260601/label_dj_bio_model_policy.json`

- [ ] **Step 1: Assign lanes without running models**

Use this policy:

- `deterministic`: source text already has role keywords and exact evidence.
- `deepseek_flash`: bounded text extraction when labels/DJ bios are present but role is not ambiguous.
- `deepseek_pro`: label/person conflict, one-DJ-only extraction from rich lineup context, or conflicting identity names.
- `mimo_multimodal`: poster-only or logo-heavy evidence where label names are visual.
- `hunyuan_summary_only`: mini-program-facing summary after facts are already extracted and gated.

- [ ] **Step 2: Add tests for lane assignment**

Fixture rows must prove that `TRUST 相信电音` routes as label conflict review, `DJ A bio` routes as source-text extraction, and poster-only label evidence routes to `mimo_multimodal`.

## Task 4: Mini-Program Display Gate

**Files:**
- Future modify only after Task 1-3 pass: `apps/weekly_activity_miniprogram/utils/publicExternalLinks.js`
- Future test: `apps/weekly_activity_miniprogram/tests/public-external-links.test.cjs`

- [ ] **Step 1: Keep speculative label/bio hidden**

Do not display label/bio rows until `miniapp_public_display_allowed=true` is proven by a later contract.

- [ ] **Step 2: Display rules for later S125/S126**

When allowed, show:

- DJ bio as a short source-backed paragraph on artist detail.
- Label/厂牌 as compact tags with original source links.
- Confidence/disposition only internally unless a user-facing warning is needed.

## Acceptance

`S125A` is complete only when the report, candidates, model policy, scorecard, JSON parse, py_compile, pytest, SSOT pointer audit, and no-write/no-secret guards all pass. Completion of `S125A` does not authorize DB2 projection, DB3 identity writes, mini-program upload/release, or public display.
