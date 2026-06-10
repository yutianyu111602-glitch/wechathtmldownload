# Step-by-step merge_map pipeline — adapted for cross_db_identity 20260608
$ErrorActionPreference = "Stop"
$repo = "C:\code\githubstar\wechathtmldownload"
Set-Location $repo
$outDir = "$repo\tools\stage7_rewrite\reports\atlas_core_merge_map_20260608"
$dataset = "atlas_core_merge_map_20260608"
$mergeMap = "$outDir\merge_map.json"

Remove-Item -Recurse -Force $outDir -ErrorAction SilentlyContinue

$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()

function Step($name, $script) {
    $start = Get-Date
    Write-Host ""
    Write-Host "=== [$($stopwatch.Elapsed.ToString('mm\:ss'))] $name ===" -ForegroundColor Cyan
    try {
        & $script
        $elapsed = (Get-Date) - $start
        Write-Host "[OK] $name ($($elapsed.TotalSeconds.ToString('0.0'))s)" -ForegroundColor Green
    } catch {
        Write-Host "[FAIL] $name : $_" -ForegroundColor Red
        throw
    }
}

Write-Host "========================================" -ForegroundColor Magenta
Write-Host " Atlas Core + merge_map (20260608)" -ForegroundColor Magenta
Write-Host " Merge: 1700 DB2→DB3 + 16927 existing remaps" -ForegroundColor Magenta
Write-Host " Start: $(Get-Date -Format 'HH:mm:ss')" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta

Step "1/4 Build core DB + merge_map" {
    python -u tools\stage7_rewrite\scripts\build_atlas_core_candidate.py `
        --out-dir tools\stage7_rewrite\reports\atlas_core_merge_map_20260608 `
        --dataset-id atlas_core_merge_map_20260608 `
        --merge-map tools\stage7_rewrite\reports\atlas_core_merge_map_20260608\merge_map.json 2>&1
}

Write-Host ""
Write-Host "--- Core DB readback ---" -ForegroundColor Yellow
python -c @"
import sqlite3
db = sqlite3.connect(r'$outDir\atlas_core.sqlite')
for t in ['core_entity','entity_legacy_id','core_event','entity_event_edge','entity_relation_edge','external_link_evidence','identity_resolution_case']:
    n = db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'  {t}: {n:,}')
db.close()
"@

Step "2/4 Export serving SQLite" {
    python -u tools\stage7_rewrite\scripts\export_atlas_core_to_serving_sqlite.py `
        --core-db tools\stage7_rewrite\reports\atlas_core_merge_map_20260608\atlas_core.sqlite `
        --out tools\stage7_rewrite\reports\atlas_core_merge_map_20260608\atlas_serving.sqlite 2>&1
}

Step "3/4 Export miniapp SQLite" {
    python -u tools\stage7_rewrite\scripts\export_atlas_core_to_miniapp_sqlite.py `
        --core-db tools\stage7_rewrite\reports\atlas_core_merge_map_20260608\atlas_core.sqlite `
        --out tools\stage7_rewrite\reports\atlas_core_merge_map_20260608\atlas_miniapp.sqlite 2>&1
}

Step "4/4 Export miniapp index" {
    python -u tools\stage7_rewrite\scripts\export_atlas_core_to_miniapp_index.py `
        --miniapp-db tools\stage7_rewrite\reports\atlas_core_merge_map_20260608\atlas_miniapp.sqlite `
        --out tools\stage7_rewrite\reports\atlas_core_merge_map_20260608\atlas_index.json.gz 2>&1
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Magenta
Write-Host " DONE  Total: $($stopwatch.Elapsed.ToString('mm\:ss'))" -ForegroundColor Magenta
Write-Host "========================================" -ForegroundColor Magenta

# Final readback
Write-Host ""
Write-Host "--- Final output ---" -ForegroundColor Yellow
Get-ChildItem $outDir | ForEach-Object {
    $sz = "{0:N1} MB" -f ($_.Length / 1MB)
    Write-Host "  $($_.Name) ($sz)" -ForegroundColor Green
}
Write-Host ""

# Quick count comparison
Write-Host "--- Count comparison (merge_map vs no-merge) ---" -ForegroundColor Yellow
$mergeCore = "$outDir\atlas_core.sqlite"
$noMergeCore = "$repo\tools\stage7_rewrite\reports\atlas_core_candidate_20260605_legacy_rank_org_fix\atlas_core.sqlite"
python -c @"
import sqlite3
tables = ['core_entity','entity_legacy_id','core_event']
for t in tables:
    mc = sqlite3.connect(r'$mergeCore')
    nc = sqlite3.connect(r'$noMergeCore')
    mn = mc.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    nn = nc.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    diff = mn - nn
    print(f'  {t}: merge={mn:,} no-merge={nn:,} diff={diff:+d} ({100*diff/nn:.1f}%)' if nn else f'  {t}: merge={mn} no-merge={nn}')
    mc.close(); nc.close()
"@
