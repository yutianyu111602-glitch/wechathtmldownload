# Atlas Core Serving FTS Compatibility Design

Date: 2026-06-05
Status: Approved by prior user implementation directive; report-local only.
Scope: Atlas Core candidate serving exporter and validation reports.

## Problem

Atlas Core candidate exports a legacy `atlas_serving.sqlite` read model for old scripts. The current candidate uses `search_document_fts tokenize='unicode61'`, while the selected old serving DB uses `tokenize='trigram'`.

The shadow-read comparison found no key coverage regression across `dj_profile`, `performance_event`, `dj_event`, `dj_relation_rollup`, `evidence_ref`, and `search_document`, but it found search-count regressions:

- `OIL`: old `55099`, new `33866`
- `Loopy`: old `460`, new `339`

The follow-up diagnosis proved the content is not missing: old/new `LIKE` coverage is identical for both queries. The difference is tokenizer semantics. Old scripts that query `search_document_fts` expect trigram substring matching, including mixed strings like `OIL油`, `Loopyy`, `4LOOPY`, and `loopy遗孀`.

## Goals

- Preserve old table name `search_document_fts` and restore legacy trigram behavior in report-local `atlas_serving.sqlite`.
- Keep the existing `search_document` table and all old fields unchanged.
- Preserve a path for unicode/CJK-friendly search without forcing old consumers to understand it.
- Keep all output report-local under `tools/stage7_rewrite/reports`.
- Prove source DB hashes remain unchanged.
- Prove no raw URL or secret-like value appears in public report artifacts.

## Non-Goals

- No production DB write.
- No DB3/S232D-4 write.
- No selected serving DB overwrite.
- No CloudRun/VPS deploy.
- No mini-program upload, review, or release.
- No change to old consumer API response shape.
- No cookie, token, profile, `.env`, or browser secret read.

## Chosen Approach

Use a dual-FTS serving export:

1. `search_document_fts` keeps the legacy public table name and uses `tokenize='trigram'`.
2. `search_document_fts_unicode61` is added as an optional companion table using `tokenize='unicode61'`.
3. Both tables index the same `search_document` rows.
4. `build_metadata` records:
   - `search_document_fts_tokenizer=trigram`
   - `search_document_fts_unicode61_tokenizer=unicode61`
5. `Stage7AtlasSqliteStore` keeps querying the legacy table first, then falls back to the unicode companion only when the legacy table returns no rows or errors.

This preserves old scripts because the table they already query has the old tokenizer. It also keeps the new city/CJK capability available for future shadow-mode consumers or query-layer experiments.

## Alternatives Considered

### Keep only `unicode61`

This preserves the current city/CJK FTS counts but breaks old substring behavior. It conflicts with the user requirement that old scripts and fields remain compatible.

### Add query-layer expansion only

This avoids schema changes but forces every old consumer to change its query behavior. That is the wrong dependency direction: compatibility should be in the exported read model first.

### Use only `trigram`

This fully restores old behavior but loses the proven unicode/CJK benefits for future Atlas Core shadow mode. Adding the companion table is low-risk and keeps both modes visible.

## Data Flow

```text
atlas_core.sqlite
  -> export_atlas_core_to_serving_sqlite.py
  -> search_document rows
  -> search_document_fts           trigram legacy table
  -> search_document_fts_unicode61 unicode companion table
  -> report-local atlas_serving.sqlite
  -> shadow-read compare and diagnosis reports
```

## Consumer Contract

Old consumers continue to use:

```sql
SELECT sd.*
FROM search_document_fts f
JOIN search_document sd ON sd.doc_rowid = f.rowid
WHERE search_document_fts MATCH ?
ORDER BY bm25(search_document_fts), sd.rank_score DESC, sd.doc_rowid
```

The serving store may use the companion fallback when legacy trigram returns no rows:

```sql
SELECT sd.*
FROM search_document_fts_unicode61 f
JOIN search_document sd ON sd.doc_rowid = f.rowid
WHERE search_document_fts_unicode61 MATCH ?
ORDER BY bm25(search_document_fts_unicode61), sd.rank_score DESC, sd.doc_rowid
```

No existing consumer is required to use the companion table.

## Validation

Required checks:

- Unit tests prove the exporter creates both FTS tables and metadata keys.
- Unit tests prove legacy `search_document_fts` matches substring cases that `unicode61` misses.
- Safe runner readback records both legacy and unicode FTS counts.
- Store-level smoke proves `OIL`, `Loopy`, `深圳`, and `DJ` return results from the dual-FTS candidate.
- Shadow-read compare no longer treats `OIL` and `Loopy` as legacy table regressions after rebuilding the candidate.
- Source hash guard remains unchanged.
- Leak scan remains `0`.

## Risks

- Some previous smoke checks expected `search_document_fts` to return short CJK city terms directly. Those checks must move to either store-level fallback or the unicode companion table.
- SQLite builds without `trigram` tokenizer support need a fallback. In that case the candidate must mark `search_document_fts_tokenizer` as `default` and block promotion-grade compatibility, while still staying report-local.

## Acceptance

The design is accepted when a rebuilt report-local candidate shows:

- `search_document_fts_tokenizer=trigram`
- `search_document_fts_unicode61_tokenizer=unicode61`
- `OIL` and `Loopy` legacy FTS counts are not below the old serving DB in shadow-read compare
- `Stage7AtlasSqliteStore` returns non-zero results for `OIL`, `Loopy`, `深圳`, and `DJ` against the report-local FTS compatibility candidate
- `source_hashes_unchanged=true`
- `leak_finding_count=0`
- no production write flags are true
