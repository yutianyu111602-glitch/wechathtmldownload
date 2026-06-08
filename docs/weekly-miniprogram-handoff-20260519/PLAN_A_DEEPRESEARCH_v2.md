# 计划一强化版 v2：周活小程序识别准确率

Updated: 2026-05-19  
Status: **候选研究稿**（HOLD_FOR_HERMES_DECISION，未实施）  
Supersedes: `PLAN_A_WEEKLY_RECOGNITION_ACCURACY.md`（保留 v1 作概要）

## LDR 在线推理证据

| 项 | 值 |
|----|-----|
| 引擎 | local-deep-research-wechat `run-artifact-research.py` |
| 模型 | `deepseek-v4-pro` |
| 端点 | `https://api.deepseek.com` |
| 生成时间 | 2026-05-19T20:50:16 |
| 源包 | `source_pack/weekly_plan_deepresearch_20260519`（10 份文档） |
| 原始报告 | `C:\code\local-deep-research-wechat\data\research_outputs\weekly_plan_a_deepseek_v4_pro_20260519.md` |

---
## 1. 执行摘要

- **核心目标**：在保持“宁可空不可错”与现有 0 hard_fail 门禁前提下，将已发布活动有 lineup 且通过 strict 的比例从 ~39%（40/103）提升至 55–65%，同时消除后端 51 条 CDN URL 行，建立可复现的字段置信分层与 Golden Set 评测闭环。
- **关键措施**：引入字段级置信 schema（show / show_with_hint / hide）与 evidence 溯源；实施 Golden Set 首批 80–120 条人工标注及每周增量；将 repair 阶段由硬清空改为评分制；在 build 层清洗 URL；深化 OCR+L A 硬门·L B 软分·L C 金标三层验证。
- **生产模型策略**：维持 DeepSeek Flash no‑thinking 全量 + Pro no‑thinking 风险行，禁止 thinking‑enabled 用于 JSON 物化 [2]。
- **时间线**：分 P0–P4 共 12 周，首两周产出 Golden Set 与 baseline 报告。
- **风险边界**：不放松 duplicate/source URL 硬门；不引入 LLM 自由 bio；不采用向量猜 lineup 等不可解释方案。

## 2. 现状与根因（证据引用）

### 2.1 当前数字

| 指标 | 数值 | 证据 |
|------|------|------|
| 已发布活动总数 | 103 | `weekly-api-033` [5] |
| 有 lineup（strict 通过） | ~40（约 39%） | [1] 北极星指标推算 |
| missing_lineup 审计计数 | 63/103 | [6] audit materialized |
| backendRawHits（URL） | 51（仅 `description_original_lines`） | [3] 实测结果 |
| visibleHits | 0 | [6] release guardian |
| 发布条数（管道审计另一次） | 104 | [4]（差异源于窗口/时间点，以 103 为准） |
| prefetch 入队 | 8819 | [4] |
| OCR 实跑/跳过 | 94 / 1631 | [4] |
| API 层过滤：outside_date_window | 1613 | [4] |
| blocked_before_publish 账号 | 49 | [4] |

### 2.2 根因链

- **lineup 大量缺失**（61%）：主因并非单纯 LLM 抽取能力不足，而是 **保守 repair 门 + OCR 覆盖率低 + 日期窗口漏斗** 三重叠加。DeepSeek 提取的 lineup 候选在 `repair_weekly_lineup_address_time_fields.py` 阶段被 `bio gate`、`event_context` 硬清空 [1][6]。同时海报 OCR 由于覆盖面窄、仅前 N 图、preflight 阻断，未能提供足够 evidence [1][4]。最终 publication 窗口又过滤了大量旧活动，导致基础集偏小。
- **后端 51 条 URL 行**：OCR/正文拆行后写入了 `description_original_lines`，未在 build 阶段剥离 CDN URL，仅在前端 `format.js` 过滤，造成后端冗余 [3]。
- **缺少置信分层**：当前 pipeline 只有二元判定（展示/不展示），无法对“有部分证据但不够强”的字段进行差异化处理（如 `show_with_hint`），导致大量 borderline 案例直接被藏匿 [1]。
- **无 Golden Set 评测**：没有人工标注的标准集，现有 `evaluate_weekly_deepseek_prompt_matrix.py` 仅基于离线文章分数，无法量化线上精准率、召回率 [2]。

## 3. 目标架构与数据流

```
L0 源       HTML + 海报 ──OCR──> source_evidence.md
                          │
L1 确定性   日期 regex、registry 候选、DJ 邻域
                          │
L2 模型     Flash no-thinking (全量)
                │ 风险行 → Pro no-thinking (yellowpage_gate_v3)
                │ 输出 field_evidence_refs + confidence
                          │
L3 裁决     merge → repair(评分制) → audit(strict)
                │
             build API (清洗 URL) → tier 注入
                │
             CloudRun 只读 /api/v1/weekly/*
                │
             小程序 format.compactItem → UI (分层展示)
```

- **核心改变**：L2 模型输出增加 `confidence` 与 `evidence[]`；L3 repair 从清除改为保留软分；build 增加 URL 过滤器。
- **不变的硬门**：duplicate 0，source URL 硬门，missing_lineup 本身不设置为 hard_fail [1][5]。

## 4. 字段级置信 schema

### 4.1 通用结构

物品化时每条活动字段均附置信对象（JSON），示例：

```json
{
  "itemId": "some-club:event-hash",
  "lineup_artists": {
    "confidence": 0.86,
    "tier": "show",
    "evidence": [
      {
        "type": "ocr",
        "image_id": "img_abc",
        "quote": "DJ LINEUP: A, B, C"
      },
      {
        "type": "body",
        "quote": "w/ Artist A, Artist B"
      }
    ],
    "provenance": "ocr+body"
  },
  "event_time": {
    "confidence": 0.95,
    "tier": "show",
    "evidence": [
      {
        "type": "body",
        "quote": "2026-06-01 22:00"
      }
    ],
    "provenance": "body"
  },
  "address": {
    "confidence": 0.40,
    "tier": "hide",
    "evidence": [],
    "provenance": "none"
  }
}
```

### 4.2 字段定义

| 字段 | 置信度来源 | 三层 tier 判定 |
|------|-----------|----------------|
| `event_time` / `event_date` | regex + 窗口校验 + 非冲突 | confidence≥0.8 → show；0.5‑0.8 → show_with_hint；<0.5 → hide |
| `lineup_artists` | OCR 海报区块 + body cue + registry 邻域 | evidence 非空且无冲突 → show；仅 body cue 或部分匹配 → show_with_hint；无 evidence 或明确否决 → hide [1] |
| `address` | registry 优先 + OCR 地址过滤 | registry/atlas verified → show；OCR 低置信→ hide |
| `bio` / `dj_bio_lines` | 仅 `registry bio_manual` 或 atlas verified | 缺一不可展示（当前恒 [] 不变，需计划二解锁）[5] |
| `venue_name` | 同 address 逻辑 | 有 registry/cue → show；纯 OCR 猜测 → hide |

**provenance 枚举**：`ocr` | `body` | `registry` | `atlas_verified` | `merged` | `none`

## 5. Golden Set 规范

### 5.1 首批构建

- **规模**：80–120 条已发布/候选活动，覆盖 4–5 个城市、有/无 lineup、纯文字/图重/聚合子等类型，确保`title_date_mismatch`、`lineup_noise`、`image_heavy`、`aggregate_child` 四类样本均衡 [1][2]。
- **标注维度**：
  - 活动日期/时间（start/end，误差 0 天为正确）
  - lineup 集合（人名列表）
  - 地址/场地名称
  - 是否应该展示（全局判定：show / show_with_hint / hide）
  - hard_error 标记：若管线 output 明确与标注相悖且展示，计为 hard_error（一票否决该版本）[1]。
- **标注界面/格式**：使用 JSON Lines 文件（`golden_set_v1.jsonl`），每条包含活动 ID、原始文本摘要（脱敏）、标注字段、标注人、时间戳。配备简易 Web 标注工具或 Excel 导入。
- **增流**：每周从当周已发布 & 被过滤活动中随机抽取 20‑30 条补充，并复注，维持总数 120‑150 条，防止过时。

### 5.2 度量闭环

每阶段结束后，跑以下度量：

```
precision = |shown ∩ gold_lineup| / |shown|
recall    = |shown ∩ gold_lineup| / |gold_lineup|
hard_error_rate = (hard_error 活动数) / (gold 总数)
```

目标：精准率 ≥92%，召回率 ≥75% [1]。

## 6. 分阶段 OKR 表

| 阶段 | 周期 | 交付物 | 负责人角色 | 度量 baseline → 目标 | 退出门禁 | 依赖脚本 |
|------|------|--------|------------|----------------------|----------|----------|
| **P0 度量** | 2 周 | Golden Set 80 条、baseline 报告（精准/召回/URL 计数） | 数据标注负责人 + 评测工程师 | 未测 → 精准≥92%? 召回≥75%? | Golden Set inter‑annotator agreement >90%；baseline 报告通过 review | `evaluate_weekly_deepseek_prompt_matrix.py`（扩展金标评测） |
| **P1 证据** | 3 周 | DeepSeek 输出增加 `field_evidence_refs` 与 `confidence`；OCR 覆盖率提升试点；URL 清洗生产上线 | OCR 管道工程师 + 后端 | OCR 实跑从 94/1631 提升到 ≥200 活动有 OCR；backendRawHits 51→0 | 所有模型输出必须包含 `evidence` 且 schema 校验通过；guardian 中 `backendRawHits=0` 升为硬门 [3] | `enrich_weekly_activity_pack_with_deepseek.py`、build 脚本、ocr 脚本 |
| **P2 候选+裁决** | 4 周 | repair 评分制替代硬清空；event_context 评分化；regex 候选器；Pro 风险扩面（有候选但 Flash 空） | 管线工程师 + 产品 | missing_lineup 从 63 降至 ≤45；lineup 精准率≥90%（P0 金标） | repair 改动后不引入 hard_error；audit strict 通过 | `repair_weekly_lineup_address_time_fields.py`、`audit_weekly_lineup_address_time.py`、`enrich_weekly_activity_pack_with_deepseek.py` |
| **P3 展示** | 3 周 | 小程序端根据 tier 展示 `show` / `show_with_hint` / `hide`；verified bio 接口（需计划二下行） | 前端工程师 + 后端 | 有 show_with_hint 的活动≥30%；无硬错 | 前端新 tier 展示通过 UI review；不影响旧版 0 hard_fail | `format.js`、`build_weekly_activity_miniprogram_api.py`、api 层 |
| **P4 闭环** | 持续 | 每周金标增量 + 人工复核 → registry 修正；OCRed 结果回流优化 [1] | 管线 + 图谱团队 | 每周 recall 增速 ≥2% | 无回退，连续 4 周 recall 不降 | 全部 |

**说明**：所有基线数据来自 [1]、[3]、[4]、[6]；目标值基于 [1] 北极星建议适度调整。

## 7. 脚本/模块改造清单

| 脚本 | 优先级 | 改动内容 | 新增测试 |
|------|--------|----------|----------|
| `enrich_weekly_activity_pack_with_deepseek.py` | P1 | 在 `yellowpage_gate_v3` 输出基础上，添加 `confidence` 计算（基于 evidence 密度/类型）与 `evidence[]` 字段；保留 Flash 主干，Pro 风险行不变 [2] | 单元测试：confidence 范围、evidence schema；集成测试：golden 回归 |
| `repair_weekly_lineup_address_time_fields.py` | P2 | 移除 `lineup_cleared` 全局清除；改为按行评分，保留评分 ≥0.6 的 lineup；bio gate 改为降级而非清除 [1] | 测试评分逻辑边界；回归已修复的假阴性案例 |
| `audit_weekly_lineup_address_time.py` | P2 | 纳入 golden set 比对逻辑，输出 hard_error 标记；保留 strict 硬门，增加缺失 lineup 的统计但不成硬 fail [1] | 金标一致性测试；无重复冲突测试 |
| `archive_old/build_weekly_activity_miniprogram_api.py` | P1 | 写入 `description_original_lines` 前增加 URL 清洗（移除 `mmbiz.qpic.cn` 等 CDN 行），规则与 `format.js` DISPLAY_URL_RE 同构 [3] | 验证清洗后 rawHits=0；不误删 cover_image_url |
| `evaluate_weekly_deepseek_prompt_matrix.py` | P0 | 扩展为可接收 golden set 文件，输出精准/召回分字段报告 | 金标评测 cli 测试；对比不同 prompt 效果 |
| `check_weekly_release_guard.ps1` | P1 | 新增门禁：`backendRawHits` 必须为 0 否则阻止发布 [3] | — |

## 8. 评测与回归命令

### 8.1 Golden Set 评测

```powershell
# 运行对 golden_set_v1.jsonl 的评测
python tools\stage7_rewrite\scripts\evaluate_weekly_deepseek_prompt_matrix.py `
  --golden-file D:\downstream_results\golden\golden_set_v1.jsonl `
  --prompt yellowpage_gate_v3 `
  --models deepseek-v4-flash deepseek-v4-pro `
  --output reports\golden_baseline_202605XX.json
```

### 8.2 全量回归（包含 URL 清洗验证）

```powershell
# 运行 guardian，backendRawHits 必须为 0
powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\pc\.codex\skills\huaidj-weekly-release-guardian\scripts\check_weekly_release_guard.ps1 `
  -CurrentReleaseDir D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_YYYYMMDD

# Python 单元测试（管线）
python -m unittest tools.stage7_rewrite.tests.test_weekly_activity_miniprogram_api `
  tools.stage7_rewrite.tests.test_repair_weekly_lineup_address_time_fields `
  tools.stage7_rewrite.tests.test_weekly_activity_deepseek_enrichment -v
```

### 8.3 小程序端回归

```powershell
cd apps\weekly_activity_miniprogram
node --test tests/*.test.cjs
```

## 9. 与计划二的接口点

当前计划一专注于周活管线识别与展示层。与计划二（电子音乐图鉴）的耦合仅限以下契约，具体实现不在本计划展开 [5]：

| 契约点 | 周活侧需求 | 计划二提供 |
|--------|------------|------------|
| Verified artist bio | 需 `dj_bio_lines` 展示，但必须来自可信源 | 提供 Atlas verified bio 下行接口（JSON），含 `artist_id`、`bio_manual`、`image_url`、验证时间戳 |
| Artist name 解析 | 周活 lineup 识别后需确认人名是否存在 | 计划二提供 artist name resolution API（匹配 known alias → canonical id） |
| Venue 信息增强 | `show` tier 地址可附场地描述 | 计划二按 `venue_id` 或 `account_id` 返回 registry 中的场地详情 |
| Golden Set 共享 | 标注中部分边界案例需复盘 | 计划二提供图谱中已知的 DJ 名单以辅助标注一致性 |

**接口格式示例**（计划二需实现）：
`GET /atlas/verify/artist?name=Anyma` → `{ "canonical_id": "...", "verified": true, "bio_manual": "...", "source": "resident_advisor,beatport", "last_updated": "..." }`

周活侧在获取 verified bio 后，将在 API 构建时填充 `dj_bio_lines`（需产品批准）[1][5]。

## 10. 待用户拍板决策表

| 决策项 | 选项 A（推荐） | 选项 B | 依赖/风险 |
|--------|---------------|--------|-----------|
| 1. **URL 清洗位置** | 在 build 层（Python）清洗，与前端规则同步，gate 为 0 [3] | 仅维持前端过滤，不处理后端 | 推荐 A：可降低 payload 浪费，且后端不再携带冗余 |
| 2. **repair 评分制实施强度** | 先试点 2 城市，观察 1 周 golden 回归后全量 | 直接全量推 | 推荐 A：保守，避免一次引入大量硬错误 |
| 3. **OCR 投入力度** | 牺牲部分非优先账号，集中海报 OCR 给 top 50 账号 | 对所有文章无差别 OCR | 推荐 A：有限算力下提升高价值活动证据 [4] |
| 4. **show_with_hint 的 UI 形态** | 前端在 lineup 空缺处显示“部分艺人待确认，查看原文”，并指向 source 页 | 直接降级到 hide（维持现状） | 需产品与设计评审；推荐 A 可在不误导前提下提升信息量 |
| 5. **bio 展示解锁时机** | 待计划二 verified 接口可用且通过 2 周回测后开放 | 解锁但允许直接展示 DeepSeek 生成的 bio | 禁止 B，因为违原则 [1]；推荐 A 符合图谱下行策略 [5] |

---

*此文档为候选研究，所有变更需经用户审批后进入实施，当前状态：**HOLD_FOR_HERMES_DECISION**。*
