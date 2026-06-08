# Atlas Core Serving FTS Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore legacy trigram behavior for `search_document_fts` in the Atlas Core candidate serving export while retaining a unicode companion FTS table for future CJK-friendly shadow search.

**Architecture:** Keep the old public table name `search_document_fts` as the compatibility surface and add `search_document_fts_unicode61` as an optional companion. Safe runner and shadow-read reports must read both tokenizers explicitly and keep every artifact report-local.

**Tech Stack:** Python standard library (`sqlite3`, `pathlib`, `json`, `argparse`), pytest, existing Atlas Core scripts under `tools/stage7_rewrite/scripts`.

---

## Scope Check

This plan implements only FTS compatibility for report-local `atlas_serving.sqlite` exported from Atlas Core. It does not implement S119 approvals, S232D-4 writes, production pointer switching, CloudRun deployment, mini-program release, or DB3 mutation.

## File Structure

- Modify: `tools/stage7_rewrite/scripts/export_atlas_core_to_serving_sqlite.py`
  - Responsibility: create legacy trigram FTS, create unicode companion FTS, populate both, write metadata.
- Modify: `tools/stage7_rewrite/scripts/run_atlas_core_candidate_safe.py`
  - Responsibility: read back legacy and companion FTS counts separately and block only on the compatibility-critical legacy checks.
- Modify: `tools/stage7_rewrite/scripts/compare_atlas_core_serving_shadow_read.py`
  - Responsibility: include tokenizer metadata and keep old-vs-new search comparison tied to `search_document_fts`.
- Modify: `services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs`
  - Responsibility: query legacy FTS first, then use `search_document_fts_unicode61` when legacy FTS has no rows or errors.
- Modify: `tools/stage7_rewrite/tests/test_atlas_core_candidate.py`
  - Responsibility: prove dual-FTS export and readback behavior.
- Modify: `services/weekly_activity_cloudrun/tests/stage7SqliteLocal.test.mjs`
  - Responsibility: prove store-level companion fallback for short Latin terms such as `DJ`.
- Generate: `tools/stage7_rewrite/reports/atlas_core_candidate_20260604/atlas_serving.sqlite`
  - Responsibility: rebuilt candidate serving DB only, not production.
- Generate: `tools/stage7_rewrite/reports/atlas_core_serving_shadow_read_compare_20260605/`
  - Responsibility: refreshed shadow-read report.

## Task 1: Exporter Dual-FTS Schema

**Files:**
- Modify: `tools/stage7_rewrite/scripts/export_atlas_core_to_serving_sqlite.py`
- Test: `tools/stage7_rewrite/tests/test_atlas_core_candidate.py`

- [x] **Step 1: Write the failing test**

Add this assertion block to `test_core_exporters_preserve_serving_miniapp_and_json_index_contracts` after opening `serving_db`:

```python
tokenizers = dict(con.execute("SELECT key, value FROM build_metadata WHERE key LIKE 'search_document_fts%'").fetchall())
assert tokenizers["search_document_fts_tokenizer"] == "trigram"
assert tokenizers["search_document_fts_unicode61_tokenizer"] == "unicode61"
tables = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
assert "search_document_fts" in tables
assert "search_document_fts_unicode61" in tables
```

- [x] **Step 2: Run the targeted test and verify it fails**

Run:

```powershell
python -m pytest tools/stage7_rewrite/tests/test_atlas_core_candidate.py::test_core_exporters_preserve_serving_miniapp_and_json_index_contracts -q
```

Expected before implementation: failure because `search_document_fts_tokenizer` is `unicode61` and `search_document_fts_unicode61_tokenizer` is absent.

- [x] **Step 3: Implement dual-FTS schema**

Change `create_serving_schema()` so it creates `search_document_fts` with `tokenize='trigram'` and then creates `search_document_fts_unicode61` with `tokenize='unicode61'`. Return a dictionary:

```python
tokenizers = {"search_document_fts": "trigram", "search_document_fts_unicode61": "unicode61"}
```

If trigram creation fails, create the legacy table without an explicit tokenizer and return:

```python
tokenizers = {"search_document_fts": "default", "search_document_fts_unicode61": "unicode61"}
```

- [x] **Step 4: Populate both FTS tables**

After the existing `INSERT INTO search_document_fts(...) SELECT ... FROM search_document`, add:

```sql
INSERT INTO search_document_fts_unicode61(rowid, display_name, normalized_name, aliases_text, city_text, taxon_path, search_text)
SELECT doc_rowid, display_name, normalized_name, aliases_text, city_text, taxon_path, search_text
FROM search_document;
```

- [x] **Step 5: Write metadata for both tokenizers**

Replace the single metadata row with:

```python
("search_document_fts_tokenizer", tokenizers["search_document_fts"]),
("search_document_fts_unicode61_tokenizer", tokenizers["search_document_fts_unicode61"]),
```

- [x] **Step 6: Run the targeted test and verify it passes**

Run:

```powershell
python -m pytest tools/stage7_rewrite/tests/test_atlas_core_candidate.py::test_core_exporters_preserve_serving_miniapp_and_json_index_contracts -q
```

Expected: `1 passed`.

## Task 2: Safe Runner Readback

**Files:**
- Modify: `tools/stage7_rewrite/scripts/run_atlas_core_candidate_safe.py`
- Test: `tools/stage7_rewrite/tests/test_atlas_core_candidate.py`

- [x] **Step 1: Write readback assertions**

In `test_safe_runner_rebuilds_candidates_without_mutating_sources`, assert:

```python
assert report["readback"]["serving"]["fts_tokenizer"] == "trigram"
assert report["readback"]["serving"]["unicode61_fts_tokenizer"] == "unicode61"
assert report["readback"]["serving"]["unicode61_fts_counts"]["深圳"] >= 1
```

- [x] **Step 2: Update safe runner readback**

In `readback()`, keep `fts_counts` for legacy `search_document_fts`, add `unicode61_fts_counts` for `search_document_fts_unicode61`, and add `unicode61_fts_tokenizer` from `build_metadata`.

Use these queries:

```python
legacy_count = serving.execute(
    "SELECT COUNT(*) FROM search_document_fts WHERE search_document_fts MATCH ?",
    (query,),
).fetchone()[0]
unicode_count = serving.execute(
    "SELECT COUNT(*) FROM search_document_fts_unicode61 WHERE search_document_fts_unicode61 MATCH ?",
    (query,),
).fetchone()[0]
```

- [x] **Step 3: Adjust smoke blocker logic**

Keep blocker checks for legacy `OIL`; use unicode companion counts for `DJ` and short CJK city terms. The old selected serving DB returns `0` for `DJ` under trigram, so `DJ` is not a valid legacy-table required count.

```python
legacy_required = ["OIL"]
unicode_required = ["DJ", "深圳", "上海"]
```

Block when any required count is `<= 0`.

- [x] **Step 4: Run safe runner test**

Run:

```powershell
python -m pytest tools/stage7_rewrite/tests/test_atlas_core_candidate.py::test_safe_runner_rebuilds_candidates_without_mutating_sources -q
```

Expected: `1 passed`.

## Task 3: Shadow Compare Tokenizer Metadata

**Files:**
- Modify: `tools/stage7_rewrite/scripts/compare_atlas_core_serving_shadow_read.py`
- Test: `tools/stage7_rewrite/tests/test_atlas_core_candidate.py`

- [x] **Step 1: Add tokenizer metadata to report**

Add helper `fts_tokenizer(conn, schema, table)` that reads the FTS `CREATE VIRTUAL TABLE` SQL and extracts `tokenize='...'`.

Report:

```json
"fts_tokenizers": {
  "old_search_document_fts": "trigram",
  "new_search_document_fts": "trigram",
  "new_search_document_fts_unicode61": "unicode61"
}
```

- [x] **Step 2: Add fixture assertion**

In `test_serving_shadow_read_compare_reports_no_key_regression_for_fixture`, assert:

```python
assert "fts_tokenizers" in report
assert report["fts_tokenizers"]["new_search_document_fts"] in {"trigram", "unicode61", "default"}
```

- [x] **Step 3: Run comparator test**

Run:

```powershell
python -m pytest tools/stage7_rewrite/tests/test_atlas_core_candidate.py::test_serving_shadow_read_compare_reports_no_key_regression_for_fixture -q
```

Expected: `1 passed`.

## Task 4: Rebuild Candidate And Reports

**Files:**
- Generate under: `tools/stage7_rewrite/reports/atlas_core_candidate_20260604/`
- Generate under: `tools/stage7_rewrite/reports/atlas_core_serving_shadow_read_compare_20260605/`
- Generate under: `tools/stage7_rewrite/reports/atlas_core_serving_search_diagnosis_20260605/`

- [x] **Step 1: Run full targeted tests**

Run:

```powershell
python -m pytest tools/stage7_rewrite/tests/test_atlas_core_candidate.py -q
```

Expected: all tests pass.

- [x] **Step 2: Rebuild report-local Atlas Core candidate**

Run:

```powershell
python tools/stage7_rewrite/scripts/run_atlas_core_candidate_safe.py --out-dir tools/stage7_rewrite/reports/atlas_core_candidate_20260604 --readiness-out-dir tools/stage7_rewrite/reports/atlas_core_migration_readiness_20260604
```

Expected decision: `atlas_core_safe_execution_passed`.

- [x] **Step 3: Rerun shadow-read compare**

Run:

```powershell
python tools/stage7_rewrite/scripts/compare_atlas_core_serving_shadow_read.py --old-serving-db reports/atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018/atlas_serving.sqlite --new-serving-db tools/stage7_rewrite/reports/atlas_core_candidate_20260604/atlas_serving.sqlite --out-dir tools/stage7_rewrite/reports/atlas_core_serving_shadow_read_compare_20260605
```

Expected: `source_hashes_unchanged=True`, `key_coverage_regression_count=0`, and no `OIL`/`Loopy` legacy regression.

- [x] **Step 4: Rerun search diagnosis**

Run:

```powershell
python tools/stage7_rewrite/scripts/diagnose_atlas_core_serving_search_regressions.py --old-serving-db reports/atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018/atlas_serving.sqlite --new-serving-db tools/stage7_rewrite/reports/atlas_core_candidate_20260604/atlas_serving.sqlite --out-dir tools/stage7_rewrite/reports/atlas_core_serving_search_diagnosis_20260605
```

Expected: the report explains no remaining `OIL`/`Loopy` regression on legacy `search_document_fts`, or records any residual difference with source hashes unchanged.

## Task 5: Store Companion Fallback

**Files:**
- Modify: `services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs`
- Modify: `services/weekly_activity_cloudrun/tests/stage7SqliteLocal.test.mjs`

- [x] **Step 1: Add a failing store test**

Create a minimal serving read-model fixture with:

```sql
CREATE VIRTUAL TABLE search_document_fts USING fts5(search_text, content='search_document', content_rowid='doc_rowid', tokenize='trigram');
CREATE VIRTUAL TABLE search_document_fts_unicode61 USING fts5(search_text, content='search_document', content_rowid='doc_rowid', tokenize='unicode61');
```

Insert one `search_document` row with `search_text='DJ Alpha 深圳 artist performer'`.

Assert:

```js
assert.equal(db.prepare("SELECT COUNT(*) AS count FROM search_document_fts WHERE search_document_fts MATCH ?").get("\"DJ\"").count, 0);
assert.equal(db.prepare("SELECT COUNT(*) AS count FROM search_document_fts_unicode61 WHERE search_document_fts_unicode61 MATCH ?").get("\"DJ\"").count, 1);
const result = await store.search({ q: "DJ", limit: 5 });
assert.equal(result.resultCount, 1);
assert.equal(result.results[0].title, "DJ Alpha");
```

- [x] **Step 2: Implement fallback**

In `servingSearchDocuments()`, replace the inline legacy FTS query with a helper:

```js
const ftsRows = (ftsTable) => db.prepare(`
  SELECT sd.*
  FROM ${ftsTable} f
  JOIN search_document sd ON sd.doc_rowid = f.rowid
  WHERE ${ftsTable} MATCH ?${typeFilter}
  ORDER BY bm25(${ftsTable}), sd.rank_score DESC, sd.doc_rowid
  LIMIT ?
`).all(ftsQuery(query), ...params, pageLimit);
```

After legacy rows return empty, try:

```js
if (sqliteTableExists(db, "search_document_fts_unicode61")) {
  const unicodeRows = ftsRows("search_document_fts_unicode61");
  if (unicodeRows.length) return unicodeRows;
}
```

- [x] **Step 3: Run targeted Node test**

Run:

```powershell
node --test --test-name-pattern "serving search falls back to unicode companion FTS" services/weekly_activity_cloudrun/tests/stage7SqliteLocal.test.mjs
```

Expected: `pass 1`.

- [x] **Step 4: Run direct store smoke**

Run a Node module snippet against `tools/stage7_rewrite/reports/atlas_core_candidate_20260605_fts_compat/atlas_serving.sqlite` and query `OIL`, `Loopy`, `深圳`, and `DJ`.

Expected: each query has `resultCount > 0`.

## Task 6: Closeout Evidence

**Files:**
- Modify: `tools/stage7_rewrite/reports/atlas_core_candidate_20260604/ATLAS_CORE_CANDIDATE_HANDOFF_20260605.md`
- Modify: `tools/stage7_rewrite/reports/atlas_core_candidate_20260604/ATLAS_CORE_CANDIDATE_HANDOFF_20260605.html`

- [x] **Step 1: Update handoff**

Add the final tokenizers and shadow-read status:

```text
search_document_fts_tokenizer=trigram
search_document_fts_unicode61_tokenizer=unicode61
legacy search regression for OIL/Loopy resolved or explicitly documented
```

- [x] **Step 2: Run leak scan**

Run the existing value-shaped scan over the three report directories and the two handoff files.

Expected:

```text
value_shaped_leak_scan_findings=0
```

- [x] **Step 3: Run py_compile**

Run:

```powershell
python -m py_compile tools/stage7_rewrite/scripts/atlas_core_common.py tools/stage7_rewrite/scripts/audit_atlas_core_migration_readiness.py tools/stage7_rewrite/scripts/build_atlas_core_candidate.py tools/stage7_rewrite/scripts/export_atlas_core_to_serving_sqlite.py tools/stage7_rewrite/scripts/export_atlas_core_to_miniapp_sqlite.py tools/stage7_rewrite/scripts/export_atlas_core_to_miniapp_index.py tools/stage7_rewrite/scripts/run_atlas_core_candidate_safe.py tools/stage7_rewrite/scripts/build_atlas_core_external_link_identity_mapping.py tools/stage7_rewrite/scripts/compare_atlas_core_serving_shadow_read.py tools/stage7_rewrite/scripts/diagnose_atlas_core_serving_search_regressions.py
```

Expected: exit code `0`.

## Task 7: Phase F ATLAS_CORE_SQLITE_DB Opt-In

**Goal:** Add the Phase F environment variable without changing the default production read path.

**Files:**
- Modify: `services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs`
- Modify: `services/weekly_activity_cloudrun/src/server.mjs`
- Modify: `services/weekly_activity_cloudrun/tests/stage7SqliteLocal.test.mjs`

- [x] **Step 1: Add opt-in path selection**

`Stage7AtlasSqliteStore` now uses this precedence:

```text
options.stage7SqliteDbPath
STAGE7_ATLAS_SQLITE_DB
ATLAS_CORE_SQLITE_DB
ATLAS_SERVING_SQLITE_DB
default selected read model
```

`createServer()` now instantiates `Stage7AtlasSqliteStore` when `ATLAS_CORE_SQLITE_DB` is present.

- [x] **Step 2: Add env-path test**

Added a minimal serving read-model fixture proving that `ATLAS_CORE_SQLITE_DB` selects the candidate DB and supports search without passing `stage7SqliteDbPath`.

- [x] **Step 3: Verify with tests and candidate smoke**

```powershell
node --test --test-name-pattern "ATLAS_CORE_SQLITE_DB selects|serving search falls back" services/weekly_activity_cloudrun/tests/stage7SqliteLocal.test.mjs
node --check services/weekly_activity_cloudrun/src/server.mjs
node --check services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs
```

Direct env smoke against `tools/stage7_rewrite/reports/atlas_core_candidate_20260605_activity_evidence/atlas_serving.sqlite` returned results for `OIL`, `Loopy`, `深圳`, and `DJ`, with `isServingReadModel=true`.

## Self-Review

- Spec coverage: covers legacy compatibility, unicode companion, store fallback, report-local safety, source hash guard, leak scan, and handoff update.
- Placeholder scan: no placeholder work items are left.
- Type consistency: tokenizer metadata keys match the planned code and readback fields.
