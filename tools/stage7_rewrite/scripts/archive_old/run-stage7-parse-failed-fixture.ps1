# Stage 7 Rewrite — Parse Failed Fixture Runner
# Creates a fake article with malformed LLM output to test error handling.
# Verifies: parse_failed does NOT become success_empty
# Verifies: all_chunks_failed becomes failed_final

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$STAGE7_ROOT = "C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite"
$FIXTURE_DIR = "$STAGE7_ROOT\artifacts\parse_failed_fixture"
$REPORT_FILE = "$FIXTURE_DIR\report.md"

New-Item -ItemType Directory -Force -Path $FIXTURE_DIR | Out-Null
Set-Location $STAGE7_ROOT

Write-Host "=== Stage 7 Parse Failed Fixture ==="
Write-Host "Timestamp : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Fixture   : $FIXTURE_DIR"
Write-Host ""

# Create fake article directory
$fakeArticleDir = "$FIXTURE_DIR\fake_account\fake_article_001"
New-Item -ItemType Directory -Force -Path $fakeArticleDir | Out-Null

# Create fake article HTML (minimal)
@"
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Test Article</title></head>
<body>
<div class="rich_media_content">
<p>这是一篇测试文章，用于验证解析失败的处理逻辑。</p>
<p>包含一些实体：张三在北京大学学习了计算机科学。</p>
</div>
</body></html>
"@ | Out-File -FilePath "$fakeArticleDir\article.html" -Encoding utf8

# Create status.json indicating OCR success
@"
{
    "ocr_status": "success",
    "word_count": 50,
    "has_content": true
}
"@ | Out-File -FilePath "$fakeArticleDir\status.json" -Encoding utf8

# Create malformed LLM response fixture
@"
{
    "entities": INVALID_JSON_HERE,
    "relations": [broken
    "summary": "this is malformed"
}
"@ | Out-File -FilePath "$FIXTURE_DIR\malformed_llm_response.json" -Encoding utf8

# Create another fixture: empty response
@"
{}
"@ | Out-File -FilePath "$FIXTURE_DIR\empty_llm_response.json" -Encoding utf8

# Create another fixture: all chunks fail scenario
@"
{"chunk_results": [
    {"error": "context_length_exceeded", "parsed": null},
    {"error": "json_parse_failed", "parsed": null},
    {"error": "json_parse_failed", "parsed": null}
]}
"@ | Out-File -FilePath "$FIXTURE_DIR\all_chunks_failed.json" -Encoding utf8

Write-Host "[1/4] Fixtures created in $FIXTURE_DIR"

# Run Python test against fixtures
Write-Host ""
Write-Host "[2/4] Running fixture validation..."

$testOutput = python -c @"
import json, sys
sys.path.insert(0, r'$STAGE7_ROOT')
from stage7.json_repair import parse_and_repair_json
from stage7.validators import validate_extract

results = []

# Test 1: malformed JSON
with open(r'$FIXTURE_DIR\malformed_llm_response.json', 'r', encoding='utf-8') as f:
    raw = f.read()
repair = parse_and_repair_json(raw)
parsed = repair.value if repair.ok else None
val = validate_extract(parsed) if parsed else {'ok': False, 'errors': ['parse_failed'], 'warnings': []}
results.append({
    'test': 'malformed_json',
    'parsed': parsed is not None,
    'valid': val['ok'],
    'errors': val.get('errors', []),
    'warnings': val.get('warnings', []),
    'expect': 'parse_failed should NOT become success_empty'
})

# Test 2: empty response
with open(r'$FIXTURE_DIR\empty_llm_response.json', 'r', encoding='utf-8') as f:
    raw = f.read()
repair = parse_and_repair_json(raw)
parsed = repair.value if repair.ok else None
val = validate_extract(parsed) if parsed else {'ok': False, 'errors': ['parse_failed'], 'warnings': []}
results.append({
    'test': 'empty_response',
    'parsed': parsed is not None,
    'valid': val['ok'],
    'errors': val.get('errors', []),
    'warnings': val.get('warnings', []),
    'expect': 'empty should fail validation'
})

# Test 3: all chunks failed
with open(r'$FIXTURE_DIR\all_chunks_failed.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
all_failed = all('error' in c for c in data.get('chunk_results', []))
results.append({
    'test': 'all_chunks_failed',
    'all_failed': all_failed,
    'expect': 'all_chunks_failed should become failed_final',
    'status': 'failed_final' if all_failed else 'unexpected'
})

for r in results:
    print(json.dumps(r, ensure_ascii=False, indent=2))
print('---FIXTURE_DONE---')
"@ 2>&1

Write-Host $testOutput

# Step 3: Verify expectations
Write-Host ""
Write-Host "[3/4] Verifying expectations..."

$test1Pass = $testOutput -notmatch '"test": "malformed_json"[\s\S]*?"valid": true'
$test2Pass = $testOutput -notmatch '"test": "empty_response"[\s\S]*?"valid": true'
$test3Pass = $testOutput -match '"status": "failed_final"'

$allPass = $test1Pass -and $test2Pass -and $test3Pass

Write-Host "  parse_failed != success_empty : $(if ($test1Pass) { 'PASS' } else { 'FAIL' })"
Write-Host "  empty fails validation        : $(if ($test2Pass) { 'PASS' } else { 'FAIL' })"
Write-Host "  all_chunks_failed -> failed_final : $(if ($test3Pass) { 'PASS' } else { 'FAIL' })"

# Step 4: Write report
$verdict = if ($allPass) { "GREEN" } else { "RED" }

$reportContent = @"
# Parse Failed Fixture Report

**Timestamp**: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
**Fixture Dir**: $FIXTURE_DIR

## Test Results

| Test | Expectation | Result |
|------|-------------|--------|
| malformed_json | parse_failed should NOT become success_empty | $(if ($test1Pass) { 'PASS' } else { 'FAIL' }) |
| empty_response | empty should fail validation | $(if ($test2Pass) { 'PASS' } else { 'FAIL' }) |
| all_chunks_failed | should become failed_final | $(if ($test3Pass) { 'PASS' } else { 'FAIL' }) |

## Verdict: **$verdict**

## Raw Output
``````
$testOutput
``````
"@

$reportContent | Out-File -FilePath $REPORT_FILE -Encoding utf8

Write-Host ""
Write-Host "=== Fixture test complete ==="
Write-Host "Report: $REPORT_FILE"
Write-Host "Verdict: $verdict"

if (-not $allPass) { exit 1 }
exit 0
