"""Quick manifest structure check."""
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
rows = [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
r = rows[0]
print(f"total_rows={len(rows)}")
print(f"keys={sorted(r.keys())}")
print(f"sample_uid={str(r.get('article_uid','N/A'))[:40]}")
print(f"llm_input={str(r.get('llm_input_path','N/A'))[:120]}")
print(f"status={r.get('status','N/A')}")
# Count pending
pending = sum(1 for row in rows if row.get('status') in {None, 'pending'})
print(f"pending_rows={pending}")
