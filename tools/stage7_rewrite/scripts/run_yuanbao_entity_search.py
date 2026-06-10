#!/usr/bin/env python3
"""Phase 4: Yuanbao-enhanced entity search for unmatched DB2 entities.

For DB2 entities that had NO match in DB3 (not even fuzzy name match):
1. Search entity name + "electronic music DJ club" via Yuanbao
2. Extract potential DB3 matches from Yuanbao's knowledge
3. Record as enrichment candidates

Uses opencli yuanbao CLI (must be installed).

Report-only: outputs yuanbao_entity_search_results.json
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

INVENTORY_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports"
    r"\cross_db_entity_inventory_20260608\cross_db_eid_inventory.json"
)
DECISIONS_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports"
    r"\cross_db_identity_resolution_20260608\cross_db_identity_decisions.jsonl"
)
OUT_DIR = DECISIONS_PATH.parent

BATCH_SIZE = 15  # entities per yuanbao call (batch mode)
MAX_ENTITIES = 200  # increased from 50 to cover more unmatched


def load_inventory() -> tuple[list[dict], dict]:
    data = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    db2_entities = data.get("db2_entities", [])
    db3_lookup = {e["entity_id"]: e for e in data.get("db3_entities", [])}
    return db2_entities, db3_lookup


def load_matched_eids() -> set[str]:
    """Get eids already matched from LLM decisions."""
    matched = set()
    if DECISIONS_PATH.exists():
        for line in DECISIONS_PATH.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                if d.get("decision") == "match" and d.get("matched_db3_entity_id"):
                    matched.add(d.get("eid", ""))
            except json.JSONDecodeError:
                pass
    return matched


def get_unmatched(
    db2_entities: list[dict], matched_eids: set[str], db3_lookup: dict
) -> list[dict]:
    """Find DB2 entities with zero match in DB3."""
    # Check which eids were already cross-referenced
    matched_in_inventory = set()
    for e in db2_entities:
        matched = e.get("matched_db3_ids", [])
        if matched:
            matched_in_inventory.add(e["eid"])

    # Also add LLM-matched
    all_matched = matched_in_inventory | matched_eids

    unmatched = [
        e
        for e in db2_entities
        if e["eid"] not in all_matched and e.get("primary_name")
    ]

    # Sort by platform diversity (more platforms = more interesting)
    unmatched.sort(key=lambda e: len(e.get("platforms", [])), reverse=True)
    return unmatched


def search_yuanbao(entities: list[dict]) -> dict[str, Any]:
    """Use Yuanbao to search for entity enrichment."""
    entity_list = []
    for e in entities:
        name = e.get("primary_name", "")
        handles = ", ".join(e.get("handles", [])[:3])
        platforms = ", ".join(e.get("platforms", []))
        entity_list.append(f"- {name} (handles: {handles}, platforms: {platforms})")

    prompt = f"""以下是中国地下电子音乐场景中的实体（DJ/俱乐部/厂牌），请判断它们是否在以下已知实体列表中。

已知实体类型：DJ个人、俱乐部venue、音乐厂牌label、主办方organizer

实体列表：
{chr(10).join(entity_list)}

请为每个实体回答：
1. 这个实体最可能是什么类型（DJ/俱乐部/厂牌/主办方/其他）
2. 它的中文名或常用名是什么
3. 是否与以下已知俱乐部有关联：Dada, OIL, 招待所ZhaoDai, loopy, wigwam, ALL Club, Elevator, Heim, SYSTEM, 莫须有工厂

输出JSON格式（只输出JSON，不要其他文字）：
[
  {{"name": "实体名", "type": "dj|club|label|organizer|other", "chinese_name": "中文名或空", "related_club": "关联俱乐部或空", "confidence": "high|medium|low"}}
]"""

    try:
        # Use shell=True to inherit PATH (opencli is a global npm binary)
        result = subprocess.run(
            f'opencli yuanbao ask --timeout 180 --search true --think true "{prompt}"',
            capture_output=True, text=True, timeout=200,
            shell=True,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500],
            "entities_searched": [e.get("primary_name") for e in entities],
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "timeout", "stdout": "", "stderr": ""}
    except FileNotFoundError:
        return {"success": False, "error": "opencli not found", "stdout": "", "stderr": ""}


def main():
    print("=" * 60)
    print("Phase 4: Yuanbao Entity Search (report-only)")
    print("=" * 60)

    # Check opencli
    try:
        result = subprocess.run(
            "opencli yuanbao status",
            capture_output=True, text=True, timeout=10,
            shell=True,
        )
        print(f"  opencli status: {result.stdout.strip()[:100]}")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print("  ⚠️  opencli not found. Skipping yuanbao search.")
        print("     Install: npm install -g @jackwener/opencli")
        return

    db2_entities, db3_lookup = load_inventory()
    matched_eids = load_matched_eids()
    unmatched = get_unmatched(db2_entities, matched_eids, db3_lookup)

    print(f"  DB2 entities:    {len(db2_entities):,}")
    print(f"  Matched (LLM):   {len(matched_eids):,}")
    print(f"  Unmatched:       {len(unmatched):,}")
    print(f"  Will search:     {min(len(unmatched), MAX_ENTITIES)}")

    if not unmatched:
        print("  ✅ All DB2 entities matched!")
        return

    # Sample top entities for search
    sample = unmatched[:MAX_ENTITIES]

    results = []
    for i in range(0, len(sample), BATCH_SIZE):
        batch = sample[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        names = [e.get("primary_name", "") for e in batch]
        print(f"\n  Batch {batch_num}: {names}")

        result = search_yuanbao(batch)
        result["batch"] = batch_num
        results.append(result)

        if result.get("success"):
            print(f"    ✅ Yuanbao responded ({len(result.get('stdout', ''))} chars)")
        else:
            print(f"    ❌ {result.get('error', 'unknown error')}")

        if i + BATCH_SIZE < len(sample):
            time.sleep(2)  # Rate limit

    # Save results
    report = {
        "schema_version": "yuanbao_entity_search.v1",
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "total_unmatched": len(unmatched),
        "searched": len(sample),
        "results": results,
    }
    report_path = OUT_DIR / "yuanbao_entity_search_results.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✅ Yuanbao results: {report_path}")


if __name__ == "__main__":
    main()
