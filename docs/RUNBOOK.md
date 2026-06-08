# HUAIDJ Weekly Pipeline Runbook v3.0

> 2026-06-07 | Round88 完整实测 | 覆盖 Exporter → 管线 → 海报 → 部署 → 测试

---

## 速查表

```
入口一：桌面 QR 刷新         .\desktop_exporter_qr_refresh_puppeteer.ps1
入口二：Session 检查         python manage_weekly_exporter_auth.py --mode status
入口三：全量管线             run_openclaw_weekly_daily_publish.ps1 -WeekStart 2026-06-07 -WindowDays 8
入口四：海报迁移             migrate_weekly_public_posters_to_cloudbase.py --env-id <个人版>
入口五：部署                 robocopy MERGED_CURRENT → current_release
入口六：Yuanbao 海报恢复      opencli yuanbao ask '读一览文章' → yuanbao_recover_agg_posters.py
入口七：Yuanbao 管线集成       expand_weekly_aggregate_articles.py --use-yuanbao
入口八：全量测试               pytest + node tests + PS1 parse + quality gate + docker profiles
入口九：Exporter 升级           docker pull + 本地 build (patch UA) + 替换容器
```

---

## 1. Exporter 管理

### 1.1 启动/升级

```powershell
# 启动（标准镜像）
docker run -d --name wechat-article-exporter -p 127.0.0.1:17300:3000 `
    -v C:\code\githubstar\wechathtmldownload\.mptext-data:/app/.data `
    -e NODE_TLS_REJECT_UNAUTHORIZED=0 ghcr.io/wechat-article/wechat-article-exporter:latest

# 本地 build（修 UA）
cd vendor\wechat-article-exporter
# 改 config/index.ts: User-Agent → Chrome 131 Windows
docker build -t wechat-article-exporter-local:latest .
docker stop wechat-article-exporter; docker rm wechat-article-exporter
docker run -d --name wechat-article-exporter -p 127.0.0.1:17300:3000 `
    -v C:\code\githubstar\wechathtmldownload\.mptext-data:/app/.data `
    -e NODE_TLS_REJECT_UNAUTHORIZED=0 wechat-article-exporter-local:latest

# 端口不通时
wsl --shutdown    # 重启 WSL2 修复 Docker Desktop 端口转发
```

### 1.2 Login

```powershell
# A. Puppeteer 出 QR（推荐）
docker cp tools\stage7_rewrite\scripts\puppeteer_exporter_qr.cjs wechat-article-exporter:/app/
docker exec -e QR_OUT=/app/.data/current-login-qr.png wechat-article-exporter node /app/puppeteer_qr.cjs qr
copy .mptext-data\current-login-qr.png tools\stage7_rewrite\reports\login-qr.png
start microsoft.windows.photos: tools\stage7_rewrite\reports\login-qr.png
# → 手机微信扫码（必须扫桌面屏幕，不能扫相册图片）

# B. 浏览器仪表盘（备选）
start http://127.0.0.1:17300/dashboard/account
# → 点"登录公众号" → 手机扫码

# 登录后缓存 API key
$env:MPTEXT_AUTH_KEY = "<从仪表盘/api页面复制>"

# 验证 Session
python tools\stage7_rewrite\scripts\manage_weekly_exporter_auth.py --mode status
# 期望: auth_lifecycle_ok=true, session_ok=true
```

### 1.3 QR 故障

| 现象 | 原因 | 处理 |
|------|------|------|
| `getqrcode` 200 body=0 | WeChat API 变更（`WAE/1.0` UA 被标记） | 改用 Puppeteer QR（真实浏览器 UA） |
| `scanloginqrcode_empty` | upstream QR endpoint | 同上 |
| `127.0.0.1:17300` 不通 | Docker Desktop 端口转发 bug | `wsl --shutdown` |

---

## 2. 管线执行

### 2.1 一命令全量

```powershell
$env:MPTEXT_AUTH_KEY = "<API_KEY>"
.\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1 `
    -WeekStart "2026-06-07" -WindowDays 8 -MinExpectedItems 30
```

### 2.2 管线段落

```
Pre-flight:  session → QR → auth recovery → full-incremental gate
Step 0:      刷新 130 公众号下载队列 (~10-20min)
Step 1-3.7:  规则提取 → OCR → Entity → DeepSeek Flash/Pro LLM
Step 4:      构建 Mini-Program API JSON
Merge:       增量合并 base(155) + incremental(44) → merged(174→167)
Repair:      聚合子活动源链接 + 冲突去重 + lineup/time
Audit:       strict validator（pseudo-duplicate 可忽略）
Poster:      迁移 qpic → CloudBase（需手动执行 Step 3）
Quality:     质量门验证
Closeout:    Darwin + next-action + readiness
```

### 2.3 产物

```
候选:     D:\downstream_results\...\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD\
合并:     ..._MERGED_CURRENT\
当前:     services\weekly_activity_cloudrun\data\current_release\
备份:     ...\current_release.bak.YYYYMMDD\
```

---

## 3. 海报处理

### 3.1 qpic → CloudBase 迁移

```powershell
# 注意：用 个人版 env，不是 体验版
python tools\stage7_rewrite\scripts\migrate_weekly_public_posters_to_cloudbase.py `
    --api-dir D:\...\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD_MERGED_CURRENT `
    --env-id huaidjweekly-d8g1go7-d0a07863e3e `
    --cloud-dir "weekly-posters/YYYYMMDD" `
    --report migration_report.json `
    --write --confirm-token "ENABLE_CLOUDBASE_POSTER_MIGRATION_YYYYMMDD"
```

### 3.2 聚合子活动海报恢复（Yuanbao + HTML 图片提取）

```powershell
# Step 1: 找一览文章 URL
python -c "
import json
q=r'D:\downstream_results\stage7_rewrite\longrun\LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE\latest_queue.jsonl'
targets=['loopy Club','OIL油','wigwam','Dada Bar Beijing']
with open(q) as f:
    for l in f:
        e=json.loads(l)
        t=e.get('title',''); n=e.get('account_nickname','')
        if any(x in n for x in targets) and any(k in t for k in ['本周','一览','预告']):
            print(f'{n}|{e[\"source_url\"]}')
"

# Step 2: 下载一览文章 HTML，提取图片，上传 CloudBase，patch agg-children
python tools\stage7_rewrite\scripts\yuanbao_recover_agg_posters.py
```

原理：从 exporter 下载一览文章 → 提取 body 内所有 mmbiz.qpic.cn 图片 → tcb storage upload → 每个 agg-child 分配独立海报。

### 3.3 Yuanbao 管线集成（Step 3.6）

`expand_weekly_aggregate_articles.py` 支持 `--use-yuanbao` 标志：

```powershell
# 用 yuanbao 替代 DeepSeek Pro 处理聚合文章
python tools\stage7_rewrite\scripts\expand_weekly_aggregate_articles.py `
    --pack-dir ... --weekly-queue ... --out-dir ... --use-yuanbao
```

Yuanbao 会调用 `opencli yuanbao ask` 读取文章 URL，提取结构化事件。不加 flag 时回退原有 DeepSeek Pro 流程。

**工具模块**：`scripts/yuanbao_weekly_utils.py`
- `find_overview_urls()` — 从 download queue 搜索一览文章
- `yuanbao_extract_events()` — 调用 yuanbao 提取事件
- `yuanbao_extract_children()` — 替代 `deepseek_extract_children()`

### 3.3 前端 Contract

```
posterUseRawSourceFirst: false    ← 只认 cloud:// fileId
posterStorage: cloudbase          ← 必须 cloudbase
coverUrl = cloud:// fileId        ← 运行时 getTempFileURL 转 temp URL
禁止: qpic/mmbiz, temp URL, wxfile://, /api/v1/weekly/poster/
```

---

## 4. 部署

```powershell
# 备份
robocopy services\weekly_activity_cloudrun\data\current_release `
         services\weekly_activity_cloudrun\data\current_release.bak.YYYYMMDD /MIR

# 部署
robocopy D:\...\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD_MERGED_CURRENT `
         services\weekly_activity_cloudrun\data\current_release /MIR

# 修 manifest provenance
python -c "
import json; p=r'services\weekly_activity_cloudrun\data\current_release\manifest.json'
d=json.load(open(p)); d['out_dir']=p.replace('manifest.json','')
json.dump(d,open(p,'w'),ensure_ascii=False,indent=2)
"

# 验证
python tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py `
    --api-dir services\weekly_activity_cloudrun\data\current_release `
    --report report.json --require-internal-posters --enforce-window-start
```

---

## 5. 全量测试

```powershell
# 一键测试
$r="C:\code\githubstar\wechathtmldownload"
python -m pytest $r\tools\stage7_rewrite\tests\test_build_* -q
node $r\apps\weekly_activity_miniprogram\tests\production-data-source.test.cjs
node $r\apps\weekly_activity_miniprogram\tests\cloud-poster-url.test.cjs
powershell -NoProfile -Command '$null=[scriptblock]::Create((gc C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1 -Raw));\"parse_ok\"'
python $r\tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py --api-dir $r\services\weekly_activity_cloudrun\data\current_release --report NUL --require-internal-posters --enforce-window-start
python $r\tools\stage7_rewrite\scripts\manage_weekly_exporter_auth.py --mode status --timeout-sec 10
```

期望：全部 PASS。

### 5.1 质量阈值

| 指标 | 目标 | 最低 |
|------|------|------|
| `ok` | true | true |
| `item_count` | ≥76 | ≥30 |
| `missing_internal_poster_count` | 0 | 0 |
| `public_wechat_or_qpic_poster_count` | 0 | 0 |
| `missing_geo_count` | 0 | ≤5 |
| agg-children CloudBase | 11/11 | 10/11 |

---

## 6. Docker Profiles

```powershell
@("openclaw-source-exporter","openclaw-source-queue-cache","openclaw-ocr",
  "openclaw-poster-ocr-recovery","openclaw-llm-extraction","openclaw-map-verify",
  "openclaw-package-merge","openclaw-deploy-upload-wrapper") | %{
    docker compose -f tools\stage7_rewrite\docker\openclaw-weekly\docker-compose.openclaw-weekly.yml `
        --profile $_ config --services
}
```

期望：8/8 返回对应 service。

---

## 7. 故障速查

| 现象 | 原因 | 修复 |
|------|------|------|
| `127.0.0.1:17300` 不通 | Docker Desktop 端口转发 bug | `wsl --shutdown` |
| QR 返回 0 字节 | WeChat API 变更 | Puppeteer QR 方案 |
| `tcb storage upload` Access Denied | 体验版 env 无写权限 | 用个人版 env |
| strict audit 报 pseudo-duplicate | 同一活动多篇推文 | 可忽略 |
| manifest_provenance_stale | out_dir 相对路径 | 部署后修 |
| 海报迁移 `exit=1` | env 不对 | 确认 `huaidjweekly-d8g1go7-d0a07863e3e` |
| yuanbao 上下文污染 | opencli session persistent | 用独立浏览器窗口 |

---

## 8. Skills

| Skill | 路径 | 用途 |
|-------|------|------|
| `openclaw-weekly-daily-run` | `C:\Users\pc\.openclaw\skills\...\SKILL.md` | 管线编排，fail-closed |
| `openclaw-docker-arsenal` | 同上 | Docker profile 合同验证 |
| WSL mirror | `\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\...` | DeepSeek TUI 副本 |

### 8.1 Skill 变更后同步

```powershell
$pairs = @(
  @('C:\Users\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md','\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md'),
  @('C:\Users\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md','\\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md')
)
foreach ($p in $pairs) {
  Copy-Item $p[0] $p[1] -Force
  if ((Get-FileHash $p[0]).Hash -ne (Get-FileHash $p[1]).Hash) { throw "SYNC FAILED" }
}
```

---

## 9. Cron

```powershell
# 每日 10:00 Session 检查
schtasks /Create /TN "HUAIDJ\ExporterAuthCheck" /SC DAILY /ST 10:00 `
    /TR "powershell -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\daily_exporter_auth_check.ps1"

# 每周五 10:30 全量管线
schtasks /Create /TN "HUAIDJ\WeeklyPipeline" /SC WEEKLY /D FRI /ST 10:30 `
    /TR "powershell -File C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\run_pipeline_background.ps1"
```
