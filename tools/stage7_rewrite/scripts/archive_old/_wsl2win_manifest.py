"""Convert WSL manifest paths to Windows and verify."""
import json, sys
from pathlib import Path

manifest = Path(sys.argv[1])
out_path = Path(sys.argv[2])

converted = 0
missing = 0
with manifest.open('r', encoding='utf-8') as fin, out_path.open('w', encoding='utf-8') as fout:
    for line in fin:
        if not line.strip():
            continue
        row = json.loads(line)
        for key in ('llm_input_path', 'meta_path', 'poster_ocr_path', 'article_dir'):
            val = row.get(key, '')
            if isinstance(val, str) and val.startswith('/mnt/'):
                # /mnt/d/... -> D:\...
                new_val = val[5:]  # remove '/mnt/'
                new_val = new_val.replace('/', '\\')
                new_val = new_val[0].upper() + ':' + new_val[1:]  # d\... -> D:\...
                row[key] = new_val
        # Verify
        llm = Path(row.get('llm_input_path', ''))
        if not llm.exists():
            missing += 1
        converted += 1
        fout.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + '\n')

print(f"converted={converted} missing={missing}")
