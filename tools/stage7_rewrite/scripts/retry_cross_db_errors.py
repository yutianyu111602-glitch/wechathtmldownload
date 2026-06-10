#!/usr/bin/env python3
"""Retry failed cross-DB identity resolution candidates.

Reads error cases from decisions file, re-queries DeepSeek Flash,
appends results to the existing decisions file.
"""
import json
import sys
import time
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_cross_db_identity_resolution import (
    resolve_one,
    load_env,
    ENV_FILE,
)

DECISIONS_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports"
    r"\cross_db_identity_resolution_20260608\cross_db_identity_decisions.jsonl"
)
QUEUE_PATH = Path(
    r"C:\code\githubstar\wechathtmldownload\tools\stage7_rewrite\reports"
    r"\cross_db_identity_resolution_20260608\cross_db_identity_queue.jsonl"
)


def main():
    # Load queue to get full candidate data
    queue = {}
    with open(QUEUE_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                c = json.loads(line)
                queue[c["cluster_id"]] = c

    # Find errors in decisions
    errors = []
    all_decisions = []
    with open(DECISIONS_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                all_decisions.append(d)
                if d.get("decision") == "error":
                    errors.append(d)

    print(f"Errors found: {len(errors)}")
    if not errors:
        print("No errors to retry.")
        return

    # Load API key
    env = load_env(ENV_FILE)
    api_key = env.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("ERROR: No API key")
        sys.exit(1)

    # Prepare error eids to replace
    error_ids = {e["cluster_id"] for e in errors}

    # Retry each error
    retried = 0
    for err in errors:
        cid = err["cluster_id"]
        candidate = queue.get(cid)
        if not candidate:
            print(f"  {cid}: candidate not in queue, skipping")
            continue

        print(f"  Retrying: {err.get('primary_name', '?')} (eid={err.get('eid', '?')[:12]}...)")
        decision = resolve_one(candidate, api_key, "deepseek-v4-pro", "https://api.deepseek.com")
        print(f"    → {decision['decision']} conf={decision.get('confidence',0)} {decision.get('reason_zh','')[:60]}")

        # Replace in decisions list
        for i, d in enumerate(all_decisions):
            if d["cluster_id"] == cid and d.get("decision") == "error":
                all_decisions[i] = decision
                break

        retried += 1
        time.sleep(0.5)

    # Rewrite decisions file
    with open(DECISIONS_PATH, "w", encoding="utf-8") as f:
        for d in all_decisions:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"\n✅ Retried {retried}/{len(errors)} errors. Decisions file updated.")

    # Recalculate stats
    from collections import Counter
    counts = Counter(d["decision"] for d in all_decisions)
    new_matches = counts.get("match", 0)
    print(f"   Updated: match={new_matches} no_match={counts.get('no_match',0)} error={counts.get('error',0)}")


if __name__ == "__main__":
    main()
