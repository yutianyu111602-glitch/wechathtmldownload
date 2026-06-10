import json
from collections import Counter

rows = [json.loads(l) for l in open(r"D:\downstream_results\stage7_rewrite\stage8\region_maps\JINGHU_GPT_OSS_QA_20260509\gpt_oss_qa_rows.jsonl", encoding="utf-8")]
print("total:", len(rows))

cats = Counter(r["category"] for r in rows)
print("categories:", dict(cats))

accts = Counter(r.get("account","?") for r in rows)
print("top accounts:", accts.most_common(10))

ev_counts = [r.get("event_count",0) or 0 for r in rows]
ent_counts = [r.get("entity_count",0) or 0 for r in rows]
print("avg event_count:", round(sum(ev_counts)/len(ev_counts),2))
print("avg entity_count:", round(sum(ent_counts)/len(ent_counts),2))

ev_drop = [r.get("evidence_drop_count",0) or 0 for r in rows]
print("avg evidence_drop:", round(sum(ev_drop)/len(ev_drop),2))

prios = Counter(r.get("priority","?") for r in rows)
print("priorities:", dict(prios))

# Sample titles
print("\nsample titles (high_evidence_drop):")
for r in [x for x in rows if x["category"]=="high_evidence_drop"][:5]:
    print(" ", r.get("title","?")[:80])
print("\nsample titles (low_confidence_map_candidate):")
for r in [x for x in rows if x["category"]=="low_confidence_map_candidate"][:5]:
    print(" ", r.get("title","?")[:80])
