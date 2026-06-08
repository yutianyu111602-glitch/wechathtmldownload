<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# WeChat Article Pipeline Super Long Run Plan v1

**生成时间:** 2026-04-27  
**模式:** 纯规划/只读，不执行任何命令  
**状态:** DRAFT v1  

---

## 一、超级长跑计划总览

### 1. 当前项目状态
| 模块 | 状态 | 说明 |
|------|------|------|
| Stage 0-3 采集/归档/处理/导出 | ✅ COMPLETE | 93,653 篇 / 63 clubs |
| Stage 4 final_pack | ✅ COMPLETE | `_llm_release_v2/` 93,000 篇 |
| Stage 5 参数校准 | ✅ COMPLETE | stable (temp=0.1, top_p=0.9, max=2048) |
| Stage 6 下游评估 | ✅ COMPLETE | 60 evals, 95% success |
| rawwechat MarkItDown | ⚠️ PAUSED | 8095 total, 3146 succeeded, 4948 queued, 1 stale running |
| D 盘安全 | 🔴 INCIDENT | WSL `find` 曾导致 16T HDD 高 I/O，已固化禁令 |
| OCR 后端 | ✅ LOCKED | PaddleOCR only, no EasyOCR fallback |
| OpenClaw/AG | 🧊 FROZEN | 不作为长跑主控，仅保留最小监控能力 |

### 2. 已完成产物
- `D:/DDownload/_llm_release_v2/` — 93,000 篇完整 release pack
- `qwen3.6-calibration/` — 4 profile 校准结果 (480 rows)
- `tmp-downstream-eval/` — 60 条下游评估结果
- `NIGHT_WATCHER_FINAL_REPORT_2026-04-27.md` — 最终报告
- `safe-night-watch.ps1` — 安全守夜脚本

### 3. 未完成任务
- 全量 93K 下游结构化抽取
- 质量报告与统计
- 图谱候选包生成
- rawwechat 8095 篇 MarkItDown 恢复
- D 盘安全策略硬化
- 最终 handoff 与下一阶段交接

### 4. 当前禁止事项
- ❌ 递归扫描 `D:\DDownload`、`D:\aidata`、`/mnt/d/*`
- ❌ 自动删除 stage lock / 自动修复业务任务
- ❌ 自动写入生产库 / 自动触发破坏性命令
- ❌ 启动 OpenClaw / AG / Hermes 作为主控
- ❌ 重跑 Stage 0-6
- ❌ Mac M3 Pro / 向量模型进入当前主链

### 5. 主控角色分工
| 角色 | 职责 | 权限 |
|------|------|------|
| **Qwen3.6-27B** | 规划、运维手册、监控规范、策略制定 | 只读分析 + 文档输出 |
| **GA Agent** | 只读监控、checkpoint 检查、D 盘安全、告警摘要 | 只读，禁止写/删/杀进程 |
| **OpenCode** | 后续执行器，仅执行明确命令 | 按指令执行，不自主决策 |
| **OpenClaw** | 冻结 | 不作为主控 |
| **AG** | 冻结 | 不作为主控 |
| **Hermes** | 本阶段不用 | 冻结 |

### 6. 分阶段路线图
```
Phase 0: Baseline Freeze (只读快照)
  ↓
Phase 1: Downstream Dry-run 100 (100 篇验证)
  ↓
Phase 2: Downstream Smoke 1000 (1000 篇压力测试)
  ↓
Phase 3: Full 93K Downstream Batch (全量抽取)
  ↓
Phase 4: Downstream Quality Report (质量统计)
  ↓
Phase 5: Graph Candidate Pack (图谱候选生成)
  ↓
Phase 6: Rawwechat Legacy Repair (8095 篇恢复)
  ↓
Phase 7: Final Handoff (总结/交接)
```

### 7. 每阶段输入/输出/验收/停止条件
| Phase | Input | Output | 验收标准 | 停止条件 |
|-------|-------|--------|----------|----------|
| 0 | 当前产物目录 | baseline.json | 文件数/大小/哈希一致 | 磁盘 < 5GB |
| 1 | release_v2 + prompts | 100 条 JSONL | 100% JSON valid rate ≥ 90% | 失败 > 20% |
| 2 | release_v2 + prompts | 1000 条 JSONL | resume 可用，错误分类完整 | 吞吐 < 10 篇/小时 |
| 3 | release_v2 + prompts | 93K 条 JSONL | 覆盖率 ≥ 98% | GPU OOM / 失败 > 15% |
| 4 | Phase 3 输出 | quality_report.json | 统计完整，图表可生成 | 数据损坏 |
| 5 | Phase 4 输出 | candidate_pack/ | 实体/事件/关系完整 | 图谱冲突 > 10% |
| 6 | rawwechat status | repaired status + .md | stale 清除，queued 恢复 | 状态文件损坏 |
| 7 | 全部产物 | final_report.md | 所有指标可追溯 | 无 |

### 8. GA 监控指标
- checkpoint 最新时间 & 增长趋势
- run log 大小 & 最后写入时间
- D 盘 I/O (busy/read/write)
- 可疑进程数 (find/scandisk/递归扫描)
- final_pack 运行状态
- OpenClaw/AG 进程状态
- OCR env 是否为 PaddleOCR
- RED 条件触发次数

---

## 二、运维手册

### WeChat Pipeline Operations Manual v1

### 1. 启动前检查
- [ ] `D:\` 剩余空间 ≥ 100 GB
- [ ] `llama-swap:11434` 返回 `Qwen3.6-27B`
- [ ] 无残留 `.wechat-live-stage-lock.json`
- [ ] `WECHAT_OCR_COMMAND` 指向 `tools/ocr-image-paddle.ps1`
- [ ] 无 `find /mnt/d/` 或递归扫描进程
- [ ] OpenClaw/AG 未作为主控运行

### 2. 模型参数
| 参数 | 值 | 来源 |
|------|-----|------|
| model | Qwen3.6-27B | llama-swap:11434 |
| temperature | 0.1 | US-004 校准最优 |
| top_p | 0.9 | US-004 校准最优 |
| max_tokens | 2048 | US-004 校准最优 |
| timeout_ms | 180000 | 默认 |

### 3. D 盘安全规则
- 🚫 禁止 `find /mnt/d/DDownload` 或 `/mnt/d/aidata`
- 🚫 禁止 `Get-ChildItem -Recurse` 扫描 `D:\DDownload` 或 `D:\aidata`
- 🚫 禁止任何无边界递归遍历 16T HDD
- ✅ 仅允许按 club/article 路径精确访问
- ✅ 发现可疑扫盘进程立即记录并告警，不自动 kill

### 4. OCR Backend Policy
- ✅ 主链: `PaddleOCR` (`tools/ocr-image-paddle.ps1`)
- 🚫 禁止自动 fallback 到 EasyOCR
- 🚫 禁止修改 `WECHAT_OCR_COMMAND` 环境变量
- ✅ PaddleOCR 输出必须符合 TypeScript 契约: `box` / `score`
- ⚠️ EasyOCR 输出 `coordinates` / `confidence` 不符合契约，仅用于历史审计

### 5. safe-night-watch 运行方式
- 前台 PowerShell 直接执行: `.\safe-night-watch.ps1`
- 🚫 禁止 `Start-Process` 包装 (会破坏 `2>&1 | Tee-Object` 管道)
- 🚫 禁止后台静默运行
- ✅ 必须可见日志输出，可随时 Ctrl+C 中断

### 6. Checkpoint 检查方式
```powershell
# 检查最新 checkpoint
Get-ChildItem "D:\DDownload\_llm_release_v2\_state\checkpoints\" | Sort-Object LastWriteTime -Descending | Select-Object -First 3
# 验证 JSON 完整性
Get-Content "latest-checkpoint.json" -Raw | ConvertFrom-Json
```

### 7. Final Report 检查方式
- 检查 `NIGHT_WATCHER_FINAL_REPORT_*.md` 是否存在
- 验证包含: 阶段结果、数据统计、失败分布、下一步建议
- 验证所有 JSON/JSONL 产物可解析

### 8. RED / AMBER / GREEN 处理
| 级别 | 条件 | 处理 |
|------|------|------|
| 🟢 GREEN | 正常运行，指标健康 | 继续，记录 checkpoint |
| 🟡 AMBER | 失败率 5-15%，吞吐下降，轻微 I/O 波动 | 暂停新批次，检查日志，人工确认 |
| 🔴 RED | 失败率 > 15%，GPU OOM，D 盘高 I/O，锁冲突 | 立即停止，保存现场，写 handoff，不重试 |

### 9. 必须人工介入的情况
- 磁盘空间 < 5 GB
- GPU OOM 或模型不可用 (3 次重试后)
- D 盘出现高 I/O / 炒豆子现象
- 状态文件损坏或无法解析
- 失败率超过 stop gate
- 需要修改生产数据或配置

### 10. 禁止 Agent 自动修复的情况
- 删除 stage lock / 业务锁
- 修改 `WECHAT_OCR_COMMAND` 或模型参数
- 重写/覆盖 `_llm_release_v2/` 或 `D:\rawwechat_md\`
- 启动 OpenClaw / AG / Hermes
- 触发 `find` 或递归扫描
- 自动写入生产数据库

### 11. 日志/报告目录约定
| 类型 | 路径 |
|------|------|
| 运行日志 | `C:\code\githubstar\wechathtmldownload\logs\` |
| 监控报告 | `C:\Users\pc\.openclaw\reports\` |
| 接手报告 | `C:\code\githubstar\wechathtmldownload\HANDOFF_*.md` |
| 最终报告 | `C:\code\githubstar\wechathtmldownload\NIGHT_WATCHER_FINAL_REPORT_*.md` |
| 校准结果 | `qwen3.6-calibration/` |
| 评估结果 | `tmp-downstream-eval/` |

### 12. 产物目录约定
| 产物 | 路径 |
|------|------|
| Release Pack | `D:/DDownload/_llm_release_v2/` |
| LLM Artifacts | `D:/DDownload/_llm_artifacts/` |
| MD Mirror | `D:/DDownload/_llm_md/` |
| Rawwechat MD | `D:/rawwechat_md/` |
| Graph Candidate | `D:/DDownload/_graph_candidate/` (Phase 5) |

### 13. 回滚和恢复原则
- 任何生产写入前，先备份目标目录的 `status.json` / `manifest.json`
- 失败时，保留所有日志和 checkpoint，不覆盖、不清理
- 恢复时，从最新有效 checkpoint 继续，不从头开始
- 状态文件损坏时，优先人工审计，不自动重建

### 14. 长跑失败后的 Handoff 模板
```markdown
# Handoff — [日期] [阶段]

## 当前状态
- 阶段: [Phase X]
- 进度: [X/Y] ([Z]%)
- 最后成功时间: [timestamp]

## 失败原因
- [具体错误/现象]
- 日志位置: [path]
- 已尝试修复: [list]

## 现场保护
- 未清理任何文件
- checkpoint 保留: [path]
- 状态文件: [path]

## 下一步建议
1. [人工检查项]
2. [恢复步骤]
3. [是否可继续]

## 禁止事项
- [列出当前环境下的硬性禁令]
```

---

## 三、GA Agent 监控规范

### GA Read-Only Monitor Spec v1

**核心原则:** GA 仅做只读监控，禁止任何写入、删除、启动、修复操作。

### GA 允许的操作
1. 查看 checkpoint 是否新增 (读取目录列表/时间戳)
2. 查看 run log 是否增长 (读取文件大小/最后修改时间)
3. 查看 D 盘 I/O (读取 `Get-Volume` / `Get-Counter`)
4. 查看可疑扫盘进程 (读取 `Get-Process` / `Get-CimInstance`)
5. 查看 final_pack 是否运行 (读取进程列表)
6. 查看 OpenClaw 是否运行 (读取进程列表/端口)
7. 查看 AG 是否运行 (读取进程列表)
8. 查看 OCR env 是否仍是 PaddleOCR (读取环境变量)
9. 写监控摘要到指定路径

### GA 禁止的操作
1. 🚫 `kill` / `Stop-Process` 任何进程
2. 🚫 启动 OpenClaw / AG / Hermes
3. 🚫 启动 `finalize-llm-pack` 或任何生产任务
4. 🚫 修改配置文件 / 环境变量
5. 🚫 删除任何文件 (包括 lock / status)
6. 🚫 `Get-ChildItem -Recurse` 扫描 `D:\DDownload` / `D:\aidata`
7. 🚫 `find /mnt/d/DDownload` / `find /mnt/d/aidata`
8. 🚫 自动修复 / 重试失败任务
9. 🚫 触发业务管线任务

### GA 每 10 分钟检查项
| # | 检查项 | 方法 | 告警阈值 |
|---|--------|------|----------|
| 1 | checkpoint 最新时间 | `Get-ChildItem ...checkpoints\*` | > 30 分钟无新增 |
| 2 | run log 最新时间 & 大小 | `Get-Item log.txt` | > 30 分钟无增长 |
| 3 | D 盘 busy/read/write | `Get-Counter` / `Get-Volume` | Disk Time > 80% |
| 4 | 可疑进程数量 | `Get-Process find, scandisk` | > 0 |
| 5 | final_pack 状态 | `Get-Process *finalize*` | 意外运行 |
| 6 | OpenClaw 状态 | `Get-Process *openclaw*` | 意外运行 |
| 7 | AG 状态 | `Get-Process *genericagent*` | 意外运行 |
| 8 | OCR backend 状态 | `$env:WECHAT_OCR_COMMAND` | 非 PaddleOCR |
| 9 | RED 条件 | 综合 1-8 | 触发任意 |

### GA 输出
```
C:\Users\pc\.openclaw\reports\GA_MONITOR_SUMMARY_2026-04-27.md
```

格式:
```markdown
# GA Monitor Summary — [timestamp]

## Status: 🟢 GREEN / 🟡 AMBER / 🔴 RED

| Check | Value | Status |
|-------|-------|--------|
| Checkpoint | [time] | ✅/❌ |
| Log Growth | [size/time] | ✅/❌ |
| D Disk I/O | [busy%] | ✅/❌ |
| Suspicious Procs | [count] | ✅/❌ |
| final_pack | [running/idle] | ✅/❌ |
| OpenClaw | [running/idle] | ✅/❌ |
| AG | [running/idle] | ✅/❌ |
| OCR Backend | [Paddle/Easy] | ✅/❌ |
| RED Triggered | [yes/no] | ✅/❌ |

## Notes
- [异常说明]
- [建议人工介入项]
```

---

## 四、阶段计划

### Phase 0: Baseline Freeze
**目标:** 冻结当前产物状态，创建只读快照，不跑生产任务。  
**输入:** `D:/DDownload/_llm_release_v2/`, `qwen3.6-calibration/`, `tmp-downstream-eval/`  
**输出:** `baseline-snapshot.json` (文件数/大小/哈希)  
**验收:** 快照可验证，与实际一致  
**停止:** 磁盘 < 5GB / 文件损坏  
**GA 监控:** 检查快照完整性，确认无意外写入

### Phase 1: Downstream Dry-run 100
**目标:** 从 93K release pack 中抽取 100 篇跑结构化下游抽取，验证 pipeline 通畅。  
**输入:** `_llm_release_v2/` + `prompts/downstream/` + 校准参数  
**输出:** `dry-run-100.jsonl` (100 条)  
**验收:** 100% 执行完成，JSON valid rate ≥ 90%，无 OOM  
**停止:** 失败 > 20% / 模型不可用  
**GA 监控:** 检查输出增长，确认无 D 盘扫描

### Phase 2: Downstream Smoke 1000
**目标:** 跑 1000 篇，验证 resume、checkpoint、吞吐、错误类型分布。  
**输入:** `_llm_release_v2/` + 校准参数  
**输出:** `smoke-1000.jsonl` + `smoke-checkpoints/`  
**验收:** resume 可用，错误分类完整，吞吐 ≥ 50 篇/小时  
**停止:** 吞吐 < 10 篇/小时 / 失败 > 15%  
**GA 监控:** 吞吐趋势，checkpoint 频率，D 盘 I/O

### Phase 3: Full 93K Downstream Batch
**目标:** 对 93,000 篇做全量结构化抽取。  
**输入:** `_llm_release_v2/` + 校准参数  
**输出:** `full-downstream-93k.jsonl` + `full-checkpoints/`  
**验收:** 覆盖率 ≥ 98%，失败 < 5%，可 resume  
**停止:** GPU OOM / 失败 > 15% / 磁盘 < 50GB  
**GA 监控:** 进度比率，失败率，D 盘 I/O，GPU 温度

### Phase 4: Downstream Quality Report
**目标:** 统计 JSON parse rate、实体质量、事件质量、失败分布。  
**输入:** Phase 3 输出  
**输出:** `quality-report.json` + `quality-charts/`  
**验收:** 统计完整，图表可生成，失败原因分类清晰  
**停止:** 数据损坏 / 统计不一致  
**GA 监控:** 报告生成状态，无异常进程

### Phase 5: Graph Candidate Pack
**目标:** 生成 entities/events/venues/djs/edges/evidence 候选包，不写生产库。  
**输入:** Phase 4 输出  
**输出:** `graph-candidate-pack/` (JSON/JSONL)  
**验收:** 实体去重合理，关系可追溯，无冲突 > 10%  
**停止:** 图谱冲突 > 10% / 生成失败  
**GA 监控:** 输出增长，无生产库写入

### Phase 6: Rawwechat Legacy Repair
**目标:** 安全处理 rawwechat stale running，恢复 queued 批次。  
**输入:** `D:/rawwechat_md/markitdown-batch-status.json`  
**输出:** 修复后的 status.json + 恢复日志  
**验收:** stale 清除，queued 恢复，status.json 可解析  
**停止:** status 文件损坏 / 备份丢失  
**GA 监控:** 状态文件变更，无意外删除

### Phase 7: Final Handoff
**目标:** 生成最终报告、handoff、下一阶段计划。  
**输入:** 全部阶段产物  
**输出:** `FINAL_HANDOFF_*.md` + `NEXT_PHASE_PLAN.md`  
**验收:** 所有指标可追溯，计划清晰  
**停止:** 无  
**GA 监控:** 报告完整性

---

## 五、User Stories

### US-001 Baseline Freeze
| 字段 | 内容 |
|------|------|
| **id** | US-001 |
| **title** | Baseline Freeze |
| **priority** | 1 |
| **goal** | 冻结当前产物状态，创建可验证快照 |
| **input** | `_llm_release_v2/`, `qwen3.6-calibration/`, `tmp-downstream-eval/` |
| **output** | `baseline-snapshot.json` |
| **acceptance criteria** | 快照包含文件数/大小/哈希，与实际一致，可重复验证 |
| **stop gates** | 磁盘 < 5GB / 核心文件损坏 |
| **GA monitor checks** | 快照完整性，无意外写入 |
| **human decision required?** | 否 |

### US-002 Downstream Dry-run 100
| 字段 | 内容 |
|------|------|
| **id** | US-002 |
| **title** | Downstream Dry-run 100 |
| **priority** | 2 |
| **goal** | 验证 100 篇下游抽取通畅，确认参数可用 |
| **input** | `_llm_release_v2/` (随机 100 篇) + prompts + 校准参数 |
| **output** | `dry-run-100.jsonl` |
| **acceptance criteria** | 100 条完整记录，JSON valid rate ≥ 90%，无 OOM/超时 |
| **stop gates** | 失败 > 20% / 模型不可用 (3 次重试) |
| **GA monitor checks** | 输出增长，D 盘 I/O 正常 |
| **human decision required?** | 否 |

### US-003 Downstream Smoke 1000
| 字段 | 内容 |
|------|------|
| **id** | US-003 |
| **title** | Downstream Smoke 1000 |
| **priority** | 3 |
| **goal** | 压力测试 1000 篇，验证 resume/checkpoint/吞吐 |
| **input** | `_llm_release_v2/` (1000 篇) + 校准参数 |
| **output** | `smoke-1000.jsonl` + `smoke-checkpoints/` |
| **acceptance criteria** | resume 可用，错误分类完整，吞吐 ≥ 50 篇/小时 |
| **stop gates** | 吞吐 < 10 篇/小时 / 失败 > 15% |
| **GA monitor checks** | 吞吐趋势，checkpoint 频率，GPU 温度 |
| **human decision required?** | 是 (若触发 stop gate) |

### US-004 Full 93K Downstream Batch
| 字段 | 内容 |
|------|------|
| **id** | US-004 |
| **title** | Full 93K Downstream Batch |
| **priority** | 4 |
| **goal** | 全量 93,000 篇结构化抽取 |
| **input** | `_llm_release_v2/` (全量) + 校准参数 |
| **output** | `full-downstream-93k.jsonl` + `full-checkpoints/` |
| **acceptance criteria** | 覆盖率 ≥ 98%，失败 < 5%，可 resume，checkpoint 完整 |
| **stop gates** | GPU OOM / 失败 > 15% / 磁盘 < 50GB |
| **GA monitor checks** | 进度比率，失败率，D 盘 I/O，GPU 温度/VRAM |
| **human decision required?** | 是 (若触发 stop gate 或需调整参数) |

### US-005 Quality Report
| 字段 | 内容 |
|------|------|
| **id** | US-005 |
| **title** | Downstream Quality Report |
| **priority** | 5 |
| **goal** | 统计 JSON parse rate、实体/事件质量、失败分布 |
| **input** | Phase 3 输出 (`full-downstream-93k.jsonl`) |
| **output** | `quality-report.json` + `quality-charts/` |
| **acceptance criteria** | 统计完整，图表可生成，失败原因分类清晰，无数据遗漏 |
| **stop gates** | 数据损坏 / 统计不一致 / 输入文件缺失 |
| **GA monitor checks** | 报告生成状态，无异常进程 |
| **human decision required?** | 否 |

### US-006 Graph Candidate Pack
| 字段 | 内容 |
|------|------|
| **id** | US-006 |
| **title** | Graph Candidate Pack |
| **priority** | 6 |
| **goal** | 生成 entities/events/venues/djs/edges/evidence 候选包 |
| **input** | Phase 4 输出 + quality report |
| **output** | `graph-candidate-pack/` (JSON/JSONL) |
| **acceptance criteria** | 实体去重合理，关系可追溯，冲突 < 10%，不写生产库 |
| **stop gates** | 图谱冲突 > 10% / 生成失败 / 意外写入生产库 |
| **GA monitor checks** | 输出增长，无生产库写入，D 盘 I/O |
| **human decision required?** | 是 (若冲突 > 10% 或需调整去重策略) |

### US-007 Rawwechat Stale Repair
| 字段 | 内容 |
|------|------|
| **id** | US-007 |
| **title** | Rawwechat Stale Repair |
| **priority** | 7 |
| **goal** | 安全处理 stale running，恢复 queued 批次 |
| **input** | `D:/rawwechat_md/markitdown-batch-status.json` |
| **output** | 修复后的 `markitdown-batch-status.json` + 恢复日志 |
| **acceptance criteria** | stale 清除 (running=0)，queued 恢复，status.json 可解析 |
| **stop gates** | status 文件损坏 / 备份丢失 / 解析失败 |
| **GA monitor checks** | 状态文件变更，无意外删除/覆盖 |
| **human decision required?** | 是 (修改 status.json 前必须人工确认) |

### US-008 Rawwechat MarkItDown Resume
| 字段 | 内容 |
|------|------|
| **id** | US-008 |
| **title** | Rawwechat MarkItDown Resume |
| **priority** | 8 |
| **goal** | 恢复 4948 篇 queued MarkItDown 转换 |
| **input** | 修复后的 `markitdown-batch-status.json` + `D:/rawwechat/` |
| **output** | 新增 `.md` 文件 + 更新 status |
| **acceptance criteria** | 转换完成，status 更新，无重复处理 |
| **stop gates** | 磁盘 < 10GB / 转换失败 > 20% / 进程卡死 > 30min |
| **GA monitor checks** | 进度增长，D 盘 I/O，无递归扫描 |
| **human decision required?** | 是 (若触发 stop gate) |

### US-009 Safety Policy Hardening
| 字段 | 内容 |
|------|------|
| **id** | US-009 |
| **title** | Safety Policy Hardening |
| **priority** | 9 |
| **goal** | 固化 D 盘安全规则，防止无边界扫描 |
| **input** | 当前环境配置 + 历史事故记录 |
| **output** | `safety-policy.md` + 环境检查脚本 |
| **acceptance criteria** | 规则文档完整，检查脚本可运行，拦截测试通过 |
| **stop gates** | 规则冲突 / 影响正常业务 |
| **GA monitor checks** | 策略生效状态，无误拦截 |
| **human decision required?** | 是 (策略生效前必须人工审核) |

### US-010 GA Monitor Integration
| 字段 | 内容 |
|------|------|
| **id** | US-010 |
| **title** | GA Monitor Integration |
| **priority** | 10 |
| **goal** | 集成 GA 只读监控，输出定期摘要 |
| **input** | GA Monitor Spec v1 |
| **output** | `GA_MONITOR_SUMMARY_*.md` (每 10 分钟) |
| **acceptance criteria** | 9 项检查完整，格式正确，告警准确，无越权操作 |
| **stop gates** | GA 越权 / 输出格式错误 / 监控中断 > 20min |
| **GA monitor checks** | 自检输出完整性 |
| **human decision required?** | 是 (若 GA 越权或告警) |

### US-011 Final Report and Handoff
| 字段 | 内容 |
|------|------|
| **id** | US-011 |
| **title** | Final Report and Handoff |
| **priority** | 11 |
| **goal** | 生成最终报告、handoff、下一阶段计划 |
| **input** | 全部阶段产物 + 质量报告 + 监控日志 |
| **output** | `FINAL_HANDOFF_*.md` + `NEXT_PHASE_PLAN.md` |
| **acceptance criteria** | 所有指标可追溯，计划清晰，mem0 记录完整 |
| **stop gates** | 无 |
| **GA monitor checks** | 报告完整性 |
| **human decision required?** | 否 |

---

## 六、给 GA Agent 的监控提示词草稿

```markdown
# GA Read-Only Monitor Prompt

你是 WeChat Article Pipeline 的只读监控 Agent。你的唯一职责是定期检查系统状态并输出摘要。

## 硬性禁令 (绝对禁止)
1. 禁止 kill / Stop-Process 任何进程
2. 禁止启动 OpenClaw / AG / Hermes / final_pack / 任何业务任务
3. 禁止修改配置文件 / 环境变量 / 状态文件
4. 禁止删除任何文件 (包括 lock / status / log)
5. 禁止 Get-ChildItem -Recurse 扫描 D:\DDownload 或 D:\aidata
6. 禁止 find /mnt/d/DDownload 或 find /mnt/d/aidata
7. 禁止自动修复 / 重试失败任务
8. 禁止写入生产数据库或任何生产目录

## 每 10 分钟执行以下只读检查
1. 检查 `D:\DDownload\_llm_release_v2\_state\checkpoints\` 最新文件时间
2. 检查运行日志最后修改时间和大小
3. 检查 D 盘 I/O (Get-Volume / Get-Counter)
4. 检查可疑进程 (find, scandisk, 递归扫描)
5. 检查 final_pack 是否意外运行
6. 检查 OpenClaw 是否意外运行
7. 检查 AG 是否意外运行
8. 检查 $env:WECHAT_OCR_COMMAND 是否仍为 PaddleOCR
9. 综合判断是否触发 RED 条件

## 输出格式
写入 `C:\Users\pc\.openclaw\reports\GA_MONITOR_SUMMARY_YYYY-MM-DD.md`

包含:
- 状态: 🟢 GREEN / 🟡 AMBER / 🔴 RED
- 9 项检查结果表格
- 异常说明 (如有)
- 建议人工介入项 (如有)

## 告警规则
- Checkpoint > 30 分钟无新增 → 🟡
- D 盘 Disk Time > 80% → 🔴
- 发现可疑进程 → 🔴
- final_pack/OpenClaw/AG 意外运行 → 🔴
- OCR 非 PaddleOCR → 🔴
- 任意 🔴 触发 → 立即输出摘要并停止后续检查

## 记住
你只是观察者，不是执行者。只读，只报告，不干预。
```

---

**文档版本:** v1  
**状态:** DRAFT — 待人工审核  
**下一步:** 人工审核本计划，确认无破坏性建议后，进入 Phase 0 执行。
