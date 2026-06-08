<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# GA Stage7 架构优化交接报告
**日期**: 2026-04-28
**交接人**: GA (GenericAgent)

---

## 1. 当前判断
- **Stage 1-6**: 已完成 (Hermes)
- **Stage 7 (当前)**: 正在运行，2,848篇完成，97.3%成功率
- **Stage 8-10**: 待推进 (Graph Pack → Vector → Neo4j)
- **阻塞项**: 当前 Qwen3.6-27B 无 speculative decoding，速度~800篇/时

## 2. 已确认路径
| 路径 | 类型 | 状态 |
|-----|------|------|
| `D:\DDownload\_llm_release_v2\articles\` | 输入 | ✅ 63公众号, 93K文章 |
| `D:\downstream_results\` | 输出 | ✅ 2,848篇, 13公众号 |
| `D:\models\Qwen3.6-27B\Qwen3.6-27B-Q4_K_M.gguf` | 主模型 | ✅ 15.7GB |
| `D:\models\Qwen3-1.7B-Q4_K_M.gguf` | Draft模型 | ✅ 1.03GB (已下载) |
| `C:\llama-cpp\config.yaml` | llama-swap配置 | ✅ 待新增spec模型 |
| `C:\llama-cpp\bin\llama-server.exe` | 推理后端 | ✅ v8851, 支持全部spec参数 |

## 3. 已发现的现有架构
- 当前使用 Qwen3.6-27B @ llama-swap:11434，单模型，无 spec
- 下游抽取脚本: run-downstream-llm-batch (旧版，45K失败批次已废弃)
- 当前成功批次: `D:\downstream_results\` (独立运行，97.3%)

## 4. 4模型优化架构
| 模型 | 角色 | 位置 | 状态 |
|-----|------|------|------|
| Qwen3.6-27B | 主抽取 (spec) | 本地 | 🟡 待配置spec |
| Qwen3-1.7B | Foreman/质检 | 本地 | 🟢 就绪 |
| bge-m3 (Mac) | 文章embedding | Mac:11435 | 🔵 参考handoff |
| stella (Mac) | 实体embedding | Mac:11436 | 🔵 参考handoff |

## 5. 创建/修改的文件
| # | 文件 | 说明 |
|---|------|------|
| 1 | docs/stage7/GA_STAGE7_READONLY_AUDIT_2026-04-28.md | 只读审计报告 |
| 2 | docs/stage7/GA_STAGE7_4MODEL_ARCHITECTURE_2026-04-28.md | 4模型分工架构 |
| 3 | docs/stage7/GRAPH_CANDIDATE_SCHEMA_V1.md | 候选Schema定义 |
| 4 | docs/stage7/GA_STAGE7_ACCEPTANCE_GATES_2026-04-28.md | 验收门禁 |
| 5 | docs/stage7/GA_STAGE7_RUNBOOK_2026-04-28.md | 运行手册 |
| 6 | prompts/stage7/00_system_extractor_zh.md | 系统约束提示词 |
| 7 | prompts/stage7/01_article_precheck_foreman_zh.md | Foreman预检提示词 |
| 8 | prompts/stage7/02_main_extract_graph_candidate_zh.md | 主抽取提示词 |
| 9 | prompts/stage7/03_json_repair_zh.md | JSON修复提示词 |
| 10 | prompts/stage7/04_schema_validation_judge_zh.md | Schema验证提示词 |
| 11 | prompts/stage7/05_empty_result_judge_zh.md | 空结果裁判提示词 |
| 12 | prompts/stage7/06_event_relation_refine_zh.md | 事件关系整理提示词 |
| 13 | prompts/stage7/07_entity_merge_candidate_zh.md | 实体合并候选提示词 |
| 14 | docs/stage7/GA_STAGE7_HANDOFF_2026-04-28.md | **本文** |

## 6. 建议下一步 smoke test 命令
```powershell
# 1. 先完成 spec 部署 (修改config.yaml后重启)
# 2. 验证模型上线:
Invoke-RestMethod http://127.0.0.1:11434/v1/models

# 3. Smoke test (100篇):
python scripts/stage7/run_extraction_batch.py --model qwen36-27b-q4-spec-8k --count 100
```

## 7. 风险与禁止事项
- ❌ 不要全量跑93K直到smoke通过
- ❌ 不要覆盖现有 downstream_results
- ❌ 不要让小模型做主抽取
- ❌ 不要让向量模型阻塞抽取管道
- ❌ 不要扫描 D:\aidata 或 D:\DDownload 根目录全递归
- ❌ 不要将 LLM 结果直接写入 Neo4j
- ⚠️ 修改 config.yaml 前先备份

## 8. 是否可以进入小规模100篇smoke
**条件判断**:
- ✅ 输入路径确认
- ✅ 输出路径确认
- ✅ 主模型存在
- ✅ Draft模型存在
- ✅ 推理后端支持 spec
- ⬜ llama-swap config 待修改 (新增spec模型)
- ⬜ 服务重启
- ⬜ 模型上线验证

**结论**: 在完成 spec 模型配置和重启后，可以进入 100 篇 smoke。
