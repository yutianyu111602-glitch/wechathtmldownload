<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# GA Stage7 4模型分工架构
**日期**: 2026-04-28

---

## 核心原则
**不要把 4 个模型当成 4 个聊天机器人，而是当成一条异步工厂流水线。**

## 模型分工

### A. Qwen3.6-27B (Main Extractor)
| 属性 | 值 |
|-----|-----|
| 角色 | 主抽取引擎 |
| 模型 | `D:\models\Qwen3.6-27B\Qwen3.6-27B-Q4_K_M.gguf` (15.7GB) |
| 后端 | llama-swap @ :11434 |
| spec加速 | 待部署: Qwen3-1.7B draft + speculative decoding |
| 目标速度 | ~2000+ tok/s (spec加速后) |

**职责**:
- 读取 `llm_input.md` + `meta.json` + `poster_ocr.json`
- 输出严格 JSON (graph_candidate.v1)
- 抽取 entities, events, relations, claims, topics, time, location
- 每条候选结果带 evidence 追溯
- 不做最终去重，不直接写 Neo4j

**输出**: `D:\downstream_results\candidates\<公众号>\<文章ID>\candidate.v1.json`

### B. Qwen3-1.7B (Foreman / Cheap Judge)
| 属性 | 值 |
|-----|-----|
| 角色 | 轻量前检/质量门 |
| 模型 | `D:\models\Qwen3-1.7B-Q4_K_M.gguf` (1.03GB) |
| 后端 | 同llama-swap (多模型配置) |
| 显存 | <2GB |

**职责**:
- 快速判断文章类型 (访谈/活动公告/评论/新闻/转发/纯图片/无正文/广告)
- 预检 llm_input.md 过短/乱码/重复/OCR噪声高
- 失败分类 (invalid_json / schema_invalid / empty / timeout)
- 轻量 JSON 修复建议 (仅语法，不补事实)
- 给主抽取 prompt 选择 mode
- 给 watcher 生成简短中文摘要

**禁止**:
- ❌ 做最终结构化抽取
- ❌ 覆盖 Qwen3.6 的候选结果
- ❌ 凭空补事实

**输出**: `D:\downstream_results\foreman\<公众号>\<文章ID>\foreman.v1.json`

### C. Mac 向量模型 1: Article Embedding
| 属性 | 值 |
|-----|-----|
| 角色 | 文章级/段落级 embedding |
| 模型 | bge-m3 @ Mac :11435 |
| 后端 | llama-server (参考 mac_vector_mem0_handoff.md) |

**职责**:
- 文章标题/正文/摘要 embedding
- 相似文章检索、去重
- 同主题文章聚类

**输出**: `D:\downstream_results\vectors\article_chunks\`

### D. Mac 向量模型 2: Entity Embedding
| 属性 | 值 |
|-----|-----|
| 角色 | 实体级/事件级 embedding |
| 模型 | stella @ Mac :11436 |
| 后端 | llama-server (参考 mac_vector_mem0_handoff.md) |

**职责**:
- entity name/alias/event title/relation phrase embedding
- 实体合并候选、关系合并候选
- 图谱边去重

**输出**: `D:\downstream_results\vectors\graph_candidates\`

## 流水线架构

```
┌─────────────────────────────────────────────────────────────┐
│ 输入: D:\DDownload\_llm_release_v2\articles\            │
│   └─ <公众号>/<文章ID>/{llm_input.md, meta.json, ocr.json}  │
└──────────┬──────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────┐
│ B. Foreman (Qwen1.7B) │  ← 轻量预检 + 分流
│  article_type, risk,  │
│  extract_mode         │
└──────────┬───────────┘
           │ (预检通过)
           ▼
┌──────────────────────────────┐
│ A. Extractor (Qwen3.6-27B)   │  ← 主抽取 (spec加速)
│  entities, events, relations, │
│  claims, topics, evidence    │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│ B. Post-check (Qwen1.7B)     │  ← JSON校验/失败分类/修复建议
│  schema check, repair,       │
│  empty judge                 │
└──────────┬───────────────────┘
           │ (通过)
           ▼
┌──────────────────────────────┐
│ C/D. Vector (Mac async)      │  ← 异步 embedding
│  article_chunks embedding    │
│  graph_candidates embedding  │
└──────────┬───────────────────┘
           │
           ▼
┌──────────────────────────────┐
│ Graph Candidate Pack         │  ← Neo4j/Gephi 前处理
│ venues.csv / artists.csv     │
│ 边表格 / 实体合并候选        │
└──────────────────────────────┘
```

## 状态机

```
pending → prechecked → extracting → extracted → validated → vector_pending → vectorized → graph_pack_ready
                                              ↘ json_invalid → retrying → extracting
                                              ↘ schema_invalid → retrying → extracting
                                              ↘ empty_but_valid → validated
                                              ↘ failed_terminal
