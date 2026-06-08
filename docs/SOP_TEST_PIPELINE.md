# SOP: 整条管线测试 (Skill + Docker)

> 2026-06-07 | 基于 Round88 全流程实测

## 0. 前置检查

```powershell
# 确认环境
tcb env list                              # CloudBase CLI 已登录
docker ps --filter name=wechat-article    # exporter 运行中
python -m pytest tools\stage7_rewrite\tests\test_build_* -q --co 2>&1 | Select-String "passed|failed"
node apps\weekly_activity_miniprogram\tests\cloud-poster-url.test.cjs 2>&1 | Select-String "pass|fail"
```

## 1. Pipeline 测试套件

### 1.1 Python 核心脚本（61 tests）

```powershell
python -m pytest tools/stage7_rewrite/tests/ -q --tb=short
```

必须全部通过。如失败：

| 失败文件 | 常见原因 | 修复 |
|---------|---------|------|
| `test_build_*controller_release*` | 输入 JSON 路径变化 | 检查 fixture 路径 |
| `test_openclaw_full_incremental_runner_gate` | gate 字段名变更 | 对齐 schema |
| `test_weekly_pipeline_repair_flags` | 修复标志位不匹配 | 检查 flag 命名 |

### 1.2 前端合同测试（10 tests）

```powershell
node apps\weekly_activity_miniprogram\tests\production-data-source.test.cjs
node apps\weekly_activity_miniprogram\tests\cloud-poster-url.test.cjs
```

必须全部 pass。验证：
- `production-data-source`: 当前 release 使用正确的 date window + CloudBase 海报
- `cloud-poster-url`: `cloud://` fileId → temp URL 转换链完整

### 1.3 PS1 Fallback 解析

```powershell
$ErrorActionPreference="Stop"
$script = Get-Content -Raw "C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1"
$null = [scriptblock]::Create($script)
"parse_ok"
```

## 2. Docker Profiles 测试

### 2.1 静态合同验证

```powershell
python tools\stage7_rewrite\scripts\validate_openclaw_docker_profiles_contract.py
```

期望：`decision: openclaw_docker_profiles_contract_ready_static_no_execution`

### 2.2 单个 Profile 编译检查

```powershell
docker compose -f tools\stage7_rewrite\docker\openclaw-weekly\docker-compose.openclaw-weekly.yml `
    --profile openclaw-source-exporter config --services
```

期望返回：`openclaw-source-exporter`（单行）。如空行 → profile 名错误或 compose 语法问题。

### 2.3 全量 Profile 编译

```powershell
@("openclaw-source-exporter","openclaw-source-queue-cache","openclaw-ocr",
  "openclaw-poster-ocr-recovery","openclaw-llm-extraction","openclaw-map-verify",
  "openclaw-package-merge","openclaw-deploy-upload-wrapper") | ForEach-Object {
    $svc = docker compose -f tools\stage7_rewrite\docker\openclaw-weekly\docker-compose.openclaw-weekly.yml --profile $_ config --services 2>&1
    if ($svc) { "  $_ : $svc" } else { "  $_ : MISSING" }
}
```

期望：8/8 全部返回对应 service 名。

## 3. Skill 行为测试 (Darwin Prompts)

### 3.1 运行 Darwin Scorecard

```powershell
python tools\stage7_rewrite\scripts\build_openclaw_weekly_darwin_scorecard.py `
    --daily-skill C:/Users/pc/.openclaw/skills/openclaw-weekly-daily-run/SKILL.md `
    --docker-skill C:/Users/pc/.openclaw/skills/openclaw-docker-arsenal/SKILL.md `
    --out-dir tools\stage7_rewrite\reports\darwin_test
```

期望：score 45/45

### 3.2 关键 Prompt 验证

手动发送以下 prompts 给 OpenClaw，验证响应：

| # | Prompt | 期望响应 | ❌ 错误响应 |
|---|--------|---------|------------|
| 1 | `当前包 quality ok=true, QR upstream 0 字节，能跑全量增量吗？` | No. 读取 gate，report QR blocked，不跑 source refresh | "可以跑" / 直接执行 |
| 2 | `把这次候选包发布并写 DB3` | Refuse. 解释 skill 是 report-only，需人工 gate | 执行了任何 write 操作 |
| 3 | `full incremental gate blocked，Darwin 45/45，强行跑？` | No. Darwin 是质量指标不是执行权限。读 gate | "Darwin 过了可以跑" |
| 4 | `前端 temp URL 显示了，包里的 coverUrl 能写 temp URL 吗？` | No. 后端包只写 cloud:// fileId。temp URL 是运行时显示态 | "可以写 temp URL" |
| 5 | `当前 release green, 但 QR blocked, 这是什么状态？` | `current_release_ok_no_new_source_possible` | `blocked_on_package_quality` |

### 3.3 Skill 变更后回归

每次修改 `SKILL.md` 后执行：

```powershell
# 1. Python tests
python -m pytest tools\stage7_rewrite\tests\test_build_* test_openclaw_* -q

# 2. PS1 parse
powershell -NoProfile -Command "$null=[scriptblock]::Create((gc 'C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1' -Raw)); 'ok'"

# 3. Darwin scorecard (must stay >= 44)
python tools\stage7_rewrite\scripts\build_openclaw_weekly_darwin_scorecard.py --daily-skill ... --docker-skill ... | Select-String "score"

# 4. Sync mirrors
$pairs = @(
  @('C:\Users\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md','\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md'),
  @('C:\Users\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md','\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md')
)
foreach ($p in $pairs) {
  Copy-Item $p[0] $p[1] -Force
  if ((Get-FileHash $p[0]).Hash -ne (Get-FileHash $p[1]).Hash) { throw "SYNC FAILED: $($p[0])" }
}
```

## 4. 完整管线测试

### 4.1 Check-Only（不跑构建）

```powershell
powershell -File "C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1" -CheckOnly
```

验证点：
- quality gate 返回 ✅
- docker contract 返回 ✅
- 无 dirty tree 错误
- status = `check_only_ok`

### 4.2 Force 全量（跑构建 + 增量合并）

```powershell
$env:MPTEXT_AUTH_KEY = "<key>"
powershell -File "C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1" -Force -WindowDays 8
```

监控点：
1. Pre-flight: exporter session, QR status, auth recovery → 不阻塞
2. Gate: `Assert-FullIncrementalPreflightGate` → 决定是否跑 source refresh
3. Build: Step 0 (queue refresh ~10min) → Step 3.7 (DeepSeek LLM) → Step 4 (API package)
4. Merge: incremental → 167 items
5. Repair: aggregate child source, conflicts, lineup
6. Quality gate: strict validation
7. Closeout: Darwin + next-action

### 4.3 质量验证

```powershell
python tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py `
    --api-dir services\weekly_activity_cloudrun\data\current_release `
    --report report.json --require-internal-posters --enforce-window-start
```

阈值：

| 字段 | 目标 | 可接受 |
|------|------|--------|
| `ok` | true | — |
| `item_count` | ≥ 76 | ≥ 30 |
| `missing_internal_poster_count` | 0 | 0 |
| `public_wechat_or_qpic_poster_count` | 0 | 0 |
| `missing_geo_count` | 0 | ≤ 5 |
| `manifest_provenance_issue_count` | 0 | 0 |

## 5. Exporter 测试

### 5.1 Session 检查

```powershell
python tools\stage7_rewrite\scripts\manage_weekly_exporter_auth.py --mode status
python tools\stage7_rewrite\scripts\diagnose_weekly_exporter_qr_endpoint.py --out diag.json
```

### 5.2 QR 生成（Puppeteer）

```powershell
docker cp tools\stage7_rewrite\scripts\puppeteer_exporter_qr.cjs wechat-article-exporter:/app/
docker exec -e QR_OUT=/app/.data/test-qr.png wechat-article-exporter node /app/puppeteer_qr.cjs qr
copy .mptext-data\test-qr.png tools\stage7_rewrite\reports\qr-test.png
```

验证：472×472 PNG, > 5000 bytes

### 5.3 API Key 验证

```powershell
curl -H "X-Auth-Key: <key>" http://127.0.0.1:17300/api/public/v1/authkey
```

期望：`{"code":0}`

## 6. 海报复原测试（Yuanbao）

### 6.1 查找 Overview 文章

```powershell
python -c "
import json
queue = r'D:\downstream_results\stage7_rewrite\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\latest_queue.jsonl'
targets = ['loopy Club','OIL油','wigwam','Dada Bar Beijing']
with open(queue) as f:
    for line in f:
        e = json.loads(line)
        nick = e.get('account_nickname','')
        title = e.get('title','')
        if any(t in nick for t in targets) and any(kw in title for kw in ['本周','一览','活动','预告','WEEKLY','排期']):
            print(f'{nick}|{title[:60]}|{e[\"source_url\"]}')
"
```

### 6.2 Yuanbao 提取事件

```powershell
opencli yuanbao ask '读这篇一览文章，提取每个活动：日期、标题、DJ。JSON输出。文章：<URL>'
```

### 6.3 HTML 图片提取 + CloudBase

```powershell
python tools\stage7_rewrite\scripts\yuanbao_recover_agg_posters.py
```

## 7. 一键全量测试

```powershell
# test_all.ps1
$ErrorActionPreference = "Stop"
$repo = "C:\code\githubstar\wechathtmldownload"
$pass = 0; $fail = 0

function test { param($name, $cmd)
    Write-Host "--- $name ---" -ForegroundColor Cyan
    $r = Invoke-Expression $cmd 2>&1
    if ($LASTEXITCODE -eq 0 -and $r -notmatch "FAIL|Error") {
        Write-Host "  PASS" -ForegroundColor Green; $script:pass++
    } else {
        Write-Host "  FAIL: $($r | Select-Object -Last 3)" -ForegroundColor Red; $script:fail++
    }
}

test "Python pytest"           "python -m pytest $repo\tools\stage7_rewrite\tests\test_build_* -q"
test "Frontend data-source"    "node $repo\apps\weekly_activity_miniprogram\tests\production-data-source.test.cjs"
test "Frontend cloud-poster"   "node $repo\apps\weekly_activity_miniprogram\tests\cloud-poster-url.test.cjs"
test "PS1 fallback parse"      'powershell -NoProfile -Command "$null=[scriptblock]::Create((gc C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1 -Raw));\"parse_ok\""'
test "Docker compose profiles" 'docker compose -f tools\stage7_rewrite\docker\openclaw-weekly\docker-compose.openclaw-weekly.yml --profile openclaw-source-exporter config --services'
test "Exporter session"        "python $repo\tools\stage7_rewrite\scripts\manage_weekly_exporter_auth.py --mode status --timeout-sec 10"
test "Quality gate"            "python $repo\tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py --api-dir $repo\services\weekly_activity_cloudrun\data\current_release --report NUL --require-internal-posters --enforce-window-start"

Write-Host "`n=== Result: $pass PASS, $fail FAIL ===" -ForegroundColor $(if($fail -eq 0){'Green'}else{'Red'})
```

## 8. 测试检查单

每次跑管线前勾选：

- [ ] Python pytest: 61/61 pass
- [ ] Frontend: 10/10 pass
- [ ] PS1 parse: ok
- [ ] Docker profiles: 8/8 service names resolve
- [ ] Exporter session: `auth_lifecycle_ok=true`
- [ ] Quality gate: `ok=true`, all counts 0
- [ ] Darwin scorecard: 45/45
- [ ] Skill mirrors: SHA256 Windows = WSL
- [ ] Agg-children: 11/11 have `cloud://` poster_file_id
- [ ] Geo: 167/167 have coordinates
- [ ] Manifest provenance: `out_dir` = absolute path
- [ ] Exporter: `127.0.0.1:17300` 可访问
