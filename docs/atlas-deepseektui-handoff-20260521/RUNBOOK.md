# Atlas DeepSeekTUI Runbook

Generated: 2026-05-21 17:52 CST

Lifecycle update, 2026-05-23: this runbook is historical/reference evidence, not current execution authorization. Its monitor, throttle, and Post-Filter commands describe the 2026-05-21 handoff shape. Before using any command, re-anchor on `..\ATLAS_SOCIAL_SEARCH_RULES_SSOT_20260521.md` and `..\..\reports\ATLAS_PUBLIC_SEARCH_COMPLETION_AND_POST_FILTER_CLOSEOUT_20260522.md`; public-search and full Post-Filter are already complete, Layer D remains dry-run/report-only, and graph-entry is still blocked until human acceptance plus separate staged-promotion authorization.

## 1. Monitor Current Run

Run from PowerShell:

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
  priority = if ($p) { $p.PriorityClass } else { $null }
  affinity = if ($p) { '0x{0:X}' -f $p.ProcessorAffinity.ToInt64() } else { $null }
  stderr_bytes = (Get-Item -LiteralPath $stderrPath).Length
} | Format-List
```

## 2. Reapply Desktop-Friendly Throttle If Needed

Use only if the process is alive and the desktop is laggy:

```powershell
$pid = 108336
$p = Get-Process -Id $pid -ErrorAction SilentlyContinue
if ($p) {
  $p.PriorityClass = 'Idle'
  $p.ProcessorAffinity = [IntPtr]0xF0000000
}
```

Do not kill or restart the run unless a separate incident review proves it is dead.

## 3. Full Post-Filter Command

Run only after:

- `status == COMPLETE`
- `processed_review_rows == queue_entity_keys`
- stderr is empty or understood

```powershell
cd C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite

python scripts\build_atlas_entity_public_search_post_filter_queue.py `
  --review-jsonl reports\atlas_entity_public_search_138102_20260521\entity_public_search_review.jsonl `
  --evidence-jsonl reports\atlas_entity_public_search_138102_20260521\entity_public_search_evidence.jsonl `
  --rules config\atlas_entity_public_search_post_filter_rules.json `
  --out-dir reports\atlas_entity_public_search_post_filter_full_20260521 `
  --min-post-filter-score 35 `
  --review-score 45 `
  --emit-quarantine `
  --confirm-full-run COMPLETE
```

## 4. Verify Post-Filter

After running, inspect:

```powershell
Get-Content -LiteralPath 'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\atlas_entity_public_search_post_filter_full_20260521\entity_public_search_post_filter_summary.json' -Raw
```

Do not proceed to Maigret/OpenCLI/Camofox until the summary is reviewed and reduced queue sizes are known.

## 5. Maigret Later, Not Now

When a reduced handle-seed candidate file exists, Maigret must use the active service port:

```powershell
cd C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite

python scripts\run_maigret_http_canary.py `
  --base-url http://127.0.0.1:15051 `
  --candidates <reduced-maigret-candidates.jsonl> `
  --out-dir reports\<maigret-run-dir> `
  --limit <bounded-limit> `
  --top-sites 30
```

Do not run this against raw public-search rows.

## 6. Social Outlink Expansion Later

Run only against reduced review queues:

```powershell
cd C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite

python scripts\expand_atlas_social_profile_outlinks.py `
  --review-queue reports\<post-filter-dir>\entity_public_search_review_queue.jsonl `
  --out-dir reports\<social-outlink-dir> `
  --fetch-mode http `
  --timeout-sec 12 `
  --sleep-sec 0.2 `
  --follow-aggregators `
  --max-aggregator-pages 100
```

Current limitation: this script has no `opencli` or `camofox` fetch mode yet.
