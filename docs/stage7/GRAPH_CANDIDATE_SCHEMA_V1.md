<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Graph Candidate Schema V1
**版本**: graph_candidate.v1
**日期**: 2026-04-28

## 顶层结构
```json
{
  "schema_version": "graph_candidate.v1",
  "article": { ... },
  "quality": { ... },
  "entities": [ ... ],
  "events": [ ... ],
  "relations": [ ... ],
  "claims": [ ... ],
  "topics": [ ... ],
  "evidence": [ ... ],
  "errors": [ ... ]
}
```

## article
```json
{
  "article_id": "string",
  "account_name": "string",
  "title": "string",
  "url": "string",
  "published_at": "string (ISO 8601 or null)",
  "source_path": "string",
  "input_hash": "string (SHA256)"
}
```

## quality
```json
{
  "is_extractable": true,
  "article_type": "event_announcement|interview|review|news|repost|image_only|empty|ad|mixed",
  "language": "zh",
  "confidence": 0.0,
  "empty_reason": null,
  "warnings": []
}
```

## entities
```json
{
  "local_id": "string (e.g. e-001)",
  "name": "string",
  "type": "venue|artist|dj|label|promoter|organization|brand|work|location|person|other",
  "aliases": [],
  "description_short": "string (max 200 chars)",
  "confidence": 0.0,
  "evidence_ids": []
}
```

## events
```json
{
  "local_id": "string (e.g. ev-001)",
  "title": "string",
  "type": "party|festival|workshop|talk|exhibition|residency|open_deck|other",
  "time": {
    "start": "string (ISO 8601 or fuzzy)",
    "end": "string (ISO 8601 or null)",
    "fuzzy_text": "string (original text)"
  },
  "location": {
    "venue": "string (venue name)",
    "city": "string",
    "address": "string"
  },
  "participants": [],
  "confidence": 0.0,
  "evidence_ids": []
}
```

## relations
```json
{
  "local_id": "string (r-001)",
  "subject_local_id": "string (entity local_id)",
  "predicate": "string",
  "object_local_id": "string (entity local_id)",
  "confidence": 0.0,
  "evidence_ids": []
}
```

## claims
```json
{
  "local_id": "string (c-001)",
  "claim_text": "string",
  "claim_type": "fact|opinion|description|quotation|other",
  "confidence": 0.0,
  "evidence_ids": []
}
```

## evidence
```json
{
  "evidence_id": "string (ev-001)",
  "source": "string (llm_input|meta|poster_ocr)",
  "quote_short": "string (exact quote, max 200 chars)",
  "char_start": 0,
  "char_end": 0,
  "confidence": 0.0
}
```

## 约束规则
1. 每个 entity/event/relation/claim 必须引用至少1个 evidence_id
2. evidence 必须来自原文（llm_input.md 或 meta.json 或 poster_ocr.json）
3. 没证据就不抽
4. 不确定就降低 confidence
5. events 为空时必须写 empty_reason
6. confidence 范围 0.0 ~ 1.0
7. 不允许 Markdown 输出
8. 不允许代码块包裹 JSON
