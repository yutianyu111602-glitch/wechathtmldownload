"""Quick audit of vector_jobs.gate_plan.jsonl quality."""
import json, pathlib, collections, sys

gate_dir = pathlib.Path(r"D:\downstream_results\stage7_rewrite\stage8\region_maps\JINGHU_GATE_FULL_4K_20260509")
plan_file = gate_dir / "vector_jobs.gate_plan.jsonl"

city_counts = collections.Counter()
venue_filled = 0
entity_in_card = 0
event_in_card = 0
short_cards = []
total_article = 0
ct_len_list = []

with plan_file.open("r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if row.get("object_kind") != "article":
            continue
        total_article += 1
        ct = row.get("canonical_text") or ""
        meta = row.get("metadata") or {}
        city = meta.get("city") or ""
        venue = meta.get("venue") or ""
        city_counts[city if city else "EMPTY"] += 1
        if venue:
            venue_filled += 1
        if "Top实体:" in ct:
            entity_in_card += 1
        if "时间" in ct or "event_time" in ct:
            event_in_card += 1
        ct_len_list.append(len(ct))
        if len(ct) < 80:
            short_cards.append(ct)

filled_city = sum(v for k, v in city_counts.items() if k != "EMPTY")
print(f"Articles: {total_article}")
print(f"City filled: {filled_city} / {total_article}  ({100*filled_city//total_article}%)")
print(f"City EMPTY: {city_counts['EMPTY']}")
print(f"City breakdown: {dict(city_counts.most_common(8))}")
print(f"Venue filled (meta): {venue_filled} / {total_article}  ({100*venue_filled//total_article}%)")
print(f"Top实体 in card: {entity_in_card} / {total_article}  ({100*entity_in_card//total_article}%)")
print(f"Card len avg/min/max: {sum(ct_len_list)//len(ct_len_list)} / {min(ct_len_list)} / {max(ct_len_list)}")
print()
print(f"Short cards (<80 chars): {len(short_cards)}")
for s in short_cards[:8]:
    print(" ", repr(s))

# Check a well-filled article card
print()
print("=== Best article card (longest) ===")
with plan_file.open("r", encoding="utf-8") as f:
    rows = [json.loads(l) for l in f if l.strip()]
articles = [r for r in rows if r.get("object_kind") == "article"]
best = max(articles, key=lambda r: len(r.get("canonical_text") or ""))
print(best.get("canonical_text", ""))
