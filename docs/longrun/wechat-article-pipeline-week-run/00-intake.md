<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Intake: WeChat Article Pipeline Week Run

时间：2026-04-27 13:15 +08
用户指令：出门一周，要求完整阅读新旧文档、产物和管线目录，先计划后执行，使用 longrun skill 和 Ralph/prd.json。

## 可验证目标

在无人值守约束下，把 `rawwechat` 旧 MarkItDown 管线、`D:\DDownload\_llm_release` 新 article-release 产物、当前 L1/L2/L3 抽取产物统一成一个可恢复、可验证、可继续的长跑流程。

## 成功标准

- 有一个唯一入口 manifest。
- 有 PRD 和 Ralph `prd.json`，每个 story 一轮可完成。
- 每轮执行后有 handoff、计数、验证结果和 next cursor。
- `D:\rawwechat_md` 不被误删、不被非 resume 全量覆盖。
- MarkItDown stale running 被备份后安全恢复。
- L2/L3 产物在进入下游前被清洗和验证。
- 全链路停止时能从 manifest、latest handoff、prd.json 继续。

## 非目标

- 不发布、不部署、不 git push、不提交 commit。
- 不删除生产产物。
- 不使用 `llama-server.exe`。
- 不处理密钥、付费 API 或外部发布。
- 不把旧文档全部改写成新口径；只在本长跑目录集中收口。

## 硬停止条件

- 发现另一个进程正在写同一状态文件或输出目录。
- 状态 JSON 修改后无法解析。
- 同一 story 连续失败 3 次。
- 需要删除、覆盖、发布、付费、密钥、强推或主线合并。
