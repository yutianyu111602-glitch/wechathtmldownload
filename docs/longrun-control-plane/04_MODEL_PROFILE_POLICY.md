<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Model Profile Policy

**Created:** 2026-04-27
**Status:** SKELETON
**Source config:** C:\Users\pc\.config\opencode\opencode.jsonc

## Active Profiles (OpenCode)

### deepseek-builder — Document & Plan Generator

```yaml
model: deepseek-v4-pro (via official API)
output: 4096 tokens
temperature: 0.2
timeout: 180s
use: PRD, execution plans, runbooks, skeleton files, config
forbidden: production batch, verify, build, test, dry-run
```

### deepseek-v4-pro — RED Escalation Analyzer

```yaml
model: deepseek-v4-pro (via official API)
output: 8192 tokens
temperature: 0.2
timeout: 300s
use: RED root-cause, complex AMBER, Need Human assessment
forbidden: file writes, batch execute, skeleton generation, production
```

### deepseek-v4-flash — Watch & Monitor

```yaml
model: deepseek-v4-flash (via official API)
output: 2048 tokens (base) / 4096 (extended for AMBER review)
temperature: 0.1
timeout: 90s (base) / 120s (extended)
use: daily patrol, log summary, GREEN/AMBER classification
forbidden: decisions, config changes, escalation analysis, file writes
```

### deepseek-v4-flash-extended — AMBER Reviewer

```yaml
model: deepseek-v4-flash
output: 4096 tokens
temperature: 0.1
timeout: 120s
use: AMBER persistent > 30min review, checkpoint diff comparison
forbidden: RED analysis, decisions, config changes
```

## Pro Timeout Policy

If deepseek-v4-pro times out:
1. Reduce analysis depth (3 bullets, not full report)
2. Reduce output to 4096
3. Do NOT increase timeout past 300s
4. If still fails: mark Need Human: YES

## Local Models

Local GGUF models (llama.cpp) are for **brainstorming, taste tests, and offline summaries only**. They do NOT replace the GA main pipeline.

See `05_LOCAL_MODEL_REGISTRY.md` for details.

## Provider Policy

- Active: DeepSeek official direct (api.deepseek.com/v1)
- OpenRouter: registered but not active (do not enable)
- Volcengine/Dashscope/Kimi: registered but not active for this pipeline
