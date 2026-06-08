<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Qwen3.6-27B 1M Context Path Audit
**Date**: 2026-04-28
**Machine**: Windows, RTX 4090 24GB, CUDA 13.1

---

## 1. llama-server Version & Build
- Binary: `C:\llama-cpp\bin\llama-server.exe`
- Build: v8851 (e365e658f)
- Compiler: Clang 19.1.5 for Windows x86_64
- Size: 12.6 MB
- CUDA backend: ✅ loaded (1 device, 24563 MiB)

## 2. YaRN Runtime Rope Scaling
- `--rope-scaling {none,linear,yarn}`: ✅ SUPPORTED
- `--rope-scale N`: ✅ SUPPORTED
- Note: YaRN is available but NOT YET VALIDATED for long context stability on this build.

## 3. KV-Q2 Support
- `-ctk q2_k` / `--cache-type-k q2_k`: ❌ NOT SUPPORTED
- `-ctv q2_k` / `--cache-type-v q2_k`: ❌ NOT SUPPORTED
- Available KV types: q8_0, q6_K, q5_K, q4_0, q4_1, f16 (and f32 for some)
- Limitation: KV-Q2 requires newer llama.cpp build or ik_llama.cpp fork.

## 4. Draft Model Long Context
- `-md`/`--model-draft`: ✅ SUPPORTED
- `-cd`/`--ctx-size-draft`: ✅ SUPPORTED
- `-ngld`/`--gpu-layers-draft`: ✅ SUPPORTED
- Draft model scales with main model context; larger context = more VRAM for both.

## 5. 192K Reproduction Feasibility
- Reference: 192K @ 152 tok/s, q4_0 KV, 1.7B draft, ~559MB free
- VRAM estimate for 4090 24GB:
  - Qwen3.6-27B Q4_K_M: ~16 GB
  - KV cache @ q4_0 192K: ~6-8 GB
  - Draft model @ q4_0: ~1 GB
  - Total: ~23-24 GB → tight but possible
- Status: **LIKELY REPRODUCIBLE** with `-c 196608 -ctk q4_0 -ctv q4_0 --draft-max 8`

## 6. 256K Feasibility
- Estimated VRAM: ~24-25 GB → likely OOM on 24GB
- Needs: YaRN rope scaling + q4_0 KV + reduced draft tokens (<=6)
- If YaRN is effective, might barely fit.
- Status: **POSSIBLE WITH YaRN, NEEDS TESTING**

## 7. 384K Feasibility (YaRN required)
- Needs: `--rope-scaling yarn --rope-scale 2.0` (or larger)
- KV cache at q4_0 384K: ~12-14 GB → impossible with full KV
- Needs KV compression → KV-Q2 NOT available → **NOT FEASIBLE** with current build
- Status: **BLOCKED** (needs KV-Q2 or ik_llama.cpp or streaming)

## 8. 512K - 1M Feasibility
- 512K: KV ~16-18 GB → impossible on 24GB without KV-Q2 + streaming
- 1M: completely infeasible on single 4090 with current build
- Status: **NOT REALISTIC** for current hardware/build

## 9. Value for Stage 7
- Stage 7 articles (WeChat): average length ~2-8K tokens
- 192K: NO practical value for Stage 7
- 32K: sweet spot for long articles
- 64K: max reasonable ceiling
- Verdict: **1M is a weekend experiment, not production**

## 10. Path to 1M (theoretical)
| Step | Context | KV Type | YaRN | Draft | Feasible Now? |
|------|---------|---------|------|-------|---------------|
| Current | 192K @ 152 tok/s | q4_0 | No | 1.7B | ✅ Yes |
| Step 1 | 256K | q4_0 | Maybe | 1.7B @ d6 | ⚠️ Borderline |
| Step 2 | 384K | **q2_k needed** | 2x | Smaller | ❌ KV-Q2 missing |
| Step 3 | 512K | **q2_k needed** | 3x | 0.5B | ❌ KV-Q2 + model missing |
| Step 4 | 768K | streaming | 4x | Tiny | ❌ Not feasible |
| Step 5 | 1M | streaming | 5x | Tiny | ❌ Not feasible |
