#!/usr/bin/env python3
"""Task 6: Batch yuanbao entity disambiguation for unmatched Atlas entities.

Strategy:
- NEW session per entity (avoid context pollution — pitfall #1)
- ~45s per entity (15s new session + 30s ask + 3s rate limit)
- Prioritize 641 entities with primary_name → ~8h
- Save incrementally every 10 entities
- Resume-safe: skip already-processed names
"""

import json
import subprocess
import sys
import time
import re
from datetime import datetime
from pathlib import Path

# Force unbuffered output for background process visibility
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO = SCRIPTS_DIR.parent.parent.parent
UNMATCHED_FILE = REPO / "tools/stage7_rewrite/reports/cross_db_identity_resolution_20260608/unmatched_eids.json"
OUTPUT_DIR = Path("D:/downstream_results/stage7_rewrite/longrun/yuanbao_entity_search_20260608")

TIMEOUT_NEW_SESSION = 30
TIMEOUT_ASK = 30
RATE_LIMIT_SEC = 2


def run_opencli(args: list[str], timeout: int = 30) -> str:
    """Run opencli command and return stdout."""
    cmd = "opencli " + " ".join(args)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, shell=True,
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except Exception as e:
        return f"ERROR: {e}"


def new_session() -> bool:
    """Create a fresh yuanbao session."""
    out = run_opencli(["yuanbao", "new"], timeout=TIMEOUT_NEW_SESSION)
    return "Success" in out


def ask_yuanbao(question: str) -> str:
    """Ask yuanbao a single question in current session."""
    safe_q = question.replace('"', '\\"')
    out = run_opencli([
        "yuanbao", "ask",
        "--timeout", str(TIMEOUT_ASK),
        "--think", "false",
        "--search", "true",
        f'"{safe_q}"',
    ], timeout=TIMEOUT_ASK + 15)

    # Extract assistant response
    match = re.search(r"Role: Assistant\nText: (.+)", out, re.DOTALL)
    if match:
        return match.group(1).strip()
    return out[:500]


def classify_entity(name: str, platforms: list[str] = None) -> dict:
    """Ask yuanbao to classify a single entity with fresh session."""
    if not new_session():
        return {"name": name, "error": "new_session_failed", "classified_type": "error"}
    time.sleep(1)

    prompt = (
        f"在中国地下电子音乐/club场景中，「{name}」是什么？\n"
        f"用一句话简短回答（例如：'某城市的Techno DJ'、'某城市的俱乐部'、'电子音乐厂牌'、'主办方'、'与场景无关'）。"
    )
    raw = ask_yuanbao(prompt)

    # Simple classification from response
    response_lower = raw.lower()
    entity_type = "unknown"

    # Order matters — check specific patterns first
    if any(w in response_lower for w in ["与场景无关", "无关", "不是", "没有关系", "不确定", "无法确定"]):
        entity_type = "irrelevant"
    elif any(w in response_lower for w in ["俱乐部", "club", "酒吧", "场地", "venue", "livehouse", "夜店"]):
        entity_type = "club"
    elif any(w in response_lower for w in ["厂牌", "label", "唱片公司"]):
        entity_type = "label"
    elif any(w in response_lower for w in ["主办方", "主办", "organizer", "promoter", "派对组织", "活动组织"]):
        entity_type = "organizer"
    elif any(w in response_lower for w in ["dj", "制作人", "producer", "音乐人", "电子音乐", "techno", "house"]):
        entity_type = "dj"

    return {
        "name": name,
        "platforms": platforms or [],
        "yuanbao_response": raw[:300],
        "classified_type": entity_type,
        "ts": datetime.now().isoformat(),
    }


def extract_names(entity: dict) -> list[str]:
    """Extract searchable names, best first."""
    names = []
    if entity.get("primary_name") and len(entity["primary_name"]) > 1:
        names.append(entity["primary_name"])
    for h in entity.get("handles", []):
        h = str(h).strip()
        if h.isdigit() or len(h) < 2 or h.startswith("?") or h.startswith("@"):
            continue
        if h not in names:
            names.append(h)
    return names


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results_file = OUTPUT_DIR / "results.jsonl"

    # Load unmatched
    with open(UNMATCHED_FILE, "r", encoding="utf-8") as f:
        unmatched = json.load(f)

    # Build prioritized work queue
    work = []
    for ent in unmatched:
        names = extract_names(ent)
        if names:
            work.append({
                "eid": ent["eid"],
                "name": names[0],
                "all_names": names[:5],
                "platforms": ent.get("platforms", []),
            })

    # Priority: entities with primary_name first
    def priority(w):
        n = w["name"]
        if len(n) > 2 and not n[0].isdigit():
            return 0  # meaningful name
        if len(n) > 2:
            return 1  # has name but starts with digit
        return 2  # very short

    work.sort(key=priority)
    total = len(work)
    with_names = sum(1 for w in work if priority(w) == 0)

    # Load existing progress (resume-safe)
    done_names = set()
    done_eids = set()
    if results_file.exists():
        with open(results_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                    done_names.add(r.get("name", ""))
                    done_eids.add(r.get("eid", ""))
                except json.JSONDecodeError:
                    pass

    pending = [w for w in work if w["name"] not in done_names and w["eid"] not in done_eids]
    done = total - len(pending)

    print(f"=== Yuanbao Entity Batch Classification ===")
    print(f"Total entities: {total} ({with_names} with meaningful names)")
    print(f"Already done: {done}")
    print(f"Remaining: {len(pending)}")
    print(f"Est. time: ~{len(pending) * 45 / 3600:.1f}h")
    print(f"Output: {results_file}")
    print()

    buffer = []
    processed = 0

    try:
        for i, ent in enumerate(pending):
            name = ent["name"]
            print(f"[{done + i + 1}/{total}] {name[:50]:50s}", end=" ", flush=True)

            result = classify_entity(name, ent["platforms"])
            result["eid"] = ent["eid"]
            result["all_names"] = ent["all_names"]
            buffer.append(result)
            processed += 1

            rtype = result.get("classified_type", "?")
            resp_preview = result.get("yuanbao_response", "")[:60].replace("\n", " ")
            print(f"→ {rtype:12s} | {resp_preview}")

            # Save incrementally
            if len(buffer) >= 10:
                with open(results_file, "a", encoding="utf-8") as f:
                    for r in buffer:
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                buffer.clear()
                print(f"  💾 Saved ({done + processed}/{total})")

            # Rate limit
            if i < len(pending) - 1:
                time.sleep(RATE_LIMIT_SEC)

    except KeyboardInterrupt:
        print("\n⚠️ Interrupted. Saving...")
    finally:
        if buffer:
            with open(results_file, "a", encoding="utf-8") as f:
                for r in buffer:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
            buffer.clear()

        # Summary
        print(f"\n{'='*50}")
        print(f"Progress: {done + processed}/{total}")
        print(f"Results: {results_file}")
        print(f"Resume: python3 {__file__}")


if __name__ == "__main__":
    main()
