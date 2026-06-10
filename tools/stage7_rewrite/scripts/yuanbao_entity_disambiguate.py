#!/usr/bin/env python3
"""Yuanbao on-demand entity disambiguation for Atlas.

For entities that couldn't be matched by name or LLM,
use Yuanbao to search the web and determine entity type/identity.

Usage:
    py yuanbao_entity_disambiguate.py "酒仙桥Gangsta"
    py yuanbao_entity_disambiguate.py --batch unmatched_eids.txt
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Add scripts to path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from atlas_unified_resolver import AtlasResolver


def ask_yuanbao(question: str, timeout: int = 120) -> Optional[str]:
    """Ask Yuanbao a single question, return response text."""
    # Escape quotes for shell
    safe_q = question.replace('"', '\\"').replace("'", "\\'")
    try:
        result = subprocess.run(
            f'opencli yuanbao ask --timeout {timeout} --search true --think true "{safe_q}"',
            capture_output=True, text=True, timeout=timeout + 30,
            shell=True,
        )
        if result.returncode == 0:
            # Extract assistant response from transcript
            return result.stdout
        return None
    except subprocess.TimeoutExpired:
        return None


def disambiguate_entity(name: str, resolver: AtlasResolver | None = None) -> dict:
    """Use Yuanbao to identify an entity.

    Returns: {name, type, chinese_name, related_club, db3_candidates, confidence}
    """
    if resolver is None:
        resolver = AtlasResolver()

    # First try DB3 search
    db3_results = resolver.search_by_name(name, limit=10)

    prompt = f"""请判断以下实体在中国地下电子音乐场景中的身份：

实体名称：{name}

请回答：
1. 这是什么类型的实体？(DJ个人/俱乐部venue/音乐厂牌label/主办方organizer/其他)
2. 如果有中文名或常用别名，是什么？
3. 是否与以下俱乐部有关联：Dada, OIL, 招待所ZhaoDai, loopy, wigwam, ALL Club, Elevator, Heim, SYSTEM, 莫须有工厂？
4. 是否在中国地下电子音乐场景活跃？

只输出JSON，不要其他解释：
{{"type":"dj|club|label|organizer|other","chinese_name":"","aliases":[],"related_club":"","active_in_china":true,"confidence":"high|medium|low"}}"""

    yuanbao_raw = ask_yuanbao(prompt)

    # Try to parse JSON from yuanbao output
    parsed = {}
    if yuanbao_raw:
        try:
            # Find JSON in response
            start = yuanbao_raw.rfind("{")
            end = yuanbao_raw.rfind("}")
            if start >= 0 and end > start:
                parsed = json.loads(yuanbao_raw[start : end + 1])
        except (json.JSONDecodeError, ValueError):
            pass

    return {
        "name": name,
        "yuanbao_type": parsed.get("type", "unknown"),
        "chinese_name": parsed.get("chinese_name", ""),
        "aliases": parsed.get("aliases", []),
        "related_club": parsed.get("related_club", ""),
        "active_in_china": parsed.get("active_in_china", False),
        "confidence": parsed.get("confidence", "low"),
        "db3_candidates": [
            {"id": r["subject_id"], "name": r["display_name"], "type": r["subject_type"]}
            for r in (db3_results or [])[:5]
        ],
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: py yuanbao_entity_disambiguate.py <entity_name>")
        print("       py yuanbao_entity_disambiguate.py --batch <file>")
        sys.exit(1)

    if sys.argv[1] == "--batch" and len(sys.argv) > 2:
        batch_file = Path(sys.argv[2])
        names = [l.strip() for l in batch_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        print(f"Batch mode: {len(names)} entities")
        results = []
        resolver = AtlasResolver()
        try:
            for i, name in enumerate(names):
                print(f"  [{i+1}/{len(names)}] {name}")
                result = disambiguate_entity(name, resolver)
                results.append(result)
                if i < len(names) - 1:
                    time.sleep(3)  # Rate limit
        finally:
            resolver.close()

        out_path = batch_file.with_suffix(".yuanbao_results.json")
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n✅ Results saved: {out_path}")
    else:
        name = sys.argv[1]
        resolver = AtlasResolver()
        try:
            result = disambiguate_entity(name, resolver)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            resolver.close()


if __name__ == "__main__":
    main()
