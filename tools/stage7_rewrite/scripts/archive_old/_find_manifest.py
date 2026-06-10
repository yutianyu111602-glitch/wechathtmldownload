"""Check what manifest the pilot used, and list available large manifests."""
import json
from pathlib import Path

# Check pilot selected manifest
pilot = Path(r'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\deepseek_flash_pilot_20260509_500\selected_manifest.jsonl')
if pilot.exists():
    lines = pilot.read_text(encoding='utf-8').splitlines()
    lines = [l for l in lines if l.strip()]
    r = json.loads(lines[0])
    print(f"PILOT: {len(lines)} rows")
    print(f"  llm_input={r.get('llm_input_path','N/A')[:120]}")
    print(f"  meta={r.get('meta_path','N/A')[:120]}")
    print(f"  source_account={r.get('source_account','N/A')}")

# Look for manifests with many rows
manifest_dir = Path(r'D:\downstream_results\stage7_rewrite\manifests')
for p in sorted(manifest_dir.glob('*.jsonl'), key=lambda x: x.stat().st_size, reverse=True)[:15]:
    size_mb = p.stat().st_size / 1_000_000
    # Quick line count
    with p.open('r', encoding='utf-8') as f:
        lines = sum(1 for _ in f)
    if lines > 100:
        # Check first row to see if it has llm_input_path
        with p.open('r', encoding='utf-8') as f:
            first = json.loads(f.readline())
        has_llm = 'llm_input_path' in first
        llm_sample = str(first.get('llm_input_path', 'N/A'))[:80]
        win_path = llm_sample.startswith('D:') or llm_sample.startswith('C:')
        print(f"  {p.name}: {lines} rows, {size_mb:.1f}MB, has_llm={has_llm}, win_path={win_path}, sample={llm_sample}")
