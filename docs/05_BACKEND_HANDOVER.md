# 后端管道接手文档 — 05_BACKEND_HANDOVER.md

项目: wechat-ingest pipeline + Stage7 + CloudRun
更新: 2026-06-10

## 一、管道架构总览

本项目后端非传统 Django/Express 服务，而是**多阶段数据管道**：

```
L0 采集 → L1 Markdown → L2 LLM提取 → L3 合并 → L4 源库 → L5 服务库 → L6 消费
```

## 二、Node.js 核心管道 (src/)

| 模块 | 入口 | 职责 |
|---|---|---|
| cli.ts | 主 CLI | 所有管道命令的统一入口 |
| historyCli.ts | 历史 URL CLI | WeChat 历史文章 URL 抓取 |
| archive/ | - | 文章归档 (HTML/图片保留) |
| mptext/ | - | mptext 协议采集 |
| dajiala/ | - | Dajiala 归档修复重建 |
| llm/ | - | LLM 批处理导出 |
| markitdown/ | - | MarkItDown HTML→MD 转换 |
| pipeline/ | - | 管道编排 |
| desktop/ | main.mjs | Electron 桌面应用 |

### 关键 npm scripts

```json
"build": "tsc -p tsconfig.json"
"process-article": "tsx src/cli.ts process-article"
"archive-batch": "tsx src/cli.ts archive-batch"
"export-markitdown-batch": "tsx src/cli.ts export-markitdown-batch"
"export-llm-batch": "tsx src/cli.ts export-llm-batch"
"finalize-llm-pack": "tsx src/cli.ts finalize-llm-pack"
```

## 三、Python Stage7 管道 (tools/stage7_rewrite/)

核心数据提取与合并阶段。

### 目录结构

| 路径 | 内容 |
|---|---|
| scripts/ | 500+ Python 脚本 (build/validate/run/write) |
| tests/ | 300+ pytest 测试 |
| reports/ | 运行报告和输出数据 (数千子目录) |
| stage7/ | Stage7 核心逻辑 |
| weekly_atlas_bridge/ | 周度 Atlas 桥接 |
| docker/ | Docker 部署配置 |
| config/ | 管道配置 |

### 核心脚本模式

脚本命名遵循严格的动词-名词约定：

| 前缀 | 含义 | 示例 |
|---|---|---|
| build_ | 构建数据包/队列 | build_atlas_dj_identity_review_workbench.py |
| run_ | 执行操作 | run_atlas_db2_outlink_autowake.py |
| validate_ | 验证数据 | validate_weekly_current_release_drift.py |
| test_ | 测试脚本对应 | test_build_atlas_dj_identity_review_workbench.py |
| apply_ | 应用变更 | apply_weekly_confirmed_venue_locks.py |
| audit_ | 审计检查 | audit_atlas_db_field_contract.py |
| recover_ | 恢复修复 | recover_external_identity_source_context.py |

### 测试运行

```bash
# 全部测试 (300+)
python -m pytest tools/stage7_rewrite/tests/ -q --timeout=30

# 单个测试
python -m pytest tools/stage7_rewrite/tests/test_build_atlas_dj_completion_*.py -q
```

## 四、CloudRun 服务 (services/weekly_activity_cloudrun/)

微信小程序的 API 后端，部署在腾讯云 CloudRun。

### 目录结构

| 路径 | 内容 |
|---|---|
| src/ | API 路由和业务逻辑 |
| data/ | 静态数据和 serving DB |
| templates/ | DJ 访谈模板 |
| scripts/ | 部署辅助脚本 |
| tests/ | 服务端测试 |

### 本地运行

```bash
cd services/weekly_activity_cloudrun
npm install
npm start  # 启动在 localhost:8787
```

### Docker 部署

```bash
docker build -t weekly-api .
# 通过 CloudBase CLI 部署
tcb run deploy --service weekly-api
```

## 五、数据库操作 (安全边界)

| 操作 | 允许 | 条件 |
|---|---|---|
| 打开 serving SQLite 只读 | ✓ | 任何分析/验证 |
| 打开 source SQLite 只读 | ✓ | 明确指定路径 |
| 写入 source/raw DB | ✗ | 需 gate packet + 人工确认 |
| 写入 serving DB | ✗ | 需 preflight + 回滚计划 |
| 连接 Neo4j (只读) | ✓ | 明确指定查询 |
| 写入 Neo4j | ✗ | 需 staging gate |
| 写入 Qdrant | ✗ | 需显式 canary gate |

## 六、长跑任务

当前活跃的长跑任务 (参见 `LONGRUN_STATE.md`):

| 任务 | 状态 | 控制 |
|---|---|---|
| DB2 outlink autowake | 完成 (24 cycles) | STOP 文件控制 |
| Hive controller (外链舰队) | - | `kill <PID>` 停止 |
| Night Watcher | 历史 | 已归档 |

## 七、LLM 使用

| 模型 | 用途 | 调用方式 |
|---|---|---|
| DeepSeek Flash | 低成本批量提取 | API (DEEPSEEK_API_KEY) |
| DeepSeek Pro | 高质量合并/消歧 | API (同上) |
| 本地 Qwen3 | 嵌入向量 | Ollama |

## 八、已知问题与风险

| 问题 | 优先级 | 说明 |
|---|---|---|
| SQLite 单文件超 1.6GB | P1 | 需考虑分片或迁移 |
| 管道无自动恢复 | P1 | 需 checkpoint 机制 |
| DeepSeek API 成本 | P2 | 大批量任务需成本预估 |
| 15 张海报在 mmbiz CDN | P1 | 需迁移到 CloudBase |
| serving DB 构建耗时 | P2 | 全量重建需数小时 |
