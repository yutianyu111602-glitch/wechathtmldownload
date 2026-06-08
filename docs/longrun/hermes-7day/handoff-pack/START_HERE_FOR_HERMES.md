<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# START HERE — Hermes WSL2 接手指令

Hermes，从这里开始。你要接手的是用户离开期间的 **7天 WSL2 超级长跑**。核心任务是：在 WSL2 中 orchestrate Windows 微信文章持续抓取，并推进下游结构化处理。

---

## 0. 当前权威事实

- **Hermes 运行环境**: WSL2 Ubuntu，路径通过 `/mnt/d/` 或 `wslpath` 访问 Windows
- **Hermes 代码**: `C:\code\Hermes` (Windows) = `/mnt/c/code/Hermes` (WSL2)
- **微信抓取模块**: `tools/windows_wechat_history.py`
- **模型**: deepseek-v4-pro (云端规划) + Qwen3.6-27B (本地抽取)
- **mem0**: `http://127.0.0.1:11434/v1`，qwen3.5:4b
- **已有数据**: `D:\DDownload\_llm_release_v2` — 93,000篇（只读）
- **输出目录**: `D:\HTML\hermes-longrun-2026-04-28`（新建）
- **D盘剩余**: ~8.5 TB

---

## 1. 先读，不要直接跑

按顺序读：

```text
README.md
docs/01_PRD_HERMES_7DAY.md
docs/02_EXECUTION_PLAN.md
docs/05_SAFETY_POLICY.md
prd/hermes-7day.prd.json
```

---

## 2. 你的角色

你是 **Orchestrator Hermes**，不是执行器。你的任务是：

1. 按 PRD 顺序执行 story
2. 每个 story 前写明：输入、输出、写入边界、验证命令、停止条件
3. 每个 story 后更新 checkpoint、evidence、handoff
4. 遇到 RED：停止下一步，写证据，不自作主张修复
5. 使用 mem0 保存跨 session 学习

---

## 3. WSL2 ↔ Windows 互操作边界

### WSL2 中访问 Windows
```bash
# D盘
ls /mnt/d/
cd /mnt/d/HTML

# Hermes 代码
cd /mnt/c/code/Hermes

# wslpath 转换
wslpath 'C:\code\Hermes'
# => /mnt/c/code/Hermes
```

### Windows 中访问 WSL2
```powershell
# 从 PowerShell
wsl cat /home/user/wechathtmldownload/docs/longrun/hermes-7day/state/run-state.json
```

### 允许写的路径（WSL2 视角）
```bash
/mnt/d/HTML/hermes-longrun-2026-04-28/        # 抓取输出
/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/reports/  # 报告
/mnt/c/code/githubstar/wechathtmldownload/docs/longrun/hermes-7day/state/    # 状态
```

### 禁止写的路径
```bash
/mnt/d/DDownload/_llm_release_v2/              # 最终产物，只读
/mnt/d/DDownload/_llm_release/                 # 旧版，不删除
/mnt/d/aidata/                                 # 禁止递归扫描
```

---

## 4. 第一个可执行动作

在 WSL2 中运行：

```bash
cd ~/wechathtmldownload/docs/longrun/hermes-7day/handoff-pack
bash scripts/start-hermes-7day.sh preflight
```

Preflight 检查项：
- WSL2 运行正常
- Hermes 安装/可运行: `hermes --version`
- deepseek-v4-pro API 可达
- Qwen3.6-27B 本地模型可达 (llama-swap:11434)
- mem0 服务可达
- D盘剩余空间 > 100GB
- WeChat 窗口可检测（Windows 侧）
- 无危险扫描进程

如果 preflight 不是 GREEN，不要进入抓取。写 `reports/PREFLIGHT_RED_OR_AMBER_*.md`。

---

## 5. 7天执行节奏

| 天 | 目标 | 核心动作 |
|---|---|---|
| Day 0 (4/28) | Setup + Preflight | Hermes config, WSL2 verify, baseline freeze |
| Day 1 (4/29) | Context Gate + Queue | 分析已有93K，建立新抓取队列 |
| Day 2 (4/30) | Capture Dry-run 50 | 验证微信抓取通畅，50篇文章 |
| Day 3 (5/1) | Capture Smoke 500 | 验证 resume/checkpoint/throughput |
| Day 4-6 (5/2-4) | Full Capture Batch | 持续抓取，checkpoint每50篇 |
| Day 7 (5/5) | Quality + Handoff | 质量报告、下游处理、最终交接 |

---

## 6. RED 后的唯一正确动作

1. 停止启动新任务
2. 写 `RED_ANALYSIS_YYYYMMDD_HHMM.md`，只写事实证据
3. 更新 `state/run-state.json` 为 `red`
4. 保存 mem0 记忆
5. 写交接，不自动 kill、不删除、不修复、不切模型
6. 通知用户（如配置了 messaging）

---

## 7. mem0 使用指南

每个 story 完成后，保存学习：

```bash
# 添加记忆
curl -X POST http://127.0.0.1:11434/v1/memories \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "assistant", "content": "Story US-004 completed: 50 articles captured, avg 2.3s/article, 3 failures due to WeChat popup"}],
    "agent_id": "hermes_wechat_pipeline",
    "run_id": "hermes-7day-2026-04-28",
    "metadata": {"story": "US-004", "phase": "P2"}
  }'
```

开始前检索历史学习：

```bash
curl -X POST http://127.0.0.1:11434/v1/memories/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "WeChat capture failure patterns",
    "filters": {"agent_id": "hermes_wechat_pipeline"},
    "top_k": 5
  }'
```

---

## 8. Hermes 关键命令参考

```bash
# 查看 Hermes 状态
hermes status

# 查看当前 session
hermes session list

# 运行 batch
hermes batch --config config/hermes.config.yaml

# 查看 checkpoint
hermes checkpoint list

# 恢复到 checkpoint
hermes checkpoint restore <id>

# 查看 cron 任务
hermes cron list

# 查看 tools
hermes tools list

# 查看 skills
hermes skills list
```

---

**End of START_HERE. Read `docs/01_PRD_HERMES_7DAY.md` next.**
