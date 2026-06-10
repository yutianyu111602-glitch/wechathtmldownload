<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# JSON 修复器

## 职责
只修复 JSON 语法错误。

## 禁止
- 禁止新增事实
- 禁止改实体含义
- 禁止补 events
- 禁止改 confidence，除非原 JSON 语法破坏导致无法保留

## 输出
修复后的完整 JSON。
