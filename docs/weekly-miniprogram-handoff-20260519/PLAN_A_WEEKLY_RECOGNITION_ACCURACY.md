# 计划一：周活小程序识别准确率优化

Updated: 2026-05-19  
Scope: HUAIDJ weekly mini-program only  
Status: **设计稿**（未实施）

## 1. 目标与原则

| 原则 | 含义 |
|------|------|
| 宁可空，不可错 | 保持大众产品信任 |
| 可证明才展示 | 每条字段可指回 evidence（正文或 `ocr:img_*`） |
| 分层置信 | show / show_with_hint / hide |
| 评测驱动 | 无 golden set 不宣称「更准」 |

### 北极星指标（建议）

| 指标 | 当前粗估 | 12 周目标（示例） |
|------|----------|-------------------|
| 已发布活动有 lineup 且 strict 通过 | ~39%（40/103） | 55–65% |
| lineup 精确率（golden） | 未测 | ≥92% |
| lineup 召回率（golden） | 未测 | ≥75% |
| 时间/地址精确率 | Flash date 0.73–0.90 | ≥90%（有 OCR 子集） |
| backend raw URL hits | 51 | 0 |

## 2. 现状诊断

### 漏斗（示意）

Prefetch ~8800 → Pack ~1500 → OCR 实跑少（大量 skip）→ DeepSeek → API 过滤 → 发布 ~103 → 有 lineup ~40

### 损失点

| 阶段 | 问题 |
|------|------|
| 召回 | outside_date_window、blocked 账号 |
| OCR | 覆盖低；仅前 N 图；preflight 阻断 |
| DeepSeek | unsupported lineup 被 merge 砍；lineup_weak_evidence |
| repair | bio gate、event_context 过严 → **假阴性** |
| API | `dj_bio_lines: []` 写死 |
| 展示 | format.js 再过滤 |

**结论**：需要 **证据链 + 分字段置信 + golden 闭环**，不是单纯加强 prompt。

## 3. 目标架构

```
L0 源: HTML + 海报 → OCR → source_evidence.md
L1 确定性: 日期 regex、registry、lineup 候选（w/DJ 邻域）
L2 模型: Flash 全量 + Pro 风险行 → JSON + field_evidence_refs
L3 裁决: merge → repair → audit → published + display_tier
```

### 置信对象（概念）

```yaml
field: lineup_artists
confidence: 0.86
tier: show | show_with_hint | hide
evidence:
  - { type: ocr, image_id: img_abc, quote: "..." }
  - { type: body, quote: "w/ Artist A" }
```

## 4. 分字段策略

### 4.1 日期

- Regex + 标题范围 + 窗口校验；冲突日期禁止 dedupe 合并
- Golden：start/end 误差 0 天为对

### 4.2 Lineup（核心）

| 子策略 | 说明 |
|--------|------|
| B1 海报结构化 OCR | lineup 区 / 日期区 / 地址区分块 |
| B2 Regex 候选器 | LLM 只做裁决，不发明 |
| B3 event_context 评分制 | 替代硬清空阈值 |
| B4 Bio gate 按行打分 | 保留巡演/专场 cue |
| B5 Pro 触发扩面 | 有候选但 Flash 空 → Pro |
| B6 聚合子活动 | 子文 lineup 禁止继承父 marketing |

### 4.3 Bio / DJ 图

- 自动 bio：**仅** registry `bio_manual` 或图谱 verified
- DJ 图：poster 裁剪 + `image_id` 溯源
- API 层 `dj_bio_lines` 解锁需产品批准 + verified 管道

### 4.4 场地 / 风格 / 票价

- registry 优先；OCR 地址 garbage 过滤
- 风格仅显式字段 + 词典；票价 regex

## 5. OCR + LLM 准确性判定

### 三层验证

| 层 | 方法 |
|----|------|
| L-A 硬门 | audit strict、duplicate 0、source URL |
| L-B 软分 | confidence → tier |
| L-C 金标 | 每周 50–100 条人工标注 |

### 度量

```
precision = |shown ∩ gold| / |shown|
recall    = |shown ∩ gold| / |gold|
hard_error = gold 明确否决仍展示 → 一票否决
```

### OCR 门

| 信号 | 动作 |
|------|------|
| 低置信 + 图多文少 | needs_ocr_review，不发布 |
| OCR vs 正文时间冲突 | Pro → 仍冲突则 hide time |

## 6. 路线图

| 阶段 | 周期 | 交付 |
|------|------|------|
| P0 度量 | 2 周 | Golden 80 条 + baseline 报告 |
| P1 证据 | 3 周 | field_evidence_refs 强制；OCR A/B |
| P2 候选+裁决 | 4 周 | Regex 候选器；event_context 评分 |
| P3 展示 | 3 周 | tier UI；verified bio |
| P4 闭环 | 持续 | 每周人工复核 → registry |

## 7. 明确不做

- LLM 自由 bio
- 无 evidence lineup 展示
- 放松 duplicate / source URL 硬门

## 8. 依赖文件

- `enrich_weekly_activity_pack_with_deepseek.py`
- `archive_old/enrich_weekly_activity_pack_with_poster_ocr.py`
- `archive_old/build_weekly_activity_miniprogram_api.py`
- `repair_weekly_lineup_address_time_fields.py`
- `audit_weekly_lineup_address_time.py`
- `evaluate_weekly_deepseek_prompt_matrix.py`
