<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Board Discussion: WeChat Article Pipeline Week Run

时间：2026-04-27 13:15 +08

## Round 1: Facts

- There are two separate workstreams: old `D:\rawwechat` HTML -> `D:\rawwechat_md` MarkItDown, and new `D:\DDownload\_llm_release\articles` article-release extraction.
- Old MarkItDown is stale-running, but its successful outputs exist.
- New L1 is mostly complete; L2 is partial and needs cleanup.
- The repo has scripts for rawwechat MarkItDown and LLM artifact export.

## Round 2: Conflicts

- A prior AI misread first-level empty club dirs as missing Markdown output.
- Resume behavior in `runMarkitdownBatch.ts` skips existing outPath files, so stale status repair is less important than output-path existence.
- Starting rawwechat LLM export before validating MarkItDown completion may multiply partial data.
- L2 can proceed independently from MarkItDown, but its current JSONL needs cleaning.

## Round 3: Decision

- Use a Ralph story loop with one bounded story at a time.
- First freeze evidence and protect production state with backups.
- Then repair MarkItDown stale status and resume with `npm run export:rawwechat-md` only after checking for conflicting processes.
- In parallel only when safe, clean L2 JSONL and continue L2 with the patched runner.
- Defer full rawwechat LLM export until MarkItDown completion and output validation pass.

## Safety stance

无人值守不是无边界。任何需要删除、强覆盖、发布、付费、密钥、git push、停止他人进程的动作都必须停下来写 handoff。
