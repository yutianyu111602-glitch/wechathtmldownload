<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Global Data Inventory — WeChat Article Pipeline

**生成时间:** 2026-04-27  
**状态:** 统一口径版  
**用途:** 消除各计划间的数据口径不一致

---

## 1. LLM Release Pack (当前主产物)

| 数据项 | 值 | 路径 | 更新时间 |
|--------|-----|------|----------|
| 文章总数 | 93,000 | D:/DDownload/_llm_release_v2/ | 2026-04-27 |
| Clubs | 63 | manifest.json | 2026-04-27 |
| manifest.json | ✅ 存在 | D:/DDownload/_llm_release_v2/manifest.json | 2026-04-27 |
| index.jsonl | ✅ 93,000 lines | D:/DDownload/_llm_release_v2/index.jsonl | 2026-04-27 |
| 质量分级 | ready/review/blocked | manifest.json | 2026-04-27 |

---

## 2. LLM Artifacts (中间产物)

| 数据项 | 值 | 路径 | 更新时间 |
|--------|-----|------|----------|
| Artifacts 总数 | ~108K | D:/DDownload/_llm_artifacts/ | 2026-04-27 |
| Clubs | 63 | 按 club 分目录 | 2026-04-27 |
| 每篇文章产物 | meta.json, assets.json, rule_extract.json, clean.md, markitdown.raw.md, markitdown.cleaned.md, sidecar.json, sidecar.md, llm_input.md, quality_report.json, poster_ocr.json, background_recall.md, markitdown_warnings.json | {club}/{token}/ | 2026-04-27 |

---

## 3. LLM MD Mirror (Markdown 镜像)

| 数据项 | 值 | 路径 | 更新时间 |
|--------|-----|------|----------|
| MD 文件总数 | ~108K | D:/DDownload/_llm_md/ | 2026-04-27 |
| 与 Artifacts 一致性 | ✅ 一对一匹配 | 按 club/token 镜像 | 2026-04-27 |

---

## 4. Rawwechat (旧管线数据)

| 数据项 | 值 | 路径 | 更新时间 |
|--------|-----|------|----------|
| HTML 文件总数 | 8,095 | D:/rawwechat/ | 2026-04-27 |
| MD 文件总数 | 8,095 (100%) | D:/rawwechat_md/ | 2026-04-27 |
| MarkItDown 状态 | completed | markitdown-batch-status.json | 2026-04-27 |
| succeeded | 4,949 | 本次运行新转换 | 2026-04-27 |
| skipped | 3,146 | MD 已存在, 跳过 | 2026-04-27 |
| failed | 0 | - | 2026-04-27 |
| running | 0 | 无 stale | 2026-04-27 |
| queued | 0 | 无待处理 | 2026-04-27 |
| 耗时 | ~4 小时 8 分钟 | - | 2026-04-27 |
| 数据一致性 | ✅ 100% | HTML/MD 一对一匹配, 30/30 目录一致 | 2026-04-27 |

---

## 5. 校准与评估

| 数据项 | 值 | 路径 | 更新时间 |
|--------|-----|------|----------|
| 校准结果 | 480 rows (4 profiles × 20 samples × 6 rounds) | qwen3.6-calibration/ | 2026-04-27 |
| 最优 profile | stable (temp=0.1, top_p=0.9, max=2048) | qwen3.6-recommended-params.json | 2026-04-27 |
| 下游评估 | 60 evals (3 prompts × 20 samples × 1 model) | tmp-downstream-eval/ | 2026-04-27 |
| 成功率 | 95% (57/60) | eval-matrix-results.jsonl | 2026-04-27 |

---

## 6. 磁盘空间

| 磁盘 | 总容量 | 已用 | 剩余 | 更新时间 |
|------|--------|------|------|----------|
| D: | 16 TB | ~7.4 TB | 8,612 GB | 2026-04-27 |
| C: | - | - | - | 待补充 |

---

## 7. 模型服务

| 数据项 | 值 | 更新时间 |
|--------|-----|----------|
| 模型 | Qwen3.6-27B | 2026-04-27 |
| 服务 | llama-swap:11434 | 2026-04-27 |
| 端点 | http://127.0.0.1:11434/v1/models | 2026-04-27 |
| GPU VRAM | 20 GB free | 2026-04-27 |
| 内存 | 25 GB free | 2026-04-27 |

---

## 8. 历史数据口径差异说明

| 数据项 | 旧口径 | 新口径 | 原因 |
|--------|--------|--------|------|
| _llm_artifacts | 93,253 / ~108K / 93,508 | ~108K | 不同时间点统计, 且引用不同目录 |
| _llm_release | 68,782 / 49 clubs (partial) | 93,000 / 63 clubs | _llm_release (旧 partial) vs _llm_release_v2 (新完整) |
| rawwechat MD | 3146 / 4948 queued | 8095 / 100% completed | MarkItDown 批次已完成 |

**统一规则:**
- 所有引用 LLM 产物时, 统一使用 `_llm_release_v2` (93,000 篇)
- 所有引用 LLM artifacts 时, 统一使用 `_llm_artifacts` (~108K)
- 所有引用 rawwechat 时, 统一使用最新状态 (8095/8095, 100%)

---

## 9. 临时文件清单 (待清理)

### 9.1 tmp-* 目录 (27 个)

| 目录 | 最后修改 | 用途 |
|------|----------|------|
| tmp-batch-input/ | 2026-04-20 | 批次输入测试 |
| tmp-batch-output/ | 2026-04-20 | 批次输出测试 |
| tmp-batch-verification/ | 2026-04-21 | 批次验证 |
| tmp-cli-llm-artifacts/ | 2026-04-21 | CLI LLM 产物 |
| tmp-cli-llm-input/ | 2026-04-21 | CLI LLM 输入 |
| tmp-cli-llm-md/ | 2026-04-21 | CLI LLM Markdown |
| tmp-downstream-eval/ | 2026-04-27 | 下游评估 (保留) |
| tmp-downstream-eval-dryrun-20260422/ | 2026-04-22 | 下游评估 dryrun |
| tmp-dual-track-smoke/ | 2026-04-20 | 双轨冒烟测试 |
| tmp-image-fetch-curl/ | 2026-04-21 | 图片抓取测试 |
| tmp-image-fetch-curl-all/ | 2026-04-21 | 图片抓取全量 |
| tmp-image-fetch-test/ | 2026-04-21 | 图片抓取测试 |
| tmp-inspect-acid/ | 2026-04-21 | ACID 检查 |
| tmp-md-method-comparison/ | 2026-04-21 | MD 方法对比 |
| tmp-md-method-comparison-300/ | 2026-04-21 | MD 方法对比 300篇 |
| tmp-md-method-comparison-large/ | 2026-04-21 | MD 方法对比大量 |
| tmp-order-compare/ | 2026-04-20 | 顺序对比 |
| tmp-out/ | 2026-04-20 | 输出测试 |
| tmp-out-audit/ | 2026-04-20 | 输出审计 |
| tmp-out-npm/ | 2026-04-20 | npm 输出 |
| tmp-pcui-images/ | 2026-04-22 | PCUI 图片 (gpt-image-2 废弃) |
| tmp-runtime-evidence/ | 2026-04-23 | 运行时证据 |
| tmp-sample-batch-input/ | 2026-04-21 | 样本批次输入 |
| tmp-sample-batch-md/ | 2026-04-21 | 样本批次 MD |
| tmp-sample-batch-output/ | 2026-04-21 | 样本批次输出 |
| tmp-site-inspect/ | 2026-04-21 | 站点检查 |
| tmp-smoke-archive-test/ | 2026-04-21 | 归档冒烟测试 |
| tmp-smoke-processing/ | 2026-04-21 | 处理冒烟测试 |
| tmp-stage6-runtime-screens/ | 2026-04-21 | Stage 6 运行时截图 (废弃) |

### 9.2 根目录临时文件

| 文件模式 | 数量 | 说明 |
|----------|------|------|
| tmp-dajiala-*.js/json/html | 6 | dajiala 调试 |
| tmp-debug-*.mjs | 3 | 调试 |
| tmp-gui-screen*.png | 8 | GUI 截图 |
| tmp-final-pack-*.txt | 5 | final pack PID |
| tmp-run-final-pack*.ps1/bat | 3 | final pack 运行脚本 |
| tmp-runtime-import-report.json | 1 | 运行时导入报告 |
| tmp-stage6-runtime-report.json | 1 | Stage 6 运行时报告 |
| tmp-calibration-pid.txt | 1 | 校准 PID |
| tmp-eval-pid.txt | 1 | 评估 PID |
| tmp-product-introduction-extracted.txt | 1 | 产品介绍提取 |
| NIGHT_WATCHER_*.log | 多个 | Night Watcher 日志 |
| NIGHT_WATCHER_*.zip | 多个 | Night Watcher 打包 |
| MEM0_UPLOAD_*.json | 多个 | Mem0 上传 payload |
| MEM0_UPLOAD_*.md | 多个 | Mem0 上传报告 |

### 9.3 Mac 脚本 (Windows 项目不需要)

| 文件 | 说明 |
|------|------|
| mac_port_scan.py | Mac 网络端口扫描 |
| mac_smoke_test.py | Mac 本地 LLM 服务冒烟测试 |

### 9.4 DOUBAO 模板 (旧 prompt 模板)

| 文件 | 说明 |
|------|------|
| DOUBAO_PHASE_0_PROMPT_TEMPLATE.md | Phase 0 |
| DOUBAO_PHASE_1_PROMPT_TEMPLATE.md | Phase 1 |
| DOUBAO_PHASE_2_PROMPT_TEMPLATE.md | Phase 2 |
| DOUBAO_PHASE_3_PROMPT_TEMPLATE.md | Phase 3 |

### 9.5 gpt-image-2 废弃产物

| 路径 | 说明 |
|------|------|
| tmp-pcui-images/ | gpt-image-2 出图产物 |
| docs/superpowers/specs/2026-04-22-pcui-gpt-image-2-prompts.md | prompt pack |
| docs/superpowers/specs/2026-04-22-pcui-gpt-5.4-image-runbook.md | runbook |
| docs/superpowers/specs/2026-04-22-pcui-image-review-note-template.md | review 模板 |

---

## 10. 文档清单 (待整合)

### 10.1 Longrun 计划 (5 个)

| 计划 | 状态 | Stories | 完成度 |
|------|------|---------|--------|
| night-watcher | COMPLETED | 6/6 | 100% |
| wechat-article-pipeline-week-run | RUNNING | 2/14 | 14% |
| super-longrun-v1 | READY | 0/11 | 0% |
| pcui-performance | COMPLETED | 9/9 | 100% |
| wechat-100k-pipeline-performance | RUNNING | 4/25 | 16% |

### 10.2 过期 HANDOFF 文件 (38 个, 待归档)

保留在根目录的 (3 个):
- HANDOFF.md (主 handoff)
- HANDOFF_COMPREHENSIVE_2026-04-26.md (最近综合)
- HANDOFF_2026-04-27_NIGHT_WATCHER_COMPLETED.md (最新 Night Watcher)

其余 35 个移到 docs/handoff-archive/

### 10.3 废弃 docs/superpowers 文档 (8 个, 待移到 historical/)

- specs/2026-04-22-pcui-gpt-image-2-prompts.md
- specs/2026-04-22-pcui-gpt-5.4-image-runbook.md
- specs/2026-04-22-pcui-image-review-note-template.md
- specs/2026-04-22-autonomous-ui-pipeline-takeover-design.md
- specs/2026-04-22-pcui-frontend-handoff-v2.md
- plans/2026-04-22-pcui-redesign-plan.md
- plans/2026-04-23-pcui-ui-performance-pipeline.md
- plans/2026-04-22-autonomous-ui-pipeline-takeover-plan.md

---

## 11. 更新规则

- 每次 major checkpoint 更新本文件
- 数据变更时立即更新
- 所有计划统一引用本文件
- 不再在各计划中重复定义数据口径
