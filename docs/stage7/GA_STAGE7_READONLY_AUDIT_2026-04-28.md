<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# GA Stage7 只读审计报告
**日期**: 2026-04-28
**审计人**: GA (GenericAgent)

---

## 1. 当前目录确认
- 仓库: `C:\code\githubstar\wechathtmldownload`
- 工作目录: `D:\DDownload`
- GA 主目录: `C:\code\githubstar\wechathtmldownload\genericagent-chinese`

## 2. 输入目录
| 路径 | 状态 | 详情 |
|-----|------|------|
| `D:\DDownload\_llm_release_v2\` | ✅ 存在 | 4 items |
| `D:\DDownload\_llm_release_v2\articles\` | ✅ 存在 | **63 个公众号** |
| 样例公众号 | ✅ | 44KW(1443), ABYSS Shanghai(1063), All俱乐部(4374), AURORA BJ(2948), AXIS(3648), byyb(338), Chengdu Community Radio(202), club between(1076), ClubCeliaShanghai(1321), ClubDMT(939) |

## 3. 输出目录
| 路径 | 状态 | 详情 |
|-----|------|------|
| `D:\downstream_results\` | ✅ 存在 | 14 items (13 clubs + state) |
| 当前进度 | ✅ | ~2,848 篇完成, 成功率 ~97.3% |

## 4. 样本文章结构 (每篇6个文件)
| 文件 | 大小范围 | 说明 |
|------|---------|------|
| `llm_input.md` | 78~24KB | 标题+来源+结构化提示+Main Content+Background Recall+Poster OCR |
| `meta.json` | 370~470B | source_type, title, account_name, content_hash, html_length |
| `poster_ocr.json` | 0.5~4KB | backend(easyocr-gpu/none/skipped), blocks, plain_text, candidates |
| `assets.json` | 2.7~16KB | 资源文件清单 |
| `sidecar.json` | 7.4~32KB | 侧车元数据 |
| `quality_report.json` | ~178B | 质量报告 |

## 5. 已有脚本/工具
| 项目 | 路径 | 说明 |
|-----|------|------|
| 仓库完整 | `C:\code\githubstar\wechathtmldownload` | npm项目(wechat-ingest) |
| 现有管道 | COMPREHENSIVE_UNDERSTANDING.md | 完整管道说明 |
| downstream batch status | `D:\DDownload\_downstream_llm\downstream-batch-status.json` | 旧批次(45K失败) |
| 新批次结果 | `D:\downstream_results\` | 2,848篇, 97.3%成功率 |
| 7天长跑状态 | `D:\DDownload\wechat-pipeline-7day-longrun-2026-04-27\` | 历史长跑记录 |

## 6. 已有提示词
- 当前使用的默认 event_extract.compact-json 提示词
- 无独立prompt目录

## 7. 已有Schema
- 当前下游抽取输出JSON格式（无正式schema文档）

## 8. Checkpoint/状态文件
| 文件 | 说明 |
|-----|------|
| `D:\DDownload\.wechat-live-stage-lock.json` | 运行锁 (run-downstream-llm-batch) |
| `D:\DDownload\wechat-article-pipeline-week-run-handoff-20260427\` | 周运行接手包 |
| `D:\DDownload\_downstream_llm\downstream-batch-status.json` | 下游批处理状态 |

## 9. 主要风险
| 风险 | 严重度 | 说明 |
|-----|--------|------|
| meta.json 缺少 publish_time | ⚠️ 中 | publish_time_text/iso 均为空 |
| 大量空内容文章 | ⚠️ 高 | "Untitled" + 78 chars 空文章可能占比较高 |
| OCR backend 不一致 | ⚠️ 中 | easyocr-gpu/none/skipped 三种，部分无OCR |
| 旧批次45K失败 | ⚠️ 参考 | 非当前批次 |
| VRAM 占用高 | ⚠️ 中 | 当前 21.5GB/24GB |
| 模型无spec加速 | ⚠️ 中 | Qwen3.6-27B 无 draft model，~800篇/时 |

## 10. 不要动的项目
- 原 `D:\DDownload\_downstream_llm\` 旧批次：保留作为参考
- 原 `D:\DDownload\wechat-pipeline-*` 历史长跑：保留
- 现有 `downstream_results` 结果：不要覆盖
- llama-swap config 中原有模型定义：只新增，不修改

## 11. 下一步最小修改建议
1. 创建正式 Schema 文档 (GRAPH_CANDIDATE_SCHEMA_V1.md)
2. 优化 4 模型分工架构
3. 拆分提示词体系
4. 新增 spec 模型加速
5. 小规模 smoke test (100篇)
