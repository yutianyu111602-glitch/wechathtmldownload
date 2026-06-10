---
name: db2-outlink-crawl-pipeline
description: DB2 Swarm 外链抓取全管线 — 并行 worker、WAL 防锁死、spool 安全写、质量门禁、头像下载。给 Hermes 自动运行。
---

# DB2 Outlink Crawl Pipeline — Hermes Operator Skill

## 一句话

DB2 是 Atlas DJ 图谱的外链候选数据库。本 skill 管理完整的抓取管线：IG 裂变 → SoundCloud 深挖 → 中文平台 → 头像下载 → 外链展开 → writer 入库。SQLite WAL 保证多 worker 并行写不阻塞读。所有路径硬编码无秘密依赖。

## 架构总览

```
种子                  Worker 并行层               写入层             读取层
──────────         ──────────────────          ────────          ────────
DB1/Atlas ──→  IG Fission (2 shard)  ──┐
(只读, ro)      SC Deep ×2            ──┤
                Domestic (中文)        ──┼──→ dj_outlinks ──→ db2ctl status
                Avatar DL (spool)      ──┤    dj_social_profiles   (只读)
                Outlink Expand(spool)  ──┤    dj_avatars
                BC Deep (自发复活)     ──┘    swarm_progress

DB2: /home/pc/swarm_data/atlas_swarm_data.sqlite  (WAL, 85MB)
Cache: /home/pc/swarm_data/cache/db2_sidecar_cache.sqlite (hash-only)
Spool: /home/pc/swarm_data/write_spool/incoming/*.jsonl
Lock: /home/pc/swarm_data/.db_write.lock
```

## 三条防死锁规则

### 规则 1: 所有源 DB 只读打开

```python
# 读 DB1/DB2 快照，不被 writer 阻塞
conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
```

SQLite WAL 模式：writer 不阻塞 reader。reader 看到事务开始时的快照。

### 规则 2: 新建 DB = 独占

`atlas_core.sqlite` 每次 build_candidate 都是 `core_db.unlink()` 清掉重建，不存在竞争。

### 规则 3: 源 hash 守护

Safe runner 在 build 前后各算一次 SHA256。如果外链 worker 在 build 中间写了 DB2，after hash 对不上 → 直接报 `source_hash_changed`，pipeline 失败。不静默通过。

### WAL 单写排队

23 个 worker 并发写 `dj_outlinks` 时，SQLite WAL 自动单 writer 排队。这不是死锁，是正常串行化。读者不受影响。

## Worker 清单

### IG Fission v2 — 核心裂变引擎

```
脚本: /home/pc/scripts/ig_nuclear_fission_v2.py
Cookie: /home/pc/cookies/www.instagram.com.cookies.json (11 cookies, sessionid + csrftoken)
代理: http://192.168.8.1:7890
依赖: curl_cffi (pip3 install curl_cffi --break-system-packages)
```

**运行:**
```bash
cd /home/pc/scripts
python3 -u ig_nuclear_fission_v2.py --worker-id 1 --worker-count 2
```

**已修补问题:**
- Cookie 注入: 自动加载 `/home/pc/cookies/www.instagram.com.cookies.json` 构造 Cookie header
- Rate limit 守护: 命中 429 → sleep 60s → continue 重试同一 handle（不收为错误）
- Crash 自愈: `main()` 外包 `while True: try: main() except: sleep(30)` 无限循环
- stderr flush: 每条 log 后 `sys.stderr.flush()` 保证日志实时

**Sharding:** 按 eid 首 hex 字符分片。Worker 1 处理 0-7，Worker 2 处理 8-f。

**坑点:**
- 起步就限速是正常的 — 前几个请求可能全部 429，sleep 后恢复
- 不要用 `wsl -e` 启动这个 worker — 进程会在 WSL session 结束时死掉
- **必须用 Start-Process 或 daemon 脚本启动**（见下方）

### sc_deep — SoundCloud 深度抓取

```
脚本: /home/pc/scripts/sc_deep_worker.py
Cookie: 内置 48 个 SoundCloud cookies (脚本内硬编码)
依赖: requests
```

**运行:**
```bash
cd /home/pc/scripts
/home/pc/venv-cloak/bin/python3 -u sc_deep_worker.py --max-profiles 1000
```

**坑点:**
- 需要 venv-cloak 环境 — 标准 python3 缺 `requests` 模块
- 处理速度 ~3s/profile (SoundCloud API)
- HTTP 404 是正常的 — 很多 SC profile 已删除
- 直接写 DB（非 spool），与其他 worker WAL 排队

### domestic — 中文平台

```
脚本: /home/pc/scripts/domestic_worker.py
平台: Bilibili, NetEase Music
Cookie: /home/pc/cookies/www.bilibili.com.cookies.json + music.163.com.cookies.json
依赖: requests
```

**运行:**
```bash
cd /home/pc/scripts
python3 -u domestic_worker.py
```

**坑点:**
- 产出低 — 大部分扫描结果是 SKIP（非 DJ 账号）
- 国内平台延迟高，建议单跑不抢占 IG/SC 资源

### Avatar DL — 头像下载 (spool)

```
脚本: tools/stage7_rewrite/scripts/_run_avatar.py (wrapper)
      tools/stage7_rewrite/scripts/db2_avatar_spool_adapter.py (core)
Legacy: /home/pc/scripts/avatar_dl_worker.py
```

**运行:**
```bash
python3 /mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/scripts/_run_avatar.py 500
```

**架构:**
- 读 DB（只读）→ 下载头像文件 → 写 spool JSONL → writer 单进程入库
- `avatar_cache` (6569 hashes): 下载前查缓存，已存在的跳过
- `local_file_hits`: 本地已有文件跳过

**坑点:**
- 池已接近饱和 — 4150 remaining EIDs 中大多数无下载 URL
- cache_hits 高达 80%+，实际下载比例 10-20%
- spool 写入 `/home/pc/swarm_data/write_spool/incoming/`

### Outlink Expand — 外链展开 (spool)

```
脚本: tools/stage7_rewrite/scripts/db2_outlink_expand_spool_adapter.py
Legacy: /home/pc/scripts/outlink_expand_worker.py
```

**运行:**
```bash
python3 tools/stage7_rewrite/scripts/db2_outlink_expand_spool_adapter.py \
  --legacy-script /home/pc/scripts/outlink_expand_worker.py \
  --db /home/pc/swarm_data/atlas_swarm_data.sqlite \
  --spool-dir /home/pc/swarm_data/write_spool \
  --cache-db /home/pc/swarm_data/cache/db2_sidecar_cache.sqlite \
  --phase linktree --limit 500 --sleep 0.8
```

**坑点:**
- Linktree 池已耗尽 (2 candidates, zero_yield)
- ShortURL 池已耗尽 (0 candidates)
- IG fission 产出新 URL 后，此 worker 会有新候选

### bc_deep — Bandcamp 深抓

```
脚本: /home/pc/scripts/bc_deep_worker.py
依赖: venv-cloak, playwright (CloakBrowser)
```

**⚠️ 警告:**
- 实验性 worker，3 个 while-true 循环在 PID 1 级自动复活
- kill 后会在 120s 内重生 — 杀不完
- 杀掉方法: `kill -9` 所有 bc_deep PID + 父 bash while-true PID
- 目前自然运行中，产出 Bandcamp 外链

## 正确启动方式

### ❌ 错误: wsl -e 后台启动

```bash
# 这不会持久化 — WSL session 退出时进程死亡
wsl -e bash -c "cd /home/pc/scripts && python3 worker.py &"
```

### ✅ 正确: Start-Process 守护启动

```powershell
# 每个 worker 一个独立的 WSL 进程
Start-Process -FilePath wsl -ArgumentList '-e','bash','/home/pc/scripts/ig_daemon.sh','1','2' -WindowStyle Hidden
Start-Process -FilePath wsl -ArgumentList '-e','bash','/home/pc/scripts/ig_daemon.sh','2','2' -WindowStyle Hidden
```

### ✅ 正确: daemon 脚本模板

```bash
#!/bin/bash
# /home/pc/scripts/ig_daemon.sh
# Usage: bash ig_daemon.sh <worker-id> <worker-count>
WORKER_ID=${1:-1}
WORKER_COUNT=${2:-2}
LOG="/tmp/ig${WORKER_ID}_daemon.log"
cd /home/pc/scripts

while true; do
    echo "[$(date)] Starting worker $WORKER_ID/$WORKER_COUNT" >> $LOG
    python3 -u ig_nuclear_fission_v2.py --worker-id $WORKER_ID --worker-count $WORKER_COUNT >> $LOG 2>&1
    echo "[$(date)] Exited, restart in 30s" >> $LOG
    sleep 30
done
```

## 快速启动全量

```powershell
# IG Fission — 核心裂变
Start-Process -FilePath wsl -ArgumentList '-e','bash','/home/pc/scripts/ig_daemon.sh','1','2' -WindowStyle Hidden
Start-Process -FilePath wsl -ArgumentList '-e','bash','/home/pc/scripts/ig_daemon.sh','2','2' -WindowStyle Hidden

# sc_deep — SoundCloud
Start-Process -FilePath wsl -ArgumentList '-e','bash','-c','cd /home/pc/scripts && setsid /home/pc/venv-cloak/bin/python3 -u sc_deep_worker.py --max-profiles 1000 </dev/null >/tmp/sc.log 2>&1 &' -WindowStyle Hidden

# Avatar — 头像下载
Start-Process -FilePath wsl -ArgumentList '-e','bash','-c','cd /mnt/c/code/githubstar/wechathtmldownload && setsid python3 -u tools/stage7_rewrite/scripts/_run_avatar.py 500 </dev/null >/tmp/av.log 2>&1 &' -WindowStyle Hidden
```

## 日常运维命令

```bash
# 查看所有运行 worker
wsl -e bash -c "pgrep -af 'ig_nuclear|sc_deep|domestic|_run_avatar|bc_deep' | grep -v grep"

# DB 状态
python3 tools/stage7_rewrite/scripts/db2ctl.py status

# DB 全量数据
python3 tools/stage7_rewrite/scripts/db2ctl.py existing-data

# 健康检查（锁持有者、rogue worker）
python3 tools/stage7_rewrite/scripts/db2ctl.py health --lock-holders

# Spool backlog
python3 tools/stage7_rewrite/scripts/db2ctl.py writer status

# Writer 执行
DB2_WRITER_EXECUTE=1 python3 tools/stage7_rewrite/scripts/db2ctl.py writer once --execute

# Cache 状态
python3 tools/stage7_rewrite/scripts/db2ctl.py cache status

# Cache seed
python3 tools/stage7_rewrite/scripts/db2ctl.py cache seed --execute --limit 500

# 查看 IG 裂变进度
tail -20 /tmp/ig1_daemon.log
tail -20 /tmp/ig2_daemon.log

# 查看 sc_deep 进度
tail -20 /tmp/sc.log

# 查看头像进度
tail -5 /tmp/av.log

# 杀 bc_deep (反复复活)
wsl -e bash -c "pkill -9 -f bc_deep_worker; pkill -9 -f 'while true.*bc_deep'"

# 全局杀
wsl -e bash -c "killall python3 2>/dev/null"
```

## 成果指标

| 指标 | 06-07 初始 | 06-08 当前 | 增量 |
|------|:---:|:---:|:---:|
| dj_outlinks | 40,340 | 40,853+ | +513+ |
| dj_social_profiles | 122,099 | 123,361 | +1,262 |
| dj_avatars | 7,207 | 7,338 | +131 |
| swarm_progress done | 49,700 | 53,698 | +3,998 |
| duplicate ratio | 13.16% | 13.03% | 改善 |
| SearXNG tagged | 3,202 | 3,202 | 0 增长 |

## 质量门禁 (已完成)

- ✅ L4/L5 全量 re-fetch (514f/234b)
- ✅ Prewrite (445 unique)
- ✅ Quality gate (65 ready / 380 blocked)
- ✅ Execution gate RELEASED
- ✅ 65 行生产写入 DB2 (verified)
- ⚠️ 380 quality-blocked 行待策略决定

## 硬边界

1. **不读** `.env`, API keys, SSH keys
2. **Cookie 仅限** `/home/pc/cookies/` 下已导出的 IG/SC/Bilibili cookies
3. **不写** DB1 (Atlas 源库), DB3 (服务层)
4. **不扫描** `D:\DDownload`, `D:\aidata`, `/mnt/d` 递归
5. **不启动** searxng_discovery, nuclear_fission_engine (需 CloakBrowser + IG auth, 已有 cookie 但 API 路径不同)
6. **不部署** CloudRun, 小程序上传/审核/发布

## 已知坑点汇总

1. **IG Fission 限速**: 前几个请求全部 429 是正常的，sleep+retry 自动恢复
2. **bc_deep 反复复活**: 2 个 `while true` 循环在 init 级，kill 后 120s 内重生 — 杀父进程才能根治
3. **domestic 产出低**: Bilibili/NetEase 扫描 90%+ 是 SKIP，适合后台低优先级跑
4. **wsl -e 不持久化**: 任何 `wsl -e bash -c "... &"` 都会在 session 结束时死掉，必须用 Start-Process
5. **venv-cloak 环境**: sc_deep 和 bc_deep 需要 `/home/pc/venv-cloak/bin/python3`
6. **curl_cffi 安装**: `pip3 install curl_cffi --break-system-packages`
7. **avatar 池饱和**: 剩余 4150 EIDs 中 cache_hits 80%+，实际下载仅 10-20%
8. **linktree 池耗尽**: 仅 2 candidates，zero_yield — 等 IG fission 产出新 URL 后才有候选
9. **进度条不动**: 不是死锁 — 是 WAL 单写排队导致的正常慢速。多 worker 并行时排队等待是正常行为
10. **spool 积压**: writer 在 worker 写锁期间无法处理，积压是暂时的，锁释放后秒清

## 文件索引

```
核心脚本:
  /home/pc/scripts/ig_nuclear_fission_v2.py        IG 裂变引擎 (已修补)
  /home/pc/scripts/ig_daemon.sh                     IG 守护脚本
  /home/pc/scripts/sc_deep_worker.py                SoundCloud 深抓
  /home/pc/scripts/domestic_worker.py               中文平台
  /home/pc/scripts/bc_deep_worker.py                Bandcamp (自发)

Spool 适配器:
  tools/stage7_rewrite/scripts/db2_avatar_spool_adapter.py
  tools/stage7_rewrite/scripts/db2_outlink_expand_spool_adapter.py
  tools/stage7_rewrite/scripts/_run_avatar.py       Avatar wrapper

控制面:
  tools/stage7_rewrite/scripts/db2ctl.py            DB2 操作 CLI
  tools/stage7_rewrite/scripts/swarm_parallel.py    并行 worker 框架

Cookie:
  /home/pc/cookies/www.instagram.com.cookies.json
  /home/pc/cookies/www.bilibili.com.cookies.json
  /home/pc/cookies/music.163.com.cookies.json

DB:
  /home/pc/swarm_data/atlas_swarm_data.sqlite
  /home/pc/swarm_data/cache/db2_sidecar_cache.sqlite
  /home/pc/swarm_data/write_spool/

日志:
  /tmp/ig1_daemon.log, /tmp/ig2_daemon.log
  /tmp/sc.log, /tmp/dom.log, /tmp/av.log
```

## Hermes 接手后第一步

1. 检查当前存活 worker: `wsl -e bash -c "pgrep -af python3 | grep -v supervisord"`
2. 检查 DB 健康: `python3 tools/stage7_rewrite/scripts/db2ctl.py health --lock-holders`
3. 如果都死了，用 Start-Process 重启（见上方快速启动）
4. 每 5 分钟巡检: `db2ctl status`, `db2ctl writer status`
5. writer drain: `DB2_WRITER_EXECUTE=1 python3 tools/stage7_rewrite/scripts/db2ctl.py writer once --execute`
6. Cache seed: `python3 tools/stage7_rewrite/scripts/db2ctl.py cache seed --execute --limit 500`
