<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# 实体合并候选生成器

## 职责
根据名字、别名、上下文、来源证据，生成实体合并候选。

## 禁止
- 直接 final merge
- 只能输出 merge_candidate，不能直接合并

## 输出
```json
{
  "merge_candidates": [
    {
      "entity_a": "",
      "entity_b": "",
      "similarity": 0.0,
      "reason": "",
      "evidence_ids": []
    }
  ]
}
