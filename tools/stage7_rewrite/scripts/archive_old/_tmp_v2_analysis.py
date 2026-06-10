import json
from collections import Counter

rows = [json.loads(l) for l in open(r"D:\downstream_results\stage7_rewrite\stage8\region_maps\JINGHU_GPT_OSS_QA_20260509_v2\gpt_oss_qa_rows.jsonl", encoding="utf-8")]
print("total:", len(rows))

ok_rows = [r for r in rows if r.get("parse_ok") is True]
fail_rows = [r for r in rows if r.get("parse_ok") is False]
none_rows = [r for r in rows if r.get("parse_ok") is None]
print(f"parse_ok=True: {len(ok_rows)}, False: {len(fail_rows)}, None: {len(none_rows)}")

print("\n=== Successful parses ===")
for r in ok_rows:
    p = r.get("parsed") or {}
    print(f"  [{r['category']}] {r.get('title','')[:60]}")
    print(f"    recommended_action={p.get('recommended_action')} has_value={p.get('has_extractable_music_value')} priority={p.get('priority')}")
    print(f"    reason: {p.get('reason_short','')}")
    print(f"    tags: {p.get('scene_tags','')}")

print("\n=== Failed sample (first 3) raw_stdout ===")
for r in fail_rows[:3]:
    print(f"  [{r['category']}] returncode={r.get('returncode')} elapsed={r.get('elapsed_sec')}s")
    print(f"  raw_stdout: {repr(r.get('raw_stdout',''))[:200]}")
    print(f"  stderr: {repr(r.get('stderr',''))[:200]}")
    print()
