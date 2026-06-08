<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Model Policy — WeChat Pipeline Long Run

## 2026-05-07 Current Overlay

This file is a historical model governance baseline. For the active Stage7 extraction lane, use the current repo config:

- Config: `C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\config\default.yaml`
- API style: OpenAI-compatible `/v1/*`
- Endpoint: `http://192.168.128.1:11434`
- Model: `Qwen3.6-27B`

For vector embeddings, use `VECTOR_MODEL_REGISTRY_SSOT.md` and `tools\stage7_rewrite\config\vector_endpoints.yaml`; default 93k vector route is Mac `11437`, `stella-large-zh-v2`, dimension `1024`.

**Created:** 2026-04-27
**Model:** qwen3.6-max (planning)
**Status:** CONSOLIDATED from existing skeleton files
**Sources:**
- `docs/longrun-control-plane/04_MODEL_PROFILE_POLICY.md`
- `docs/longrun-control-plane/05_LOCAL_MODEL_REGISTRY.md`

---

## 1. Cloud API Profiles (OpenCode)

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

### qwen3.6-max — Architecture Planning (Local)

```yaml
model: qwen3.6-max (local, via llama-swap or direct)
use: Architecture planning, PRD writing, runbook writing, task decomposition
forbidden: production batch execution, config changes
```

## 2. Pro Timeout Policy

If deepseek-v4-pro times out:
1. Reduce analysis depth (3 bullets, not full report)
2. Reduce output to 4096
3. Do NOT increase timeout past 300s
4. If still fails: mark Need Human: YES

## 3. Local Model Registry (D:\models)

All models in `D:\models\`. RTX 4090 = 24GB VRAM. Only ONE model fits at a time.

### 3.1 Qwen3.6-27B-Q4_K_M

```yaml
path: D:\models\Qwen3.6-27B\Qwen3.6-27B-Q4_K_M.gguf
size: 15.66 GB
quant: Q4_K_M
recommended_use: Local Watch / Brainstorm / Quick Summary / Structured Extraction
suitable_for_llama_cpp: yes
suitable_for_opencode: yes (via local OpenAI-compatible server)
suitable_for_ga: yes (watch/summary only, not escalation)
test_status: tested (llama-swap:11434, ~40 t/s gen, ~186-293 t/s prompt)
notes: Already loaded via llama-swap:11434. Proven for calibration+eval.
```

### 3.2 Qwen3.6-35B-A3B-UD-Q4_K_M

```yaml
path: D:\models\Qwen3.6-35B-A3B-GGUF\Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
size: 20.61 GB
quant: UD-Q4_K_M
recommended_use: Local Builder Brain / PRD / Runbook / Complex Planning
suitable_for_llama_cpp: yes
suitable_for_opencode: yes
suitable_for_ga: partial (planning, NOT execution)
test_status: not tested
notes: Larger MoE model. Higher quality for planning tasks. VRAM-intensive.
```

### 3.3 Qwen3.6-35B-A3B-IQ4_NL

```yaml
path: D:\models\Qwen3.6-35B-A3B-GGUF\Qwen_Qwen3.6-35B-A3B-IQ4_NL.gguf
size: 18.50 GB
quant: IQ4_NL
recommended_use: Fallback / Speed Test / Low-resource Comparison
suitable_for_llama_cpp: yes
suitable_for_opencode: yes
suitable_for_ga: no (lower quality, use as control group only)
test_status: not tested
notes: IQ4_NL quantization trades some quality for speed/size. Compare vs UD.
```

### 3.4 Gemma-4-31B-JANG_4M-CRACK

```yaml
path: D:\models\Gemma-4-31B-JANG_4M-CRACK-GGUF\gemma-4-31b-jang-crack-Q4_K_M.gguf
size: 17.40 GB
quant: Q4_K_M
recommended_use: Experimental / Taste Test / Control Group
suitable_for_llama_cpp: yes
suitable_for_opencode: unknown (Gemma architecture, may need special flags)
suitable_for_ga: no
test_status: not tested
notes: Google Gemma architecture. "Crack" variant. Use as experimental comparison.
```

## 4. VRAM Summary

| Model | Size | VRAM Est | Fits in 24GB? |
|-------|------|----------|---------------|
| Qwen3.6-27B-Q4_K_M | 15.66 GB | ~16 GB | ✅ Yes |
| Qwen3.6-35B-A3B-UD-Q4_K_M | 20.61 GB | ~21 GB | ✅ Yes (tight) |
| Qwen3.6-35B-A3B-IQ4_NL | 18.50 GB | ~19 GB | ✅ Yes |
| Gemma-4-31B | 17.40 GB | ~18 GB | ✅ Yes |

## 5. Load Status

- Currently loaded: Qwen3.6-27B (llama-swap:11434)
- Others: not loaded

## 6. Provider Policy

- Active: DeepSeek official direct (api.deepseek.com/v1)
- OpenRouter: registered but not active (do not enable)
- Volcengine/Dashscope/Kimi: registered but not active for this pipeline
- Local GGUF: for brainstorming, taste tests, and offline summaries only

## 7. Model Selection Rules

| Task | Recommended Model | Reason |
|------|-------------------|--------|
| Architecture planning | qwen3.6-max (local) | High quality planning, no API cost |
| PRD / Runbook writing | qwen3.6-max (local) | Long context, good structure |
| Task decomposition | qwen3.6-max (local) | Complex reasoning |
| RED escalation | deepseek-v4-pro | Best root-cause analysis |
| Monitoring / Watch | deepseek-v4-flash | Fast, cheap, sufficient |
| Structured extraction | Qwen3.6-27B (local) | Proven, ~40 t/s |
| AMBER review | deepseek-v4-flash-extended | Moderate context needed |
