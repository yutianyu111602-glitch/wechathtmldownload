import time, sys, os

os.chdir(r'C:\code\githubstar\wechathtmldownload')
sys.path.insert(0, 'tools/stage7_rewrite/scripts')

start = time.time()
print(f"[{time.strftime('%H:%M:%S')}] Starting build with merge_map (WAL mode)...")
sys.stdout.flush()

from build_atlas_core_candidate import build_candidate, parse_args

args = parse_args([
    '--out-dir', 'tools/stage7_rewrite/reports/atlas_core_merge_map_20260607',
    '--dataset-id', 'atlas_core_merge_map_20260607',
])

result = build_candidate(args)

elapsed = time.time() - start
print(f"[{time.strftime('%H:%M:%S')}] Build done: {elapsed:.0f}s")
print(f"decision: {result['decision']}")

for k, v in list(result.get('core_counts', {}).items())[:8]:
    print(f"  {k}: {v:,}")
