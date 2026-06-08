# S125 DB2 Outlink Lineage Reconcile Design

Date: 2026-06-01  
Scope: S125 only. Read-only lineage reconciliation for DB2 external-link candidates.  
Status: Design spec, not implementation.

## Goal

Build a read-only reconcile layer that maps live Swarm DB2 outlinks to S119, T6 overlay, and companion DB sidecars under one unified external-link lineage contract.

The output gives OpenClaw and later research agents a stable answer to:

- Where did this DB2 outlink come from?
- Does it match any prior sidecar or overlay candidate?
- Is it blocked, candidate, report-only, or projection-ready?
- Why is it blocked from projection?
- What stable hash can be used for follow-up without exposing raw URLs?

## Non-Goals

S125 does not:

- start DB2 workers;
- modify live Swarm DB2;
- reset stale `running` tasks;
- clean or delete SearXNG rows;
- write DB1 source/raw, DB2 serving, DB3, graph, vector, mem0, or public state;
- read cookies, tokens, browser profiles, `.env`, or secret stores;
- expose raw URLs in JSONL.

## Source Inputs

| Source | Role | Path | Tables |
| --- | --- | --- | --- |
| live Swarm DB2 | active external-link crawl DB | `/home/pc/swarm_data/atlas_swarm_data.sqlite` | `dj_outlinks`, optional `dj_social_profiles`, `dj_identity_candidates` |
| S119 sidecar | projection/copyright contract | `tools/stage7_rewrite/reports/external_link_db2_sidecar_contract_s119_20260601/external_link_db2_sidecar.sqlite` | `external_link_candidates`, `promotion_gates` |
| T6 overlay | public/graph acceptance flags | `tools/stage7_rewrite/reports/atlas_t6_sidecar_new_db_overlay_t5_t6_20260526/atlas_t6_sidecar_social_overlay.sqlite` | `atlas_dj_social_links`, `atlas_dj_social_entity_rollups` |
| companion DB | historical DB2/outlink baseline | `tools/stage7_rewrite/reports/atlas_dj_companion_20260522/atlas_dj_v2.sqlite` | `dj_outlinks`, `dj_social_profiles`, `dj_identity_candidates` |

All SQLite connections must open read-only with `file:<path>?mode=ro`.

## Unified Contract

Every emitted row must include:

```json
{
  "lineage_run_id": "db2_outlink_lineage_reconcile_YYYYMMDD",
  "source_db_role": "live_swarm_external_link_db2",
  "source_table": "dj_outlinks",
  "source_row_key": "outlink_id",
  "entity_key": "eid",
  "platform": "outlink_platform",
  "url_key_hash": "sha256(canonical_url)",
  "candidate_id": "outlink_id",
  "matched_s119_sidecar_id": null,
  "matched_t6_candidate_id": null,
  "matched_companion_outlink_id": null,
  "fact_state": "candidate",
  "projection_allowed": false,
  "block_reason": "projection_gate_not_passed"
}
```

Allowed `fact_state` values:

```text
candidate
report_only
review_ready
blocked
public_fact
production_effective
```

S125 should normally emit only `candidate`, `report_only`, `review_ready`, or `blocked`. It must not emit `public_fact` or `production_effective`.

## URL Policy

JSONL output must not include raw URLs.

Use:

```text
url_key_hash = sha256(canonical_url)
```

Canonicalization rules:

- lowercase scheme and host;
- strip leading `www.`;
- normalize empty path to `/`;
- strip trailing slash except root;
- remove common tracking parameters such as `utm_*`, `fbclid`, `gclid`, `igsh`, `mc_cid`, `mc_eid`, and `spm`;
- preserve non-tracking query parameters.

Markdown summary also defaults to no raw URLs. If a future private operator report needs raw URLs, it must be a separate local-only artifact with explicit naming and must not be copied into GPT/public research bundles.

## Matching Strategy

Primary match:

```text
url_key_hash
```

Secondary attributes:

```text
eid / entity_search_id / entity_id
platform
host
candidate_id / sidecar_id / outlink_id
```

Precedence:

1. Match by `url_key_hash`.
2. Use `eid/platform` only as supporting metadata, not as a replacement for URL hash.
3. If URL hash is empty, emit row as `report_only` or `blocked` with `block_reason=missing_url_key_hash`.
4. Never join solely by display name.

Rationale: identity names and handles are noisy; URL hash is the least ambiguous key for external-link reconciliation.

## Block And Projection Rules

Default:

```text
fact_state = candidate
projection_allowed = false
block_reason = projection_gate_not_passed
```

Rules:

| Condition | fact_state | projection_allowed | block_reason |
| --- | --- | --- | --- |
| `source_layer` or `outlink_platform` contains `searx` | blocked | false | `searxng_source_blocked` |
| S119 `copyright_safety` blocks direct media/archive | blocked | false | `copyright_safety_blocked` |
| T6 `source_raw_db_write_executed != 0` | blocked | false | `source_raw_write_boundary_violation` |
| T6 `public_serving_field_allowed != 1` | candidate | false | `projection_gate_not_passed` |
| S119 `db2_projection_allowed != 1` | candidate | false | `projection_gate_not_passed` |
| URL hash missing | report_only | false | `missing_url_key_hash` |

S125 must not promote anything to public projection. If a row appears to satisfy all projection prerequisites, emit `review_ready`, not `public_fact`.

## Outputs

Repo-local output:

```text
tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_YYYYMMDD/
  db2_outlink_lineage_reconcile.jsonl
  db2_outlink_lineage_reconcile.md
```

WSL/OpenClaw mirror:

```text
/home/pc/reports/DB2_OUTLINK_LINEAGE_RECONCILE_YYYYMMDD.jsonl
/home/pc/reports/DB2_OUTLINK_LINEAGE_RECONCILE_YYYYMMDD.md
```

Markdown summary must include:

- row count;
- fact state counts;
- platform counts;
- matched S119 count;
- matched T6 count;
- matched companion count;
- projection_allowed count;
- SearXNG blocked count;
- boundary statement that no live DB writes occurred.

## CLI Shape

Recommended script:

```text
tools/stage7_rewrite/scripts/build_db2_outlink_lineage_reconcile_s125.py
```

Recommended CLI:

```powershell
python tools\stage7_rewrite\scripts\build_db2_outlink_lineage_reconcile_s125.py `
  --live-db \\wsl.localhost\Ubuntu\home\pc\swarm_data\atlas_swarm_data.sqlite `
  --s119-db tools\stage7_rewrite\reports\external_link_db2_sidecar_contract_s119_20260601\external_link_db2_sidecar.sqlite `
  --t6-db tools\stage7_rewrite\reports\atlas_t6_sidecar_new_db_overlay_t5_t6_20260526\atlas_t6_sidecar_social_overlay.sqlite `
  --companion-db tools\stage7_rewrite\reports\atlas_dj_companion_20260522\atlas_dj_v2.sqlite `
  --output-dir tools\stage7_rewrite\reports\db2_outlink_lineage_reconcile_s125_20260601
```

Implementation should also support:

```text
--limit N
--lineage-run-id VALUE
--mirror-wsl-dir /home/pc/reports
```

`--limit` is for smoke runs only.

## Testing Design

Tests should use temporary fixture SQLite DBs and must not require live DB access.

Required tests:

1. Reads all fixture DBs with read-only path semantics.
2. Emits required contract fields.
3. Defaults `projection_allowed=false`.
4. Blocks SearXNG rows.
5. Does not emit raw URLs in JSONL.
6. Matches S119/T6/companion by canonical URL hash.
7. Emits `missing_url_key_hash` when URL is empty.
8. Keeps rows `candidate` or `blocked`; never `public_fact`.

Focused test command:

```powershell
python -m pytest tools\stage7_rewrite\tests\test_build_db2_outlink_lineage_reconcile_s125.py -q
```

## Safety Checks

Before considering S125 complete:

```powershell
python -m py_compile tools\stage7_rewrite\scripts\build_db2_outlink_lineage_reconcile_s125.py
python -m pytest tools\stage7_rewrite\tests\test_build_db2_outlink_lineage_reconcile_s125.py -q
Select-String -LiteralPath tools\stage7_rewrite\reports\db2_outlink_lineage_reconcile_s125_20260601\db2_outlink_lineage_reconcile.jsonl -Pattern 'https://|http://|cookie|token|secret|C:\\|D:\\|/mnt/d'
```

The final `Select-String` should return no matches.

## Open Decisions

Settled for this design:

- JSONL emits hash only, not raw URL.
- `url_key_hash` is primary matching key.
- `eid/platform` are supporting attributes only.
- Projection remains false by default.
- S125 is read-only and can be implemented before safe launcher or nightwatch.

Deferred:

- Whether to create a separate private raw-URL operator report.
- Whether to add a quarantine table for SearXNG rows.
- Whether identity candidate reimport should happen before or after S126 recovery preflight.

## Acceptance Criteria

S125 design is satisfied when:

- the script can generate JSONL and Markdown from fixture DBs;
- a bounded live read-only smoke can run with `--limit`;
- output rows include the unified contract;
- no raw URL or secret-like string appears in JSONL;
- all rows remain candidate/report-only/blocked/review-ready;
- WSL mirror paths can be produced for OpenClaw;
- no live DB mutation occurs.

