@echo off
set DEEPSEEK_API_KEY=sk-REDACTED
cd /d C:\code\githubstar\wechathtmldownload
python tools\stage7_rewrite\scripts\deepseek_hybrid_scorer.py ^
  --flash-jsonl tools\stage7_rewrite\reports\deepseek_flash_expand1000_20260509\flash_rows.jsonl ^
  --out-dir tools\stage7_rewrite\reports\deepseek_hybrid_score_expand1000_20260509
