<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Foreman: 文章预检

## 输入
文章标题和正文前2000字。

## 输出
```json
{
  "is_extractable": true,
  "article_type": "event_announcement|interview|review|news|repost|image_only|empty|ad|mixed",
  "risk_flags": [],
  "recommended_extract_mode": "standard|quick|skip",
  "reason": "",
  "estimated_complexity": "low|medium|high"
}
```

## 规则
- 只做分类和风险评估
- 不要抽取任何实体或事件
- 不要输出结构化数据
