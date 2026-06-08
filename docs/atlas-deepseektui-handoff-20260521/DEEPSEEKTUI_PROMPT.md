# DeepSeekTUI Copy-Paste Prompt

Lifecycle update, 2026-05-23: do not copy this prompt as a current execution prompt without rewriting it from the current Atlas SSOT. It is historical command-shape evidence from 2026-05-21. Its `RUNNING` public-search status, PID `108336`, full Post-Filter blocker, and worker sequencing are stale; current authority is `..\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` plus `..\..\reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md`.

Copy the following prompt into DeepSeekTUI exactly. It is intentionally strict and bounded.

```text
You are taking over the Atlas graph subsequent-search longrun worker lane only.

Workspace:
C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite

Read first, in order:
1. C:\code\githubstar\wechathtmldownload\docs\atlas-deepseektui-handoff-20260521\MANIFEST.md
2. C:\code\githubstar\wechathtmldownload\docs\atlas-deepseektui-handoff-20260521\RUNBOOK.md
3. C:\code\githubstar\wechathtmldownload\docs\atlas-deepseektui-handoff-20260521\QUALITY_GATE.md
4. C:\code\githubstar\wechathtmldownload\NEXT_AGENT_HANDOFF_ATLAS_GRAPH_SUPERLONGRUN_20260521.md
5. C:\code\githubstar\wechathtmldownload\reports\ATLAS_SOCIAL_SEARCH_MAIGRET_OPENCLI_CAMOFOX_SCHEME_RESEARCH_20260521.md
6. C:\code\githubstar\wechathtmldownload\docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md
7. C:\code\githubstar\wechathtmldownload\docs\DOCUMENTATION_INDEX.md
8. C:\code\githubstar\wechathtmldownload\docs\current-runtime.md

Current task:
Monitor the active Atlas public-search longrun. Do not restart it while PID 108336 is alive. Do not run full Post-Filter until the status JSON proves the run is complete.

Status file:
C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json

Stderr file:
C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_stderr.log

Latest checked snapshot before handoff:
2026-05-21T17:52:37+08:00
status RUNNING
PID 108336 alive
progress 62.4134%
processed 153,552 / 246,024
remaining 92,472
slices 307
stderr bytes 0
process priority Idle
affinity 0xF0000000

Unblock condition:
Only when status == COMPLETE and processed_review_rows == queue_entity_keys, run full report-only Post-Filter with --confirm-full-run COMPLETE.

Correct route:
full public-search COMPLETE
-> full Post-Filter
-> reduced handle seeds
-> Maigret breadth discovery only on reduced handle seeds
-> HTTP/Scrapling/OpenCLI page evidence on reduced profile/page rows
-> Camofox only as anti-bot/render fallback
-> social outlink second-hop expansion
-> strict adjudication
-> eligible rows to later LLM/human gate
-> staged graph promotion only after explicit gate

Do not run Maigret over raw 246,024 rows. Maigret results are candidate_only_not_identity_proof, never identity proof.

Allowed browser-session shape:
OpenCLI/Camofox may read bounded public profile/outlink pages through existing browser session state when needed.

Forbidden browser/session actions:
Do not export, print, persist, copy, or inspect cookie/token values.
Do not read browser credential stores.
Do not mutate accounts.
Do not capture private/follower-only pages.

Hard red lines:
No graph/vector/SQLite/Neo4j/Qdrant/mem0/agentmemory writes.
No CloudRun deploy.
No mini-program upload or review.
No broad D:\ root scan.
No paid API.
No 9router probe or startup.
No destructive git cleanup/reset/checkout/clean.

Desktop friendliness:
Keep long worker processes at Idle priority where possible.
Use bounded batches and sleeps.
Write status after every batch.
If CPU or memory pressure hurts the desktop, pause or slow worker loops rather than increasing parallelism.

When status is still RUNNING:
Report generated_at, progress_pct, processed_review_rows, queue_entity_keys, remaining_review_rows, slices_completed, pid, PID alive, stderr bytes, and next check time. Do not do anything else.

When status is COMPLETE:
1. Verify count equality and stderr.
2. Run the full Post-Filter command in RUNBOOK.md.
3. Write a new report dir under tools\stage7_rewrite\reports.
4. Update docs\current-runtime.md and NEXT_AGENT_HANDOFF_ATLAS_GRAPH_SUPERLONGRUN_20260521.md with the result.
5. Do not proceed to Maigret/OpenCLI/Camofox until the Post-Filter summary is inspected and queue sizes are known.
```
