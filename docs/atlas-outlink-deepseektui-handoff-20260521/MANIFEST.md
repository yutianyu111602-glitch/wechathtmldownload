# Atlas Outlink Search DeepSeekTUI Handoff Packet 20260521

Generated: 2026-05-21 20:41 CST

Scope: **Only Atlas graph external outlink / social profile second-hop evidence search**.

This packet supersedes the broader DeepSeekTUI packet when the user says DeepSeekTUI should take over only "Atlas 图谱外链搜索". It is narrower by design.

## Lifecycle / Current Authority Note

Status: `historical-or-evidence` / `reference` / `verify-before-use`.

This manifest is a 2026-05-21 local handoff index for the narrow Atlas outlink / social-profile evidence packet. It remains useful for locating the packet files, script names, ownership boundaries, and OpenHuman import notes, but it is not current runtime authority by itself.

Current authority must be read from:

1. `C:\code\githubstar\wechathtmldownload\docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md`
2. `C:\code\githubstar\wechathtmldownload\reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md`
3. `C:\code\githubstar\wechathtmldownload\docs\current-runtime.md`

Verified current state as of the 2026-05-22 closeout: public-search is `COMPLETE`, processed `246,024 / 246,024`, `missing_unique_entity_search_ids=0`; full Post-Filter was generated at `2026-05-22T10:36:47+08:00` with reduced review queue `27`, filtered candidates `349`, and quarantine `245,653`; Layer D is dry-run only over `20 / 27` rows, and `accepted_for_graph`, `identity_proof`, and `graph_write_allowed` remain blocked until human acceptance and separate staged-promotion authorization.

Historical snapshot fields below, including the `RUNNING` PID/progress, hourly automation id, old read order, "canonical plan" wording, and D-drive avatar-download wording, are 2026-05-21 handoff context only. They do not authorize public-search, Post-Filter, browser, provider, Stage7, avatar download, D-drive, graph/vector/database, deployment, upload, or runtime work.

## Packet Files

### Plan Documents
- `MANIFEST.md` — this packet index (updated 2026-05-21 22:15; lifecycle note added 2026-05-23).
- `FULL_ENTITY_OUTLINK_SEARCH_PLAN.md` — historical plan including sections 10-14 (multi-strategy, cross-validation, adaptive, avatars, automation); current runtime gates are superseded by the authority files above.
- `MULTI_STRATEGY_DEEP_RESEARCH_PLAN.md` — detailed L1-L5 multi-strategy design.
- `CURRENT_RUNTIME_PLAN.md` — current runtime snapshot + resume instructions.
- `DEEPSEEKTUI_PROMPT.md` — copy-paste prompt for DeepSeekTUI.
- `RUNBOOK.md` — exact longrun commands and gates.
- `LONGRUN_STABILITY_PLAN.md` — stable unattended execution design.
- `QUALITY_GATE.md` — quality rules and acceptance boundaries.
- `INDEX.html` — browser-friendly overview.

### New Scripts (created 2026-05-21)

Path existence was rechecked during documentation reconciliation, but script existence is not execution authorization.

- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\cross_validate_atlas_outlinks.py` — Atlas alias/URL cross-validation
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\adaptive_outlink_orchestrator.py` — multi-method adaptive orchestrator
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\download_atlas_profile_avatars.py` — historical avatar-download helper; do not run or use D-drive targets from this manifest
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\test_search_strategy_variations.py` — 13-策略对比测试 (query formulation, platform priority, multi-pass)
- `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\monitor_outlink_quality.py` — 质量监控 + 趋势检测 + 策略调整建议
- `/home/pc/scripts/atlas_outlink_supervisor.py` — gate monitoring + ETA tracking

## Read First

DeepSeekTUI should read these in order:

1. `C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\MANIFEST.md`
2. `C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\FULL_ENTITY_OUTLINK_SEARCH_PLAN.md`
3. `C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\DEEPSEEKTUI_PROMPT.md`
4. `C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\RUNBOOK.md`
5. `C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\LONGRUN_STABILITY_PLAN.md`
6. `C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\QUALITY_GATE.md`
7. `C:\code\githubstar\wechathtmldownload\reports\ATLAS_SOCIAL_SEARCH_MAIGRET_OPENCLI_CAMOFOX_SCHEME_RESEARCH_20260521.md`
8. `C:\code\githubstar\wechathtmldownload\docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md`
9. `C:\code\githubstar\wechathtmldownload\docs\current-runtime.md`

## Latest Checked Gate Snapshot

Lifecycle note: this section is a historical 2026-05-21 snapshot. The current checked gate is the 2026-05-22 closeout listed above.

Source:

`C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json`

Latest checked at `2026-05-21T22:12:36+08:00`:

- status: `RUNNING`
- pid: `108336`
- pid alive: `true`
- progress: `77.66%`
- processed: `191,052 / 246,024`
- remaining: `54,972`
- slices: `382`
- stderr bytes: `0`
- ETA: ~6.0 hours (~2026-05-22 04:00 CST)

This is a moving snapshot. DeepSeekTUI must recheck before acting.

**Automation active**: ID `2a6ada79`, HOURLY, next check ~23:10 CST.

## Current Decision

The user's proposed direction is accepted with optimization:

```text
full public-search COMPLETE
-> full Post-Filter
-> reduced profile URL rows and handle seed rows only
-> HTTP first for outlink extraction
-> Scrapling for difficult static pages
-> OpenCLI browser-session reads for rendered public profiles
-> Camofox only as anti-bot / render fallback
-> Linktree / Instagram / SoundCloud / Mixcloud / RA / Bandcamp / YouTube second-hop expansion
-> strict review/adjudication
-> no graph write until later explicit human/gate acceptance
```

The critical correction is:

```text
Do not run Maigret or browser extraction over raw 246,024 rows.
```

## Ownership Boundary

DeepSeekTUI owns only:

- monitoring whether prerequisite public-search and Post-Filter are ready
- external profile/outlink evidence collection
- social second-hop expansion
- report-only queues and summaries
- stability logs and restart-safe status files

DeepSeekTUI does not own:

- whole Atlas graph production
- Neo4j/Qdrant/SQLite/mem0/agentmemory writes
- CloudRun or mini-program deployment
- weekly mini-program work
- FinAgent or other projects
- browser credential extraction

## Current Implementation Facts

Confirmed from current code/reports:

- `expand_atlas_social_profile_outlinks.py` exists and supports `dry-run` and `http` modes.
- It already does public HTTP second-hop extraction and token/openid sanitization.
- It does not yet support `opencli` or `camofox` fetch modes.
- `fetch_atlas_entity_public_search_content_evidence.py` supports `dry-run`, `http`, and `scrapling-get`.
- `opencli_social_profile_evidence.py` exists, but its input schema is older PRD-16 style, not direct full Post-Filter queue.
- Camofox service is healthy, but no generic Atlas Camofox evidence adapter exists yet.
- Maigret is only breadth discovery for reduced handle seeds and remains `candidate_only_not_identity_proof`.

## Transfer Status

This packet is local-file based and ready for same-machine DeepSeekTUI handoff.

If the handoff must travel through Git, these files still need task-scoped package/commit handling because the workspace contains many untracked files.

## OpenHuman Import Status

- previous 20:28 packet imported: yes
- 20:41 `FULL_ENTITY_OUTLINK_SEARCH_PLAN.md` re-imported: no
- source_id: `wechathtmldownload/atlas/outlink-deepseektui-handoff-20260521-source`
- chunk_ids:
  - `2acb4d2efd352a622ead3053985b7e7b`
  - `107817b8e46826158c06bb939d27a2d8`
- method: source build/run from `C:\code\openhuman`
- command shape: `rustup run stable cargo run --quiet --bin openhuman-core -- memory_tree ingest ...`
- note: there is currently no prebuilt `openhuman-core.exe` under the checked target paths; source compilation/run is the correct OpenHuman entry on this machine.
- note: use the local files as canonical for this 20:41 plan unless a later thread explicitly re-imports the updated packet.
