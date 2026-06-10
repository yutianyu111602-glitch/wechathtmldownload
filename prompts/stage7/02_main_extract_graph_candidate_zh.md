<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Main Extractor: 文章→Graph Candidate

## 输入
- llm_input.md (全文)
- meta.json (元数据)
- poster_ocr.json (海报OCR)

## 输出
graph_candidate.v1 JSON

## 强制规则
1. 只从原文抽取
2. 每个 entity/event/relation/claim 必须引用 evidence_ids
3. evidence 必须来自原文
4. 没证据就不抽
5. 不确定就降低 confidence
6. events 为空必须写 empty_reason
7. 不允许 Markdown
8. 不允许解释
9. 不允许代码块包裹 JSON
