# Atlas Outlink Search — Current Runtime State

Generated: 2026-05-21 22:15 CST
Authoritative entry: `docs/atlas-outlink-deepseektui-handoff-20260521/MANIFEST.md`

## 2026-05-22 Lifecycle / Current Authority

Lifecycle: `historical-or-evidence` / `verify-before-use`.

This file is a 2026-05-21 runtime snapshot and handoff plan. Its `RUNNING`
public-search status, PID, ETA, slice count, estimated Post-Filter survivor
count, service-health table, and resume commands are not current runtime
authority.

Current authority for Atlas social / outlink search is
`docs/ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md`, with Stage7 overlays in
`tools/stage7_rewrite/SSOT.md` and `tools/stage7_rewrite/STAGE7_SSOT_20260514.md`.
As of the 2026-05-22 closeout, public-search is `COMPLETE`, full Post-Filter
completed at `2026-05-22T10:36:47+08:00`, the reduced review queue is `27`,
and graph-write flags remain blocked until explicit human acceptance.

Use the sections below only as historical planning evidence for the
DeepSeekTUI/outlink handoff. Re-verify every path, service, queue count, and
write target against the current SSOT and closeout reports before running
anything.

## Prerequisite: Public-Search

| Field | Value |
|-------|-------|
| Status | RUNNING |
| PID | 108336 (alive) |
| Progress | 77.66% (191,052 / 246,024) |
| Remaining | 54,972 rows / ~110 slices |
| ETA | ~6.0 hours (~2026-05-22 04:00 CST) |
| Stderr | 0 bytes (clean) |
| Slices | 382 completed |
| Speed | ~195 sec/slice, stable |

## Automation

| Field | Value |
|-------|-------|
| ID | `2a6ada79-6e21-49df-8212-0bc111181591` |
| Name | Atlas Outlink Supervisor Hourly |
| Schedule | HOURLY (every 60 min) |
| Status | active |
| Last run | 2026-05-21 22:11 CST |
| Next run | 2026-05-21 23:10 CST |

## Pipeline (when public-search COMPLETE)

```
Step 1  Gate Check          supervisor.py
Step 2  Post-Filter          build_atlas_entity_public_search_post_filter_queue.py
                             35/45 thresholds → ~890 entities
Step 3  Cross-Validation     cross_validate_atlas_outlinks.py
                             53k aliases + 155 URLs → strategy routing
Step 3.5 Adaptive Orch.      adaptive_outlink_orchestrator.py
                             multi-method parallel + quality scoring
Step 4  Scale Best Method    HTTP outlink or Maigret at scale
Step 4c Avatar Download      download_atlas_profile_avatars.py
                             → D:\DJ_DATA\avatars\ + atlas_avatars.sqlite
Step 5  Summary Report       all paths + counts + safety
```

## Quality Audit Results (from prefix50k + evidence analysis)

- Evidence rows: 527,268 for 182,552 entities (~2.88/entity)
- Score 0: 87.6% → Post-Filter quarantines these
- Weak/unmatched decisions: 94.1%
- Music domains: 4.1% (21,524 rows)
- Social domains: 1.6% (8,637 rows)
- Post-Filter survival: 0.38% (192/50,000) — aggressive but 100% accurate
- Extrapolated full run: ~890 entities survive Post-Filter

## Database Targets

| Database | Path | Purpose |
|----------|------|---------|
| Atlas SQLite | `reports/atlas_local_sqlite_db_138102_20260521/atlas.sqlite` | Entity metadata (read-only) |
| Avatar SQLite | `D:\DJ_DATA\databases\atlas_avatars.sqlite` | Downloaded avatars (write) |
| Avatar files | `D:\DJ_DATA\avatars/` | SHA256-named image files |

## Script Inventory

| Script | Path | Status |
|--------|------|--------|
| Supervisor | `/home/pc/scripts/atlas_outlink_supervisor.py` | Active |
| Cross-Validate | `scripts/cross_validate_atlas_outlinks.py` | Tested ✅ |
| Adaptive Orch. | `scripts/adaptive_outlink_orchestrator.py` | Tested ✅ |
| Avatar Download | `scripts/download_atlas_profile_avatars.py` | Tested (DB init) ✅ |
| Post-Filter | `scripts/build_atlas_entity_public_search_post_filter_queue.py` | Existing |
| HTTP Outlink | `scripts/expand_atlas_social_profile_outlinks.py` | Existing |
| Maigret | `scripts/run_maigret_http_canary.py` | Existing |
| OpenCLI | `scripts/opencli_social_profile_evidence.py` | Existing |
| Scrapling | `scripts/fetch_atlas_entity_public_search_content_evidence.py` | Existing |

## Services

| Service | Address | Status |
|---------|---------|--------|
| Maigret | 127.0.0.1:15051 | HTTP 200 ✅ |
| Camofox | 127.0.0.1:9377 | Healthy (Windows) ✅ |
| OpenCLI | ejk3c3qe | Doctor OK ✅ |
| llama.cpp (mem0) | 127.0.0.1:11434 | OK ✅ |

## Safety

- `accepted_for_graph`: **false** (all rows)
- `identity_proof`: **false** (all rows)
- `graph_write_allowed`: **false** (all rows)
- `accepted_graph_edges_remain_empty`: **true**
- No Neo4j/Qdrant/SQLite/mem0/agentmemory writes
- No cookie/token export, no credential-store reads
- No account mutation, no private page capture
- Report-only outputs

## How to Resume

```bash
# Check current status
python3 /home/pc/scripts/atlas_outlink_supervisor.py

# View log
tail -10 /home/pc/scripts/atlas_outlink_supervisor_log.jsonl

# When COMPLETE, manually trigger Post-Filter:
cd /mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite
python3 scripts/build_atlas_entity_public_search_post_filter_queue.py \
  --review-jsonl reports/atlas_entity_public_search_138102_20260521/entity_public_search_review.jsonl \
  --evidence-jsonl reports/atlas_entity_public_search_138102_20260521/entity_public_search_evidence.jsonl \
  --rules config/atlas_entity_public_search_post_filter_rules.json \
  --out-dir reports/atlas_entity_public_search_post_filter_full_138102_20260521 \
  --min-post-filter-score 35 --review-score 45 \
  --emit-quarantine --confirm-full-run COMPLETE

# Then cross-validate:
python3 scripts/cross_validate_atlas_outlinks.py

# Then adaptive orchestrate:
python3 scripts/adaptive_outlink_orchestrator.py

# Then download avatars:
python3 scripts/download_atlas_profile_avatars.py
```
