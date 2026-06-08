<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# UI 层业务依赖契约 2026-04-21

## 文档定位

Scope: 本文只描述 Electron UI 层读取和触发业务能力时依赖的 IPC 与文件投影契约。

Source of truth:

- repo 级当前事实源：`..\FULL_AUDIT_AND_CANONICAL_TRUTH_2026-04-21.md`
- IPC 实现：`..\desktop\main.mjs`
- preload 暴露：`..\desktop\preload.cjs`
- renderer 消费：`..\desktop\renderer.js`

Non-goals:

- 本文不声明 GUI 已经能一键触发全部 CLI 主链。
- 本文不替代业务层 schema 测试。
- 本文不描述历史 UI 阶段设计。

---

## 当前 UI 能力边界

GUI 已有 5 个工作区：

- `task-bus`
- `collect`
- `archive`
- `process`
- `artifact`

GUI 当前能启动的写入路径：

- `batch:start` with `pipeline="dual-track"`
- `batch:start` with `pipeline="llm-export"`
- `audit:run` -> `audit-archive-run`
- `pack:finalize` -> `finalize-llm-pack`
- `batch:cancel`

GUI 当前只读展示但没有按钮触发的业务能力：

- `prefetch-account-urls`
- `archive-batch`
- `download-archive-assets-batch`
- `run-downstream-llm`
- `run-keeper`

---

## IPC 契约

| IPC Channel | Payload | 返回 | UI 用途 |
|---|---|---|---|
| `dialog:pick-directory` | `defaultPath` | `string` | 选择目录 |
| `app:open-path` | `filePath` | void | 打开目录或文件 |
| `batch:start` | `{inputRoot,outRoot,resume,pipeline,mirrorRoot?}` | `{accepted,message}` | 启动 dual-track / llm-export / keeper 后台批次 |
| `batch:cancel` | none | `{accepted,message}` | 取消当前批次 |
| `batch:get-latest-snapshot` | none | `BatchSnapshot \| null` | 初始化任务总线 |
| `collect:get-state` | `{rootDir,accountsPath?}` | `CollectState` | 采集与账号工作区 |
| `archive:get-state` | `{archiveRoot}` | `ArchiveState` | 归档与下载工作区 |
| `process:get-state` | `{outRoot,statusPath?}` | `ProcessState` | 处理与导出工作区 |
| `audit:get-projection` | `{archiveRoot}` | `AuditProjection \| null` | archive stages |
| `audit:run` | `{archiveRoot?,manifestPath?,outDir?}` | `{accepted,message}` | 触发 archive audit 并刷新 stages |
| `pack:get-projection` | `{releaseRoot}` | `FinalPackProjection \| null` | 产物与审查工作区 |
| `pack:finalize` | `{artifactRoot?,releaseRoot?,archiveRoot?,manifestPath?}` | `{accepted,message}` | 生成 final LLM pack 并刷新 pack projection |

Realtime event:

| Event | Payload | UI 用途 |
|---|---|---|
| `batch:snapshot` | `BatchSnapshot` | task bus 实时运行态 |
| `batch:error` | `string` | 失败流 |

---

## 工作区数据源

### task-bus

Source:

- live `batch:snapshot`
- `batch:get-latest-snapshot`

UI consumes:

- `status`
- `inputRoot`
- `outRoot`
- `startedAt`
- `endedAt`
- `totalItems`
- `queuedCount`
- `runningCount`
- `succeededCount`
- `failedCount`
- `skippedCount`
- `cancelledCount`
- `completedCount`
- `progressRatio`
- `currentFile`
- `currentPhase`
- `items[]`

### collect

Source:

- `{rootDir}\_state\account-url-prefetch-status.json`
- `{rootDir}\_queues\download_ready_queue.jsonl`
- optional `accountsPath`
- recent `history_*` directories

UI consumes:

- `status`
- `sources.rootDir`
- `sources.prefetchStatusPath`
- `sources.queuePath`
- `summary.totalAccounts`
- `summary.completedAccounts`
- `summary.totalDiscovered`
- `summary.totalEnqueued`
- `summary.readyQueueCount`
- `accounts[].fakeid`
- `accounts[].nickname`
- `accounts[].status`
- `accounts[].estimatedSize`
- `accounts[].lastDiscoveredAt`
- `accounts[].discoveredCount`
- `accounts[].enqueuedCount`
- `accounts[].duplicateCount`
- `accounts[].errorMessage`

### archive

Source:

- `{archiveRoot}\archive-status.json`
- `{archiveRoot}\asset-retention-status.json`
- `{archiveRoot}\{accountKey}\{token}\*`
- `{archiveRoot}\ui-projection.json`

UI consumes from `archive:get-state`:

- `summary.archive`
- `summary.assets`
- `summary.bundles`
- `items[].token`
- `items[].accountKey`
- `items[].sourceUrl`
- `items[].outDir`
- `items[].archiveStatus`
- `items[].assetStatus`
- `items[].captureComplete`
- `items[].mhtmlComplete`
- `items[].pdfComplete`
- `items[].assetsComplete`
- `items[].imageCount`
- `items[].mediaCount`
- `items[].lastError`
- `items[].files`

UI consumes from `audit:get-projection`:

- `stages[].id`
- `stages[].label`
- `stages[].total`
- `stages[].succeeded`
- `stages[].failed`
- `stages[].skipped`
- `stages[].running`
- `stages[].recoverable`
- `stages[].latest_error`

### process

Source:

- `{outRoot}\batch-status.json`
- article bundle directories under `{outRoot}`
- live snapshot fallback if current running batch uses same `outRoot`

UI consumes:

- `summary.totalItems`
- `summary.succeededCount`
- `summary.failedCount`
- `summary.partialCount`
- `summary.warningCount`
- `summary.downstreamReadyCount`
- `items[].articleId`
- `items[].token`
- `items[].title`
- `items[].accountName`
- `items[].sourceUrl`
- `items[].outDir`
- `items[].status`
- `items[].phase`
- `items[].qualityStatus`
- `items[].sidecarStatus`
- `items[].llmInputStatus`
- `items[].downstreamStatus`
- `items[].warningCount`
- `items[].errorMessage`
- `items[].files`

### artifact

Source:

- `{releaseRoot}\manifest.json`
- `{releaseRoot}\index.jsonl`

UI consumes:

- `generatedAt`
- `artifactRoot`
- `releaseRoot`
- `archiveRoot`
- `totalArticles`
- `copiedArticles`
- `qualityCounts.ready`
- `qualityCounts.review`
- `qualityCounts.blocked`
- `sources.manifestPath`
- `sources.indexPath`
- `indexRows[].token`
- `indexRows[].title`
- `indexRows[].account`
- `indexRows[].quality_grade`
- `indexRows[].warning_count`
- `indexRows[].local_image_count`
- `indexRows[].main_content_chars`
- `indexRows[].background_recall_chars`

---

## 安全边界

- UI 只读 projection 和 bundle 文件矩阵。
- UI 不读取 `.mptext-data`、cookie、auth、token、secret。
- `finalize-llm-pack` 负责排除敏感路径和 raw archive 文件。
- GUI 写入能力必须通过主进程 IPC 调业务命令，不允许 renderer 直接写业务状态文件。

---

## 当前验证

本轮验证结果：

- `npm run build`: 通过。
- `npm test`: 通过，`74/74`。
- `node --check desktop\main.mjs`: 通过。
- `node --check desktop\renderer.js`: 通过。
- `node --check desktop\preload.cjs`: 通过。

当前目录不是 git repo。
