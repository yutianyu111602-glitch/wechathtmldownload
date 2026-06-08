# Atlas Outlink Search DeepSeekTUI Runbook

Generated: 2026-05-21 20:41 CST

Lifecycle status: `historical-or-evidence` / `reference` / `verify-before-use`.

Current authority: use `C:\code\githubstar\wechathtmldownload\docs\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` and `C:\code\githubstar\wechathtmldownload\reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md` before following any command here.

2026-05-23 verification note: this runbook is an older 2026-05-21 operational handoff. Its public-search recheck and full Post-Filter launch commands are no longer the current gate state. Current verified state is public-search `COMPLETE`, processed `246,024 / 246,024`, full Post-Filter generated at `2026-05-22T10:36:47+08:00`, reduced review queue `27`, filtered candidates `349`, quarantine `245,653`, and Layer D verified only as a report-only dry-run over `20 / 27` reduced rows. `accepted_for_graph`, `identity_proof`, and `graph_write_allowed` must remain blocked until human acceptance and separate staged-promotion authorization.

Do not run this file as a live procedure without re-authorizing the exact bounded step from current authority. In particular, do not restart public-search, rebuild full Post-Filter, fetch HTTP/Scrapling/OpenCLI/Maigret/Camofox evidence, use browser sessions, call LLM/model providers, write graph/vector/SQLite/memory lanes, deploy CloudRun, upload/review mini-program code, sync GitHub, scan D-drive roots, or create auth files from this historical runbook alone.

Canonical all-entity outlink plan:

`C:\code\githubstar\wechathtmldownload\docs\atlas-outlink-deepseektui-handoff-20260521\FULL_ENTITY_OUTLINK_SEARCH_PLAN.md`

Run from:

`C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite`

## 1. Recheck Public-Search Gate

```powershell
$statusPath = 'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_status.json'
$stderrPath = 'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_138102_20260521\entity_public_search_full_run_stderr.log'
$s = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json
$p = Get-Process -Id $s.pid -ErrorAction SilentlyContinue
[pscustomobject]@{
  generated_at = $s.generated_at
  status = $s.status
  progress_pct = $s.progress_pct
  processed_review_rows = $s.processed_review_rows
  queue_entity_keys = $s.queue_entity_keys
  remaining_review_rows = $s.remaining_review_rows
  slices_completed = $s.slices_completed
  pid = $s.pid
  pid_alive = [bool]$p
  stderr_bytes = (Get-Item -LiteralPath $stderrPath).Length
} | Format-List
```

If status is `RUNNING`, stop here and report only.

## 2. Full Post-Filter Prerequisite

Only if:

- `status == COMPLETE`
- `processed_review_rows == queue_entity_keys`
- stderr is empty or explained

Run:

```powershell
cd C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite

python scripts\build_atlas_entity_public_search_post_filter_queue.py `
  --review-jsonl reports\atlas_entity_public_search_138102_20260521\entity_public_search_review.jsonl `
  --evidence-jsonl reports\atlas_entity_public_search_138102_20260521\entity_public_search_evidence.jsonl `
  --rules config\atlas_entity_public_search_post_filter_rules.json `
  --out-dir reports\atlas_entity_public_search_post_filter_full_138102_20260521 `
  --min-post-filter-score 35 `
  --review-score 45 `
  --emit-quarantine `
  --confirm-full-run COMPLETE
```

Inspect:

```powershell
Get-Content -LiteralPath 'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_138102_20260521\entity_public_search_post_filter_summary.json' -Raw
```

## 3. HTTP Outlink Expansion First

Use only the reduced Post-Filter review queue:

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

Expected outputs:

- `atlas_social_profile_fetches.jsonl`
- `atlas_social_profile_outlinks.jsonl`
- `atlas_social_outlink_followup_queue.jsonl`
- `atlas_social_profile_outlink_errors.jsonl`
- `atlas_social_profile_outlinks_summary.json`

## 4. Batch Mode For Stability

If the full queue is large, run bounded batches:

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

After each batch, inspect the summary and errors before continuing.

## 5. Scrapling Content Evidence

Use Scrapling for reduced page-content rows where HTTP text is weak. This is Layer-D content evidence, not direct graph proof:

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

## 6. OpenCLI / Camofox Not Yet Generic

Current fact:

- OpenCLI generic profile reading exists, but the script still uses older input schema.
- Camofox is healthy, but there is no generic Atlas adapter for the reduced queue.
- DeepSeekTUI should not invent graph acceptance from these tools.

Allowed next work:

- implement or request a separate adapter if needed
- run only bounded public-page extraction
- do not export or inspect cookie/token values

## 7. Maigret Is Handle Discovery, Not Outlink Proof

Maigret belongs after reduced handle seeds. Use only if a reduced handle candidate file exists.

Use explicit port:

```powershell
python scripts\run_maigret_http_canary.py `
  --base-url http://127.0.0.1:15051 `
  --candidates <reduced-maigret-candidates.jsonl> `
  --out-dir reports\<maigret-run-dir> `
  --limit 500 `
  --top-sites 30
```

Do not treat Maigret output as identity proof.
