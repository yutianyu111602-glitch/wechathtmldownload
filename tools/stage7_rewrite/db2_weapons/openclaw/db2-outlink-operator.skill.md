---
name: db2-outlink-operator
description: OpenClaw operator skill for DB2 external-link crawling. Use only through db2ctl and Docker Compose profiles; keep live DB2 read-only except db2-writer.
---

# DB2 Outlink Operator Skill For OpenClaw

## Purpose

Operate the DB2 external-link candidate crawl lane through a small allowlist. The Atlas underground-map database is the only upstream product; DB2 external-link weapons/OpenClaw is a consumer worker-runtime lane that supplies external-link/evidence capability for Atlas. DB2 is a candidate/report-only crawl database, not a public serving database or independent publishing target.

## Storage Boundary

- Live DB2 stays on WSL ext4 at `/home/pc/swarm_data/atlas_swarm_data.sqlite`.
- C: is fast system/workspace SSD; D: is mechanical cold data and must not be used for AI high-speed IO; E: is the fast AI data/model/cache SSD.
- Heavy AI model/cache/high-IO data goes under E drive mounted paths, not D drive.
- Do not mount cookie directories by default.

## Allowed Commands

OpenClaw may run these without additional approval:

```bash
db2ctl status
db2ctl health
db2ctl health --lock-holders
db2ctl preflight
db2ctl locks --dry-run
db2ctl existing-data
db2ctl schedule --profile safe
db2ctl schedule --profile safe --only-worker outlink_expand_linktree
db2ctl schedule --profile safe --only-worker outlink_expand_shorturl
db2ctl schedule --profile safe --only-worker avatar_dl
db2ctl recovery stale-running-plan
db2ctl recovery stale-running-reset --snapshot-path SNAPSHOT
db2ctl cache status
db2ctl cache seed --limit 1000
db2ctl policy
db2ctl contracts list
db2ctl contracts show s232d_no_cookie_provider_anchor
db2ctl contracts verify-all
db2ctl lineage --limit 100
db2ctl writer status
db2ctl compose mount-doctor
db2ctl compose readonly
db2ctl compose browser
db2ctl compose writer
db2ctl up safe
db2ctl up steady
db2ctl up safe --worker outlink_expand_linktree
db2ctl up safe --worker outlink_expand_shorturl
db2ctl up safe --worker avatar_dl
db2ctl up safe --worker avatar_dl --limit 10
db2ctl production avatar-batch --limit N --execute
db2ctl production worker-batch --worker outlink_expand_linktree --limit N --execute
db2ctl production worker-batch --worker outlink_expand_shorturl --limit N --execute
db2ctl production cycle --max-batches N --execute
python tools/stage7_rewrite/scripts/evaluate_db2_openclaw_skill.py
skillopt-eval-codex-oauth --config C:\code\githubstar\SkillOpt\configs\searchqa\default.yaml --skill tools\stage7_rewrite\db2_weapons\openclaw\db2-outlink-operator.skill.md --split test
skillopt-train-codex-oauth --config C:\code\githubstar\SkillOpt\configs\searchqa\default.yaml --skill_init tools\stage7_rewrite\db2_weapons\openclaw\db2-outlink-operator.skill.md
```

The `db2ctl up safe` and `db2ctl up steady` commands print the controlled Docker Compose command. They do not grant permission to bypass stop gates.
The worker-specific `db2ctl up safe --worker ...` commands print one-shot Compose commands and should be used for migrated workers before full-profile execution. Use `--limit N` for first production canaries.
Before a worker-specific one-shot command, run the matching worker-specific schedule gate, for example `db2ctl schedule --profile safe --only-worker avatar_dl`.
Before any container worker command, run `db2ctl compose mount-doctor` and require `passed=true`. The doctor must prove `/db2-data/atlas_swarm_data.sqlite`, `/db2-scripts/avatar_dl_worker.py`, `/db2-scripts/outlink_expand_worker.py`, `/db2-spool`, and `/db2-cache/db2_sidecar_cache.sqlite` are visible inside the worker container. Do not start a worker if the doctor reports empty Docker Desktop overlay mounts or any blocker.
Production execution must prefer `db2ctl production ... --execute` over hand-spliced Docker commands. The wrapper performs schedule, rogue legacy worker, writer backlog, cache, mount-doctor, worker, db2-writer, cache seed, health, and lock-holder checks as one bounded unit.
Every `db2ctl production` run writes a redacted `summary.json` under its report directory. Use that file as the durable production evidence if the terminal, Codex thread, or OpenClaw session drops before stdout is preserved.
For longer unattended OpenClaw operation, prefer `db2ctl production cycle --execute` over manually sequencing multiple production commands. The cycle command runs preflight, writer, lock-holder, rogue-worker, and worker-specific schedule gates, then selects only migrated one-shot workers. Shorturl is opt-in for cycle: do not pass `--include-shorturl` unless a recent schedule shows new redirect-shortener work; when included, it still skips `outlink_expand_shorturl` when `selected_after_source_processed_skip=0`. The default cycle consumes remaining Linktree work before raising Linktree limits, and then uses avatar as the throughput lane when avatar candidates remain. It still calls the existing production batch wrappers for each selected worker, so every batch keeps its own `summary.json`.

## Human Confirmation Required

Require human confirmation before:

```bash
DB2_WORKER_EXECUTE=1
DB2_WRITER_EXECUTE=1
db2ctl writer once --execute
db2ctl production avatar-batch --limit N --execute
db2ctl production worker-batch --worker WORKER --limit N --execute
db2ctl production cycle --execute
db2ctl recovery stale-running-reset --execute --snapshot-path SNAPSHOT --confirm reset-stale-running
db2ctl cache seed --execute
db2ctl snapshot NAME --execute
db2ctl checkpoint truncate --execute
docker compose up -d db2-light-workers
docker compose up -d db2-browser-tools
```

## Denied Commands

Never run:

```bash
python3 swarm_restart_v3.py
python3 swarm_restart_v3.py --workers all
db2ctl up all
db2ctl up searxng
db2ctl delete-wal
db2ctl sql-write
db2ctl read-cookies
rm -f /home/pc/swarm_data/*.sqlite-wal
rm -f /home/pc/swarm_data/*.sqlite-shm
```

Also deny raw cookie/token reads, DB1 writes, direct public projection, SearXNG discovery, audio/video downloads, and experimental BC/RA/nuclear live execution without smoke reports.

## DB Lock Rule

DB lock is treated as an architecture issue, not a timeout issue:

```text
workers -> /home/pc/swarm_data/write_spool/incoming/*.jsonl
db2_writer_daemon -> live DB2
analysis/agents -> read-only live DB or snapshots
new development -> delta sidecar, not live DB writes
```

Only `db2-writer` may mount live DB2 read-write. Worker containers mount DB2 read-only and write spool files.
Use `db2ctl writer status` and `db2ctl status` to inspect writer metrics before raising concurrency. The required signals are `spool_backlog`, `incoming_bytes`, `events_by_table`, `events_by_op`, `write_tx_attempts`, and `lock_retries`.
Use `db2ctl health` or `db2ctl schedule` to inspect `rogue_legacy_workers`. If `rogue_legacy_workers_running` appears, do not start production. Stop or migrate direct legacy `/home/pc/scripts/*_worker.py` processes before using `db2ctl production`.

## Worker Migration State

`db2ctl policy` prints the machine-readable OpenClaw allowlist/denylist policy. The policy is read-only, includes `one_shot_allowed_workers`, denied commands, denied workers, storage boundaries, and the required worker-specific schedule template.

Spool-ready worker commands:

```bash
db2ctl up safe --worker outlink_expand_linktree
db2ctl up safe --worker outlink_expand_shorturl
db2ctl up safe --worker avatar_dl
db2ctl up safe --worker avatar_dl --limit 10
```

These route legacy `/home/pc/scripts/outlink_expand_worker.py` through `db2_outlink_expand_spool_adapter.py`, so worker SELECTs use read-only DB2 and writes become JSONL events under `/home/pc/swarm_data/write_spool/incoming`.
The avatar command routes legacy `/home/pc/scripts/avatar_dl_worker.py` through `db2_avatar_spool_adapter.py`: DB2 SELECTs use read-only connections, `avatar_cache` skips already-seen avatar URLs before legacy `download_file`, avatar files write only to `/home/pc/swarm_data/output/avatars` when not skipped, and `insert_avatar` events target `dj_avatars` through `db2-writer`.

Full `safe` or `steady` execute mode must fail if it contains a worker that has not been migrated to spool. Do not override this by mounting DB2 read-write into workers.

## Open-Source Tool Assembly Rule

Open-source projects are tools inside Docker layers, not OpenClaw skills. The skill is only the operator contract:

```text
OpenClaw skill -> db2ctl allowlist -> Docker Compose profile -> worker adapter -> JSONL spool -> db2-writer
```

Do not paste crawler scripts, incremental update logic, Maigret configs, browser automation logic, or open-source project code into this skill. Put code in the repo/container layer and keep this skill to routing, gates, and verification.
Do not train future crawling or incremental-update logic into the skill body. New weapons must be expressed as Docker/container worker contracts first, then exposed through `db2ctl policy`, schedule gates, and allowlisted production wrappers.
S232D-style no-cookie/provider-anchor collection is a future worker-contract/input-format topic only: no cookies, no browser profile reads, bounded provider-anchor inputs, hash-first sidecar effects, JSONL/report-only outputs, and no live run until the controller releases that gate.
Use `db2ctl contracts list`, `db2ctl contracts show s232d_no_cookie_provider_anchor`, and `db2ctl contracts verify-all` to inspect future worker contracts. These commands are read-only and do not authorize execution. `verify-all` must report `passed=true`, `read_only=true`, `would_write=false`, `live_run_allowed=false`, and `production_commands_exposed=false` before OpenClaw treats contract docs as valid control-plane input. The S232D contract has no production command surface; do not invent `db2ctl production` or `db2ctl up` commands for it until a migrated Docker worker, schedule gate, and writer boundary are implemented and verified.

Before starting a worker, run `db2ctl existing-data` and prefer work that fills gaps instead of repeating canonical URL hashes already present in DB2.
Use `db2ctl cache status` and dry-run `db2ctl cache seed --limit 1000` to inspect the hash-first sidecar cache contract before longer runs. The sidecar cache stores URL/avatar/path hashes and metadata only; it must not print raw URLs, raw local paths, cookies, or tokens. `db2ctl cache seed --execute` writes only `/home/pc/swarm_data/cache/db2_sidecar_cache.sqlite`, never live DB2, and still requires human confirmation.
Pre-crawl dedupe is mandatory before expensive fetches. The sidecar `source_processed_cache` records processed `linktree_expand`, `shorturl_resolve`, and `ig_bio` source URL hashes. `db2_outlink_expand_spool_adapter.py` checks `source_processed_cache` before `fetch_linktree_page` or `resolve_short_url`, and checks `url_seen_cache` before emitting an output spool event.
`db2ctl schedule --profile safe` includes `worker_candidate_audit` for the active outlink workers. Use it to inspect the remaining fetchable work before raising a limit. If `selected_after_source_processed_skip=0`, do not raise the limit; choose another lane or reseed the sidecar cache.
`outlink_expand_shorturl` must use the host-normalized redirect-shortener selector from `db2_shorturl_candidates.py`. It must only resolve exact redirect shortener hosts and subdomains; legacy substring patterns such as `%t.co%` must not match unrelated domains such as `beatport.com`. Link-in-bio landing domains are audited separately and must not be resolved by the shorturl worker.
`db2ctl production worker-batch --worker outlink_expand_linktree ...` and `--worker outlink_expand_shorturl ...` persist hash-only `source_completion_upsert` rows into the sidecar after the worker and writer steps. Duplicate-only, no-link, source-cache-hit, and unresolved shorturl sources are considered processed source work and should enter `source_processed_cache` before the next cache/status seed. This prevents repeat network fetches even when no new `dj_outlinks` row was inserted.
Avatar dedupe is mandatory before expensive avatar file work. `db2_avatar_spool_adapter.py` selects distinct `(eid, platform)` profiles before legacy execution and checks `avatar_cache` before `download_file`, so duplicate profile rows and already-seen avatar URL hashes skip network download and local file IO; it also checks `avatar_cache` before emitting an `insert_avatar` spool event.
For avatar scheduling, prefer `selected_after_pre_crawl_skip` from `db2ctl schedule --profile safe --only-worker avatar_dl` over raw missing-row counts. `legacy_limited_rows != legacy_limited_distinct_eids` means the old limit window is wasting work on duplicate profiles. `avatar_dl:<platform>` source completions are sidecar-only attempt/failure markers; after a validation gate, require `source_processed_cache` to increase and require the next avatar schedule to show `selected_source_processed_hits > 0` before raising avatar limits.
Before allowing a longer worker run, check writer status: backlog must be understood, failed spool files must be investigated, and nonzero `lock_retries` should downscale worker concurrency instead of increasing `busy_timeout`.
Before starting any long-running profile, run `db2ctl schedule --profile safe`. The schedule report is read-only and combines S126 preflight, existing-data dedupe coverage, sidecar cache status, dry-run cache seed counts, writer backlog, and worker spool-readiness. If it reports `hold_production`, do not start the full profile; use only the reported worker-specific one-shot migrated workers after resolving the listed production blockers.
For migrated one-shot workers, run a worker-specific schedule gate such as `db2ctl schedule --profile safe --only-worker avatar_dl`. This avoids treating the full mixed `safe` profile as executable while still exposing remaining blockers for that specific worker path.
If the schedule or health report includes `rogue_legacy_workers_running`, do not treat it as a stale-row issue or skip. Collect the process evidence, stop or migrate the direct `/home/pc/scripts` legacy worker, then rerun `db2ctl health --lock-holders` and the worker-specific schedule gate before production.
If the schedule report includes `stale_running_requires_reset_before_worker_start`, run `db2ctl recovery stale-running-plan`. The stale-running plan is read-only, reports affected running rows, stale/fresh counts, phase/platform/worker groups, and reset SQL for review. Do not execute a reset unless a separate reviewed execute gate exists and the plan has no blockers.
The reviewed execute gate is `db2ctl recovery stale-running-reset --execute --snapshot-path SNAPSHOT --confirm reset-stale-running`. It must only run after a snapshot file exists, snapshot `PRAGMA integrity_check` is `ok`, `active_worker_count=0`, `fresh_running_count=0`, no lock holders are present, and the dry-run form `db2ctl recovery stale-running-reset --snapshot-path SNAPSHOT` has no blockers. Never blindly reset stale running rows without snapshot proof.
Use `db2ctl health --lock-holders` for bounded read-only lock-holder evidence before starting workers when `stale_running_count`, writer backlog, or SQLite lock symptoms are present.
Default migrated worker execute mode must wait for the worker process to finish and preserve stdout/stderr in the Compose logs. Treat `worker_start`, `worker_finish`, final returncode, writer status, and post-run schedule/status as the completion evidence. Only use `--detach` for an explicitly reviewed long-running background run. Do not treat a started PID as completion evidence.
For production wrappers, also treat report-dir `summary.json` as required completion evidence. If the summary is missing, rerun the read-only gates and determine whether the wrapper exited before persistence rather than assuming success from partial logs.

## SkillOpt Loop

After every change to this skill:

1. Run `python tools/stage7_rewrite/scripts/evaluate_db2_openclaw_skill.py`.
2. Run `skillopt-eval-codex-oauth` using `docs/longrun/db2-outlink-skillopt-loop/skillopt-codex-oauth/searchqa_split`.
3. Use `skillopt-train-codex-oauth` only as a bounded local training experiment, then inspect the candidate before promotion.
4. Run targeted DB2 tests.
5. Record the result in `docs/longrun/db2-outlink-skillopt-loop/iteration-XXX.md`.
6. Use the latest iteration report as the next optimization input.

Each iteration report must explicitly include `Overall Objective`, `Previous Iteration Summary`, and `Current Iteration Delta` so the operator loop does not drift or rely on memory.
