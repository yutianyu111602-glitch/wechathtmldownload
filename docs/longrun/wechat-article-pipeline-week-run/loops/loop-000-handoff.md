<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Loop 000 Handoff: Planning Complete

时间：2026-04-27 13:15 +08
状态：planned, user approved unattended start

## 已完成

- 建立长跑目录：`docs/longrun/wechat-article-pipeline-week-run`。
- 写入 manifest、intake、evidence map、board discussion、PRD、execution plan。
- 建立 Ralph 目录：`.omc/ralph/wechat-article-pipeline-week-run`。

## 当前事实

- `D:\rawwechat` HTML count: `8095`.
- `D:\rawwechat_md` Markdown count: `3146`.
- MarkItDown status: `running`, `3146/8095`, `queued=4948`, `running=1`.
- `D:\DDownload\_llm_release\articles`: `49` clubs, `68733` article dirs.
- L2 current: `94/180` unique rows, quality caveat remains.

## 下一步

执行 `US-001: Freeze baseline evidence`，写 `loops/loop-001-handoff.md`。

## 禁止动作

- 不删除 `D:\rawwechat_md`。
- 不非 resume 重跑 MarkItDown。
- 不启动 `llama-server.exe`。
- 不启动 rawwechat LLM export，直到 MarkItDown 和 dry-run gates 通过。
