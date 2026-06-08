<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Board Discussion — Super Long Run v1 统一口径

**日期:** 2026-04-27  
**模式:** 蜂群分析 + 自主决策  
**参与:** Qwen3.6-27B (规划), 6 个 subagent (扫描)

---

## Round 1: Facts (事实)

### 1.1 代码事实 (subagent: 新管线代码分析)

- **项目:** wechat-ingest v0.1.0, TypeScript ESM + Electron + Python sidecar
- **核心管线:** Stage 0-6 (FETCH → ARCHIVE → ASSETS → PROCESS → EXPORT → PACK → DOWNSTREAM)
- **双轨处理:** Track A (cheerio 规则提取) + Track B (MarkItDown 转换)
- **入口:** src/cli.ts (1215行, 26 个命令)
- **测试:** 58 个测试文件, Node.js 内置 test runner
- **状态管理:** SQLite (better-sqlite3) + JSONL manifest
- **问题:**
  - cli.ts 过长, 应拆分为命令注册表
  - 类型重复 (BatchSnapshot vs ArchiveBatchSnapshot)
  - 硬编码路径 (D:/rawwechat, D:/DDownload)
  - 错误处理不一致
  - 工具函数重复定义 (toStringValue, toNumberValue, nowIso)

### 1.2 旧管线事实 (subagent: 旧管线代码分析)

- **三代管线:**
  1. loopy-archiver (Python + Playwright, 外部项目 C:\code\loopy-archiver)
  2. rawwechat MarkItDown (D:/rawwechat → D:/rawwechat_md)
  3. 当前管线 (mptext API + TypeScript dual-track)
- **临时文件泛滥:**
  - 27 个 tmp-* 目录 (可安全清理)
  - 38 个 HANDOFF .md 文件 (大部分过期)
  - Mac 脚本 (mac_port_scan.py, mac_smoke_test.py)
  - DOUBAO 模板 (4 个)
  - gpt-image-2 废弃产物
- **genericagent-chinese/:** 独立旧项目, 含 .git/, 与当前管线无关
- **rawwechat 脚本:** package.json 中 6 个 export:rawwechat-* 脚本

### 1.3 文档事实 (subagent: 计划文档分析)

- **5 个 longrun 计划:**
  1. night-watcher: COMPLETED (6/6 stories pass)
  2. wechat-article-pipeline-week-run: RUNNING (US-001, US-002 完成)
  3. super-longrun-v1: DRAFT (纯规划)
  4. pcui-performance: COMPLETED (9/9 stories)
  5. wechat-100k-pipeline-performance: RUNNING (iteration 10)
- **口径不一致:**
  - night-watcher 双 prd.json (新版 passes=true, 旧版 passes=false)
  - super-longrun-v1 重复文档 (01 和 02 内容一致)
  - 数据口径漂移 (_llm_artifacts: 93,253 / ~108K / 93,508)
  - 3 份守夜手册重叠
- **缺失文档:**
  - night-watcher 缺失最终报告
  - super-longrun-v1 缺失 prd.json 和 execution-plan
  - 多个计划缺失 loop handoff

### 1.4 产物事实 (subagent: 产物状态分析)

- **D:/DDownload/_llm_release_v2/:** 93,000 篇, manifest.json + index.jsonl
- **D:/DDownload/_llm_artifacts/:** 108K+ artifacts
- **D:/DDownload/_llm_md/:** Markdown 镜像
- **磁盘空间:** D 盘 8,612GB 剩余

### 1.5 rawwechat 事实 (subagent: rawwechat 状态分析)

- **状态:** COMPLETED (8095/8095, 100%)
- **succeeded:** 4949 (新转换)
- **skipped:** 3146 (已有 .md)
- **failed:** 0
- **running:** 0 (无 stale)
- **queued:** 0 (无待处理)
- **耗时:** ~4 小时 8 分钟
- **数据一致性:** 100% (HTML/MD 一对一匹配, 30/30 目录一致)
- **结论:** Phase 6 (Rawwechat Legacy Repair) 不需要了

### 1.6 Tools 脚本事实 (subagent: tools 脚本分析)

- **29 个脚本:** 24 .mjs, 2 .ps1, 1 .py, 1 rust/
- **分类:**
  - OCR: 4 个 (paddle, openai, python runner, quality check)
  - OCR 修复: 2 个 (repair corrupted, repair none backend)
  - 监控: 3 个 (watch export, watch archive, watch markitdown)
  - PCUI: 8 个 (screenshot, performance, interaction, audit, gpt image)
  - LLM 评估: 2 个 (eval matrix, calibration)
  - GPT Image: 2 个 (generate, prompts)
  - 数据辅助: 4 个 (github recommendations, experiment)
  - 其他: 4 个

---

## Round 2: Conflicts (冲突)

### 2.1 Phase 6 冲突

- **super-longrun-v1 Phase 6:** Rawwechat Legacy Repair (8095 篇恢复)
- **实际状态:** rawwechat 已 100% 完成, 无需修复
- **决策:** Phase 6 需要重新定义

### 2.2 文档冗余

- **01-super-longrun-plan-v1.md vs 02-super-longrun-plan-user-echo.md:** 内容完全一致
- **决策:** 合并为单一文件, 02 归档到 archive/

### 2.3 数据口径

- **_llm_artifacts 数量:** 93,253 / ~108K / 93,508 (三个计划不同数字)
- **原因:** 不同时间点统计, 且引用不同目录 (_llm_release vs _llm_release_v2 vs _llm_artifacts)
- **决策:** 建立全局数据清单, 统一口径

### 2.4 代码问题优先级

- **cli.ts 1215行:** 应拆分, 但不是当前紧急任务
- **硬编码路径:** 影响可移植性, 应在后续重构
- **类型重复:** 技术债, 不影响功能
- **决策:** 代码问题记录为技术债, 不在当前长跑中处理

---

## Round 3: Decisions (决策)

### 3.1 Phase 6 重新定义

**原 Phase 6:** Rawwechat Legacy Repair (8095 篇恢复)  
**新 Phase 6:** Temp Files Cleanup & Documentation Consolidation

**目标:** 清理临时文件, 归档过期文档, 统一文档口径

**理由:**
- rawwechat 已完成, 无需修复
- 27 个 tmp-* 目录占用空间且混乱
- 38 个 HANDOFF 文件大部分过期
- 文档口径不一致影响后续 agent 理解

### 3.2 新增 Phase 8: Code Quality Baseline

**目标:** 建立代码质量基线, 记录技术债, 不修改代码

**内容:**
- 记录 cli.ts 拆分需求
- 记录类型重复问题
- 记录硬编码路径清单
- 记录错误处理不一致问题
- 生成 TECH_DEBT.md

### 3.3 文档统一规则

1. **单一真相源:** manifest.md 为每个计划的唯一入口
2. **prd.json 位置:** 统一放在 longrun 子目录内, 不使用 .omc/ralph/
3. **数据口径:** 在 super-longrun-v1 manifest 中建立全局数据清单
4. **历史文档:** 移到 archive/ 子目录, 标记 historical
5. **重复文档:** 合并或删除, 保留最新版本

### 3.4 清理优先级

| 优先级 | 类别 | 操作 | 风险 |
|--------|------|------|------|
| P0 | 27 个 tmp-* 目录 | 删除 | 低 |
| P0 | 根目录临时文件 | 删除 | 低 |
| P1 | 过期 HANDOFF 文件 | 归档到 docs/handoff-archive/ | 低 |
| P1 | 废弃 docs/superpowers 文档 | 移到 historical/ | 低 |
| P2 | Mac 脚本 | 删除 | 低 |
| P2 | DOUBAO 模板 | 删除 | 低 |
| P2 | gpt-image-2 产物 | 删除 | 低 |
| P3 | genericagent-chinese/ | 确认后移除 | 中 |
| P3 | rawwechat package.json 脚本 | 确认后清理 | 中 |

### 3.5 管线运行方式决策

**当前最佳实践:**
1. **直接 CLI 执行** (不依赖 OpenClaw cron)
2. **前台 PowerShell** (不 Start-Process 包装)
3. **可见日志输出** (可随时 Ctrl+C 中断)
4. **checkpoint 持久化** (支持中断恢复)
5. **failure_budget=3** (同一 story 最多修复 3 次)
6. **每 3 个 story 一次 major checkpoint**

**模型参数 (已校准):**
- model: Qwen3.6-27B
- temperature: 0.1
- top_p: 0.9
- max_tokens: 2048
- timeout_ms: 180000

---

## 结论

1. Phase 6 重新定义为清理和文档整合
2. 新增 Phase 8: 代码质量基线
3. 统一文档规则 (manifest 入口, prd.json 位置, 数据口径)
4. 清理优先级已确定 (P0-P3)
5. 管线运行方式已确定 (直接 CLI, 前台, 可见日志, checkpoint)

**下一步:** 生成统一 PRD → Ralph prd.json → 大计划
