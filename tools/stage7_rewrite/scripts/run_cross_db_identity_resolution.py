#!/usr/bin/env python3
"""Run DeepSeek Flash over cross-DB identity resolution candidates.

Follows the proven $15 merge pipeline pattern:
- deepseek-v4-pro
- concurrency 6 (not 10)
- checkpoint every 10
- --resume support
- Report-only: no DB writes

Produces: cross_db_identity_decisions.jsonl
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / "services" / "weekly_activity_cloudrun" / ".env"
DEFAULT_QUEUE = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "cross_db_identity_resolution_20260608"
    / "cross_db_identity_queue.jsonl"
)
DEFAULT_OUT_DIR = DEFAULT_QUEUE.parent
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com"

SYSTEM_PROMPT = """你是 Atlas 图谱数据库的跨库实体消歧裁决器。
任务：判断 DB2（外部社交证据库）中的实体是否与 DB3（服务图谱库）中某个实体指向同一真实世界实体。

严格规则：
1. DB2 entity 来自社交媒体/外部平台爬取，名称可能是 handle/@用户名/拼音变体
2. DB3 entity 来自微信文章提取，名称是正式中文/英文名称
3. 如果名称明显指向同一实体（如 "Dada Bar Beijing" ↔ "DADA BEIJING"），匹配
4. 如果 DB2 的 name/handle 与 DB3 某实体名称近似但不完全相同，判断是否同一实体
5. DJ/个人与俱乐部/场地不能匹配到一起
6. 不同城市同名连锁保持分开（如 Dada Beijing ≠ Dada Kunming）
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


def load_env(path: Path) -> dict[str, str]:
    """Load .env file into dict."""
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                env[key.strip()] = val.strip().strip('"').strip("'")
    return env


def call_deepseek(
    prompt: str, api_key: str, model: str, base_url: str, timeout_s: int = 60
) -> tuple[dict, dict, float]:
    """Call DeepSeek API, return (parsed_json, usage, latency_ms)."""
    started = time.perf_counter()
    endpoint = base_url.rstrip("/")
    if not endpoint.endswith("/v1"):
        endpoint += "/v1"
    endpoint += "/chat/completions"

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
        "stream": False,
        "thinking": {"type": "disabled"},
    }

    req = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"API {e.code}: {body}")

    data = json.loads(raw)
    msg = (data.get("choices") or [{}])[0].get("message") or {}
    content = (msg.get("content") or "").strip()

    if not content:
        raise RuntimeError("Empty response content")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(content[start : end + 1])
        else:
            raise

    latency = (time.perf_counter() - started) * 1000
    return parsed, data.get("usage") or {}, latency


def build_user_prompt(candidate: dict) -> str:
    """Build a focused prompt for cross-DB identity resolution."""
    db2_info = candidate.get("canonical_hint", {})
    db3_members = candidate.get("members", [])

    return json.dumps(
        {
            "task": "cross_db_identity_resolution",
            "db2_entity": {
                "eid": db2_info.get("eid"),
                "primary_name": db2_info.get("primary_name"),
                "handles": db2_info.get("handles", [])[:5],
                "platforms": db2_info.get("platforms", []),
            },
            "db3_candidates": [
                {
                    "entity_id": m["entity_id"],
                    "names": m.get("names", [])[:3],
                    "types": m.get("types", []),
                    "cities": m.get("cities", []),
                }
                for m in db3_members[:15]  # Cap at 15 to avoid huge prompts
            ],
            "match_type": candidate.get("match_type"),
            "match_source": candidate.get("match_source"),
        },
        ensure_ascii=False,
    )


def resolve_one(
    candidate: dict, api_key: str, model: str, base_url: str
) -> dict:
    """Resolve one candidate, returns decision dict."""
    cluster_id = candidate["cluster_id"]
    prompt = build_user_prompt(candidate)

    base = {
        "cluster_id": cluster_id,
        "eid": candidate.get("canonical_hint", {}).get("eid"),
        "primary_name": candidate.get("canonical_hint", {}).get("primary_name"),
        "db3_candidate_count": candidate.get("member_count", 0),
        "prompt_chars": len(prompt),
        "model": model,
        "created_at": datetime.now().isoformat(),
    }

    try:
        parsed, usage, latency = call_deepseek(prompt, api_key, model, base_url)
        decision = (parsed.get("decision") or "").casefold()
        if decision not in ("match", "no_match"):
            decision = "no_match"

        return {
            **base,
            "decision": decision,
            "matched_db3_entity_id": parsed.get("matched_db3_entity_id") or "",
            "matched_db3_name": parsed.get("matched_db3_name") or "",
            "confidence": float(parsed.get("confidence", 0)),
            "reason_zh": (parsed.get("reason_zh") or "")[:150],
            "usage": usage,
            "latency_ms": round(latency),
            "error": "",
        }
    except Exception as e:
        return {**base, "decision": "error", "error": str(e)[:200], "usage": {}, "latency_ms": 0}


def main():
    parser = argparse.ArgumentParser(description="Cross-DB identity resolution via DeepSeek Flash")
    parser.add_argument("--queue", default=str(DEFAULT_QUEUE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--max-candidates", type=int, default=0)
    parser.add_argument("--resume", action="store_true", default=False)
    parser.add_argument("--sleep-s", type=float, default=0.3)
    parser.add_argument("--execute", action="store_true", default=False)
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load API key
    env = load_env(ENV_FILE)
    api_key = env.get("DEEPSEEK_API_KEY", "")
    if not api_key and args.execute:
        print("ERROR: DEEPSEEK_API_KEY not found in .env")
        sys.exit(1)

    # Load queue
    queue_path = Path(args.queue)
    candidates = []
    with open(queue_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                candidates.append(json.loads(line))

    total = len(candidates)
    print(f"Queue: {total:,} candidates")

    # Resume
    decisions_path = out_dir / "cross_db_identity_decisions.jsonl"
    errors_path = out_dir / "cross_db_identity_errors.jsonl"
    done_ids: set[str] = set()

    if args.resume and decisions_path.exists():
        with open(decisions_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    d = json.loads(line)
                    if d.get("decision") != "error":
                        done_ids.add(d.get("cluster_id", ""))
        candidates = [c for c in candidates if c["cluster_id"] not in done_ids]
        print(f"Resumed: {len(done_ids):,} done, {len(candidates):,} remaining")

    if args.max_candidates > 0:
        candidates = candidates[: args.max_candidates]

    # Dry run
    if args.dry_run:
        print(f"\nDRY RUN — would process {len(candidates):,} candidates")
        print(f"Model: {args.model}")
        print(f"Concurrency: {args.concurrency}")
        est_tokens = sum(c.get("prompt_chars", 500) for c in candidates[:5]) / min(len(candidates), 5) * len(candidates) / 2.5
        est_cost = est_tokens * 0.14 / 1_000_000
        print(f"Est tokens: ~{est_tokens:,.0f}, Est cost: ~${est_cost:.2f}")
        return

    if not args.execute:
        print("\nUse --execute to make API calls (or --dry-run to estimate)")
        return

    print(f"\nExecuting with concurrency={args.concurrency}, model={args.model}")
    print(f"API key: {'SET' if api_key else 'MISSING'}")

    counts = Counter()
    completed = 0

    def save_decision(decision: dict):
        nonlocal completed
        counts[decision["decision"]] += 1
        completed += 1
        with open(decisions_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(decision, ensure_ascii=False) + "\n")
        if decision["decision"] == "error":
            with open(errors_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(decision, ensure_ascii=False) + "\n")

    start_time = time.perf_counter()
    checkpoint_interval = args.checkpoint_every

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {}
        idx = 0
        pending = list(candidates)

        # Submit initial batch
        for _ in range(min(args.concurrency, len(pending))):
            c = pending.pop(0)
            futures[pool.submit(resolve_one, c, api_key, args.model, args.base_url)] = c

        while futures:
            done_futures = []
            for f in as_completed(futures):
                c = futures.pop(f)
                try:
                    decision = f.result()
                except Exception as e:
                    decision = {
                        "cluster_id": c.get("cluster_id"),
                        "decision": "error",
                        "error": str(e)[:200],
                    }
                save_decision(decision)
                done_futures.append(f)

                # Checkpoint
                if completed % checkpoint_interval == 0:
                    elapsed = time.perf_counter() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    print(
                        f"  [{completed}/{total}] "
                        f"match={counts.get('match',0)} "
                        f"no_match={counts.get('no_match',0)} "
                        f"error={counts.get('error',0)} "
                        f"({rate:.1f}/s)"
                    )

                # Submit next
                if pending:
                    c = pending.pop(0)
                    futures[pool.submit(resolve_one, c, api_key, args.model, args.base_url)] = c

                if args.sleep_s:
                    time.sleep(args.sleep_s)

                break  # Process one at a time to maintain order-ish

    elapsed = time.perf_counter() - start_time
    print(f"\n{'='*60}")
    print(f"✅ Cross-DB Identity Resolution Complete")
    print(f"   Completed: {completed:,}")
    print(f"   Duration:  {elapsed:.0f}s ({completed/elapsed:.1f}/s)")
    print(f"   match:     {counts.get('match',0):,}")
    print(f"   no_match:  {counts.get('no_match',0):,}")
    print(f"   error:     {counts.get('error',0):,}")
    print(f"   Decisions: {decisions_path}")

    # Summary
    summary = {
        "schema_version": "cross_db_identity_resolution.v1",
        "generated_at": datetime.now().isoformat(),
        "model": args.model,
        "total": total,
        "completed": completed,
        "counts": dict(counts),
        "elapsed_s": round(elapsed),
        "rate_per_s": round(completed / elapsed, 1),
        "concurrency": args.concurrency,
    }
    summary_path = out_dir / "cross_db_identity_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"   Summary:   {summary_path}")


if __name__ == "__main__":
    main()
