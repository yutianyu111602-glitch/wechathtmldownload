<!-- CODE_ALIGNMENT_2026_04_30_START -->
> Code alignment note (2026-04-30): this document was reviewed during the repository-wide docs/code sync. Treat `README.md`, `AGENTS.md`, `docs/CURRENT_CODE_MAP.md`, `docs/CLI_REFERENCE.md`, `docs/CONFIGURATION.md`, `docs/CODE_AUDIT.md`, and `docs/DOCUMENTATION_INDEX.md` as current code-aligned SSOT. Older dated handoffs/logs remain historical evidence and must be checked against current code before execution.
<!-- CODE_ALIGNMENT_2026_04_30_END -->

# Stage7 运行手册
**日期**: 2026-04-28
**模型**: Qwen3.6-27B (spec) + Qwen3-1.7B (foreman) + Mac向量

## 运行流程

### Phase 1: 初始化
```powershell
# 1. 确认输入
Test-Path "D:\DDownload\_llm_release_v2\articles\"
Test-Path "D:\downstream_results\"

# 2. 确认模型服务
Invoke-RestMethod http://127.0.0.1:11434/v1/models

# 3. 确认 checkpoint 目录
New-Item -ItemType Directory -Force -Path "D:\downstream_results\state"
```

### Phase 2: Smoke Test (100篇)
```powershell
# 从63个公众号各取1-2篇，共100篇
python scripts/stage7/smoke_test.py --count 100
```

### Phase 3: 8K Extraction Batch
```powershell
# 按公众号分批，每批1000篇
python scripts/stage7/run_extraction_batch.py ^
  --model qwen36-27b-q4-spec-8k ^
  --mode extract ^
  --batch-size 1000 ^
  --checkpoint-every 100
```

### Phase 4: Foreman Validation
```powershell
# 对下游结果做 foreman 质检
python scripts/stage7/run_foreman_batch.py ^
  --model qwen36-27b-q4-spec-8k ^
  --batch-size 500
```

### Phase 5: 32K Long Context (备用)
当文章超过8K char时才切32K模型：
```powershell
python scripts/stage7/run_extraction_batch.py ^
  --model qwen36-27b-q4-spec-32k ^
  --mode extract-long ^
  --input-threshold 8000
```

## 中断恢复
```powershell
# 从上次 checkpoint 继续
python scripts/stage7/run_extraction_batch.py --resume
```

## 监控命令
```powershell
# 实时进度
python scripts/stage7/monitor_progress.py --watch

# 失败分析
python scripts/stage7/analyze_failures.py --last 1000
```
