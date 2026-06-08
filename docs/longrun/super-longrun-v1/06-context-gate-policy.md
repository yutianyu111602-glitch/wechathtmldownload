<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Context Gate Policy — Super Long Run v1

**Date:** 2026-04-27
**Status:** ENFORCED
**Pre-requisite:** US-001 (Baseline Freeze)
**Applies to:** US-002, US-003, US-004

---

## 1. Problem Statement

Qwen3.6-27B has 8K context limit. Downstream evaluation found articles at ~9.8K tokens fail on 3 prompts. Blind batch processing would cause repeated failures on long articles, wasting GPU time and inflating error counts.

## 2. Token Estimation

For each article before entering the model batch:

| Field | Source | How |
|-------|--------|-----|
| Article body tokens | llm_input.md or clean.md | Read file size, estimate: bytes * 0.3 |
| Prompt tokens | Prompt template | Fixed: ~500 tokens per prompt |
| Schema tokens | JSON schema in prompt | Fixed: ~200 tokens |
| Max output tokens | Config | 2048 (from model params) |

Estimated total = body_tokens + prompt_tokens + schema_tokens + max_output_tokens

## 3. Queue Classification

| Estimated Total | Queue | Action |
|-----------------|-------|--------|
| <= 6K tokens | normal_queue | Process in batch as usual |
| 6K - 12K tokens | compress_or_truncate_queue | Truncate body to fit before sending |
| > 12K tokens | long_context_queue | Skip. Do not attempt. |

Thresholds account for tokenizer overhead and safety margin.

## 4. Evidence Requirements

Every gated article MUST produce an evidence record:
```json
{
  "article_id": "club/token",
  "body_bytes": 12345,
  "estimated_body_tokens": 3704,
  "prompt_tokens": 500,
  "schema_tokens": 200,
  "max_output_tokens": 2048,
  "estimated_total": 6452,
  "decision": "normal",
  "reason": "estimated_total <= 6000",
  "target_queue": "normal_queue"
}
```

Evidence written to `context-gate-log.jsonl`.

## 5. Output Queues

| File | Contents | Used By |
|------|----------|---------|
| normal_queue.jsonl | Articles <= 6K tokens | US-002, US-003, US-004 |
| compress_queue.jsonl | Articles 6K-12K tokens | Future US (truncated batch) |
| long_context_queue.jsonl | Articles > 12K tokens | Review only, no batch |
| review_queue.jsonl | From manifest: quality=review | US-005 |
| blocked_queue.jsonl | From manifest: quality=blocked | US-005 |
| context-gate-report.md | Summary statistics | Human review |

## 6. Gate Rules

| Rule | Enforcement |
|------|-------------|
| Normal batch only processes normal_queue | Input filter at batch start |
| No auto-retry on gated articles | Process control |
| Long context articles NEVER enter batch | Hard gate |
| Review/blocked articles NEVER enter batch | Hard gate |
| Gate must run BEFORE any batch | Sequence dependency |
| If gate fails, no batch starts | Pre-condition check |

## 7. Edge Cases

| Case | Handling |
|------|----------|
| Body file missing | Classify as blocked_queue, reason: "missing_body" |
| Body file > 100KB | Auto-classify as long_context_queue |
| Empty body | Classify as normal_queue (trivial, no risk) |
| Multi-file article (no single body) | Use llm_input.md as body, else blocked |

## 8. Implementation Plan

See `tools/super-longrun/context-gate-plan.ps1` for the execution script.

The script:
1. Reads manifest.json for article list and quality grades
2. Finds body files (llm_input.md or clean.md) per article
3. Estimates tokens from file size
4. Classifies into queues
5. Writes queue JSONL files and evidence log
6. Generates context-gate-report.md

## 9. Re-Run Policy
- Gate can be re-run (idempotent)
- Queue files are overwritten (not appended)
- Evidence log is overwritten
- Re-run after queue changes or model parameter changes
