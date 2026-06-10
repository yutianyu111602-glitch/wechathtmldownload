# DB2 Weapons Container Stack

This stack provides a layered Docker Compose runtime for DB2 external-link tools.

## Important docs

- `reports/DB2_FULL_STACK_DOCKER_AGENT_PLAN_20260601.md` is the saved full-stack DB2 optimization plan.
- `docs/longrun/db2-outlink-skillopt-loop/DB2_OUTLINK_PIPELINE_SSOT_20260601.md` is the consolidated DB2 external-link crawl pipeline SSOT.
- `docs/decisions/ADR-003-db2-weapons-docker-profiles.md` is the accepted local implementation decision.
- `tools/stage7_rewrite/db2_weapons/docker-compose.db2-swarm.example.yml` is a reference-only worker-by-worker template. It is not the default live Compose stack.
- `tools/stage7_rewrite/db2_weapons/compose.yaml` is the current v1 operational entrypoint.
- `docs/longrun/db2-outlink-skillopt-loop/manifest.md` is the self-optimization loop manifest.
- `tools/stage7_rewrite/db2_weapons/openclaw/db2-outlink-operator.skill.md` is the OpenClaw operator skill draft.
- `tools/stage7_rewrite/db2_weapons/contracts/s232d_no_cookie_provider_anchor.contract.json` is a future no-cookie/provider-anchor worker contract. It is not executable.
- `reports/DB2_OPEN_SOURCE_ASSEMBLY_CONCURRENCY_DEDUPE_REPORT_20260601.md` is the current synthesis for Docker tool assembly, concurrency, write ceiling, dedupe, and existing-data scheduling.

## Boundaries

- Live DB stays on WSL ext4: `/home/pc/swarm_data/atlas_swarm_data.sqlite`.
- The Atlas underground-map database is the only upstream product; this DB2 stack is a consumer worker-runtime lane that supplies external-link/evidence capability for Atlas.
- `readonly` profile mounts `/db2-data` read-only.
- Worker containers mount `/db2-data` read-only and write JSONL events to `/db2-spool`; only `db2-writer` is intended to mount DB2 read-write.
- Hash-first sidecar cache defaults to `/home/pc/swarm_data/cache/db2_sidecar_cache.sqlite` and is mounted as `/db2-cache`; it stores URL/avatar/path/source-processed hashes and metadata only.
- Direct worker write paths are migrated one worker at a time. Execute mode rejects workers that are not marked spool-ready instead of silently falling back to direct SQLite writes.
- OpenClaw skills are control-plane contracts only. Crawlers, incremental update logic, adapters, and open-source weapons stay in repo/worktree code and Docker/container worker/runtime layers.
- New collector ideas, including S232D-style no-cookie/provider-anchor collection, must first become explicit worker contracts with input format, dedupe hashes, output spool/report schema, sidecar-cache effects, stop gates, tests, and runbook evidence. Do not run them from the skill body.
- Cookie directories are not mounted by default.
- SearXNG is not present in any DB2 profile.
- Light and browser worker containers default to dry-run profile output unless the operator explicitly uses an execution wrapper.
- The full-stack template's agent containers are not enabled in v1 because no stable local agent images are registered for this DB2 lane yet.
- BrowserAct is registered as an external browser/extraction weapon candidate only. It is available on Windows and WSL as `browser-act` and may be used for bounded, no-cookie, report-only rendered extraction after loading `browser-act get-skills core --skill-version 2.0.2`. Its upstream API-key solution catalog is not installed into active DB2 execution. Do not create BrowserAct browsers, import profiles/cookies, call account actions, or write DB2 from BrowserAct without a separate worker contract and gate.
- Tencent Map Skills are registered as geocode/POI/route/map-visualization weapon candidates only. Active Codex skills: `tencentmap-lbs-skill`, `tencent-lbs-webservice`, and `tencentmap-jsapi-gl-skill`; helper command: `tmap-webservice-signed` for WebService keys that require SK/SN signatures. They may produce bounded report-only location evidence and map visualizations, but must not write DB2/Atlas without a worker contract, hash-first dedupe, output schema, source timestamp, coordinate-system note, and promotion gate. Never write Tencent Map Key/SK values into docs, logs, memory, reports, or DB rows.

## Profiles

```powershell
python tools\stage7_rewrite\scripts\db2_weapons_compose.py readonly-probe
python tools\stage7_rewrite\scripts\db2_weapons_compose.py browser-up
python tools\stage7_rewrite\scripts\db2_weapons_compose.py writer-up
python tools\stage7_rewrite\scripts\db2_weapons_compose.py safe-up
python tools\stage7_rewrite\scripts\db2_weapons_compose.py steady-up
python tools\stage7_rewrite\scripts\db2_weapons_compose.py experimental-smoke
python tools\stage7_rewrite\scripts\db2_weapons_compose.py experimental-bc-smoke
python tools\stage7_rewrite\scripts\db2_weapons_compose.py experimental-ra-smoke
python tools\stage7_rewrite\scripts\db2_weapons_compose.py experimental-nuclear-smoke
```

Generated commands use:

```text
docker compose -f tools/stage7_rewrite/db2_weapons/compose.yaml
```

## Future Worker Contracts

Future collectors are defined as contracts before execution code is exposed to OpenClaw:

```powershell
python tools\stage7_rewrite\scripts\db2ctl.py contracts list
python tools\stage7_rewrite\scripts\db2ctl.py contracts show s232d_no_cookie_provider_anchor
python tools\stage7_rewrite\scripts\db2ctl.py contracts verify-all
```

The S232D no-cookie/provider-anchor contract is read-only and not executable. It defines input hashes, output/report schema, sidecar effects, stop gates, and cookie/token prohibitions. `contracts verify-all` is the read-only aggregate gate for OpenClaw; it must report `passed=true`, `read_only=true`, `would_write=false`, `live_run_allowed=false`, and `production_commands_exposed=false`. Do not add a production command for S232D until a Docker worker, schedule gate, and writer boundary are implemented and tested.

Run from WSL when accessing `/home/pc/swarm_data`. Inside WSL, DB2 Compose must resolve to `/usr/bin/docker`; `/home/pc/.local/bin/docker` is a Windows `docker.exe` wrapper and must not be used for DB2 live mounts because it can turn WSL ext4 bind mounts into empty overlay directories.

```bash
/usr/bin/docker compose -f tools/stage7_rewrite/db2_weapons/compose.yaml --profile readonly run --rm db2-reconcile
```

`db2_weapons_compose.py` automatically prefers `/usr/bin/docker` when it is running under WSL. Live `db2ctl` commands such as `status`, `preflight`, `cache`, `writer`, `schedule`, and `health` must also run inside WSL when using the default `/home/pc/swarm_data/...` paths. Windows PowerShell may print policy/Compose commands, but direct live DB2 commands fail fast on Windows default WSL paths to avoid false empty-state reads.

## Read-only first

Start with `readonly`:

```bash
/usr/bin/docker compose -f tools/stage7_rewrite/db2_weapons/compose.yaml --profile readonly run --rm db2-reconcile
```

Then run S125 from inside the image or host:

```bash
python tools/stage7_rewrite/scripts/build_db2_outlink_lineage_reconcile_s125.py \
  --live-db /home/pc/swarm_data/atlas_swarm_data.sqlite \
  --output-dir tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_20260601
```

## Worker execution

`db2-light-workers` and `db2-browser-tools` intentionally print dry-run plans by default. Do not add `--execute` until a human has reviewed preflight and stop gates.

When a migrated one-shot worker is explicitly executed, the runner waits for the worker process to finish by default and prints `worker_start`, `worker_finish`, and a final returncode summary. Use `--detach` only for an explicitly reviewed long-running background run; a started PID is not completion evidence.
Use `--limit N` on worker-specific `db2ctl up` commands for the first production canaries. This overrides the adapter's built-in default limit inside the container runner.
Before any worker canary, run `db2ctl compose mount-doctor`. It must return `passed=true` and prove the worker container can see the WSL ext4 live DB, `/db2-scripts/avatar_dl_worker.py`, `/db2-scripts/outlink_expand_worker.py`, the spool directory, and the sidecar cache. If Docker Desktop WSL integration is off, these mounts can appear as empty overlay directories; do not start workers in that state.

`db2-writer` also defaults to validation mode. It only writes to SQLite when `DB2_WRITER_EXECUTE=1` or `--execute` is explicitly used.

Worker-specific one-shot commands are preferred while migration is in progress:

```powershell
python tools\stage7_rewrite\scripts\db2ctl.py policy
python tools\stage7_rewrite\scripts\db2ctl.py existing-data
python tools\stage7_rewrite\scripts\db2ctl.py schedule --profile safe
python tools\stage7_rewrite\scripts\db2ctl.py schedule --profile safe --only-worker outlink_expand_linktree
python tools\stage7_rewrite\scripts\db2ctl.py schedule --profile safe --only-worker outlink_expand_shorturl
python tools\stage7_rewrite\scripts\db2ctl.py schedule --profile safe --only-worker avatar_dl
python tools\stage7_rewrite\scripts\db2ctl.py compose mount-doctor
python tools\stage7_rewrite\scripts\db2ctl.py recovery stale-running-plan
python tools\stage7_rewrite\scripts\db2ctl.py recovery stale-running-reset --snapshot-path SNAPSHOT
python tools\stage7_rewrite\scripts\db2ctl.py up safe --worker outlink_expand_linktree
python tools\stage7_rewrite\scripts\db2ctl.py up safe --worker outlink_expand_shorturl
python tools\stage7_rewrite\scripts\db2ctl.py up safe --worker avatar_dl
python tools\stage7_rewrite\scripts\db2ctl.py up safe --worker avatar_dl --limit 10
```

Those commands route the legacy WSL `outlink_expand_worker.py` through `db2_outlink_expand_spool_adapter.py`: SELECTs stay read-only against DB2 and INSERT/REPLACE calls become JSONL spool events for `db2-writer`.
The `avatar_dl` command routes `avatar_dl_worker.py` through `db2_avatar_spool_adapter.py`: DB2 reads stay read-only, avatar files write to `/home/pc/swarm_data/output/avatars`, `avatar_cache` skips already-seen avatar URLs before download/file IO, and `insert_avatar` events are written to `dj_avatars` only by `db2-writer`.

For production chunks, prefer the first-class wrapper instead of hand-splicing Docker commands:

```bash
python3 tools/stage7_rewrite/scripts/db2ctl.py production cycle --max-batches 2 --execute
python3 tools/stage7_rewrite/scripts/db2ctl.py production avatar-batch --limit 2000 --execute
python3 tools/stage7_rewrite/scripts/db2ctl.py production worker-batch --worker outlink_expand_linktree --limit 1000 --execute
python3 tools/stage7_rewrite/scripts/db2ctl.py production worker-batch --worker outlink_expand_shorturl --limit 500 --execute
```

The production wrapper runs schedule, rogue legacy worker detection, writer backlog, cache status, mount-doctor, the worker, `db2-writer once --execute`, cache seed, live health, lock-holder probe, and before/after DB counts as one structured unit. Allowed v1 production workers are only `avatar_dl`, `outlink_expand_linktree`, and `outlink_expand_shorturl`. The default worker timeout is `7200` seconds; do not wrap it in a shorter outer OpenClaw/Codex timeout. Runtime logs are redacted on disk for raw URLs, credential-like lines, and D-drive paths, while in-memory JSON extraction remains unredacted.
Every production wrapper run writes a redacted `summary.json` under its report directory. For outlink workers, the wrapper also extracts the final adapter payload and upserts hash-only source completions into the sidecar cache after the worker and writer finish.

For unattended OpenClaw operation, prefer `db2ctl production cycle` over manually sequencing multiple production commands. The cycle runs the same gates, selects only migrated one-shot workers, calls the existing production wrappers, and writes a top-level `summary.json` before and after every batch so a dropped parent process leaves recoverable evidence. Default cycle behavior is:

- Linktree tail first, based on `selected_after_source_processed_skip`.
- Avatar throughput second, based on `selected_after_pre_crawl_skip`.
- Shorturl skipped by default. Pass `--include-shorturl` only after a recent schedule shows new redirect-shortener work, and still skip when `selected_after_source_processed_skip=0`.

Current iteration-020 handoff boundary: do not start another production cycle from this thread. S232D no-cookie/provider-anchor remains a future contract only; inspect it with `db2ctl contracts list/show`, but do not invent worker, `production`, or `up` commands for it. The next controller-approved execute gate, if any, should be a separate tiny avatar attempt-cache validation, preferably `avatar-limit 20` or lower.

`db2ctl health`, `db2ctl schedule`, and `db2ctl production` block if they see direct legacy `/home/pc/scripts/*_worker.py` processes such as `bc_deep_worker.py` running outside the Docker/writer boundary. Stop or migrate those processes before production; they are not acceptable concurrent workers for this lane.

`db2-writer` uses the shared lock file `/home/pc/swarm_data/.db_write.lock`. `db2ctl writer once --execute` also verifies this lock path when no incoming spool is pending; this creates/opens the lock file but does not write DB rows.

## Sidecar cache

Use the cache commands before longer worker runs to reduce repeated fetch/browser work without touching live DB2:

```powershell
python tools\stage7_rewrite\scripts\db2ctl.py cache status
python tools\stage7_rewrite\scripts\db2ctl.py cache seed --limit 1000
```

`cache seed` is dry-run by default and prints only counts plus hashes. `cache seed --execute` writes only the sidecar SQLite cache and still requires human confirmation; it never writes `/home/pc/swarm_data/atlas_swarm_data.sqlite`.

Current live sidecar state after iteration 019:

```text
cache_exists=true
url_seen=33265
avatars=6569
short_urls=592
source_processed=3091
stores_raw_urls=false
stores_raw_local_paths=false
```

The migrated `outlink_expand` adapter uses the cache before expensive work:

- `source_processed_cache` skips already-processed `linktree_expand` and `shorturl_resolve` sources before `fetch_linktree_page` or `resolve_short_url`.
- `url_seen_cache` skips already-known output URLs before writing a JSONL spool event.
- `db2_shorturl_candidates.py` selects redirect shorteners by exact/subdomain host matching, not legacy substrings; link-in-bio landing domains are audited separately and are not resolved by the shorturl worker.
- Duplicate-only, no-link, source-cache-hit, and unresolved shorturl sources are upserted into `source_processed_cache` as hash-only source completions, so the next schedule can skip them before network work.

The migrated `avatar_dl` adapter uses the cache before expensive avatar file work:

- `avatar_cache` skips already-seen avatar URL hashes before legacy `download_file`.
- `avatar_cache` also skips duplicate `insert_avatar` spool events if a legacy path reaches `record_swarm_avatar`.
- The adapter now selects distinct `(eid, platform)` rows before work; legacy profile-row limits can contain many duplicate EIDs.
- The schedule report exposes `legacy_limited_rows`, `legacy_limited_distinct_eids`, `duplicate_rows_in_legacy_limit`, `selected_local_file_hits`, `selected_source_processed_hits`, and `selected_after_pre_crawl_skip`.
- Adapter output can emit hash-only `avatar_dl:<platform>` source completions for attempted profiles. `db2ctl production` can upsert them into the sidecar cache, but this path still needs a tiny live validation gate after iteration 019.
- Cache lookup is read-only; a missing cache file disables lookup without changing worker write boundaries.

## Scheduling gate

Use the schedule report before starting workers:

```powershell
python tools\stage7_rewrite\scripts\db2ctl.py schedule --profile safe
```

The report is read-only JSON. It combines S126 preflight, existing-data/dedupe coverage, sidecar cache status, dry-run cache seed counts, writer backlog, and worker spool-readiness. Long-running production must remain on hold if it reports `hold_production`; worker-specific one-shot commands are the only acceptable path while full profiles still include non-spool-migrated workers.

Use `db2ctl policy` when an agent needs a machine-readable allowlist/denylist. It lists allowed read-only commands, one-shot allowed workers, denied commands, storage boundaries, and schedule templates.

Before a worker-specific one-shot command, run the matching worker-specific schedule gate:

```powershell
python tools\stage7_rewrite\scripts\db2ctl.py schedule --profile safe --only-worker avatar_dl
```

This evaluates only the selected migrated worker path. It does not make the full `safe` profile executable and does not start a worker.

If the schedule report blocks on stale running rows, inspect the read-only recovery plan:

```powershell
python tools\stage7_rewrite\scripts\db2ctl.py recovery stale-running-plan
```

This prints affected row counts, stale/fresh grouping, and reset SQL for review. It does not execute the reset and keeps `would_write=false`.

If a reset is still required, use the reviewed execute gate only after creating a snapshot and after lock holders are clear:

```powershell
python tools\stage7_rewrite\scripts\db2ctl.py snapshot NAME --execute
python tools\stage7_rewrite\scripts\db2ctl.py health --lock-holders
python tools\stage7_rewrite\scripts\db2ctl.py recovery stale-running-reset --snapshot-path /home/pc/swarm_data/dev_snapshots/db2_NAME.sqlite
python tools\stage7_rewrite\scripts\db2ctl.py recovery stale-running-reset --execute --snapshot-path /home/pc/swarm_data/dev_snapshots/db2_NAME.sqlite --confirm reset-stale-running
```

The execute form requires snapshot integrity `ok`, `active_worker_count=0`, `fresh_running_count=0`, no lock holders, and the exact confirmation string. Never blindly reset stale `running` rows without snapshot proof.

Iteration 013 already reset the prior 76 stale rows under this gate. Iteration 015 proved production `avatar_dl` at bounded limits `10/50/200/500` through `/usr/bin/docker`, the spool adapter, and `db2-writer once --execute`; post-run `dj_avatars=5728`, `spool_backlog=0`, and `holder_signal=false`.

Iteration 016 added `db2ctl production` wrappers and ran migrated production batches:

```text
avatar_dl --limit 1000:
  downloaded=845 skipped=155 avatar_seen_hits=63 writer_events=107

outlink_expand_linktree --limit 500:
  writer processed_files=421 processed_events=2130 insert_outlink=1709 insert_progress=421

outlink_expand_shorturl --limit 500:
  processed=500 resolved=0 new_outlinks=0 writer_events=0
```

Post-run live state: `dj_outlinks=37880`, `dj_avatars=5835`, `url_seen_cache=30926`, `avatar_cache=5197`, `source_processed_cache=2259`, `spool_backlog=0`, `holder_signal=false`, and `/home/pc/swarm_data/.db_write.lock` exists. Current `db2ctl schedule --profile safe --only-worker avatar_dl --limit 2000`, `outlink_expand_linktree --limit 500`, and `outlink_expand_shorturl --limit 500` are ready after operator review, while full `safe` still holds because non-spool-migrated workers remain in that profile.

Iteration 017 added the rogue legacy worker gate and ran larger migrated production strides:

```text
avatar_dl --limit 5000:
  writer processed_files=14 processed_events=655 dj_avatars=6490 soundcloud_avatars=4636

outlink_expand_linktree --limit 1000:
  writer processed_files=707 processed_events=3253 insert_outlink=2546 insert_progress=707 dj_outlinks=40277
  follow-up required because a rogue /home/pc/scripts/bc_deep_worker.py loop held live SQLite/WAL
  the rogue loop was terminated and health returned to holder_signal=false

outlink_expand_linktree --limit 1500:
  writer processed_files=214 processed_events=260 insert_outlink=46 insert_progress=214 dj_outlinks=40323
  rogue_legacy_workers=0 holder_signal=false lock_retries=0 spool_backlog=0
```

Post-run live state: `dj_outlinks=40323`, `dj_avatars=6490`, `url_seen_cache=33265`, `avatar_cache=5852`, `source_processed_cache=2750`, `spool_backlog=0`, `holder_signal=false`, `rogue_legacy_workers=0`, and `/home/pc/swarm_data/.db_write.lock` exists. Current `db2ctl schedule --profile safe --only-worker outlink_expand_linktree --limit 2000` and `avatar_dl --limit 5000` are ready after operator review, while full `safe` still holds because non-spool-migrated workers remain in that profile.

Iteration 018 added redacted production summary persistence and source-completion dedupe:

```text
avatar_dl --limit 5000:
  writer processed_files=15 processed_events=717 insert_avatar=717 dj_avatars=7207 soundcloud_avatars=5353

outlink_expand_linktree --limit 2000:
  writer processed_files=201 processed_events=201 insert_outlink=0
  source_completion_count=297 duplicate_only=158 no_links=139 source_processed_cache=3046
  post-schedule selected_after_source_processed_skip=17

outlink_expand_shorturl --limit 100:
  candidate_selector=host_redirect_only processed=48 resolved=0 new_outlinks=0
  false_positive_total=767 beatport.com=618
  source_completion_count=46 source_processed_cache=3091
  post-schedule selected_after_source_processed_skip=0
```

Post-run live state: `dj_outlinks=40323`, `dj_avatars=7207`, `soundcloud_avatars=5353`, `url_seen_cache=33265`, `avatar_cache=6569`, `shorturl_cache=592`, `source_processed_cache=3091`, `spool_backlog=0`, `holder_signal=false`, and `rogue_legacy_workers=0`. Do not spend more shorturl budget while `selected_after_source_processed_skip=0`.

Before starting a production one-shot worker, verify the runner wait/log semantics with a dry-run or mocked test. Migrated worker execution now blocks until completion and preserves logs by default instead of returning immediately from a detached `Popen`.
Also verify `db2ctl compose mount-doctor` before a production canary. Iteration 014 found Docker Desktop/WSL bind mounts resolving to empty container overlay directories. Iteration 015 repaired the working route by starting Docker Desktop's Ubuntu user-distro proxy and routing DB2 Compose through `/usr/bin/docker`; mount doctor now must pass before every production chunk.

`safe` currently resolves to the conservative worker set:

```text
marathon, swarm_monitor, linktree, outlink_expand_linktree,
outlink_expand_shorturl, sc_deep, yt_deep, domestic, avatar_dl
```

`steady` adds `maigret`. `experimental` starts empty unless an explicit worker is passed. `bc_deep`, `ra_deep`, and `nuclear_fission` are experimental-only.

Current spool-ready workers:

```text
outlink_expand
outlink_expand_linktree
outlink_expand_shorturl
avatar_dl
```

Current non-migrated workers are still visible in dry-run plans, but `DB2_WORKER_EXECUTE=1` with `DB2_WRITE_MODE=spool` fails fast for them with `not_spool_migrated`.
