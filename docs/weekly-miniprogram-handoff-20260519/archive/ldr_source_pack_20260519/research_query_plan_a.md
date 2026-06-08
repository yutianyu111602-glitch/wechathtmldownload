# LDR 深度研究任务 — 计划一：周活小程序识别准确率

角色：资深数据管线架构师 + OCR/LLM 评测工程师 + 微信小程序产品工程师。

## 硬约束（必须遵守）

1. **只根据 source_pack 内文件**回答；不得臆造运行结果、条数、部署版本。
2. 当前权威事实（若 source 中有更新以 source 为准）：`weekly-api-033`，103 条，`2026-05-19..2026-06-02`；backendRawHits=51 URL；missing_lineup 约 63/103；visibleHits=0。
3. 产品原则：**宁可空不可错**；无 evidence 不展示 lineup/bio；**不得**建议放松 duplicate/source URL 硬门。
4. DeepSeek 生产策略（来自 matrix）：Flash no-thinking 全量 + Pro no-thinking 风险行；**禁止** thinking-enabled 用于 JSON 物化。
5. 输出为 **candidate research**，最终需 HOLD_FOR_HERMES_DECISION；不得当作已实施变更。

## 研究目标

在现有 `PLAN_A_WEEKLY_RECOGNITION_ACCURACY.md` 基础上，产出**可落地、可验收**的强化版实施计划 v2，重点：

1. **字段级置信 schema**（YAML/JSON 示例）：`field`, `confidence`, `tier` (show/show_with_hint/hide), `evidence[]`, `provenance` (ocr/body/registry/atlas_verified)
2. **Golden Set 规范**：80–120 条首批标注维度、标注界面/文件格式、每周增量流程、hard_error 定义
3. **分阶段 OKR（P0–P4）**：每阶段 2–4 周；交付物、负责人角色、退出门禁、依赖脚本路径
4. **现有脚本映射表**：`enrich_weekly_activity_pack_with_deepseek.py`, `repair_weekly_lineup_address_time_fields.py`, `audit_weekly_lineup_address_time.py`, `build_weekly_activity_miniprogram_api.py`, `evaluate_weekly_deepseek_prompt_matrix.py` — 每项改什么、加什么测试
5. **OCR+LLM 三层验证**细化：L-A 硬门 / L-B 软分 / L-C 金标；与 `yellowpage_gate_v3` 对齐
6. **URL 51 债**：build 层清洗方案（不改 format.js 掩盖）
7. **风险与不做清单**：明确拒绝的方案（LLM 自由 bio、向量猜 lineup 等）

## 输出结构（Markdown）

1. 执行摘要（5 条以内）
2. 现状与根因（证据引用 source 文件名）
3. 目标架构与数据流（可用 ASCII）
4. 字段置信 schema（完整示例）
5. Golden Set 规范
6. 分阶段 OKR 表（含度量 baseline→目标）
7. 脚本/模块改造清单（优先级 P0/P1/P2）
8. 评测与回归命令（PowerShell/python 示例）
9. 与计划二的接口点（仅契约，不展开图鉴实现）
10. 待用户拍板决策表（≤5 项）

请用**简体中文**撰写，技术术语可保留英文。篇幅充实但避免重复 handoff 全文。
