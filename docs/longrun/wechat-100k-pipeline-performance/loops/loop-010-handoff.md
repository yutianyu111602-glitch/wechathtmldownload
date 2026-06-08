<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Loop 010 Handoff - Rust Conditional Acceleration Plan

时间：2026-04-24 06:52 +08

## Scope

本轮只做计划设计和文档统一：把用户指定的 Rust 优先候选模块计入 10W+ 唯一性能计划。没有安装 Rust、没有新增 Rust 代码、没有启动生产任务、没有写 `D:\DDownload`。

## Decision

Rust 不做全量重构。当前主线仍是：

- SQLite WAL + `better-sqlite3`：运行状态/队列/lease/projection cursor。
- `p-queue`：并发、timeout、AbortSignal、backpressure。
- DuckDB：离线性能和质量聚合。
- Rust：Phase 2/2.5 条件 sidecar，仅在 benchmark 证明热点后启用。

## Rust Candidate Modules

1. 大量 checksum / hash / manifest 校验。
2. final pack 文件扫描、分区合并、checksums 生成。
3. 超大 JSONL/CSV/Parquet streaming 转换工具。
4. HTML 解析/清洗的纯 CPU 热点，前提是 profiling 和 golden corpus 证明质量不降。

## Enable Gate

Rust candidate 必须满足：

- `pipeline:perf` 或专项 benchmark 证明该模块占总耗时 >= 30%，或超过硬预算。
- Rust prototype 至少快 3x，或内存峰值降低 >= 50%。
- 输出与 TypeScript fallback 等价；不能 byte-for-byte 时必须结构化等价校验。
- Windows binary/build 可控。
- Rust binary 缺失时自动降级 TypeScript fallback，CLI 不崩溃。

## Files Updated

- `HANDOFF.md`
- `WECHAT_100K_PIPELINE_PERFORMANCE_HANDOFF_2026-04-24.md`
- `docs/longrun/wechat-100k-pipeline-performance/manifest.md`
- `docs/longrun/wechat-100k-pipeline-performance/open-source-adoption-2026-04-24.md`
- `docs/superpowers/specs/2026-04-23-wechat-100k-pipeline-performance-prd.md`
- `docs/superpowers/plans/2026-04-23-wechat-100k-pipeline-performance-v2.md`
- `.omc/ralph/wechat-100k-pipeline-performance/prd.json`
- `.omc/state/wechat-100k-pipeline-performance-ralph-state.json`

## Ralph Stories Added

- `US-020`: Rust sidecar decision gate.
- `US-021`: Rust hash/manifest scanner.
- `US-022`: Rust final-pack scanner and merger.
- `US-023`: Rust row conversion tool.
- `US-024`: Rust HTML parse/clean evaluation.

## Verification

已执行：

```powershell
node -e "const fs=require('fs'); for (const p of ['.omc/ralph/wechat-100k-pipeline-performance/prd.json','.omc/state/wechat-100k-pipeline-performance-ralph-state.json']) JSON.parse(fs.readFileSync(p,'utf8'));"
rg -n "Rust|rust|US-020|US-024|wechat-hashscan|wechat-packscan|wechat-rowconvert" HANDOFF.md docs/longrun/wechat-100k-pipeline-performance docs/superpowers/specs/2026-04-23-wechat-100k-pipeline-performance-prd.md docs/superpowers/plans/2026-04-23-wechat-100k-pipeline-performance-v2.md .omc/ralph/wechat-100k-pipeline-performance/prd.json .omc/state/wechat-100k-pipeline-performance-ralph-state.json
```

## Next

继续从 `US-003-stage-manifest-contract` 开始。Rust sidecar 不应抢在 Phase 1 之前实现；必须等 `pipeline:perf` 或专项 benchmark 证明候选热点。
