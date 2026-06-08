# HUAIDJ Weekly Pipeline SOP v2.0

> 2026-06-07 | 基于 Round88 全流程实测

## 0. 前置条件

```
Exporter: http://127.0.0.1:17300 (Docker wechat-article-exporter)
Repo:     C:\code\githubstar\wechathtmldownload
Python:   C:\Users\pc\AppData\Local\Programs\Python\Python313\python.exe
tcb:      已登录 CloudBase CLI 3.5.5
```

## 1. Exporter 登录

### 1.1 检查 Session

```powershell
python tools\stage7_rewrite\scripts\manage_weekly_exporter_auth.py --mode status
```

期望：`session_ok: true, auth_lifecycle_decision: exporter_session_ok`

### 1.2 Session 过期 → 重新登录

Session 有效期 4 天。过期后：

```powershell
# 方案 A: Puppeteer 出 QR（推荐）
docker cp tools\stage7_rewrite\scripts\puppeteer_exporter_qr.cjs wechat-article-exporter:/app/
docker exec -e QR_OUT=/app/.data/current-login-qr.png wechat-article-exporter node /app/puppeteer_qr.cjs qr
copy .mptext-data\current-login-qr.png tools\stage7_rewrite\reports\login-qr.png
start microsoft.windows.photos: tools\stage7_rewrite\reports\login-qr.png

# 方案 B: 浏览器仪表盘直登
start http://127.0.0.1:17300/dashboard/account
# → 点"登录公众号" → 手机微信扫码
```

登录成功后缓存 API key：
```powershell
python tools\stage7_rewrite\scripts\manage_weekly_exporter_auth.py --mode sync-key --from-authkey-endpoint
```

### 1.3 注意

- QR 必须从**桌面屏幕**扫描，不能从相册/iMessage 图片扫描
- 日志 `upstream_scanloginqrcode_empty_after_valid_local_session` = WeChat API 已改，只能用 Puppeteer/浏览器方案
- 当地 localhost 端口不通时（Docker Desktop bug），WSL 重启可修复：`wsl --shutdown`

## 2. 每周管线执行

### 2.1 全量跑（推荐）

```powershell
$env:MPTEXT_AUTH_KEY = "<API_KEY>"
.\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1 `
    -WeekStart (Get-Date -Format "yyyy-MM-dd") `
    -WindowDays 8 `
    -MinExpectedItems 30
```

### 2.2 参数说明

| 参数 | 默认 | 说明 |
|------|------|------|
| `-WeekStart` | 当天 | 活动窗口起始日 |
| `-WindowDays` | 8 | 窗口天数 |
| `-MinExpectedItems` | 76 | 最少期望条目数 |
| `IncrementalMerge` | True (内置) | 增量合并模式 |
| `DeployBackend` | False | 不部署后端 |
| `UploadFrontend` | False | 不上传前端 |
| `PosterCloudBaseMigration` | False | 不自动迁移海报 |

### 2.3 管线段落

```
Step 0: 刷新队列 (130 公众号, ~10-20 min)
Step 1-3.7: 规则提取 + OCR + Entity + DeepSeek LLM
Step 4: 构建 API 包
Merge:  增量合并到 MERGED_CURRENT
Repair: 聚合子活动源链接 + 冲突去重 + lineup/time
Audit:  strict validator (可能 pseudo-duplicate 失败 → 忽略)
```

### 2.4 产物位置

```
候选: D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD
合并: ..._MERGED_CURRENT
当前: services\weekly_activity_cloudrun\data\current_release
```

## 3. 海报迁移

### 3.1 检查

```powershell
python tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py `
    --api-dir D:\...\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD_MERGED_CURRENT `
    --report report.json --require-internal-posters --enforce-window-start
```

### 3.2 迁移 qpic → CloudBase

```powershell
# 注意: 使用个人版 env，不是体验版
python tools\stage7_rewrite\scripts\migrate_weekly_public_posters_to_cloudbase.py `
    --api-dir D:\...\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD_MERGED_CURRENT `
    --env-id huaidjweekly-d8g1go7-d0a07863e3e `
    --cloud-dir "weekly-posters/YYYYMMDD" `
    --report migration_report.json `
    --write --confirm-token "ENABLE_CLOUDBASE_POSTER_MIGRATION_YYYYMMDD"
```

### 3.3 再次验证

```powershell
python tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py ...
# 期望: missing_internal_poster_count=0, public_wechat_or_qpic_poster_count=0
```

## 4. 部署

### 4.1 部署到 current_release

```powershell
# 备份当前
robocopy services\weekly_activity_cloudrun\data\current_release `
         services\weekly_activity_cloudrun\data\current_release.bak.YYYYMMDD /MIR

# 部署合并候选
robocopy D:\...\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD_MERGED_CURRENT `
         services\weekly_activity_cloudrun\data\current_release /MIR
```

### 4.2 上传到 CloudBase CDN

```powershell
# 用 stage 脚本生成 release 包
python tools\stage7_rewrite\scripts\stage_weekly_miniprogram_release.py `
    --api-dir services\weekly_activity_cloudrun\data\current_release `
    --release-dir D:\...\RELEASE_YYYYMMDD

# 上传到 CDN
python tools\stage7_rewrite\scripts\_upload_release_to_cloudbase.py `
    --release-dir D:\...\RELEASE_YYYYMMDD
```

### 4.3 更新小程序

```javascript
// app.js - 更新 staticBaseUrl
staticBaseUrl: "https://...tcloudbaseapp.com/weekly/releases/entity-posterocr6-current-YYYYMMDD"
```

微信开发者工具 → 上传 → 设为体验版

## 5. 质量验证

### 5.1 快速检查

```powershell
python -m pytest tools\stage7_rewrite\tests\test_build_* test_openclaw_* test_weekly_* -q
node apps\weekly_activity_miniprogram\tests\production-data-source.test.cjs
node apps\weekly_activity_miniprogram\tests\cloud-poster-url.test.cjs
```

期望：全部通过

### 5.2 质量指标

| 指标 | 目标 |
|------|------|
| total items | ≥ 76 |
| poster CloudBase | 100% (允许 1 agg-child 例外) |
| qpic URL count | 0 |
| missing geo | ≤ 5 |
| LLM description | ≥ 95% |
| coordinates | ≥ 95% |

### 5.3 前端 Contract

```
posterUseRawSourceFirst: false  ← 只认 cloud:// fileId
posterStorage: cloudbase         ← 必须是 cloudbase
coverUrl 可以是 cloud:// ID     ← 运行时 getTempFileURL 转 temp URL
禁止: qpic/mmbiz URL, temp URL, wxfile://
```

## 6. Docker Profiles

```powershell
# L1-L7 + L3A 合约验证（报告模式，不执行实际 worker）
docker compose -f tools\stage7_rewrite\docker\openclaw-weekly\docker-compose.openclaw-weekly.yml `
    --profile <profile> config --services

# 注意: 所有 service 都是 profile-gated，不加 --profile 会显示空
```

## 7. 故障排查

| 现象 | 原因 | 修复 |
|------|------|------|
| `127.0.0.1:17300` 不通 | Docker Desktop 端口转发 bug | `wsl --shutdown` |
| QR 返回 0 字节 | WeChat API 变更 | 改用 Puppeteer QR 方案 |
| `tcb storage upload` Access Denied | 用了体验版 env | 改用个人版 env |
| strict audit 失败 pseudo-duplicate | 同一活动多篇推文 | 正常，可忽略 |
| fallback 说 session invalid | no-secret probe 无 API key | 用 `manage --mode status` 检查，status OK 即可继续 |
| 93K 提取 blocked | QR 上游 | 不影响每周管线（独立 pipeline） |

## 8. Cron 配置

```
# 每周五 10:00 自动跑
schtasks /Create /TN "HUAIDJ\WeeklyPipeline" `
    /TR "powershell -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\daily_exporter_auth_check.ps1" `
    /SC WEEKLY /D FRI /ST 10:00

# 每日 10:00 Session 健康检查
schtasks /Create /TN "HUAIDJ\ExporterAuthCheck" `
    /TR "powershell -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\daily_exporter_auth_check.ps1" `
    /SC DAILY /ST 10:00
```

## 9. Skill 关键规则

- `openclaw-weekly-daily-run`: 管线编排，fail-closed
- `openclaw-docker-arsenal`: Docker profile 合约验证
- 当前 release green + QR blocked → status=`current_release_ok_no_new_source_possible`
- QR 恢复后优先跑全量增量
- Never: deploy/upload/DB write 不经显式授权
- Scripts: `desktop_exporter_qr_refresh_puppeteer.ps1` 桌面 QR, `puppeteer_exporter_qr.cjs` Docker QR
