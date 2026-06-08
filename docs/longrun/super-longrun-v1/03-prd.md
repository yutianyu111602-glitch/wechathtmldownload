<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# PRD: WeChat Article Pipeline Super Long Run v1 (统一口径版)

**生成时间:** 2026-04-27  
**状态:** FROZEN  
**来源:** Board Discussion 2026-04-27

---

## 1. Introduction

在 night-watcher 完成 93,000 篇 LLM release pack 后, 需要继续推进下游结构化抽取、质量报告、图谱候选包生成。同时, rawwechat MarkItDown 已 100% 完成 (8095/8095), 原 Phase 6 需要重新定义。

本 PRD 统一所有计划口径, 重新规划 Phase 0-8, 并建立文档和代码质量基线。

---

## 2. Goals

- 完成 93,000 篇下游结构化抽取 (entities/events/venues/djs)
- 生成质量报告和图谱候选包
- 清理临时文件和过期文档
- 统一文档口径和代码质量基线
- 建立可长期执行的管线运行规范

---

## 3. User Stories

### US-001: Baseline Freeze
**描述:** 冻结当前产物状态, 创建可验证快照

**验收标准:**
- [ ] 生成 baseline-snapshot.json (文件数/大小/哈希)
- [ ] 快照与实际一致, 可重复验证
- [ ] D 盘剩余空间 ≥ 100GB
- [ ] 无意外写入

**优先级:** 1  
**依赖:** 无

### US-002: Downstream Dry-run 100
**描述:** 从 93K release pack 中抽取 100 篇跑结构化下游抽取, 验证 pipeline 通畅

**验收标准:**
- [ ] 100 条完整 JSONL 记录
- [ ] JSON valid rate ≥ 90%
- [ ] 无 OOM/超时
- [ ] 输出文件: dry-run-100.jsonl

**优先级:** 2  
**依赖:** US-001

### US-003: Downstream Smoke 1000
**描述:** 跑 1000 篇, 验证 resume、checkpoint、吞吐、错误类型分布

**验收标准:**
- [ ] 1000 条完整 JSONL 记录
- [ ] resume 可用 (中断后可继续)
- [ ] 错误分类完整
- [ ] 吞吐 ≥ 50 篇/小时
- [ ] 输出文件: smoke-1000.jsonl + smoke-checkpoints/

**优先级:** 3  
**依赖:** US-002

### US-004: Full 93K Downstream Batch
**描述:** 对 93,000 篇做全量结构化抽取

**验收标准:**
- [ ] 覆盖率 ≥ 98%
- [ ] 失败率 < 5%
- [ ] 可 resume
- [ ] checkpoint 完整
- [ ] 输出文件: full-downstream-93k.jsonl + full-checkpoints/

**优先级:** 4  
**依赖:** US-003

### US-005: Quality Report
**描述:** 统计 JSON parse rate、实体/事件质量、失败分布

**验收标准:**
- [ ] 统计完整
- [ ] 图表可生成
- [ ] 失败原因分类清晰
- [ ] 无数据遗漏
- [ ] 输出文件: quality-report.json + quality-charts/

**优先级:** 5  
**依赖:** US-004

### US-006: Graph Candidate Pack
**描述:** 生成 entities/events/venues/djs/edges/evidence 候选包

**验收标准:**
- [ ] 实体去重合理
- [ ] 关系可追溯
- [ ] 冲突 < 10%
- [ ] 不写生产库
- [ ] 输出文件: graph-candidate-pack/ (JSON/JSONL)

**优先级:** 6  
**依赖:** US-005

### US-007: Temp Files Cleanup
**描述:** 清理 27 个 tmp-* 目录和根目录临时文件

**验收标准:**
- [ ] 27 个 tmp-* 目录已删除
- [ ] 根目录 tmp-*.png/txt/json/ps1/bat/mjs/js/html 已删除
- [ ] Mac 脚本已删除
- [ ] DOUBAO 模板已删除
- [ ] gpt-image-2 产物已删除
- [ ] NIGHT_WATCHER 日志/zip 已删除
- [ ] MEM0 上传文件已删除
- [ ] 不影响任何功能

**优先级:** 7  
**依赖:** 无

### US-008: Documentation Consolidation
**描述:** 归档过期文档, 统一文档口径

**验收标准:**
- [ ] 过期 HANDOFF 文件归档到 docs/handoff-archive/
- [ ] 废弃 docs/superpowers 文档移到 historical/
- [ ] 重复文档合并或删除
- [ ] 建立全局数据清单 (GLOBAL_DATA_INVENTORY.md)
- [ ] 所有 prd.json 统一位置
- [ ] manifest.md 为每个计划唯一入口

**优先级:** 8  
**依赖:** 无

### US-009: Code Quality Baseline
**描述:** 建立代码质量基线, 记录技术债

**验收标准:**
- [ ] 生成 TECH_DEBT.md
- [ ] 记录 cli.ts 拆分需求
- [ ] 记录类型重复问题
- [ ] 记录硬编码路径清单
- [ ] 记录错误处理不一致问题
- [ ] 不修改代码

**优先级:** 9  
**依赖:** 无

### US-010: GA Monitor Integration
**描述:** 集成 GA 只读监控, 输出定期摘要

**验收标准:**
- [ ] 9 项检查完整
- [ ] 格式正确
- [ ] 告警准确
- [ ] 无越权操作
- [ ] 输出文件: GA_MONITOR_SUMMARY_*.md (每 10 分钟)

**优先级:** 10  
**依赖:** 无

### US-011: Final Report and Handoff
**描述:** 生成最终报告、handoff、下一阶段计划

**验收标准:**
- [ ] 所有指标可追溯
- [ ] 计划清晰
- [ ] mem0 记录完整
- [ ] 输出文件: FINAL_HANDOFF_*.md + NEXT_PHASE_PLAN.md

**优先级:** 11  
**依赖:** US-001 ~ US-010

---

## 4. Functional Requirements

### FR-1: 管线运行规范
- 直接 CLI 执行 (不依赖 OpenClaw cron)
- 前台 PowerShell (不 Start-Process 包装)
- 可见日志输出 (可随时 Ctrl+C 中断)
- checkpoint 持久化 (支持中断恢复)
- failure_budget=3 (同一 story 最多修复 3 次)
- 每 3 个 story 一次 major checkpoint

### FR-2: 模型参数
- model: Qwen3.6-27B (llama-swap:11434)
- temperature: 0.1
- top_p: 0.9
- max_tokens: 2048
- timeout_ms: 180000

### FR-3: D 盘安全规则
- 禁止 find /mnt/d/DDownload 或 /mnt/d/aidata
- 禁止 Get-ChildItem -Recurse 扫描 D:\DDownload 或 D:\aidata
- 禁止任何无边界递归遍历 16T HDD
- 仅允许按 club/article 路径精确访问
- 发现可疑扫盘进程立即记录并告警, 不自动 kill

### FR-4: OCR Backend Policy
- 主链: PaddleOCR (tools/ocr-image-paddle.ps1)
- 禁止自动 fallback 到 EasyOCR
- 禁止修改 WECHAT_OCR_COMMAND 环境变量
- PaddleOCR 输出必须符合 TypeScript 契约: box / score

### FR-5: 文档统一规则
- manifest.md 为每个计划的唯一入口
- prd.json 统一放在 longrun 子目录内
- 历史文档移到 archive/ 子目录
- 重复文档合并或删除

---

## 5. Non-Goals

- 不修改 cli.ts 架构 (记录为技术债)
- 不重构类型系统 (记录为技术债)
- 不修改硬编码路径 (记录为技术债)
- 不启动 OpenClaw / AG / Hermes 作为主控
- 不重跑 Stage 0-6
- 不引入 Mac M3 Pro / 向量模型
- 不自动写入生产库
- 不递归扫描 D:\DDownload / D:\aidata

---

## 6. Technical Considerations

### 6.1 已知约束
- D 盘为 16T 氦气机械盘, 高 I/O 会导致炒豆子
- GPU VRAM 20GB, 需控制并发
- 模型通过 llama-swap:11434 提供, 需确保服务可用

### 6.2 集成点
- 下游 LLM 调用通过 OpenAI 兼容 API
- OCR 通过 PaddleOCR GPU 本地运行
- 状态管理通过 SQLite (better-sqlite3)

### 6.3 性能要求
- 下游抽取吞吐 ≥ 50 篇/小时
- 失败率 < 5%
- 覆盖率 ≥ 98%

---

## 7. Success Metrics

- 93,000 篇下游抽取完成
- 质量报告生成
- 图谱候选包生成
- 临时文件清理完成
- 文档口径统一
- 代码质量基线建立
- GA 监控集成
- 最终报告生成

---

## 8. Risks

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| GPU OOM | 高 | 控制并发, 监控 VRAM |
| 模型不可用 | 高 | 3 次重试, 失败后停止 |
| D 盘高 I/O | 高 | 禁止递归扫描, 精确路径访问 |
| 磁盘空间不足 | 高 | 启动前检查 ≥ 100GB |
| 状态文件损坏 | 中 | 备份, 人工审计 |
| 失败率超标 | 中 | failure_budget=3, 停止并 handoff |

---

## 9. Open Questions

- 无 (所有决策已在 Board Discussion 中自主完成)
