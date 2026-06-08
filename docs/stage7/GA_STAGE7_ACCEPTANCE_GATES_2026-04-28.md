<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Stage7 验收门禁
**日期**: 2026-04-28

## 1. 输入完整性
| 指标 | 门禁值 | 处置 |
|-----|--------|------|
| 发现文章数 | >= 90,000 | 否则检查输入路径 |
| 可读 llm_input.md | >= 95% | 统计不可读原因 |
| 缺 meta | <= 1% | 输出清单 |
| 缺 poster_ocr | <= 5% | 输出清单 |

## 2. 抽取完整性
| 指标 | 门禁值 | 处置 |
|-----|--------|------|
| processed count | 与发现数一致 | checkpoint验证 |
| candidate json count | >= 90% | 检查失败原因 |
| failed count | <= 5% | 分析失败模式 |
| retryable count | 追踪 | retry队列管理 |

## 3. JSON 质量
| 指标 | 门禁值 |
|-----|--------|
| parse success rate | >= 95% |
| schema pass rate | >= 90% |
| invalid json占比 | <= 5% |

## 4. 内容质量
| 指标 | 门禁值 | 说明 |
|-----|--------|------|
| empty events ratio | <= 40% | 太高说明抽取过保守 |
| empty entities ratio | <= 30% | |
| low confidence ratio | <= 20% | confidence < 0.5 |
| evidence missing ratio | <= 5% | 必须有 evidence |

## 5. 可恢复性
| 条件 | 预期 | 验证方法 |
|-----|------|---------|
| 中断后 resume | 跳过已完成 | 重跑不重复写 |
| temp文件 | 原子 rename | 检查 temp 残留 |
| 重跑一致性 | 不重复写坏结果 | idempotent check |

## 6. 图谱准备度
| 指标 | 门禁值 |
|-----|--------|
| nodes candidate count | >= 10,000 |
| edges candidate count | >= 5,000 |
| claims count | >= 5,000 |
| evidence count | >= 20,000 |
| vector_pending | 跟踪 |
| graph_pack_ready | >= 80% |
