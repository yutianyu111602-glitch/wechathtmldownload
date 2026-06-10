$key = [System.Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', 'User')
if (-not $key) {
    Write-Error "DEEPSEEK_API_KEY not found in User environment variables"
    exit 1
}
$env:DEEPSEEK_API_KEY = $key
Set-Location C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\stage7_deepseek_flash_pilot.py `
    --mode run `
    --limit 1000 `
    --concurrency 4 `
    --out-dir tools\stage7_rewrite\reports `
    --output-root-name deepseek_flash_expand1000_20260509 `
    --manifest-jsonl tools\stage7_rewrite\reports\win_NEXT1000_SUPERRUN.jsonl `
    --max-tokens 384
