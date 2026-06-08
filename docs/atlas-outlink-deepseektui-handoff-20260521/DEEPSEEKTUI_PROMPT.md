# DeepSeekTUI Prompt: Atlas External Outlink Search Only

> Lifecycle status, verified 2026-05-23 01:18 +08:00: `historical-or-evidence` / `reference` / `verify-before-use`.
>
> This file is a 2026-05-21 DeepSeekTUI prompt template for the Atlas external outlink / social-profile second-hop evidence lane. It is not current runtime authority and must not be copied as an executable handoff without first re-anchoring on `docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` and `reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md`.
>
> Current checked authority supersedes the live snapshot inside the prompt body: public-search is `COMPLETE`, processed `246,024 / 246,024`, full Post-Filter generated at `2026-05-22T10:36:47+08:00`, reduced review queue is `27`, filtered candidates `349`, quarantine `245,653`, and Layer D is dry-run only over `20 / 27` rows with `accepted_for_graph=0`. The prompt's `RUNNING`, PID `108336`, `178,052 / 246,024`, "wait for full public-search COMPLETE", and "run full Post-Filter if missing" wording is historical snapshot context only.
>
> Lifecycle refresh, verified 2026-05-23 18:42 +08:00: the latest T6 sidecar output is now `reports\ATLAS_T6_OUTLINK_AVATAR_CANDIDATE_PACKET_20260523.md`, generated from the current 27-row reduced review queue. That packet produced report-only candidate evidence (`292` outlink rows, `291` high-value follow-up rows) and kept `accepted_for_graph=0`, `identity_proof promotion=0`, and `graph_write_allowed=0`. This 2026-05-21 prompt is therefore a historical prompt-shape reference, not the next T6 resume cursor.
>
> Using OpenCLI/Camofox/Scrapling/Maigret/outlink extraction still requires a current bounded authorization and current tool/session checks. Graph/vector/database writes, CloudRun, mini-program operations, provider probes, browser-secret reads, D-drive scans, and auth-file creation remain out of scope for this documentation truth-sync.

Historical prompt body below. Do not copy it into DeepSeekTUI as-is; re-anchor on the current T6 authority and the 2026-05-23 candidate packet first.

```text
You are taking over ONLY the Atlas graph external outlink / social-profile second-hop evidence search lane.

This is not a whole-project takeover.
This is not weekly mini-program work.
This is not graph/vector/database promotion.

Workspace:
C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite

Read first:
1. C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\FULL_ENTITY_OUTLINK_SEARCH_PLAN.md
2. C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\MANIFEST.md
3. C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\RUNBOOK.md
4. C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\LONGRUN_STABILITY_PLAN.md
5. C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\QUALITY_GATE.md
6. C:\code\githubstar\wechathtmldownload\reports\ATLAS_SOCIAL_SEARCH_MAIGRET_OPENCLI_CAMOFOX_SCHEME_RESEARCH_20260521.md
7. C:\code\githubstar\wechathtmldownload\docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md
8. C:\code\githubstar\wechathtmldownload\docs\current-runtime.md

Your goal:
Long-running, stable, report-only extraction of external profile/outlink evidence for Atlas entities, using the optimized route below.

Optimized route:
1. Wait for full public-search COMPLETE.
2. Ensure full Post-Filter exists. If it does not exist and the public-search complete gate is satisfied, run only the full report-only Post-Filter command from RUNBOOK.md.
3. Work only from reduced Post-Filter review queues, never raw public-search rows.
4. Extract profile/outlink evidence with this priority:
   a. HTTP mode first via expand_atlas_social_profile_outlinks.py.
   b. Scrapling for static pages where HTTP needs stronger extraction.
   c. OpenCLI browser-session reads for rendered public profiles and public profile anchors.
   d. Camofox only as fallback for anti-bot / render-needed public pages.
5. Follow high-value second-hop outlinks only: Linktree, Instagram profile links, SoundCloud, Mixcloud, Bandcamp, RA, YouTube, event pages, mixtapes, label/artist homepages.
6. Emit report-only artifacts and status summaries after every batch.
7. Stop at strict review/adjudication outputs. Do not write graph/vector/database state.

Current checked gate snapshot before this handoff:
status RUNNING
generated_at 2026-05-21T20:41:14+08:00
PID 108336 alive
progress 72.3718%
processed 178,052 / 246,024
remaining 67,972
slices 356
stderr bytes 0

You must recheck status before acting.

Status file:
C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json

Stderr file:
C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_stderr.log

Hard red lines:
- Do not restart public-search while PID 108336 is alive.
- Do not run Maigret, OpenCLI, Camofox, Scrapling, or outlink expansion over raw 246,024 public-search rows.
- Do not write Neo4j, Qdrant, SQLite production state, mem0, agentmemory, or any graph/vector store.
- Do not deploy CloudRun.
- Do not upload or review any mini-program.
- Do not export, print, persist, copy, or inspect cookie/token values.
- Do not read browser credential stores.
- Do not mutate accounts.
- Do not capture private/follower-only pages.
- Do not scan D:\ root.
- Do not use 9router.
- Do not run destructive Git commands.

Browser-session rule:
OpenCLI/Camofox may use existing browser session state only to read bounded public profile/outlink pages. They are page-reading tools, not cookie/token tools.

Long-run stability rules:
- Use small batches.
- Write a batch status JSON after each batch.
- Keep process priority Idle if possible.
- Sleep between network calls.
- Retry only bounded transient failures.
- Save failed rows to an error queue, do not spin forever.
- Do not increase parallelism when the desktop is laggy.
- Treat HTTP 403/429/captcha as fallback candidates or errors, not proof.

When public-search is still RUNNING:
Report status only and wait. Do not start new extraction.

When public-search is COMPLETE:
Verify counts and stderr. Then run full report-only Post-Filter if missing. After Post-Filter, inspect queue sizes and begin external outlink extraction in bounded batches.

When you finish a batch:
Report paths, counts, error count, skipped count, high-value outlink count, and confirm all graph-write flags remain false.
```
