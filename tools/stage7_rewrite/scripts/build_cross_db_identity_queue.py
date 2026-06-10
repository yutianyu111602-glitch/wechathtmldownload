#!/usr/bin/env python3
"""Build cross-DB identity resolution queue from eid inventory.

Reads cross_db_eid_inventory.json, extracts LLM candidates (multi-match + fuzzy),
and builds a JSONL queue suitable for DeepSeek Flash resolution.

Output: cross_db_identity_queue.jsonl
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

INVENTORY_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports"
    r"\cross_db_entity_inventory_20260608\cross_db_eid_inventory.json"
)
OUT_DIR = Path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports"
    r"\cross_db_identity_resolution_20260608"
)
OUT_DIR.mkdir(parents=True, exist_ok=True)

SYSTEM_PROMPT = """你是 Atlas 图谱数据库的跨库实体消歧裁决器。
任务：判断 DB2（外部社交证据库）中的实体是否与 DB3（服务图谱库）中某个实体指向同一真实世界实体。

严格规则：
1. DB2 entity 来自社交媒体/外部平台爬取，名称可能是 handle/@用户名/拼音变体
2. DB3 entity 来自微信文章提取，名称是正式中文/英文名称
3. 如果名称明显指向同一实体（如 "Dada Bar Beijing" ↔ "DADA BEIJING"），匹配
4. 如果 DB2 的 name/handle 与 DB3 某实体名称近似但不完全相同，判断是否同一实体
5. DJ/个人与俱乐部/场地不能匹配到一起
6. 不同城市同名连锁保持分开
7. 不确定的选择 no_match，不要强行匹配
8. 输出严格 JSON object，不要 Markdown

JSON schema:
{
  "decision": "match|no_match",
  "matched_db3_entity_id": "string or empty",
  "matched_db3_name": "string or empty",
  "confidence": 0.0,
  "reason_zh": "不超过120字中文说明"
}"""


def build_cluster_id(eid: str, db3_ids: list[str]) -> str:
    """Stable cluster id."""
    payload = json.dumps({"eid": eid, "db3_ids": sorted(db3_ids)}, sort_keys=True)
    return "cross_db:" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def main():
    print("Loading inventory...")
    data = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    candidates = data.get("candidates_for_llm", [])
    db3_lookup = {e["entity_id"]: e for e in data.get("db3_entities", [])}

    print(f"  Candidates: {len(candidates):,}")
    print(f"  DB3 entities: {len(db3_lookup):,}")

    # Build queue
    queue = []
    skipped = 0
    for c in candidates:
        eid = c.get("eid", "")
        primary_name = c.get("primary_name", "")
        match_type = c.get("match_type", "")
        match_source = c.get("match_source", "")
        handles = c.get("handles", [])
        platforms = c.get("platforms", [])
        db3_ids = c.get("matched_db3_ids", [])

        if not db3_ids:
            skipped += 1
            continue

        # Gather DB3 entity details
        db3_members = []
        for did in db3_ids:
            d3 = db3_lookup.get(did, {})
            db3_members.append({
                "entity_id": did,
                "names": d3.get("names", [])[:5],
                "types": d3.get("types", []),
                "cities": d3.get("cities", []),
            })

        cluster_id = build_cluster_id(eid, db3_ids)

        queue.append({
            "cluster_id": cluster_id,
            "block_key": f"cross_db:{match_type}",
            "llm_task": "cross_db_identity_resolution",
            "match_type": match_type,
            "match_source": match_source,
            "canonical_hint": {
                "source": "db2",
                "eid": eid,
                "primary_name": primary_name,
                "handles": handles[:10],
                "platforms": platforms,
            },
            "members": db3_members,
            "member_count": len(db3_members),
            "output_contract": {
                "decision": "match|no_match",
                "matched_db3_entity_id": "string",
                "matched_db3_name": "string",
                "confidence": "float 0-1",
                "reason_zh": "string",
            },
        })

    queue_path = OUT_DIR / "cross_db_identity_queue.jsonl"
    with open(queue_path, "w", encoding="utf-8") as f:
        for item in queue:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    print(f"\n  Queue: {len(queue):,} items")
    print(f"  Skipped (no db3_ids): {skipped}")

    # Token estimate
    avg_chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in queue[:20]) / min(
        len(queue), 20
    )
    total_chars = avg_chars * len(queue)
    est_tokens = total_chars / 2.5  # rough char→token for Chinese
    est_cost = est_tokens * 0.14 / 1_000_000  # $0.14/M input
    print(f"\n  💰 Cost estimate:")
    print(f"     Avg prompt: {avg_chars:,.0f} chars")
    print(f"     Total input: ~{est_tokens:,.0f} tokens")
    print(f"     Est cost (Flash): ~${est_cost:.2f}")

    # Decision breakdown
    from collections import Counter

    match_counts = Counter(c.get("match_type") for c in candidates)
    db3_counts = Counter(len(c.get("matched_db3_ids", [])) for c in candidates)
    print(f"\n  📊 Match types: {dict(match_counts)}")
    print(f"  📊 DB3 matches per candidate: {dict(db3_counts)}")


if __name__ == "__main__":
    main()
