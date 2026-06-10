#!/usr/bin/env python3
"""Phase 3: Build unified cross-DB merge_map from identity resolution decisions.

Reads cross_db_identity_decisions.jsonl and produces:
1. cross_db_merge_map.json — DB2 eid → DB3 canonical entity_id
2. cross_db_identity_report.json — statistics and unmatched entities

Query-time usage:
  db3_entity = merge_map.get(db2_eid, None)  # O(1) HashMap lookup
  if db3_entity:
      entity = db3[db3_entity]  # canonical entity
  else:
      entity = db2_standalone[db2_eid]  # DB2-only entity

No SQL UPDATE on the 2.1GB DB3.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

DECISIONS_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports"
    r"\cross_db_identity_resolution_20260608\cross_db_identity_decisions.jsonl"
)
INVENTORY_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports"
    r"\cross_db_entity_inventory_20260608\cross_db_eid_inventory.json"
)
EXISTING_MERGE_MAP_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\services\weekly_activity_cloudrun"
    r"\tmp\cloudrun_deploy_context\data\merge_map.json"
)
OUT_DIR = DECISIONS_PATH.parent


def main():
    print("=" * 60)
    print("Phase 3: Build Unified Cross-DB Merge Map")
    print("=" * 60)

    # Load decisions
    decisions = []
    with open(DECISIONS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                decisions.append(json.loads(line))

    print(f"  Decisions: {len(decisions):,}")

    # Load inventory for full DB2 context
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    db2_lookup = {e["eid"]: e for e in inventory.get("db2_entities", [])}

    # Build merge map
    merge_map = {}  # db2_eid → db3_entity_id
    matches = []
    no_matches = []
    errors = []

    for d in decisions:
        eid = d.get("eid", "")
        decision = d.get("decision", "")

        if decision == "match" and d.get("matched_db3_entity_id"):
            merge_map[eid] = d["matched_db3_entity_id"]
            matches.append(d)
        elif decision == "error":
            errors.append(d)
        else:
            no_matches.append(d)

    # Load existing merge_map
    existing_map = {}
    if EXISTING_MERGE_MAP_PATH.exists():
        existing_data = json.loads(EXISTING_MERGE_MAP_PATH.read_text(encoding="utf-8"))
        existing_map = existing_data.get("subject_map", {})
        print(f"  Existing merge_map: {len(existing_map):,} remaps")

    # Build unified output
    unified_map = {
        "schema_version": "cross_db_merge_map.v1",
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "stats": {
            "total_decisions": len(decisions),
            "matches": len(matches),
            "no_matches": len(no_matches),
            "errors": len(errors),
            "db2_eids_mapped": len(merge_map),
            "existing_remaps": len(existing_map),
        },
        "db2_to_db3_map": merge_map,
        "existing_subject_map": existing_map,
    }

    # Confidence breakdown
    conf_levels = Counter()
    for m in matches:
        conf = m.get("confidence", 0)
        if conf >= 0.9:
            conf_levels["high (≥0.9)"] += 1
        elif conf >= 0.7:
            conf_levels["medium (0.7-0.9)"] += 1
        elif conf >= 0.5:
            conf_levels["low (0.5-0.7)"] += 1
        else:
            conf_levels["very_low (<0.5)"] += 1
    unified_map["stats"]["confidence_breakdown"] = dict(conf_levels)

    # Save
    map_path = OUT_DIR / "cross_db_merge_map.json"
    map_path.write_text(
        json.dumps(unified_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✅ Merge map: {map_path} ({map_path.stat().st_size:,} bytes)")

    # Report
    report = {
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "stats": unified_map["stats"],
        "top_matches": [
            {
                "eid": m["eid"],
                "db2_name": m.get("primary_name"),
                "db3_id": m.get("matched_db3_entity_id"),
                "db3_name": m.get("matched_db3_name"),
                "confidence": m.get("confidence"),
                "reason": m.get("reason_zh"),
            }
            for m in sorted(
                matches, key=lambda x: x.get("confidence", 0), reverse=True
            )[:20]
        ],
        "high_confidence_count": conf_levels.get("high (≥0.9)", 0),
        "medium_confidence_count": conf_levels.get("medium (0.7-0.9)", 0),
        "unmatched_eids": len(no_matches),
    }
    report_path = OUT_DIR / "cross_db_identity_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ Report: {report_path}")

    print(f"\n📊 Final Summary:")
    print(f"   Total decisions:   {len(decisions):,}")
    print(f"   Match (mapped):    {len(matches):,}")
    print(f"   No match:          {len(no_matches):,}")
    print(f"   Errors:            {len(errors):,}")
    print(f"   DB2→DB3 map size:  {len(merge_map):,}")
    print(f"   Existing remaps:   {len(existing_map):,}")
    print(f"   Confidence:")
    for level, count in sorted(conf_levels.items()):
        print(f"     {level}: {count:,}")


if __name__ == "__main__":
    main()
