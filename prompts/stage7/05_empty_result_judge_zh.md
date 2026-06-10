<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# 空结果裁判

## 职责
判断空 entities / 空 events 是否合理。

## 输出
```json
{
  "empty_is_reasonable": true,
  "empty_type": "reasonable_no_event|too_short|ocr_noise|model_failure|prompt_failure|unknown",
  "reason": "",
  "retry_recommended": true
}
```
