<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Hermes 7天无人值守长跑 — 自主执行计划

**时间:** 2026-04-28 03:10 +08  
**模式:** DeepTutor 双层循环 (Solve Loop + Review Loop)  
**状态:** RUNNING  
**用户状态:** 外出7天

---

## 一、已完成（已确认）

### Night Watcher (2026-04-27) — ✅ 全部完成
- 6/6 stories passed
- 93,000 articles in `D:\DDownload\_llm_release_v2`
- Qwen3.6-27B 校准完成：stable (temp=0.1, top_p=0.9, max_tokens=2048)
- 下游评估 57/60 (95%)
- Handoff: `HANDOFF_2026-04-27_NIGHT_WATCHER_COMPLETED.md`

### Hermes 7-Day Day 0 — ✅ 完成
- WSL2 Preflight: 5/8 GREEN, 2 AMBER, 1 RED
- deepseek-v4-pro 配置完成
- 输出目录: `D:\HTML\hermes-longrun-2026-04-28`
- 目录结构已创建

---

## 二、当前系统状态

| 组件 | 状态 | 备注 |
|------|------|------|
| WSL2 | 🟢 | 正常运行 |
| Hermes | 🟢 | v0.11.0 + deepseek-v4-pro |
| llama-swap | 🟡 | 未响应 — 需恢复后才能跑下游 |
| WeChat | 🔴 | 未运行 — 需恢复后才能抓取 |
| D盘 | 🟢 | 8.4TB (43%) |
| mem0 | 🟡 | quota exceeded, 5月1日重置 |

---

## 三、Cron 心跳体系（已部署）

```
┌─────────────────────────────────────────────────────────┐
│  night-watcher-heartbeat  every 10m  [GA pack 只读心跳]   │
│  hermes-7day-watchdog     every 30m  [双层 Solve+Review]  │
│  hermes-7day-daily-exec   0 12 * * * [每日 story 推进]    │
│  prompt-review-loop       every 6h   [提示词优化循环]      │
└─────────────────────────────────────────────────────────┘
```

### DeepTutor 双层循环架构

```
Solve Loop（执行层）         Review Loop（反思层）
     ↓                           ↓
系统健康检查              自我批判 + 质量评估
story 执行推进             提示词是否需要调整？
checkpoint 写入            值得保存到 mem0 的学习？
     ↓                           ↓
         └────── 下一轮 ←─────────┘
```

每6小时的 prompt-review-loop 自动检测 cron 提示词是否需要补丁优化。

---

## 四、7天自主执行策略

### 条件自适应优先级

```
llama-swap UP?
  ├─ YES → 启动全量下游LLM处理 (93K articles, stable参数)
  │        每50篇 checkpoint
  │        Mac M3 sidecar: bge-m3 向量化 + Qwen3.6 辅助推理
  │
  └─ NO  → WeChat UP?
             ├─ YES → 启动微信文章抓取 (Day 2-6 capture)
             │        每50篇 checkpoint
             │
             └─ NO  → 分析/规划工作:
                       • baseline freeze + coverage分析
                       • 提示词质量审查与优化
                       • 清理规划 (dry-run only)
                       • 质量报告预生成
                       • 下游处理脚本准备
```

### Day-by-Day 弹性计划

| 天 | 条件 | 核心任务 | 备用任务 |
|----|------|----------|----------|
| Day 0 (4/28) | 当前 | Setup完成, cron已部署 | — |
| Day 1 (4/29) | — | Baseline freeze + context gate | 覆盖率分析 |
| Day 2-3 | WeChat UP | Capture dry-run 50 → smoke 500 | 下游处理脚本准备 |
| Day 4-6 | 服务正常 | Full capture batch OR 下游LLM处理 | 质量审计 |
| Day 7 | 任意 | Final handoff + evidence pack | 清理规划 |

### 反阻塞机制

- **AMBER** (llama-swap/mem0不可用) → 记录但不阻塞，继续执行可做任务
- **RED** (数据损坏/3次连续失败/D盘<50GB) → 停止并写handoff
- 同一story最多重试3次，超限标RED
- WeChat不可用时自动跳过capture story

---

## 五、关键路径与文件

| 用途 | 路径 |
|------|------|
| 工作目录 | `C:\code\githubstar\wechathtmldownload` |
| 状态文件 | `docs/longrun/hermes-7day/state/run-state.json` |
| 输出目录 | `D:\HTML\hermes-longrun-2026-04-28` |
| 报告目录 | `docs/longrun/hermes-7day/reports/` |
| Live root (只读) | `D:\DDownload\_llm_release_v2` |
| 发布包 | `D:\DDownload\_llm_release_v2` (93,000 篇) |
| Mac 侧车 | :8091 bge-m3, :8092 Qwen3-Reranker, :8093 Qwen2.5-Coder-7B |

## 六、硬规则

1. ❌ 不修改/删除 `D:\DDownload\_llm_release_v2`
2. ❌ 不递归扫描 D:\DDownload 或 D:\aidata
3. ❌ 不启动 OpenClaw/AG 作为主控
4. ❌ 不自动修复 RED 问题
5. ✅ 每个story写 Minimal Loop Contract
6. ✅ 每50篇或30分钟写 checkpoint
7. ✅ 所有输出到 local，不发消息给用户
8. ✅ RED后停止，写证据，等待人工

---

## 七、恢复指南（用户回来后）

### 查看状态
```bash
cat docs/longrun/hermes-7day/state/run-state.json
```

### 查看日志
```bash
ls -lt docs/longrun/hermes-7day/reports/
cat docs/longrun/hermes-7day/reports/checkpoint-day*.md
```

### 查看 cron 运行历史
```bash
hermes --profile wechatops cron list
```

### 恢复后立即做的事
1. 检查 `reports/` 下所有 checkpoint 和 RED 报告
2. 如果 WeChat 恢复 → 手动启动抓取
3. 如果 llama-swap 恢复 → 手动启动下游处理
4. 审核 prompt-review 报告中的补丁建议
