#!/usr/bin/env sh
set -eu

cd /mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite

python3 scripts/run_parallel_flash.py \
  --shards-dir reports/fullmap_manifest_20260513_routes/ready_text_remaining_shards \
  --instances 4 \
  --concurrency 3 \
  --out-dir reports \
  --run-name fullmap_47k_ready_text
