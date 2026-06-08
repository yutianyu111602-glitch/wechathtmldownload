$statusPath='D:\rawwechat_md\markitdown-batch-status.json'
$raw=Get-Content $statusPath -Raw -Encoding UTF8
$j=$raw|ConvertFrom-Json

# Find the stale running item and change to queued
$repaired=$false
foreach($item in $j.items){
  if($item.status -eq 'running'){
    $item.status='queued'
    $item.phase='queued'
    $item.message='Reset from stale running state by week-run US-002'
    $item.startedAt=''
    $item.endedAt=''
    $j.runningCount=0
    $j.queuedCount=($j.items|Where-Object {$_.status -eq 'queued'}|Measure-Object).Count
    $repaired=$true
    break
  }
}

if(-not $repaired){
  "ERROR: no stale running item found"
  exit 1
}

# Recompute completedCount and progressRatio
$j.completedCount=$j.succeededCount+$j.failedCount+$j.skippedCount
$j.progressRatio=if($j.totalItems -gt 0){[math]::Round($j.completedCount/$j.totalItems,4)}else{1}
$j.status='running'
$j.endedAt=''

# Write back
$jsonText=$j|ConvertTo-Json -Depth 5
[System.IO.File]::WriteAllText($statusPath, $jsonText, [System.Text.UTF8Encoding]::new($false))

# Verify parse
$verify=Get-Content $statusPath -Raw -Encoding UTF8|ConvertFrom-Json
"REPAIRED OK"
"status=$($verify.status)"
"total=$($verify.totalItems)"
"queued=$($verify.queuedCount)"
"running=$($verify.runningCount)"
"succeeded=$($verify.succeededCount)"
"completed=$($verify.completedCount)"
"progress=$($verify.progressRatio)"
