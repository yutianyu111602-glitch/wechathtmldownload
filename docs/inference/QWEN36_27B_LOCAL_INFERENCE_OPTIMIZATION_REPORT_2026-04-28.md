<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Qwen3.6-27B 本地推理优化报告
**Date**: 2026-04-28
**Machine**: Windows, RTX 4090 (24GB), CUDA 13.1, Driver 591.59
**Author**: GA (GenericAgent)

---

## 1. Machine Info
| Item | Value |
|------|-------|
| GPU | NVIDIA GeForce RTX 4090 |
| VRAM | 24,564 MiB |
| Current VRAM | 22,095 MiB used / 2,048 MiB free |
| Compute Cap | 8.9 |
| CUDA | 13.1 |
| Driver | 591.59 |
| Host | Windows, single GPU |

## 2. Model Files
| Model | Path | Size |
|-------|------|------|
| Target (main) | `D:\models\Qwen3.6-27B\Qwen3.6-27B-Q4_K_M.gguf` | 15.7 GB |
| Draft | `D:\models\Qwen3-1.7B-Q4_K_M.gguf` | 1.03 GB |
| FP8 (via HF) | NOT CACHED | N/A |
| 0.5B/0.6B draft | **NOT FOUND** | N/A |

## 3. Backend Versions
| Backend | Path | Version |
|---------|------|---------|
| llama-server | `C:\llama-cpp\bin\llama-server.exe` | v8851 (e365e658f) |
| llama-cli | `C:\llama-cpp\bin\llama-cli.exe` | same build |
| llama-bench | `C:\llama-cpp\bin\llama-bench.exe` | same build |
| vLLM (pip) | NOT INSTALLED | N/A |
| ik_llama.cpp | NOT FOUND | N/A |
| spark-vllm-docker | NOT CLONED | N/A |

## 4. Route A: llama.cpp Spec-Dec Benchmark Plan

### Winning Config (from public data)
```
llama-server
  -m Qwen3.6-27B-Q4_K_M.gguf
  -md Qwen3-1.7B-Q4_K_M.gguf
  -ngl 99 -ngld 99 -c 8192 -cd 4096
  -fa on -ctk q8_0 -ctv q8_0
  --draft-max 12 --draft-min 3 --draft-p-min 0.6
```

### Reference Benchmarks
| Run | tok/s | Acceptance |
|-----|-------|------------|
| Run 1 (peak) | 154.14 | 85.2% |
| Run 2 | 125.80 | 64.8% |
| Run 3 | 99.86 | 49.6% |
| 3-run avg | ~127 | ~66% |
| 192K @ q4_0 | 152 | N/A |

### Draft Model Sweep
| Draft | Status | Expected tok/s |
|-------|--------|---------------|
| No draft | Baseline | ~50-70 |
| Qwen3-1.7B-Q4_K_M | ✅ AVAILABLE | ~100-154 |
| Qwen3-0.5B (Q3/Q4) | ❌ NEEDS DOWNLOAD | ~170-190 |
| distilled 4B | ❌ NOT FOUND | N/A |

### KV Cache Sweep (8K context)
| Type | VRAM | Speed Impact |
|------|------|-------------|
| q8_0 | ~2 GB | Baseline (fastest) |
| q6_K | ~1.5 GB | ~5% slower |
| q4_0 | ~1 GB | ~10% slower |
| q2_K | ❌ NOT SUPPORTED | N/A |

### Context Sweep
| Context | KV Type | Expected VRAM | Expected tok/s |
|---------|---------|--------------|----------------|
| 8K | q8_0 | ~16 GB | ~154 |
| 32K | q8_0 | ~18 GB | ~120-140 |
| 32K | q4_0 | ~17 GB | ~110-130 |
| 64K | q4_0 | ~19 GB | ~90-110 |
| 128K | q4_0 | ~21 GB | ~70-90 |
| 192K | q4_0 | ~23 GB | ~50-70 |

### Draft Token Sweep (on 8K, q8_0)
| Draft-max | Expected Acceptance | Expected tok/s |
|-----------|--------------------|---------------|
| 3 | Very high (90%+) | ~80-90 |
| 5 | High (80%+) | ~100-120 |
| 8 | Good (70%+) | ~120-140 |
| 12 | Moderate (60%+) | ~130-154 |
| 15 | Lower (50%+) | ~120-140 (diminishing returns) |

## 5. Route B: vLLM FP8 + DFlash

### Current Status: NOT AVAILABLE
| Requirement | Status |
|-------------|--------|
| vLLM installed | ❌ |
| Qwen3.6-27B-FP8 cached | ❌ |
| spark-vllm-docker cloned | ❌ |
| 2nd GPU for TP=2 | ❌ (single 4090) |

### FP8 Single 4090 Assessment
- Qwen3.6-27B-FP8: ~16 GB weights (FP8 smaller than GGUF Q4)
- Plus KV cache at 32K: ~2-3 GB
- Total: ~18-19 GB → might barely fit
- BUT: vLLM overhead + CUDA graphs + chunked prefill → likely OOM
- Verdict: **NOT RECOMMENDED** for single 4090 production

### DFlash Assessment
- Requires vLLM + z-lab/Qwen3.6-27B-DFlash model
- Not cached locally
- Single GPU DFlash: experimental, acceptance unknown
- Verdict: **LOW PRIORITY**, only if Route A fails

## 6. YaRN + KV-Q2 Support
| Feature | Support | Notes |
|---------|---------|-------|
| `--rope-scaling yarn` | ✅ YES | Available |
| `--rope-scale N` | ✅ YES | Available |
| `-ctk q2_k` (KV-Q2) | ❌ NO | Not in v8851 |
| `-ctv q2_k` (KV-Q2) | ❌ NO | Not in v8851 |
| ik_llama.cpp | ❌ NOT FOUND | Could add KV-Q2 support |

## 7. Stage 7 Recommended Default Profile

### Production Default
```yaml
backend: llama-server (via llama-swap)
model_id: qwen36-27b-q4-spec-32k

command: |
  llama-server
    --host 127.0.0.1 --port ${PORT}
    -m "D:\models\Qwen3.6-27B\Qwen3.6-27B-Q4_K_M.gguf"
    -md "D:\models\Qwen3-1.7B-Q4_K_M.gguf"
    -ngl 99 -ngld 99
    -c 32768 -cd 4096
    -fa on
    -ctk q8_0 -ctv q8_0
    -b 2048 -ub 512
    --draft-max 12 --draft-min 3 --draft-p-min 0.6

generation:
  temperature: 0.1
  top_p: 0.9
  max_tokens: 4096
  json_only: true
  no_markdown: true
  evidence_required: true

worker:
  start_concurrency: 1
  max_concurrency: 2
```

### Fallback Profile (if VRAM tight)
```yaml
-ctk q4_0 -ctv q4_0
--draft-max 8
-c 8192
```

### Long Context Experimental (NOT default)
```yaml
-c 196608 -ctk q4_0 -ctv q4_0
--draft-max 8 --draft-min 2
--rope-scaling yarn --rope-scale 2.0  # if needed
```

## 8. 100-Article Smoke Test Plan
1. Update llama-swap config → add `qwen36-27b-q4-spec-32k` model
2. Restart llama-swap
3. Verify `/v1/models` shows new model
4. Run 100 articles through downstream pipeline
5. Measure: parse success, schema pass, tok/s, VRAM, acceptance rate
6. If pass all criteria → scale to 1000

## 9. Prohibited Actions
- ❌ Do NOT set 192K as Stage 7 default
- ❌ Do NOT run vLLM FP8 on single 4090 for production
- ❌ Do NOT use draft model for concurrent foreman + decoder (resource conflict)
- ❌ Do NOT modify existing default llama-swap models (only ADD new ones)
- ❌ Do NOT overwrite existing successful downstream results
- ❌ Do NOT run full 93K without 100-article smoke validation
