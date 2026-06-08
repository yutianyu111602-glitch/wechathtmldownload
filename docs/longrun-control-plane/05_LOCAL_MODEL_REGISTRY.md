<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Local Model Registry

**Created:** 2026-04-27
**Status:** SKELETON (not tested)

## Registered Models

All models in `D:\models\`.

### 1. Qwen3.6-27B-Q4_K_M

```yaml
path: D:\models\Qwen3.6-27B\Qwen3.6-27B-Q4_K_M.gguf
size: 15.66 GB
quant: Q4_K_M
date: 2026-04-24
recommended_use: Local Watch / Brainstorm / Quick Summary
suitable_for_llama_cpp: yes
suitable_for_opencode: yes (via local OpenAI-compatible server)
suitable_for_ga: yes (watch/summary only, not escalation)
test_status: not tested
notes: Already loaded via llama-swap:11434. Proven for calibration+eval.
```

### 2. Qwen3.6-35B-A3B-UD-Q4_K_M

```yaml
path: D:\models\Qwen3.6-35B-A3B-GGUF\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
size: 20.61 GB
quant: UD-Q4_K_M
date: 2026-04-27
recommended_use: Local Builder Brain / PRD / Runbook / Complex Planning
suitable_for_llama_cpp: yes
suitable_for_opencode: yes
suitable_for_ga: partial (planning, NOT execution)
test_status: not tested
notes: Larger MoE model. Higher quality for planning tasks. VRAM-intensive.
```

### 3. Qwen3.6-35B-A3B-IQ4_NL

```yaml
path: D:\models\Qwen3.6-35B-A3B-GGUF\Qwen_Qwen3.6-35B-A3B-IQ4_NL.gguf
size: 18.50 GB
quant: IQ4_NL
date: 2026-04-27
recommended_use: Fallback / Speed Test / Low-resource Comparison
suitable_for_llama_cpp: yes
suitable_for_opencode: yes
suitable_for_ga: no (lower quality, use as control group only)
test_status: not tested
notes: IQ4_NL quantization trades some quality for speed/size. Compare vs UD.
```

### 4. Gemma-4-31B-JANG_4M-CRACK

```yaml
path: D:\models\Gemma-4-31B-JANG_4M-CRACK-GGUF\gemma-4-31b-jang-crack-Q4_K_M.gguf
size: 17.40 GB
quant: Q4_K_M
date: 2026-04-27
recommended_use: Experimental / Taste Test / Control Group
suitable_for_llama_cpp: yes
suitable_for_opencode: unknown (Gemma architecture, may need special flags)
suitable_for_ga: no
test_status: not tested
notes: Google Gemma architecture. "Crack" variant. Use as experimental comparison.
```

## VRAM Summary

| Model | Size | VRAM Est |
|-------|------|----------|
| Qwen3.6-27B-Q4_K_M | 15.66 GB | ~16 GB |
| Qwen3.6-35B-A3B-UD-Q4_K_M | 20.61 GB | ~21 GB |
| Qwen3.6-35B-A3B-IQ4_NL | 18.50 GB | ~19 GB |
| Gemma-4-31B | 17.40 GB | ~18 GB |

GPU: RTX 4090 (24 GB VRAM). Only ONE model fits at a time. Loading a second model requires unloading the first.

## Load Status

- Currently loaded: Qwen3.6-27B (llama-swap:11434)
- Others: not loaded
