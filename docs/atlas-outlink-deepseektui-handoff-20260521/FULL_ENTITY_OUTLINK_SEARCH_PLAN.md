# Atlas 全量实体外链搜索 DeepSeekTUI 执行计划

Generated: 2026-05-21 20:41 CST

Scope: **中国地下电子音乐图鉴 / Atlas 数据库实体外链搜索**。本计划只交给 DeepSeekTUI 执行外链与社交主页二跳证据搜索；不交给它做图谱写入、向量写入、生产 SQLite 写入、CloudRun 部署、小程序上传、LLM 裁决或账号凭据操作。

## 2026-05-22 lifecycle / current-authority boundary

Classification: `historical-or-evidence` / `reference` / `verify-before-use`.

This file is a 2026-05-21 DeepSeekTUI handoff plan. It remains useful for red lines, report-only batch reporting, reduced-queue-only execution rules, and stability policy. It is not the current runtime authority for Atlas social search or graph entry.

Current authority is `C:\code\githubstar\wechathtmldownload\docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` plus `C:\code\githubstar\wechathtmldownload\reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md`.

Verified current state from the 2026-05-22 closeout:

- public-search is `COMPLETE`;
- full Post-Filter completed at `2026-05-22T10:36:47+08:00`;
- reduced review queue is `27`, filtered candidates are `349`, and quarantine rows are `245,653`;
- reduced Layer D dry-run selected `20 / 27` report-only rows;
- `accepted_for_graph`, `identity_proof`, and `graph_write_allowed` remain blocked until human acceptance and separate staged-promotion authorization.

Treat older statements in this file as snapshot or strategy evidence, especially `RUNNING` PID `108336`, `178,052 / 246,024`, `Post-Filter reduced queue (~890 entities)`, the hourly automation `2a6ada79-6e21-49df-8212-0bc111181591`, and the avatar download path `D:\DJ_DATA`. Do not restart public-search, Post-Filter, OpenCLI, Maigret, Camofox, Scrapling, browser, LLM/model, vector, graph, SQLite, mem0/agentmemory, CloudRun, mini-program, provider, GitHub sync, or D-drive work from this file.

## 1. DeepSeekTUI 的一句话任务

等待全量 public-search 完成，然后从完整 Post-Filter 的缩减队列开始，稳定、分批、report-only 地抽取 Atlas 实体的外部主页、社交主页和二跳外链证据，并把所有结果停在 review/adjudication 队列，直到人类明确验收。

## 2. 已整合的依据

DeepSeekTUI 不需要重新猜路线。当前计划已经合并这些文件的口径：

1. `C:\code\githubstar\wechathtmldownload\docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md`
2. `C:\code\githubstar\wechathtmldownload\docs\current-runtime.md`
3. `C:\code\githubstar\wechathtmldownload\docs\DOCUMENTATION_INDEX.md`
4. `C:\code\githubstar\wechathtmldownload\docs\superpowers\plans\2026-05-21-atlas-full-production-final-goals.md`
5. `C:\code\githubstar\wechathtmldownload\reports\ATLAS_SUBSEQUENT_SEARCH_DEEP_RESEARCH_20260521.md`
6. `C:\code\githubstar\wechathtmldownload\reports\ATLAS_SOCIAL_SEARCH_MAIGRET_OPENCLI_CAMOFOX_SCHEME_RESEARCH_20260521.md`
7. `C:\code\githubstar\wechathtmldownload\reports\ATLAS_ENTITY_PUBLIC_SEARCH_POST_FILTER_PLAN_20260521.md`
8. `C:\code\githubstar\wechathtmldownload\reports\ATLAS_ENTITY_PUBLIC_SEARCH_POST_FILTER_IMPLEMENTATION_20260521.md`
9. `C:\code\githubstar\wechathtmldownload\reports\ATLAS_LAYER_D_CONTENT_EVIDENCE_IMPLEMENTATION_20260521.md`
10. `C:\code\githubstar\wechathtmldownload\reports\ATLAS_PREFIX_POST_FILTER_EXPERIMENT_20260521.md`
11. `C:\code\githubstar\wechathtmldownload\reports\ATLAS_NEXT_GATE_RESILIENCE_TEST_20260521.md`
12. `C:\code\githubstar\wechathtmldownload\reports\ATLAS_OPEN_SOURCE_TOOLCHAIN_REFRESH_20260521.md`
13. `C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\MANIFEST.md`
14. `C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\RUNBOOK.md`
15. `C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\QUALITY_GATE.md`
16. `C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\LONGRUN_STABILITY_PLAN.md`

## 3. 当前运行快照

Source:

`C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json`

Latest checked at `2026-05-21T20:41:14+08:00`:

- status: `RUNNING`
- pid: `108336`
- pid alive: `true`
- processed: `178,052 / 246,024`
- remaining: `67,972`
- progress: `72.3718%`
- slices completed: `356`
- stderr bytes: `0`

This is a moving snapshot. DeepSeekTUI must recheck before any action.

## 4. 不可违反的红线

- Do not restart public-search while PID `108336` is alive.
- Do not run Post-Filter until `status == COMPLETE` and `processed_review_rows == queue_entity_keys`.
- Do not run Maigret, OpenCLI, Camofox, Scrapling, or outlink expansion over raw `246,024` public-search rows.
- Do not set `accepted_for_graph`, `identity_proof`, or `graph_write_allowed` to true.
- Do not write Neo4j, Qdrant, production SQLite, mem0, agentmemory, or any production graph/vector store.
- Do not deploy CloudRun, upload mini-program, submit review, touch CloudBase billing, or work on weekly mini-program.
- Do not call LLM/model APIs in this lane.
- Do not export, print, persist, copy, or inspect cookie/token values.
- Do not read browser credential stores.
- Do not mutate accounts or capture private/follower-only pages.
- Do not scan `D:\` root or use local `9router`.
- Do not use destructive Git commands.

Browser-session rule: OpenCLI/Camofox may use existing browser session state only to render bounded public profile/outlink pages. They are page-reading tools, not cookie/token tools.

## 5. Decision Tree

### Gate A: public-search still RUNNING

If status is `RUNNING`, do only this:

1. Report `generated_at`, `status`, `pid`, `pid_alive`, `processed_review_rows`, `queue_entity_keys`, `progress_pct`, `slices_completed`, `remaining_review_rows`, and `stderr_bytes`.
2. Do not start Post-Filter.
3. Do not start any external tool.
4. Sleep or hand back status.

### Gate B: public-search COMPLETE

Proceed only when:

- `status == COMPLETE`
- `processed_review_rows == queue_entity_keys`
- stderr is empty or every stderr line is explained as non-fatal
- accepted graph outputs are still empty

Then run the full report-only Post-Filter. Use the canonical reduced output directory:

`C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521`

### Gate C: full Post-Filter validates

The Post-Filter must produce these lanes:

- `entity_public_search_review_queue.jsonl`
- `entity_public_search_filtered_candidates.jsonl`
- quarantine output
- summary JSON

Quality requirements:

- thresholds stay `--min-post-filter-score 35 --review-score 45`
- known noisy names such as `TAG`, `house`, `DADA`, `CISCO`, `Watermelon`, `All`, `GAS`, `Disco` do not enter strict review queue
- all rows remain report-only

### Gate D: outlink extraction starts from reduced queue only

First tool is HTTP outlink expansion:

```powershell
cd C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite

python scripts\expand_atlas_social_profile_outlinks.py `
  --review-queue reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_review_queue.jsonl `
  --out-dir reports\atlas_social_profile_outlinks_full_http_20260521 `
  --fetch-mode http `
  --timeout-sec 12 `
  --sleep-sec 0.3 `
  --follow-aggregators `
  --max-aggregator-pages 300
```

For desktop stability, prefer batches first:

```powershell
python scripts\expand_atlas_social_profile_outlinks.py `
  --review-queue reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_review_queue.jsonl `
  --out-dir reports\atlas_social_profile_outlinks_batch001_http_20260521 `
  --fetch-mode http `
  --limit 500 `
  --timeout-sec 12 `
  --sleep-sec 0.5 `
  --follow-aggregators `
  --max-aggregator-pages 80
```

Expected outputs:

- `atlas_social_profile_fetches.jsonl`
- `atlas_social_profile_outlinks.jsonl`
- `atlas_social_outlink_followup_queue.jsonl`
- `atlas_social_profile_outlink_errors.jsonl`
- `atlas_social_profile_outlinks_summary.json`

### Gate E: Layer D content evidence

Use Scrapling only after Post-Filter, and only for reduced rows where normal HTTP evidence is weak:

```powershell
python scripts\fetch_atlas_entity_public_search_content_evidence.py `
  --review-queue reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_review_queue.jsonl `
  --out-dir reports\atlas_public_search_content_evidence_scrapling_reduced_20260521 `
  --fetch-mode scrapling-get `
  --scrapling-bin C:\Users\pc\bin\scrapling.cmd `
  --limit 500 `
  --timeout-sec 20 `
  --sleep-sec 0.5
```

HTTP 403, 429, captcha, and empty content are not negative identity evidence. They become fallback/error rows.

### Gate F: OpenCLI / Camofox

Current fact: OpenCLI exists for rendered profile metadata, but the script input shape is older PRD-16 style. Camofox is healthy, but there is no generic Atlas reduced-queue adapter.

DeepSeekTUI must not scale OpenCLI/Camofox until there is either:

- an adapter that consumes the reduced Post-Filter queue, or
- an explicit bounded manual sample task.

Allowed behavior:

- public profile render/read only
- no cookie/token export
- no credential-store read
- no account mutation
- report-only output

### Gate G: Maigret

Maigret is handle discovery only. It is not outlink proof and not identity proof.

Run Maigret only after reduced handle candidates exist:

```powershell
python scripts\run_maigret_http_canary.py `
  --base-url http://127.0.0.1:15051 `
  --candidates <reduced-maigret-candidates.jsonl> `
  --out-dir reports\<maigret-run-dir> `
  --limit 500 `
  --top-sites 30
```

Do not use the stale historical `5050` port unless a new health check proves it is active.

## 6. Batch Policy

- Default batch size: `500` rows.
- Start with one batch, inspect summary/errors, then continue.
- Use `Idle` priority if possible.
- Sleep between network calls.
- Prefer error queues over retries.
- Retry only bounded transient failures.
- Do not increase parallelism if the desktop is laggy.
- Write a batch status JSON or Markdown summary after every batch.

## 7. Success Definition

A successful DeepSeekTUI batch must report:

- input queue path
- output directory
- batch number or range
- rows read
- rows fetched
- outlinks found
- high-value profile/social/music outlinks found
- aggregator pages followed
- errors by type
- skipped rows by reason
- fallback-needed rows
- `accepted_for_graph=false`
- `identity_proof=false`
- `graph_write_allowed=false`

This is not success:

- raw Maigret hit count alone
- raw URL count alone
- snippet-only evidence
- OpenCLI page title only
- a report that says "done" without paths/counts/errors
- any graph/vector/DB write

## 8. DeepSeekTUI Copy-Paste Prompt

```text
You are taking over ONLY the Atlas database entity external outlink / social-profile second-hop evidence search lane.

Workspace:
C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite

Read first:
1. C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\FULL_ENTITY_OUTLINK_SEARCH_PLAN.md
2. C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\MANIFEST.md
3. C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\RUNBOOK.md
4. C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\LONGRUN_STABILITY_PLAN.md
5. C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\QUALITY_GATE.md
6. C:\code\githubstar\wechathtmldownload\docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md
7. C:\code\githubstar\wechathtmldownload\reports\ATLAS_SOCIAL_SEARCH_MAIGRET_OPENCLI_CAMOFOX_SCHEME_RESEARCH_20260521.md

First action:
Recheck C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json and stderr.

If status is RUNNING, report status only and stop.
If status is COMPLETE and processed_review_rows equals queue_entity_keys, run the report-only full Post-Filter if missing.
After full Post-Filter, work only from the reduced review queue.
Never run any tool over raw 246,024 rows.
Keep all graph-write flags false.
Do not call LLM/model APIs.
Do not write Neo4j/Qdrant/production SQLite/mem0/agentmemory.
Do not export or inspect cookies/tokens.
Do not deploy or upload anything.
```

## 9. Final Report Template

DeepSeekTUI should finish every batch with this shape:

```markdown
# Atlas Outlink Search Batch Report

Generated:
Batch:
Input:
Output:

## Gate
- public_search_status:
- post_filter_status:
- graph_write_allowed: false

## Counts
- rows_read:
- fetches_attempted:
- fetches_ok:
- outlinks_found:
- high_value_outlinks:
- errors:
- fallback_needed:

## Artifacts
- summary:
- fetches:
- outlinks:
- followup_queue:
- errors:

## Safety
- accepted_for_graph=false
- identity_proof=false
- graph_write_allowed=false
- no_cookie_token_export=true
- no_account_mutation=true
- no_model_call=true
- no_graph_vector_db_write=true

## Next
- next_batch:
- blockers:
- recommended_fallback:
```

## 10. Multi-Strategy Deep Research (Added 2026-05-21 21:25)

After quality audit revealed 87.6% of evidence rows have score 0 and 94.1% are `weak_or_unmatched`,
a multi-strategy approach is needed. Detailed design: `MULTI_STRATEGY_DEEP_RESEARCH_PLAN.md`.

### Strategy Layers

```
Post-Filter reduced queue (~890 entities)
│
├─[L1] Maigret Username Discovery   batch 50  │ Docker :15051
│   → 600+ sites → Instagram/SC/BC/MC/RA/YT usernames
│
├─[L2] Instagram Login Search + Bio  batch 20  │ OpenCLI ejk3c3qe
│   → Search entity name → match profile → extract bio outlinks
│
├─[L3] Fixed-Site Direct Search     batch 100 │ HTTP + Scrapling
│   → RA/SoundCloud/Bandcamp/Mixcloud/YouTube direct search
│
├─[L4] Camofox Verification          batch 50  │ Camofox :9377
│   → Only for HTTP 403/429/captcha blocked pages
│
└─[L5] Outlink Expansion             batch 500 │ HTTP+OpenCLI+Camofox
    → Instagram bio → Linktree → SC/BC/MC/RA/YT second-hop
```

### Execution Environment

| Component | Location | Access |
|-----------|----------|--------|
| Python scripts | WSL /mnt/c/... | python3 |
| Maigret | Docker (Windows) | HTTP 127.0.0.1:15051 |
| OpenCLI | Windows npm global | cmd.exe /c opencli |
| Camofox | Windows service | HTTP 127.0.0.1:9377 |
| Scrapling | Windows venv | C:\Users\pc\bin\scrapling.cmd |

## 11. Atlas Cross-Validation (Added 2026-05-21 21:28)

Script: `scripts/cross_validate_atlas_outlinks.py`

Cross-references Post-Filter entities against:
- Atlas alias export: 53,276 rows (canonical_name → alias mapping)
- Atlas identity_review_items: 155 existing social profile URLs
- Atlas entities SQLite: 1,510,787 entities

### Strategy Routing

| Strategy | Condition | Primary Method |
|----------|-----------|---------------|
| `direct_outlink_expansion` | Has Atlas social URLs | HTTP outlink |
| `instagram_maigret_priority` | Atlas alias match + high mentions | HTTP outlink + OpenCLI |
| `fixed_site_search` | Alias match, low mentions | Fixed-site HTTP |
| `maigret_first` | No Atlas match | Maigret discovery |

### Priority Scoring

- entity_type: artist/person/band=10, label=9, venue=7, concept=2
- Atlas mentions ≥10 + no social URLs: +10 (high-value gap)
- Post-Filter score ≥60: +5

### Test Result (prefix50k, 192 entities)

- `instagram_maigret_priority`: 106 (55%)
- `maigret_first`: 76 (40%)
- `fixed_site_search`: 10 (5%)
- Top entities: Nigls (531 mentions), Lucy (657), Jaya (378)

## 12. Adaptive Orchestration (Added 2026-05-21 21:47)

Script: `scripts/adaptive_outlink_orchestrator.py`

### Auto-Adaptive Behavior

1. Groups entities by `recommended_strategy`
2. Routes to appropriate primary methods
3. Tracks `quality_score` = (results + high_value×3) / entities_processed
4. Compares methods → recommends best for scaling
5. Failed entities → automatic fallback routing
6. Generates `adaptive_orchestration_report.json` with actionable recommendations

### Recommendation Types

- `[SCALE]`: quality_score > 0.5 → scale this method
- `[KEEP]`: quality_score > 0 → continue, try alternatives in parallel
- `[DEPRIORITIZE]`: quality_score = 0 → try other methods first
- `[FALLBACK]`: method failed → use fallback for affected entities
- `[SKIP]`: script missing or candidates missing

## 13. Avatar Download (Added 2026-05-21 21:50)

Script: `scripts/download_atlas_profile_avatars.py`

After social profiles are confirmed, downloads avatars to D: drive.

### Flow

```
Confirmed profile (priority ≥ 15)
  → Extract og:image / twitter:image / image_src from profile page
  → Download avatar (10MB max, 15s timeout)
  → SHA256 hash → deduplicate
  → Store file: D:\DJ_DATA\avatars/{sha[:2]}/{sha256}.{ext}
  → Store metadata: D:\DJ_DATA\databases\atlas_avatars.sqlite
```

### Database Schema

```sql
CREATE TABLE avatars (
    id INTEGER PRIMARY KEY,
    entity_search_id TEXT, entity_name TEXT, entity_type TEXT,
    platform TEXT, profile_url TEXT, avatar_url TEXT,
    file_path TEXT, file_size_bytes INTEGER, sha256 TEXT,
    width INTEGER, height INTEGER, content_type TEXT,
    downloaded_at TEXT, source_tool TEXT,
    cross_validation_priority INTEGER, atlas_mention_count INTEGER,
    accepted_for_graph INTEGER DEFAULT 0,
    graph_write_allowed INTEGER DEFAULT 0
);
```

### Supported Platforms

Instagram, SoundCloud, Bandcamp, Mixcloud, Resident Advisor, YouTube, Linktree, Bilibili, Spotify, Beatport.

### Policy

- Different avatars from different platforms are ALL downloaded
- SHA256 dedup prevents duplicate storage
- Each unique image stored once, linked to multiple entities if shared

## 14. Automation Pipeline (Added 2026-05-21 21:48)

Automation ID: `2a6ada79-6e21-49df-8212-0bc111181591`
Schedule: HOURLY (every 60 min)
Status: active

### Pipeline Steps

```
Step 1: Gate Check (supervisor.py)
  ├─ RUNNING → report + mem0 + stop
  ├─ COMPLETE_READY → Step 2
  └─ COMPLETE_POST_FILTER_DONE → Step 3.5

Step 2: Post-Filter (35/45 thresholds)
  → review_queue + filtered_candidates + quarantine

Step 3: Atlas Cross-Validation
  → 53k aliases + 155 URLs → strategy routing

Step 3.5: Adaptive Orchestration
  → multi-method parallel + quality scoring

Step 4: Scale Best Method
  → HTTP outlink or Maigret at scale

Step 4c: Avatar Download
  → confirmed profiles → D:\DJ_DATA\avatars\ + SQLite

Step 5: Summary Report
  → all paths, counts, errors, quality scores
```

### Monitoring

```bash
# Manual check
python3 /home/pc/scripts/atlas_outlink_supervisor.py

# Log
tail /home/pc/scripts/atlas_outlink_supervisor_log.jsonl

# Automation status
# (check automation_list in DeepSeekTUI)
```

### All Scripts Created/Used

| Script | Purpose | Status |
|--------|---------|--------|
| `atlas_outlink_supervisor.py` | Gate monitoring + ETA | Active |
| `cross_validate_atlas_outlinks.py` | Atlas alias/URL matching | Tested |
| `adaptive_outlink_orchestrator.py` | Multi-method + quality routing | Tested |
| `download_atlas_profile_avatars.py` | Avatar download to D: drive | Tested (DB init) |
| `expand_atlas_social_profile_outlinks.py` | HTTP outlink expansion | Existing |
| `run_maigret_http_canary.py` | Maigret username discovery | Existing |
| `build_atlas_entity_public_search_post_filter_queue.py` | Post-Filter | Existing |
| `opencli_social_profile_evidence.py` | OpenCLI profile reading | Existing |
