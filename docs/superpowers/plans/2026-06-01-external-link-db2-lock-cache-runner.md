# S118 External-Link DB2 Lock/Cache Runner Plan

Status: `APPROVED_FOR_EXECUTION`

## Goal

Build the S118 runner that makes external-link longruns safe to scale: lease-based task claims, stale-lock recovery, deterministic cache keys, atomic report writes, fixture smoke, and a production-ready queue mode. This is the bridge from S117 inventory to real DB2 outlink canaries.

## Files

- Add `tools/stage7_rewrite/scripts/run_external_link_lock_cache_runner.py`.
- Add `tools/stage7_rewrite/tests/test_run_external_link_lock_cache_runner.py`.
- Add `weekly:external-link-db2:lock-cache-smoke` to `package.json`.
- After verification, update the Atlas longrun manifest/current-runtime/documentation index with S118 artifacts.

## Design

1. Queue input is JSONL or JSON list. Each task needs at least `task_id` and may include `url`, `platform`, `subject`, `priority`, and metadata.
2. Locking uses per-task JSON lease files created with exclusive file creation. Stale leases can be reclaimed after `lease_ttl_sec`.
3. Cache keys are SHA-256 over normalized task identity and runner version. Cached hits skip claim/fetch work and still emit result rows.
4. Atomic writes use temporary files plus `replace`, so interrupted runs do not corrupt JSON/JSONL outputs.
5. Default mode is fixture/no-network. Production mode is enabled by explicit flags and still writes only candidate/report artifacts, not DB1/DB2/DB3.
6. Cookie/token paths are accepted only as metadata inputs. The runner records format/count/domain/expiry if supplied later, never values.

## Verification

- `python -m py_compile tools/stage7_rewrite/scripts/run_external_link_lock_cache_runner.py`
- `python -m pytest tools/stage7_rewrite/tests/test_run_external_link_lock_cache_runner.py -q`
- `npm run weekly:external-link-db2:lock-cache-smoke`

## Production Step After Smoke

If the smoke and tests pass, the next wakeup should run a larger candidate queue through the same runner with `--mode production-candidate --max-tasks` and then hand the produced cache/result manifest to S119 DB2 outlink sidecar schema work.
