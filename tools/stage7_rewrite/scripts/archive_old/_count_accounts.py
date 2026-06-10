import json
from collections import Counter
rows = [json.loads(l) for l in open(r'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\scripts\_count_accounts.py', encoding='utf-8') if l.strip()]
# Actually, open NEXT1000
rows = [json.loads(l) for l in open(r'C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports\win_NEXT1000_SUPERRUN.jsonl', encoding='utf-8') if l.strip()]
print(f'NEXT1000: total={len(rows)}, accounts={len(set(r.get("source_account","?") for r in rows))}')
