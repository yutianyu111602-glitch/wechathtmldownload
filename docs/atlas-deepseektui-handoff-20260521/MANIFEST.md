# Atlas DeepSeekTUI Handoff Packet 20260521

Generated: 2026-05-21 17:52 CST

Purpose: Give DeepSeekTUI a self-contained, bounded takeover packet for the Atlas graph subsequent-search longrun worker lane.

Lifecycle update, 2026-05-23: this packet is historical handoff/reference evidence only. Its file list, ownership model, quality boundaries, and command shapes remain useful, but its `RUNNING` public-search snapshot, PID `108336`, Post-Filter blocker, worker sequencing, and copy-paste prompt are stale. Current authority is `C:\code\githubstar\wechathtmldownload\docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` plus `C:\code\githubstar\wechathtmldownload\reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md`: public-search is `COMPLETE`, full Post-Filter is complete, the reduced review queue is `27`, Layer D is dry-run/report-only, and graph-entry flags remain blocked until human acceptance plus separate staged-promotion authorization.

## Packet Files

- `MANIFEST.md` — this index.
- `DEEPSEEKTUI_PROMPT.md` — copy-paste prompt for DeepSeekTUI.
- `RUNBOOK.md` — exact monitor and next-gate commands.
- `QUALITY_GATE.md` — current quality judgment, WARN state, and promotion boundaries.
- `INDEX.html` — browser-friendly packet overview.

## OpenHuman Import

- imported: yes
- source_id: `wechathtmldownload/atlas/deepseektui-handoff-packet-20260521-final`
- chunk_ids:
  - `bb5be1209b05942801c37d72e336ef8c`
  - `fac682f530081084aeb933a808730d10`

## Canonical Existing Files

Read these first after this packet:

- `C:\code\githubstar\wechathtmldownload\NEXT_AGENT_HANDOFF_ATLAS_GRAPH_SUPERLONGRUN_20260521.md`
- `C:\code\githubstar\wechathtmldownload\NEXT_AGENT_HANDOFF_ATLAS_GRAPH_SUPERLONGRUN_20260521.html`
- `C:\code\githubstar\wechathtmldownload\reports\ATLAS_SOCIAL_SEARCH_MAIGRET_OPENCLI_CAMOFOX_SCHEME_RESEARCH_20260521.md`
- `C:\code\githubstar\wechathtmldownload\docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md`
- `C:\code\githubstar\wechathtmldownload\docs\DOCUMENTATION_INDEX.md`
- `C:\code\githubstar\wechathtmldownload\docs\current-runtime.md`

## Latest Checked Runtime Snapshot

Source:

`C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json`

Latest checked at `2026-05-21T17:52:37+08:00`:

- status: `RUNNING`
- pid: `108336`
- pid alive: `true`
- progress: `62.4134%`
- processed: `153,552 / 246,024`
- remaining: `92,472`
- slices: `307`
- stderr bytes: `0`
- process priority: `Idle`
- affinity: `0xF0000000`

## Ownership Model

- Codex remains foreman: SSOT, gates, code changes, docs, quality review, and final judgment.
- DeepSeekTUI should act as worker: monitor the longrun, avoid restarts, run only the next report-only gate when the unblock condition is satisfied, and write artifacts to declared report dirs.

## Current Quality Judgment

`WARN, can continue`.

The warning is delivery shape, not content quality:

- Core handoff/report/SSOT files are local and several are Git-untracked.
- They are indexed and usable on this machine.
- If transfer must rely on Git, explicitly package or commit task-scoped files after verification.

## Hard Blocker

Do not run full Post-Filter until:

- `status == COMPLETE`
- `processed_review_rows == queue_entity_keys`
- stderr is empty or understood
- accepted graph edges remain empty

## Hard Red Lines

DeepSeekTUI must not:

- restart the active public-search while PID `108336` is alive
- run Maigret over raw `246,024` rows
- write graph/vector/SQLite/Neo4j/Qdrant/mem0/agentmemory state
- deploy CloudRun or upload/review a mini-program
- export, print, persist, copy, or inspect cookie/token values
- read browser credential stores
- mutate accounts
- scan `D:\` root
- use or probe 9router
