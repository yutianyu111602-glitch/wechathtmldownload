# OpenClaw DB2 External-Link Docker Arsenal — Manual Launcher

> 接手文档: `reports/DB2_EXTERNAL_LINK_DOCKER_HANDOFF_20260604.md`
> Repo-local skill: `tools/stage7_rewrite/docker/openclaw-db2-external-link/SKILL.md`
> 控制面: `scripts/db2_external_link_docker_skill.py` (✅)
> 测试: `tests/test_db2_external_link_docker_skill.py` (15/15 ✅)
> L4 proof: `tools/stage7_rewrite/reports/openclaw_db2_external_link_profiles_contract/openclaw-db2-outlink-public-fetch_public_fetch_report.json` (5/5 fetched, leak=0)
> L5 proof: `tools/stage7_rewrite/reports/openclaw_db2_external_link_profiles_contract/openclaw-db2-outlink-sidecar-merge_sidecar_merge_report.json` (5/5 merge candidates, leak=0)
> Longrun proof: `reports/DB2_EXTERNAL_LINK_DOCKER_LONGRUN_20260604.md` (748 rows, 522 merge candidates, leak=0)
> Projection prewrite packet: `reports/DB2_EXTERNAL_LINK_PROJECTION_PREWRITE_PACKET_20260604.md` (452 unique prewrite candidates, DB write=0)
> Projection execution gate: `reports/DB2_EXTERNAL_LINK_PROJECTION_EXECUTION_GATE_20260604.md` (452 work orders, execute=false)
> Projection quality gate: `reports/DB2_EXTERNAL_LINK_PROJECTION_QUALITY_GATE_20260605.md` (64 ready, 388 blocked, DB write=0)
> Quality-ready execution gate: `reports/DB2_EXTERNAL_LINK_PROJECTION_EXECUTION_GATE_QUALITY_READY_20260605.md` (64 work orders, conflicts=0, execute=false)

This folder is the DB2 external-link sibling of the weekly geo source-fetch arsenal
(`../openclaw-weekly`). It contains contract-only docker profiles for collecting
**public** outlink evidence (SoundCloud / Bandcamp / Mixcloud / RA / 小红书 / Bilibili /
Weibo / Instagram public pages) that feeds the DB2 external-link sidecar.

All contract profiles are `network_mode: "none"` and refuse DB writes, DB2 projection,
identity promotion, and CloudBase uploads by design. Docker build context is this
folder only, not the repository root; runtime data access is limited to the reports
mount.

**No script in this folder ever auto-launches a container.** Bring the arsenal up only
when you explicitly want to, and only after the project SSOT authorizes the DB2 lane.

## Component Status

| Layer | Profile | Status | Gap |
|-------|---------|--------|-----|
| L1 | `openclaw-db2-outlink-exporter` | ⚠️ stub | Replaced by S119 sidecar candidates |
| L2 | `openclaw-db2-outlink-queue-cache` | ⚠️ stub | contract-only, no queue backend |
| L3 | `openclaw-db2-outlink-normalize` | ✅ local smoke | URL classify+redact; emits L4-consumable candidates |
| L4 | `openclaw-db2-outlink-public-fetch` | ✅ local smoke | Public title/meta fetch, report-only, no DB write |
| L5 | `openclaw-db2-outlink-sidecar-merge` | ✅ local smoke | Merges L4 metadata into report-only DB2 sidecar candidates; no DB2 projection |

## Data Flow

```
S119 sidecar (748 candidates)
  → db2_external_link_docker_skill.py (control-plane)
      → L1-L5 Docker profiles
      → L3: classify + redact + normalize
      → L4: public HTTP metadata fetch     (implemented, runtime-gated)
      → L5: report-only sidecar merge      (implemented, no DB write)
      → projection prewrite packet          (452 unique candidates, no DB write)
      → projection execution gate           (452 work orders, blocked, no live spool)
      → projection quality gate             (64 ready / 388 blocked, no DB write)
      → quality-ready execution gate         (64 work orders, target conflicts 0, blocked)
```

## Pre-flight Checklist

1. Docker Desktop or compatible engine running locally.
2. A DB2 outlink queue artifact exists (jsonl of `{entity_id, source_url, platform_hint}`),
   produced by `scripts/db2_external_link_docker_skill.py` or an upstream outlink builder.
3. Inputs and outputs go through `tools/stage7_rewrite/reports/`, bind-mounted as
   `/openclaw-reports`. The repository root is not bind-mounted.
4. Cookies / tokens are never read at runtime
   (`OPENCLAW_SECRET_POLICY: environment_injection_only_no_value_read`).

## Profiles available

| Profile | Layer | Purpose |
| --- | --- | --- |
| `openclaw-db2-outlink-exporter` | L1 | export DB2 outlink candidates from atlas (contract) |
| `openclaw-db2-outlink-queue-cache` | L2 | outlink queue cache / lease contract |
| `openclaw-db2-outlink-normalize` | L3 | classify + redact + candidate-only normalize |
| `openclaw-db2-outlink-public-fetch` | L4 | bounded public metadata fetch (runtime-gated) |
| `openclaw-db2-outlink-sidecar-merge` | L5 | DB2 sidecar candidate merge contract, no network |

Run a single contract profile (manual, from repo root):

```powershell
docker compose `
  -f tools/stage7_rewrite/docker/openclaw-db2-external-link/docker-compose.openclaw-db2-external-link.yml `
  --profile openclaw-db2-outlink-normalize `
  up --build --abort-on-container-exit
```

Run the bounded public-fetch runtime (explicit network release, still report-only):

```powershell
docker compose `
  -f tools/stage7_rewrite/docker/openclaw-db2-external-link/docker-compose.openclaw-db2-external-link.yml `
  -f tools/stage7_rewrite/docker/openclaw-db2-external-link/docker-compose.openclaw-db2-external-link.runtime.yml `
  --profile openclaw-db2-outlink-public-fetch `
  run --rm openclaw-db2-outlink-public-fetch
```

Run the L5 sidecar merge contract after L4 metadata exists (no network, still report-only):

```powershell
docker compose `
  -f tools/stage7_rewrite/docker/openclaw-db2-external-link/docker-compose.openclaw-db2-external-link.yml `
  --profile openclaw-db2-outlink-sidecar-merge `
  run --rm openclaw-db2-outlink-sidecar-merge
```

The control-plane skill emits the exact command and a bounded plan without starting
anything:

```powershell
python tools/stage7_rewrite/scripts/db2_external_link_docker_skill.py --max-tasks 50
python tools/stage7_rewrite/scripts/db2_external_link_docker_skill.py --start-offset 50 --max-tasks 50
npm run weekly:external-link-db2:docker-skill -- --max-tasks 50
# add --allow-docker-run only after the DB2 lane is authorized
```

Focused validation:

```powershell
python -m py_compile `
  tools/stage7_rewrite/scripts/db2_external_link_docker_skill.py `
  tools/stage7_rewrite/docker/openclaw-db2-external-link/db2_external_link_entrypoint.py
python -m pytest tools/stage7_rewrite/tests/test_db2_external_link_docker_skill.py -q
```

Build the production-candidate / DB2 projection prewrite packet from the full
longrun archive. This only writes report-local artifacts and a dry-run spool;
it does not deliver to live DB2 or execute projection:

```powershell
python tools/stage7_rewrite/scripts/build_db2_external_link_projection_prewrite_packet.py
python -m pytest tools/stage7_rewrite/tests/test_build_db2_external_link_projection_prewrite_packet.py -q
```

Build the report-local DB2 projection execution gate from the prewrite packet
and live read-only `db2ctl` evidence. This emits writer-event previews and
snapshot work orders only; it does not copy files into the live DB2 spool:

```powershell
python tools/stage7_rewrite/scripts/build_db2_external_link_projection_execution_gate.py `
  --status-json tools/stage7_rewrite/reports/db2_external_link_projection_execution_gate_20260604/db2ctl_status.json `
  --health-json tools/stage7_rewrite/reports/db2_external_link_projection_execution_gate_20260604/db2ctl_health_lockholders.json `
  --existing-data-json tools/stage7_rewrite/reports/db2_external_link_projection_execution_gate_20260604/db2ctl_existing_data.json `
  --target-audit-json tools/stage7_rewrite/reports/db2_external_link_projection_execution_gate_20260604/db2_live_target_conflict_audit.json `
  --controller-open-requested `
  --release-live-spool
python -m pytest tools/stage7_rewrite/tests/test_build_db2_external_link_projection_execution_gate.py -q
```

Build the quality gate and current quality-ready execution subset. This keeps
low-confidence, duplicate-URL, generic RA, and live-conflict rows out of the
first write attempt; it still remains report-local until the DB2 single-writer
gate is explicitly released:

```powershell
python tools/stage7_rewrite/scripts/build_db2_external_link_projection_quality_gate.py `
  --target-audit tools/stage7_rewrite/reports/db2_external_link_projection_execution_gate_20260605/db2_live_target_conflict_audit.json `
  --execution-gate tools/stage7_rewrite/reports/db2_external_link_projection_execution_gate_20260605/db2_external_link_projection_execution_gate.json `
  --out-dir tools/stage7_rewrite/reports/db2_external_link_projection_quality_gate_20260605 `
  --scorecard reports/DB2_EXTERNAL_LINK_PROJECTION_QUALITY_GATE_20260605.md

python tools/stage7_rewrite/scripts/build_db2_external_link_projection_execution_gate.py `
  --prewrite-candidates tools/stage7_rewrite/reports/db2_external_link_projection_quality_gate_20260605/db2_external_link_projection_quality_ready_candidates.jsonl `
  --rollback-contracts tools/stage7_rewrite/reports/db2_external_link_projection_quality_gate_20260605/db2_external_link_projection_quality_ready_rollback_contracts.jsonl `
  --readback-contracts tools/stage7_rewrite/reports/db2_external_link_projection_quality_gate_20260605/db2_external_link_projection_quality_ready_postwrite_readback_contracts.jsonl `
  --status-json tools/stage7_rewrite/reports/db2_external_link_projection_execution_gate_20260605/db2ctl_status.json `
  --health-json tools/stage7_rewrite/reports/db2_external_link_projection_execution_gate_20260605/db2ctl_health_lockholders.json `
  --existing-data-json tools/stage7_rewrite/reports/db2_external_link_projection_execution_gate_20260605/db2ctl_existing_data.json `
  --target-audit-json tools/stage7_rewrite/reports/db2_external_link_projection_execution_gate_quality_ready_20260605/db2_live_target_conflict_audit_quality_ready.json `
  --out-dir tools/stage7_rewrite/reports/db2_external_link_projection_execution_gate_quality_ready_20260605 `
  --scorecard reports/DB2_EXTERNAL_LINK_PROJECTION_EXECUTION_GATE_QUALITY_READY_20260605.md `
  --controller-open-requested `
  --release-live-spool `
  --allow-candidate-subset
python -m pytest `
  tools/stage7_rewrite/tests/test_db2_external_link_docker_skill.py `
  tools/stage7_rewrite/tests/test_build_db2_external_link_projection_prewrite_packet.py `
  tools/stage7_rewrite/tests/test_build_db2_external_link_projection_execution_gate.py `
  tools/stage7_rewrite/tests/test_build_db2_external_link_projection_quality_gate.py -q
```

## What this arsenal will NOT do

- Push to CloudBase, run `tcb`, or upload the mini-program.
- Write to DB1, DB2, DB3, or any production SQLite / graph / vector store.
- Promote identity, avatar display fields, or graph truth.
- Read `.env`, cookies, browser profiles, or credentials at runtime.
- Send the repository root as Docker build context.
- Mount the repository root in the container.
- Scan `D:\`, `D:\DDownload`, `D:\aidata`, `/mnt/d`.
- Reach the network from contract profiles (`network_mode: "none"`). Only the explicit
  `openclaw-db2-outlink-public-fetch` runtime profile may touch the network, and only for
  bounded public metadata under an explicit controller release.

## Output contract

Each profile writes report-only artifacts:

- `<profile>_profile_report.json` — `openclaw_db2_external_link_profile_report.v1`
- `<profile>_normalize_report.json` + `<profile>_outlink_candidates.jsonl` — for the
  normalize / public-fetch dry-run mode (`openclaw_db2_external_link_normalize_report.v1`)
- `<profile>_public_fetch_report.json`, `<profile>_outlink_metadata.jsonl`, and
  `<profile>_public_fetch_blockers.jsonl` — for L4 public metadata fetch
  (`openclaw_db2_external_link_public_fetch_runtime.v1`)
- `<profile>_sidecar_merge_report.json`, `<profile>_sidecar_merge_candidates.jsonl`,
  and `<profile>_sidecar_merge_blockers.jsonl` — for L5 report-only sidecar merge
  (`openclaw_db2_external_link_sidecar_merge_contract.v1`)

All rows are `candidate` or `blocked`. L5 emits only `report_only_pending_db2_projection_gate`
or `blocked_report_only`; promotion to DB2 stays with the project SSOT.

## Next

1. **First write candidate is now the 64-row quality-ready subset only**: target conflicts are `0`, writer dry-run parsed, and filtered rollback/readback contracts exist.
2. **Projection execution remains blocked**: `execute_allowed_now=false` because the exact confirm token is missing and live DB2 still has lock holders / rogue legacy workers (`rogue_legacy_worker_count=23`).
3. **Maintenance window**: stop or migrate legacy DB holders before any live spool delivery attempt; do not kill them implicitly from this lane.
4. **Blocked rows policy**: keep the `388` quality-blocked rows out of the first write attempt until low-confidence, duplicate URL, generic RA, and live-conflict policies are resolved.
5. **Cron**: schedule daily dry-run only after L4/L5 gates are explicit.
6. **401/403 fallback**: keep blocked rows blocked unless a separate non-secret rendered/public fallback is approved.

See `reports/DB2_EXTERNAL_LINK_DOCKER_HANDOFF_20260604.md` for full details.
