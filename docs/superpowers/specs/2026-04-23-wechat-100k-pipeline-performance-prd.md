<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# WeChat 10W+ Pipeline Performance PRD

日期：2026-04-23  
工作区：`C:\code\githubstar\wechathtmldownload`  
状态：计划已收敛；2026-04-24 追加 live 复核显示 assets 已自然终止、export 正在运行；开源选型已更新为 SQLite WAL + `better-sqlite3`、`p-queue`、DuckDB，并加入 Rust 条件加速层。当前目录不是 git repo。

## 目标

把现有 WeChat History HTML Pipeline 从“能跑大批次脚本”升级为“可支撑 10W+ 公众号推文的可租约、可分片、可恢复流水线”。

成功标准：

- 10W+ URL / archive / assets / export / final pack 可以稳定分阶段运行。
- 任一阶段中断后可按 manifest / lease / artifact manifest 恢复。
- UI 和守夜只读状态来自稳定投影，不从 live root 猜测。
- final pack 之前不越级运行 downstream graph / `ignuke` / `D:\DJ_DATA` registry。

## 当前事实

### 已出现的生产产物

- `D:\DDownload\_queues\download_ready_queue.jsonl`：93,761 行。
- `D:\DDownload\_archive_mptext\mptext-archive-status.json`：HTML archive 已 completed。
  - total 93,761
  - succeeded 66,020
  - skipped 17,874
  - deferred 2,624
  - failed 7,243
- `D:\DDownload\_reports\archive-audit-final\archive-audit-summary.json`：
  - total_records 93,761
  - archived_count 83,894
  - retry_queue_count 9,867
  - partial 9,620
  - missing 247
- Dajiala signed repair 已完成 400/400；repair bundle 不自动折算主 manifest 的失败项。
- `D:\DDownload\_archive_mptext\asset-retention-results.jsonl`：assets 追加结果日志，2026-04-24 06:20 只读统计 145,083 行，SHA256 `16B19D767F202C6370AC927485AA3EE3EAE7F2928DD2477AB827522C92055673`。
- `D:\DDownload\_archive_mptext\asset-retention-status.json`：当前被 117-row 补跑覆盖，totalItems 117；succeededCount 113；failedCount 4；queuedCount 0；runningCount 0；itemsTruncated=false。不能单独当作全量 assets summary。
- `D:\DDownload\_llm_artifacts`：已出现，当前正在写 archive-aware export 产物。
- `D:\DDownload\_llm_artifacts\export-llm-status.json`：2026-04-24 06:40 +08 只读快照显示 export running，totalItems 93,761；completedCount 2,407；succeededCount 2,407；failedCount 0；queuedCount 91,353；runningCount 1；currentPhase `markitdown_convert`。
- Mac 轻任务 runner 服务已在 Mac 端验证：
  - `bge-m3` embedding：Mac 本机 `http://127.0.0.1:8091`，`GET /health`，`POST /embed`，验证返回 2 条 1024 维向量。
  - Qwen2.5-Coder llama.cpp OpenAI-compatible：Mac 本机 `http://127.0.0.1:8093`，`GET /v1/models`，模型 `qwen2.5-coder-7b-instruct-q4_k_m.gguf`，小样本 chat completion 通过。
  - LaunchAgent：`com.masher.embedding.bge-m3` 和 `com.masher.llamacpp.qwen2.5-coder` 均为 running。
  - 该能力只进入 Mac light-runner planning；Windows 调用时要用 Mac 主机地址或隧道，不能使用 Windows `127.0.0.1`，且必须通过 runner job/result pack 边界。
  - Mac 原始服务返回只作为 capability proof；未来接入时必须封装为 runner result pack：`results.jsonl`、`errors.jsonl`、`run_summary.json`、`hashes.json`。embedding 任务需记录 `vector_count` 与 `dimension=1024`；schema repair/text cleanup/validator/dedup-rerank 任务需保留 raw response 与 normalized JSON，不能覆盖输入文件。

### 尚未出现的生产产物

- `D:\DDownload\_llm_md`
- `D:\DDownload\_llm_release`
- `D:\DDownload\_eval`
- `D:\DDownload\_runner_jobs`
- `D:\DDownload\_graph_candidates`

这些目录当前不存在，不能在文档中说成已经生产完成。

### 最新只读复核

2026-04-23 21:29 +08：

- `download-archive-assets-batch --concurrency 2 --resume` 仍在运行。
- `asset-retention-status.json`：total 93,761；succeeded 65,672；skipped 18,269；failed 338；queued 9,481；running 1；itemsTruncated=true。
- `asset-retention-results.jsonl` 仍在增长。
- 当前只能继续只读监控、文档整理、测试设计和隔离目录实验；不能启动任何 live root 后处理。

2026-04-24 06:27 +08：

- `download-archive-assets-batch` 生产进程未发现。
- `asset-retention-results.jsonl` mtime 2026-04-24 00:18:23 +08，结果日志稳定；latest status 文件只代表 117-row 补跑。
- `export-llm-batch --inputMode archive` 进程链存在，启动时间 2026-04-24 05:26 +08。
- `export-llm-status.json`：totalItems 93,761；completedCount 2,069；succeededCount 2,069；failedCount 0；queuedCount 91,691；runningCount 1；status `running`。
- 当前 gate 转为 export-running：禁止重复启动 export、停止 export、启动 OCR/finalize/downstream/graph/registry、清理 `_llm_artifacts` 或手动创建/清理 `_llm_md`。

2026-04-24 06:40 +08：

- assets/export guard 与 live stage lock 已完成并通过 targeted tests + build。
- 开源选型口径已更新：SQLite WAL + `better-sqlite3` 是未来运行状态/队列/lease/projection cursor 真相；`p-queue` 是未来并发/backpressure 执行器；DuckDB 用于离线性能和质量聚合。
- JSONL 保留为 manifest/audit/export 格式，不再作为高频 mutable state 主存储。
- Rust 进入 Phase 2/2.5 条件加速层：只处理 checksum/hash/manifest 校验、final pack scan/partition merge/checksum、超大 JSONL/CSV/Parquet 转换、以及经质量证明的 HTML parse/clean CPU 热点；不做全量重构。

## 当前执行游标

已完成：

1. `download_ready_queue.jsonl`
2. `mptext-archive-batch`
3. final archive audit
4. incomplete queue
5. Dajiala signed repair candidates
6. Dajiala signed repair 400/400
7. repair 后 re-audit
8. `download-archive-assets-batch` 自然终止；需以后续 freeze report 固化全量 results 覆盖和失败项

正在运行：

9. `export-llm-batch --inputMode archive`

尚未开始：

10. OCR/VLM enrichment
11. final pack
12. downstream LLM matrix
13. graph candidate pack / `ignuke` / `D:\DJ_DATA` registry

## 当前计划能力状态

| 能力 | 当前状态 | 口径 |
| --- | --- | --- |
| assets-running CLI gate | 已实现 | `archiveAssetRunGuard` 已接入相关 CLI，latest status 文件不能单独代表全量 completion 的风险已写入文档。 |
| export-running gate | 已实现 | export running 时拒绝重复 export、OCR、finalize、downstream 等相关入口。 |
| live stage lock / single writer | 已实现 | `liveStageLock` 已在生产 root family 上提供单写者保护；单测只用 temp dir。 |
| stage manifest | 计划中 | 尚未实现，不可当生产能力。 |
| durable queue / state DB | 计划中 | 当前 `jobStore` 仍是数组 + JSON snapshot，不适合 10W 主线；下一步改为 SQLite WAL + `better-sqlite3`。 |
| compact projection | 部分已有 snapshot compaction | 仍缺 event-backed bounded projection。 |
| artifact manifest resume | 计划中 | 当前 resume 主要看 `llm_input.md`。 |
| dual-track bounded concurrency | 计划中 | `process-batch` 解析 concurrency，但 runner 未完整消费。 |
| `export-llm-batch` concurrency | 缺失 | 需要显式传递到 `runDualTrackBatch`。 |
| mirror root safety | 缺失 | 当前 mirror 会先删除目标目录。 |
| MarkItDown worker pool | 计划中 | 当前每篇 spawn Python。 |
| partitioned final pack | 计划中 | 当前 final pack 单体扫描 artifact root。 |
| Mac light-runner capability | 已验证服务，未接入主链 | Mac 端 `bge-m3` embedding 和 Qwen2.5-Coder 7B 服务可用；仅作为后续 embedding/schema repair/validator 小任务 runner，不写 live root。 |
| Rust sidecar acceleration | 条件计划中 | 只在 profiling 证明热点且 Rust prototype >= 3x faster 或内存峰值降低 >= 50% 后启用；必须有 TypeScript fallback。 |

## 安全闸门

- assets 未完成前，禁止 export / OCR / finalize / downstream / graph / registry。2026-04-24 追加：assets 已自然终止，但 completion 判断必须基于 results log、run_id 覆盖、mtime 稳定和进程退出，不可只看 latest status 文件。
- export running 时，禁止重复启动 export、停止 export、清理 `_llm_artifacts`、手动创建/清理 `_llm_md`、启动 OCR / finalize / downstream / graph / registry。
- export running 时，禁止在 `D:\DDownload` 下写 shard manifest、rescue queue、perf report 或实验产物。
- 所有 10W dry-run、fixture、benchmark 必须写 repo-local `tmp-*` 或明确隔离实验目录。
- `D:\DDownload` 命令在计划文档中只表示未来生产命令，不表示当前可执行。
- Dajiala repair bundle 不自动折算主 manifest；后续消费必须通过单独 reconcile 产物。

## Agentteam 三轮讨论收敛

### Round 1：事实

- 权威入口是 `HANDOFF.md`；其他 2026-04-21 / 2026-04-22 文档若有路径、阶段、变量冲突，以 `HANDOFF.md` 和本 PRD 为准。
- 304 篇分层样本已经证明最佳主链是 `audit -> assets -> archive-aware export -> final pack`，不是 `html-only`。
- 旧项目质量优势来自 browser rendered capture、MHTML/PDF、lazy-load、结构化 sidecar、media pass、poster fallback；不来自旧 UI/OCR 采集本身。
- 当前性能瓶颈不是单个函数，而是：
  - 全量 `items` snapshot 常驻内存。
  - 高频状态写触发 O(N) 重算、compact 和 JSON 写入。
  - `runDualTrackBatch` 串行，`process-batch` 解析了 `--concurrency` 但当前没有传入 runner。
  - MarkItDown 每篇 spawn Python/import，10W+ 会极慢。
  - job store 用全量 JSON + `Array.find`，10W 注册/更新会退化。
  - final pack / checksums 会全量扫描和复制百万级小文件。

### Round 2：方案

推荐统一口径：

- 10W+ 主路：API-first mptext 私有节点 + durable queue + resumable CLI stages。
- 质量补强：旧项目 browser/MHTML/PDF 路线只做 selective rescue，不做 10W 全量默认路径。
- 状态层：从全量 snapshot 文件升级为 SQLite WAL + `better-sqlite3`，JSONL 只做 manifest/audit/export，聚合投影从 SQLite 状态生成。
- 执行层：batch runner 拆成 discovery、queue claim、stage executor、projection writer。
- 输出层：按 2k-5k article shard 分区，最终 pack 只合并 index / manifest / checksums。
- MarkItDown：改成长驻 Python worker pool 或 service，避免每篇冷启动。

### Round 3：质疑与收敛

- 只加 `Promise.all` 不够，会把瓶颈转移到状态写、Python 进程、NTFS 小文件和外部 API 限流。
- 全量 Playwright/MHTML/PDF 不适合 10W；它应该被用作低质量、image-heavy、poster-like 的补救阶段。
- Dajiala repair 成功 bundle 不自动折算主 manifest 的失败项；需要 reconcile 产物或单独消费。
- 当前可以先用外部分片作为最小可行运行方式，但长期必须统一到 durable queue 和 stage manifest。

### Round 4：第二轮 agentteam 复核

- 文档口径风险：旧文档和第一版计划容易让后续 agent 误以为 assets 运行中可以开始 shard/export/OCR/finalize。
- 代码风险 1：archive-mode 下游 guard 只检查 mptext 状态，没有检查 assets 状态。
- 代码风险 2：`runLlmExportBatch` 的 mirror 步骤会删除 `mirrorRoot`，未加安全闸门前不能指向已有重要目录。
- 代码风险 3：`runDualTrackBatch` 每次 phase 更新都重算全量 snapshot，10W 下是错误复杂度。
- 代码风险 4：`jobStore` 的 `Array.find` 和整 JSON snapshot 只能用于小中批量，不是 10W queue。
- Ralph 风险：第一版 Ralph stories 与计划 task 不是一一映射；store/projection、runner concurrency、MarkItDown worker 都需要拆小。

### Round 5：2026-04-24 live 状态复核

- 文档口径已落后于 live root：`_llm_artifacts` 已出现，export 正在运行。
- assets completion gate 要读取多证据：manifest 行数、results log run_id 覆盖、latest status、mtime 稳定、进程退出。
- 当前最重要生产 gate 是 export-running，不是 assets-running。
- 不能中途优化当前 live export；正确做法是等待自然完成，同时在 repo-local 代码和测试里补 guard、manifest、store、projection、artifact resume、worker pool。
- V2 计划仍正确，但下一步执行顺序必须先冻结 export，再考虑 OCR/finalize。

### Round 6：开源选型收口

- 采用 `better-sqlite3` + SQLite WAL 作为 10W 运行状态、任务 lease、projection cursor 的主存储，避免自造数据库。
- 采用 `p-queue` 作为并发、timeout、AbortSignal、backpressure 的基础能力，项目内只保留薄包装。
- 采用 DuckDB 做离线性能报表、质量分布、失败聚合，不作为 live writer。
- BullMQ/Redis、Meilisearch、LanceDB、ClickHouse、AG Grid/TanStack Virtual 都不进入当前主线；只有多机 runner、搜索/embedding、服务化 OLAP 或现有 UI gate 失败时再开新 track。

### Round 7：Rust 条件加速层

- 不做 Rust 全量重构；Node/TypeScript 继续负责 CLI 编排、Electron UI、SQLite 状态、stage orchestration 和业务 glue code。
- Rust 优先候选模块：
  - 大量 checksum / hash / manifest 校验。
  - final pack 文件扫描、分区合并、checksums 生成。
  - 超大 JSONL/CSV/Parquet streaming 转换。
  - HTML 解析/清洗纯 CPU 热点，前提是 golden corpus 证明质量不降。
- Rust 启用门槛：
  - 该模块在 `pipeline:perf` 或专项 benchmark 中占总耗时 >= 30%，或超过预算。
  - Rust prototype 至少快 3x，或内存峰值降低 >= 50%。
  - 与 TypeScript fallback 同输入同输出；不能 byte-for-byte 时必须结构化等价校验。
  - Windows binary/build 可控；binary 缺失时自动降级 TypeScript fallback。

## 功能需求

1. 统一文章 ID、stage ID、artifact ID、runner manifest ID。
2. 支持按 shard 生成 stage manifest，每个 shard 可独立运行、重试、校验。
3. 支持 durable queue claim / lease / ack，避免多进程重复写同一产物。
4. 状态写入必须落到 SQLite WAL 事务和索引查询；JSONL audit 可追加，但不能作为高频状态主存储。
5. `process-batch` / `export-llm-batch` 必须通过 `p-queue` backed executor 支持 bounded concurrency 和 backpressure。
6. Resume 判断必须基于 `artifact_manifest.json`，不能只看 `llm_input.md`。
7. MarkItDown 支持 worker pool 或 service 模式。
8. final pack 支持 partition finalize，再合并全局 index / manifest。
9. runner job pack 支持从 manifest partition 读取，不再全量目录扫描。
10. selective strong capture rescue 只处理 audit / quality 指定子集。
11. CLI 必须有 assets completion gate：`asset-retention-status.json` 仍 running/queued 或进程存在时，禁止 export / OCR / finalize / downstream。
12. `export-llm-batch` 必须显式传递 concurrency / shard / SQLite store / projection 参数，并加 mirror root 安全闸门。
13. MarkItDown worker pool 必须可用 fake worker 单测证明 N 次转换的 spawn 数不超过 worker count。
14. 10W performance harness 必须覆盖 shard generation、projection、resume、MarkItDown pool fallback、partition merge。
15. Rust sidecar 必须以 benchmark 触发，不得默认替换 TypeScript 路径；必须覆盖 binary discovery、missing-binary fallback、golden equivalence 和专项性能报告。
16. Rust 优先模块依次为 hash/manifest scanner、final-pack scanner/merger、row converter、HTML clean candidate。

## 非目标

- 不在 assets 运行中启动 export / OCR / finalize。
- 不在 export 运行中启动 OCR / finalize / downstream / graph / registry。
- 不停止、kill、重启或清理当前 live export，除非用户明确要求。
- 不把 `D:\DJ_DATA` 当 live processing root。
- 不把 LLM 输出当图谱真值。
- 不为了“像旧项目”而重做 OCR/UIA URL discovery。
- 不全量跑 Playwright/MHTML/PDF。
- 不在本计划里修改 PCUI 视觉结构；PCUI 已有 100k 虚拟表格性能线。

## 性能预算

- 10W manifest 导入：可分片导入；单 shard 2k-5k 行。
- 状态投影 JSON：默认不超过 5MB；超过时必须 compact，并保留 SQLite 状态和 JSONL audit 证据。
- 单次状态更新：不允许扫描 10W items。
- 单 shard status/result log：可独立恢复，不影响其他 shard。
- UI 100k 行：继续沿用 PCUI 预算，live DOM rows <= 300。
- MarkItDown：长驻 worker 模式下每篇不重复 import。
- final pack：分区构建，global merge 不复制 raw archive，不进入敏感文件。
- Rust sidecar：专项 benchmark 必须证明 >= 3x speedup 或 >= 50% memory reduction；否则保持 TypeScript 路径。

## 验收标准

- `npm run build` 通过。
- `npm test` 通过。
- 新增 100k fixture 性能测试覆盖：
  - SQLite queue claim / ack
  - status projection
  - artifact manifest resume
  - shard merge
  - MarkItDown worker fallback
  - Rust sidecar candidate benchmark and fallback equivalence
- 新增 guard 测试覆盖：
  - assets running 时拒绝 export / OCR / finalize
  - mirror root 非 disposable 时拒绝删除
  - 两个 manifest row 映射同一 outDir 时不启动 worker
- 10W dry-run 可在不写 live root 的临时目录中生成 shard manifest 和状态投影。
- assets 未 completed 时，文档和 CLI 都禁止 export / OCR / finalize。
