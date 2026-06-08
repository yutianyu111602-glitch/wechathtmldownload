<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PRD: Hermes 7-Day WSL2 Super Longrun

**Version:** v1.0
**Date:** 2026-04-28
**Owner:** User
**Executor:** Hermes Agent (WSL2) + deepseek-v4-pro
**Mode:** unattended-but-guarded / 有护栏无人值守
**Primary Artifact:** WeChat article capture pipeline from WSL2 orchestration

---

## 1. Product Goal

在 WSL2 中运行 Hermes Agent，使用 deepseek-v4-pro 作为规划/决策模型，持续 orchestrate Windows 微信文章抓取 pipeline 7天。目标：

1. 持续抓取微信公众号新文章（PDF + manifest）
2. 触发 loopy-archiver 后续处理（实体提取、关系抽取、图谱构建）
3. 使用 mem0 保存跨 session 学习
4. 使用 Qwen3.6-27B 做本地结构化抽取
5. 生成完整 evidence pack 供用户审查

---

## 2. Background

### 2.1 Existing Ecosystem

| System | Role | Location |
|--------|------|----------|
| Hermes | AI Agent framework | WSL2 + Windows (`C:\code\Hermes`) |
| WeChat PC | Article source | Windows desktop app |
| wechathtmldownload | Pipeline core | `C:\code\githubstar\wechathtmldownload` |
| loopy-archiver | Archive + extract + graph | `C:\code\loopy-archiver` |
| mem0 | Cross-session memory | Local (`127.0.0.1:11434`) |
| ignuke | Instagram pipeline | `C:\code\ignuke` |
| OBSIDIAN | Knowledge base | `C:\code\githubstar\OBSIDIAN` |

### 2.2 Existing Data

| Dataset | Location | Count | Status |
|---------|----------|-------|--------|
| Release v2 | `D:\DDownload\_llm_release_v2` | 93,000 | COMPLETE, READ-ONLY |
| Release v1 | `D:\DDownload\_llm_release` | ~68,782 | LEGACY, DO NOT DELETE |
| HTML captures | `D:\HTML` | Variable | ACTIVE WORKSPACE |
| loopy DB | `D:\HTML\.loopy_archiver\archiver.db` | Growing | ACTIVE |

### 2.3 Why Hermes in WSL2

- Hermes 原生不支持 Windows，只支持 Linux/macOS/WSL2
- WSL2 提供完整的 Linux 环境 + Windows 互操作
- Hermes 有 cron 调度、batch processing、skill 系统、memory 系统
- deepseek-v4-pro 通过 API 调用，不受本地 GPU 限制
- Qwen3.6-27B 本地模型用于结构化抽取，不消耗 API 额度

---

## 3. Scope

### 3.1 In Scope

- WSL2 Hermes 环境 setup 和 preflight
- WeChat 文章持续抓取（通过 `tools/windows_wechat_history`）
- 抓取输出管理（PDF + manifest.jsonl）
- loopy-archiver 后续处理触发
- mem0 记忆保存和检索
- Qwen3.6-27B 本地结构化抽取
- Checkpoint/resume 机制
- 每日/最终 quality report
- Graph candidate pack dry-run
- Final handoff with evidence

### 3.2 Out of Scope

- 不修改 `D:\DDownload\_llm_release_v2`
- 不删除 `_llm_release` 旧目录
- 不修复 WeChat 客户端本身的问题
- 不处理需要人工交互的微信验证码/登录
- 不启动 OpenClaw / AG 作为主控
- 不引入 OpenRouter fallback
- 不处理 review/blocked 的二次 OCR
- 不操作 Instagram (ignuke)——除非用户明确授权

---

## 4. User Stories

| ID | Name | Priority | Phase | Day |
|----|------|----------|-------|-----|
| US-000 | Hermes WSL2 Setup & Preflight | 0 | P0 | Day 0 |
| US-001 | deepseek-v4-pro Provider Config | 1 | P0 | Day 0 |
| US-002 | Baseline Freeze | 2 | P1 | Day 1 |
| US-003 | Context Gate & Queue Build | 3 | P1 | Day 1 |
| US-004 | WeChat Capture Dry-run 50 | 4 | P2 | Day 2 |
| US-005 | Capture Failure Analysis | 5 | P2 | Day 2 |
| US-006 | Capture Smoke 500 + Resume | 6 | P3 | Day 3 |
| US-007 | Throughput & Stability Test | 7 | P3 | Day 3 |
| US-008 | Full Capture Batch Start | 8 | P4 | Day 4 |
| US-009 | Loopy-Archiver Integration | 9 | P4 | Day 4-6 |
| US-010 | mem0 Learning Loop | 10 | P4 | Day 4-6 |
| US-011 | Qwen3.6 Downstream Extract | 11 | P5 | Day 5-6 |
| US-012 | Quality Report Generation | 12 | P5 | Day 6 |
| US-013 | Graph Candidate Dry-run | 13 | P6 | Day 6-7 |
| US-014 | OBSIDIAN Knowledge Update | 14 | P6 | Day 7 |
| US-015 | Final Handoff & Cleanup Plan | 15 | P7 | Day 7 |

---

## 5. Functional Requirements

### FR-1: WSL2 Hermes Preflight

Hermes 必须检查：
- WSL2 运行状态
- Hermes CLI 可用 (`hermes --version`)
- deepseek-v4-pro API key 配置
- Qwen3.6-27B 本地模型可达
- mem0 服务可达
- D 盘剩余空间
- WeChat 窗口状态（Windows 侧检测）
- 无危险扫描进程

输出：`reports/preflight-*.md`

### FR-2: WeChat Article Capture

通过 `tools/windows_wechat_history.WechatHistoryArchiver`：
- 参数：`output_dir`, `html_fallback=True`, `page_idle_limit=2`, `item_retry_limit=1`, `resume=True`
- 输出：PDF 文件 + `.url.txt` + `manifest.jsonl`
- 每个 capture run 生成独立的 output directory

### FR-3: Loopy-Archiver Integration

触发 loopy-archiver pipeline：
- 新 PDF → `archiver.py --save-only`（如果已归档）
- 或 `pipeline_keeper.py` 处理新 captures
- 实体提取：`extract_entities.py`
- 关系抽取：`extract_relationships.py`
- 图谱构建：`graph_builder.py`

### FR-4: mem0 Learning Loop

每个 story 完成后：
- 用 mem0 API 保存学习（成功模式、失败原因、优化参数）
- 新 session 开始时检索相关历史学习
- 使用 `agent_id=hermes_wechat_pipeline`

### FR-5: Qwen3.6 Downstream Extraction

对抓取的文章做本地结构化抽取：
- 使用 stable 参数：temp=0.1, top_p=0.9, max_tokens=2048
- 通过 llama-swap:11434
- 输出 JSONL 格式的结构化数据

### FR-6: Checkpoint & Resume

- 每 50 篇文章或 30 分钟写一个 checkpoint
- checkpoint 包含：manifest 行数、成功数、失败数、最后处理 URL
- resume 时从最后 checkpoint 继续
- 不重复处理已完成的条目（通过 manifest 去重）

### FR-7: Quality Report

聚合抓取和处理结果：
- 总抓取数、成功数、失败数、重复数
- 每公众号统计
- 失败原因分类
- 下游处理覆盖率
- throughput 趋势

### FR-8: Final Handoff

Day 7 输出最终交接：
- 完成项、未完成项
- 恢复命令
- 风险清单
- 证据路径
- 下一阶段建议

---

## 6. Non-Functional Requirements

- **可恢复**：任何中断后能从 checkpoint 继续
- **可审计**：每个 story 有 evidence pack
- **最小写入**：只写 allowed directories
- **低耦合**：Hermes config 不依赖外部 npm 包
- **保守**：遇到不确定状态先降级为 AMBER 或 RED
- **跨 session**：使用 mem0 保持学习连续性

---

## 7. Success Criteria

| 指标 | GREEN | AMBER | RED |
|------|-------|-------|-----|
| Preflight | 全 PASS | 非关键项缺失 | API/model/disk 关键失败 |
| Capture success rate | >= 85% | 70-84% | < 70% |
| Smoke throughput | >= 30/hr | 15-29/hr | < 15/hr |
| Loopy processing | 100% of new | 90-99% | < 90% |
| mem0 save/retrieve | 100% | 90-99% | < 90% |
| Checkpoint age | < 30min | 30-60min | > 60min |
| Disk free | > 100GB | 50-100GB | < 50GB |
| Model health | 3次内成功 | 间歇失败 | 3次连续失败 |

---

## 8. Hermes Execution Boundaries

| Allowed | Forbidden |
|---------|-----------|
| Run pre-approved CLI commands | Start OpenClaw / AG as controller |
| Execute read-only audit scripts | Delete data/log/lock/DB files |
| Write reports and documentation | Modify `D:\DDownload\_llm_release_v2` |
| Create baseline snapshots | Recursive scan `D:\DDownload` or `D:\aidata` |
| Run WeChat capture with config | Start 93K full batch without gates |
| Trigger loopy-archiver pipeline | Call external paid API without approval |
| Save/retrieve mem0 memories | Auto-fix failed capture tasks |
| Generate quality reports | Let Hermes run silently > 30 min without checkpoint |
| Build graph candidate packs (dry-run) | Git commit / push automatically |
| Run cleanup planning (dry-run only) | Use OpenRouter fallback |

---

## 9. Risk Register (Top 15)

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | WeChat 窗口被最小化/遮挡 | High | High | 检测窗口状态，尝试恢复，不行则标 RED |
| R2 | WeChat 需要重新登录/验证码 | Medium | Critical | 标 RED，等待人工处理 |
| R3 | deepseek-v4-pro API 限流/超时 | Medium | High | 重试 3 次，降级到本地 Qwen |
| R4 | WSL2 关机/崩溃 | Low | Critical | checkpoint 每 30min，开机后 resume |
| R5 | D 盘 I/O 过载（HDD） | Medium | Medium | 限速抓取，监控 Disk Time |
| R6 | Hermes skill 误操作 Windows UI | Medium | High | 白名单命令，禁止 mouse/keyboard 自动化 |
| R7 | mem0 服务不可用 | Low | Medium | 本地文件 fallback |
| R8 | Qwen3.6-27B VRAM 耗尽 | Medium | Medium | One model at a time |
| R9 | 抓取重复率过高 | Medium | Medium | manifest 去重，skip existing |
| R10 | loopy-archiver pipeline 卡住 | Medium | Medium | 超时检测，独立进程 |
| R11 | Hermes context 耗尽 | Medium | High | `/compress` 定期清理 |
| R12 | Evidence pack 不完整 | Medium | Medium | Mandatory checklist per task |
| R13 | Profile config drift | Low | High | Config diff in every evidence pack |
| R14 | Handoff ambiguity | Medium | Medium | Strict template, mandatory sections |
| R15 | Disk space耗尽 mid-run | Low | Critical | Pre-run check >= 100GB, monitor every 30min |

---

## 10. WSL2-Specific Considerations

### 10.1 Path Translation

| Windows Path | WSL2 Path |
|--------------|-----------|
| `C:\code\Hermes` | `/mnt/c/code/Hermes` |
| `D:\HTML` | `/mnt/d/HTML` |
| `D:\DDownload` | `/mnt/d/DDownload` |
| `C:\code\githubstar\wechathtmldownload` | `/mnt/c/code/githubstar/wechathtmldownload` |

### 10.2 WSL2 Interop Commands

```bash
# Windows exe from WSL2
powershell.exe -Command "Get-Process WeChat"

# WSL2 path to Windows
wslpath -w /mnt/d/HTML
# => D:\HTML

# Windows path to WSL2
wslpath 'D:\HTML'
# => /mnt/d/HTML
```

### 10.3 WSL2 Process Management

```bash
# Check WSL2 status
wsl.exe --status

# Shutdown WSL2
wsl.exe --shutdown

# Check Windows processes from WSL2
powershell.exe -Command "Get-Process | Where-Object { $_.ProcessName -like '*WeChat*' }"
```

---

**Next: Read `docs/02_EXECUTION_PLAN.md` for day-by-day schedule.**
