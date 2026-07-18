# Hermes 完全接手文档 — HUAIDJ 每周活动管线

> 2026-06-07 | 供 Hermes 桌面端直接执行 | 所有命令可直接复制运行

---

## 0. 项目概述

**HUAIDJ Weekly** 是一个 DJ/俱乐部活动信息聚合系统，包含：
- **数据管线**：从 130+ 微信公众号抓取活动信息，经 DeepSeek LLM 提取，生成结构化 JSON
- **微信小程序**：展示每周活动（日期/城市/DJ/海报）
- **CloudBase**：腾讯云托管（CDN + CloudRun API）

**Hermes 的职责**：每天跑一次管线，保持活动数据更新。

---

## 1. 环境速查

```
仓库:       C:\code\githubstar\wechathtmldownload
Python:     C:\Users\pc\AppData\Local\Programs\Python\Python313\python.exe
Exporter:   http://127.0.0.1:17300 (Docker 容器 wechat-article-exporter)
tcb CLI:    C:\Users\pc\AppData\Roaming\npm\tcb.cmd (已登录)
enjoy CLI:  opencli (C:\Users\pc\AppData\Roaming\npm\opencli.cmd)

CloudBase:
  体验版: huaidjweekly-d8g1go7kj48ec76c9  (CDN + CloudRun)
  个人版: huaidjweekly-d8g1go7-d0a07863e3e (海报存储)
```

---

## 2. 每日管线（一条命令）

```powershell
$env:MPTEXT_AUTH_KEY = "<discover from the current Docker exporter session; never persist here>"
cd C:\code\githubstar\wechathtmldownload
.\tools\stage7_rewrite\run_openclaw_weekly_daily_publish.ps1 `
    -WeekStart (Get-Date -Format "yyyy-MM-dd") `
    -WindowDays 8 `
    -MinExpectedItems 30
```

`MPTEXT_AUTH_KEY` 是 Docker exporter/mptext 当前登录会话产生的短期凭证。
运行前必须从当前容器的最新 cookie/auth discovery 结果验证并注入进程环境；
不得复用文档、脚本或旧 checkpoint 中的值，也不得把值提交到 Git。

**执行流程**（约 30-60 分钟）：
```
Step 0:  刷新 130 公众号下载队列
Step 1-3: 规则提取 → OCR → Entity 富化
Step 3.6: 聚合文章展开（DeepSeek Pro 或 Yuanbao --use-yuanbao）
Step 3.7: DeepSeek Flash/Pro LLM 富化（最慢，并发6）
Step 4:   构建 API JSON
Merge:    增量合并到 current_release
Repair:   冲突去重 + 字段修复
Quality:  质量门验证
```

**产物**：`D:\downstream_results\...\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD_MERGED_CURRENT\`

---

## 3. 管线后续步骤

### 3.1 海报迁移（如有新的 qpic URL）

```powershell
# 注意：用个人版 env
python tools\stage7_rewrite\scripts\migrate_weekly_public_posters_to_cloudbase.py `
    --api-dir D:\...\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD_MERGED_CURRENT `
    --env-id huaidjweekly-d8g1go7-d0a07863e3e `
    --cloud-dir "weekly-posters/YYYYMMDD" `
    --report migration.json `
    --write --confirm-token "ENABLE_CLOUDBASE_POSTER_MIGRATION_YYYYMMDD"
```

### 3.2 部署

```powershell
# 备份旧版
robocopy services\weekly_activity_cloudrun\data\current_release `
         services\weekly_activity_cloudrun\data\current_release.bak.YYYYMMDD /MIR

# 部署新版
robocopy D:\...\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD_MERGED_CURRENT `
         services\weekly_activity_cloudrun\data\current_release /MIR

# 修复 manifest provenance（必须做，否则质量门失败）
python -c "import json; p=r'services\weekly_activity_cloudrun\data\current_release\manifest.json'; d=json.load(open(p)); d['out_dir']=r'C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release'; json.dump(d,open(p,'w'),ensure_ascii=False,indent=2)"
```

### 3.3 上传 CDN

```powershell
$id = "entity-posterocr6-current-YYYYMMDD"
$src = "C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun\data\current_release"
$cloud = "weekly/releases/$id"
@("current.json","manifest.json","by-city","by-date","source_actions\source_url_map.json","llm\enrichment_index.json") | ForEach-Object {
    tcb hosting deploy "$src\$_" "$cloud\$_" -e huaidjweekly-d8g1go7kj48ec76c9
}
```

### 3.4 更新小程序

修改 `apps\weekly_activity_miniprogram\app.js` 第 22 行：
```js
staticBaseUrl: "https://huaidjweekly-d8g1go7kj48ec76c9-1371956557.tcloudbaseapp.com/weekly/releases/entity-posterocr6-current-YYYYMMDD",
```

---

## 4. Exporter 管理

### 4.1 日常检查

```powershell
# Session 状态
python tools\stage7_rewrite\scripts\manage_weekly_exporter_auth.py --mode status
# 期望: auth_lifecycle_ok=true, session_ok=true

# 如果端口不通
wsl --shutdown  # 重启 WSL2 修复 Docker Desktop 端口转发
```

### 4.2 重新登录（每 4 天）

Session 有效期 4 天。过期后运行：

```powershell
# Puppeteer 出 QR（推荐）
docker cp tools\stage7_rewrite\scripts\puppeteer_exporter_qr.cjs wechat-article-exporter:/app/
docker exec -e QR_OUT=/app/.data/current-login-qr.png wechat-article-exporter node /app/puppeteer_qr.cjs qr
copy .mptext-data\current-login-qr.png tools\stage7_rewrite\reports\login-qr.png
start microsoft.windows.photos: tools\stage7_rewrite\reports\login-qr.png
# → 手机微信扫码桌面屏幕（不能扫相册图片）
```

登录后将 API key 写到缓存：
```powershell
python -c "
import json
key='<从仪表盘复制>'
open(r'.mptext-data\kv\auth-key-current.json','w').write(json.dumps({
    'schema_version':'mptext_runtime_auth_cache.v1',
    'updated_at':'$(Get-Date -Format s)',
    'endpoint':'http://127.0.0.1:17300',
    'source':'hermes',
    'api_key':key,
    'api_key_hash':key[:12]
},ensure_ascii=False,indent=2))
"
```

### 4.3 容器管理

```powershell
# 重启
docker restart wechat-article-exporter

# 重建
docker stop wechat-article-exporter; docker rm wechat-article-exporter
docker run -d --name wechat-article-exporter -p 127.0.0.1:17300:3000 `
    -v C:\code\githubstar\wechathtmldownload\.mptext-data:/app/.data `
    -e NODE_TLS_REJECT_UNAUTHORIZED=0 ghcr.io/wechat-article/wechat-article-exporter:latest
```

---

## 5. 聚合子活动海报修复

当管线产生的 `agg-child-*` 条目没有独立海报时：

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

# Step 2: 下载 HTML 图片 → CloudBase → patch
python tools\stage7_rewrite\scripts\yuanbao_recover_agg_posters.py
```

---

## 6. 质量验证

### 6.1 一键检查

```powershell
$r = "C:\code\githubstar\wechathtmldownload"

# Python tests
python -m pytest $r\tools\stage7_rewrite\tests\test_build_* -q
# 期望: 32+ passed

# Frontend tests
node $r\apps\weekly_activity_miniprogram\tests\production-data-source.test.cjs
node $r\apps\weekly_activity_miniprogram\tests\cloud-poster-url.test.cjs
# 期望: 2 passed + 8 passed

# Quality gate
python $r\tools\stage7_rewrite\scripts\validate_weekly_release_package_quality.py `
    --api-dir $r\services\weekly_activity_cloudrun\data\current_release `
    --report NUL --require-internal-posters --enforce-window-start
# 期望: ok=true, hard_failures=[]

# PS1 parse
powershell -NoProfile -Command '$null=[scriptblock]::Create((gc C:\Users\pc\.openclaw\bin\openclaw-weekly-daily-nonllm-fallback.ps1 -Raw));"parse_ok"'
```

### 6.2 质量阈值

| 指标 | 必须 |
|------|------|
| `ok` | true |
| `missing_internal_poster_count` | ≤ 1（1个 agg-child 无独立海报可接受） |
| `public_wechat_or_qpic_poster_count` | 0 |
| `missing_geo_count` | ≤ 5 |
| `item_count` | ≥ 76 |

---

## 7. 故障速查

| 现象 | 原因 | 修复 |
|------|------|------|
| `127.0.0.1:17300` 不通 | Docker Desktop 端口转发 bug | `wsl --shutdown`，等 15 秒 |
| QR 返回 0 字节 | WeChat API 变更 | 改用 Puppeteer QR 方案（§4.2） |
| `tcb storage upload` Access Denied | env 不对（体验版无写权限） | 用个人版 env `huaidjweekly-d8g1go7-d0a07863e3e` |
| strict audit pseudo-duplicate | 同一活动多篇推文 | 可忽略，不影响部署 |
| `manifest_provenance_stale` | out_dir 相对路径 | 部署后执行 §3.2 的修复命令 |
| DeepSeek step 卡住 | API key 未传到子进程 | 用当前终端直接跑，不要用 Start-Process |
| `tcb hosting deploy` 超时 | 文件太多 | 分目录上传（§3.3） |
| 418 CDN 错误 | CDN WAF 拦截非微信客户端 | 正常，真机小程序不受影响 |

---

## 8. 关键文件索引

```
C:\code\githubstar\wechathtmldownload\
├── services\weekly_activity_cloudrun\data\current_release\   ← 当前发布数据
├── apps\weekly_activity_miniprogram\app.js                    ← 小程序配置（staticBaseUrl）
├── tools\stage7_rewrite\
│   ├── run_openclaw_weekly_daily_publish.ps1                  ← 管线主入口
│   ├── scripts\
│   │   ├── expand_weekly_aggregate_articles.py               ← Step 3.6（支持 --use-yuanbao）
│   │   ├── yuanbao_weekly_utils.py                           ← Yuanbao 工具模块
│   │   ├── yuanbao_recover_agg_posters.py                    ← 海报恢复
│   │   ├── puppeteer_exporter_qr.cjs                         ← Docker 内 Chromium QR
│   │   ├── manage_weekly_exporter_auth.py                    ← Exporter 管理
│   │   ├── migrate_weekly_public_posters_to_cloudbase.py     ← 海报迁移
│   │   ├── validate_weekly_release_package_quality.py        ← 质量门
│   │   └── daily_exporter_auth_check.ps1                     ← 每日 auth 检查
│   └── reports\                                              ← 运行报告
├── docs\
│   ├── RUNBOOK.md                                            ← 本文档
│   ├── SOP_WEEKLY_PIPELINE.md                                ← 完整 SOP
│   ├── SOP_TEST_PIPELINE.md                                  ← 测试 SOP
│   └── YUANBAO_CLI_INTEGRATION.md                            ← Yuanbao 集成方案
└── .mptext-data\kv\                                          ← Exporter KV 数据
```

## 9. Skills

| Skill | 路径 | 触发词 |
|-------|------|--------|
| `openclaw-weekly-daily-run` | `C:\Users\pc\.openclaw\skills\openclaw-weekly-daily-run\` | 每日运行、daily run、周报 |
| `openclaw-docker-arsenal` | `C:\Users\pc\.openclaw\skills\openclaw-docker-arsenal\` | docker武器库、arsenal |

变更后同步到 WSL：
```powershell
Copy-Item C:\Users\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md \\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-weekly-daily-run\SKILL.md -Force
Copy-Item C:\Users\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md \\wsl.localhost\Ubuntu\home\pc\.openclaw\skills\openclaw-docker-arsenal\SKILL.md -Force
```
