#!/usr/bin/env python3
"""
Atlas LLM Extraction - Fill remaining missing city/time_iso fields using LLM APIs.

Tests all available Chinese LLM APIs, picks the fastest, then processes
remaining unfilled records in batches of 20.

APIs tested:
  - ZhipuAI (GLM): https://open.bigmodel.cn/api/paas/v4/chat/completions
  - DashScope (Qwen): https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
  - Kimi (Moonshot): https://api.moonshot.cn/v1/chat/completions
  - DeepSeek: https://api.deepseek.com/v1/chat/completions
"""

import sqlite3
import json
import os
import re
import sys
import time
import threading
import requests
from datetime import datetime, timedelta
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────
DB_PATH = "/tmp/atlas_work.sqlite"
DB_PATH_ORIGINAL = "/mnt/c/code/githubstar/wechathtmldownload/reports/atlas_incremental_wechat_refresh_20260522_1438/atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/atlas.sqlite"
OUTPUT_DIR = "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_llm_extraction_20260528"
SUMMARY_PATH = os.path.join(OUTPUT_DIR, "llm_extraction_summary.json")
BATCH_SIZE = 20
RATE_LIMIT_SECONDS = 6.0  # max 10 calls/min = 6s between calls
MAX_BATCHES = 30  # safety limit per run (30 x 6s = 180s per phase)

# ── API Configs ────────────────────────────────────────────────────────────
API_CONFIGS = {
    "zhipu_glm4": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-plus",
        "key_env": "ZHIPUAI_API_KEY",
    },
    "qwen_plus": {
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-plus",
        "key_env": "DASHSCOPE_API_KEY",
    },
    "kimi": {
        "url": "https://api.moonshot.cn/v1/chat/completions",
        "model": "moonshot-v1-8k",
        "key_env": "KIMI_CODE_API_KEY",
    },
}


def get_api_key(api_name, config):
    """Get API key from environment."""
    env_name = config["key_env"]
    key = os.environ.get(env_name, "")
    if not key and api_name == "deepseek":
        # Try alternative env var names
        for alt in ["DEEPSEEK_API_KEY", "OPENAI_API_KEY"]:
            key = os.environ.get(alt, "")
            if key:
                break
    return key


def test_api_with_timeout(api_name, config, timeout_seconds=15):
    """Test an API with a simple call, using thread-based timeout."""
    result = [False, 0, ""]

    def _do_test():
        try:
            api_key = get_api_key(api_name, config)
            if not api_key:
                result[0], result[1], result[2] = False, 0, "no API key"
                return

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            payload = {
                "model": config["model"],
                "messages": [
                    {"role": "user", "content": "回复: 你好"}
                ],
                "max_tokens": 20,
                "temperature": 0.1,
            }

            t0 = time.time()
            resp = requests.post(config["url"], headers=headers, json=payload, timeout=10)
            latency = (time.time() - t0) * 1000

            if resp.status_code == 200:
                data = resp.json()
                if "choices" in data and len(data["choices"]) > 0:
                    result[0], result[1], result[2] = True, latency, data["choices"][0]["message"]["content"][:50]
                else:
                    result[0], result[1], result[2] = False, latency, f"unexpected: {str(data)[:100]}"
            else:
                result[0], result[1], result[2] = False, latency, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            result[0], result[1], result[2] = False, 0, str(e)[:200]

    t = threading.Thread(target=_do_test, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if t.is_alive():
        return False, timeout_seconds * 1000, f"timeout after {timeout_seconds}s"
    return tuple(result)


def extract_cities_batch(api_name, config, batch_rows):
    """
    Send a batch of place names to LLM for city extraction.
    batch_rows: list of (row_pk, place) tuples
    Returns: list of (city, row_pk) tuples (city FIRST for SQL UPDATE SET city = ? WHERE row_pk = ?)
    """
    api_key = get_api_key(api_name, config)
    if not api_key:
        raise ValueError(f"No API key for {api_name}")

    # Build prompt
    items = [f"{pk}: {place}" for pk, place in batch_rows]
    items_text = "\n".join(items)

    prompt = f"""Extract the Chinese city name from each venue address below.
Return ONLY a JSON array of objects with "row_pk" and "city" fields.
If no city can be identified, use empty string for city.
Chinese city names only (e.g., 北京, 上海, 深圳, 成都, 杭州, 昆明, etc.)

Venue addresses:
{items_text}

Return format example:
[{{"row_pk": 1, "city": "上海"}}, {{"row_pk": 2, "city": ""}}]
"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": "You are a Chinese address parser. Return only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 2048,
        "temperature": 0.1,
    }

    resp = requests.post(config["url"], headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"API error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]

    # Parse JSON response
    # The LLM might wrap in markdown code blocks
    content = content.strip()
    if content.startswith("```"):
        # Remove markdown code blocks
        content = re.sub(r'```(?:json)?\s*', '', content)
        content = re.sub(r'```\s*$', '', content)

    try:
        results = json.loads(content)
    except json.JSONDecodeError:
        # Try to extract JSON array from response
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            try:
                results = json.loads(match.group(0))
            except json.JSONDecodeError:
                print(f"  WARNING: Could not parse LLM response: {content[:200]}")
                return []
        else:
            print(f"  WARNING: No JSON array found in: {content[:200]}")
            return []

    # Validate and return (city FIRST for UPDATE SET city = ? WHERE row_pk = ?)
    output = []
    for item in results:
        if isinstance(item, dict) and "row_pk" in item:
            city = item.get("city", "").strip()
            if city:
                output.append((city, int(item["row_pk"])))
    return output


def parse_time_batch(api_name, config, batch_rows):
    """
    Send a batch of time_text strings to LLM for date parsing.
    batch_rows: list of (row_pk, time_text, article_date) tuples
    article_date can be None
    Returns: list of (time_iso, row_pk) tuples (time_iso FIRST for UPDATE SET time_iso = ? WHERE row_pk = ?)
    """
    api_key = get_api_key(api_name, config)
    if not api_key:
        raise ValueError(f"No API key for {api_name}")

    # Build prompt with context
    items = []
    for pk, time_text, article_date in batch_rows:
        ctx = f" (article published: {article_date})" if article_date else ""
        items.append(f"{pk}: {time_text}{ctx}")

    items_text = "\n".join(items)

    prompt = f"""Parse each event time expression into an ISO date (YYYY-MM-DD format).
Context may include the article's publish date when available.
For relative dates like "今晚", "明天", "本周五", use the article publish date as reference.
For dates like "7/19", assume the year from the article context or most recent year.
For recurring patterns like "每周末", "每周三" or events without enough context, return empty string.

Return ONLY a JSON array of objects with "row_pk" and "time_iso" fields.

Time expressions:
{items_text}

Return format example:
[{{"row_pk": 1, "time_iso": "2024-07-19"}}, {{"row_pk": 2, "time_iso": ""}}]
"""

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": "You are a date parser. Return only valid JSON."},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 2048,
        "temperature": 0.1,
    }

    resp = requests.post(config["url"], headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"API error {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    content = data["choices"][0]["message"]["content"]

    # Parse JSON response
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r'```(?:json)?\s*', '', content)
        content = re.sub(r'```\s*$', '', content)

    try:
        results = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            try:
                results = json.loads(match.group(0))
            except json.JSONDecodeError:
                print(f"  WARNING: Could not parse LLM response: {content[:200]}")
                return []
        else:
            print(f"  WARNING: No JSON array found in: {content[:200]}")
            return []

    # Validate date format and return
    output = []
    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    for item in results:
        if isinstance(item, dict) and "row_pk" in item:
            time_iso = item.get("time_iso", "").strip()
            if time_iso and date_pattern.match(time_iso):
                output.append((time_iso, int(item["row_pk"])))
    return output


def process_city_batch(write_db, api_name, config, batch_rows):
    """Process one batch of city extraction."""
    try:
        results = extract_cities_batch(api_name, config, batch_rows)
        if results:
            write_db.execute("BEGIN IMMEDIATE")
            write_db.executemany(
                "UPDATE events SET city = ? WHERE row_pk = ?",
                results
            )
            write_db.execute("COMMIT")
            write_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return len(results), 0
    except Exception as e:
        print(f"  ERROR in city batch: {e}")
        return 0, len(batch_rows)


def process_time_batch(write_db, api_name, config, batch_rows):
    """Process one batch of time parsing."""
    try:
        results = parse_time_batch(api_name, config, batch_rows)
        if results:
            write_db.execute("BEGIN IMMEDIATE")
            write_db.executemany(
                "UPDATE events SET time_iso = ? WHERE row_pk = ?",
                results
            )
            write_db.execute("COMMIT")
            write_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return len(results), 0
    except Exception as e:
        print(f"  ERROR in time batch: {e}")
        return 0, len(batch_rows)


def main():
    start_time = datetime.now()
    print(f"=== Atlas LLM Extraction ===")
    print(f"Started: {start_time.isoformat()}")
    print(f"DB: {DB_PATH}")
    print(f"Batch size: {BATCH_SIZE}")
    print(f"Rate limit: {60/RATE_LIMIT_SECONDS:.0f} calls/min")
    print()

    # ── Step 1: Test all APIs ──────────────────────────────────────────────
    print("=== Testing APIs ===")
    available_apis = []
    for name, config in API_CONFIGS.items():
        print(f"  Testing {name} ({config['model']})...", end=" ", flush=True)
        ok, latency, msg = test_api_with_timeout(name, config, timeout_seconds=15)
        if ok:
            available_apis.append((name, latency))
            print(f"OK ({latency:.0f}ms) - {msg[:50]}")
        else:
            print(f"FAIL: {msg[:80]}")

    if not available_apis:
        print("\nFATAL: No APIs available!")
        sys.exit(1)

    # Sort by latency (fastest first)
    available_apis.sort(key=lambda x: x[1])
    primary_api, primary_latency = available_apis[0]
    backup_apis = available_apis[1:]
    print(f"\n  Primary API: {primary_api} ({primary_latency:.0f}ms)")
    if backup_apis:
        print(f"  Backup APIs: {', '.join(f'{n}({l:.0f}ms)' for n, l in backup_apis)}")

    # ── Step 2: Query remaining work ───────────────────────────────────────
    print("\n=== Querying remaining work ===")
    read_db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    read_db.row_factory = sqlite3.Row

    # City extraction: where place has no city
    city_rows = read_db.execute("""
        SELECT row_pk, place FROM events
        WHERE (city IS NULL OR city = '')
          AND place IS NOT NULL AND place != ''
        ORDER BY row_pk
        LIMIT ?
    """, (BATCH_SIZE * MAX_BATCHES,)).fetchall()
    read_db.close()

    print(f"  City extraction candidates: {len(city_rows)}")

    # Time parsing: get time_text + article context
    read_db2 = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    read_db2.row_factory = sqlite3.Row

    time_rows = read_db2.execute("""
        SELECT e.row_pk, e.time_text, a.publish_time
        FROM events e
        LEFT JOIN articles a ON e.source_article_uid = a.article_uid
        WHERE (e.time_iso IS NULL OR e.time_iso = '')
          AND e.time_text IS NOT NULL AND e.time_text != ''
        ORDER BY e.row_pk
        LIMIT ?
    """, (BATCH_SIZE * MAX_BATCHES,)).fetchall()
    read_db2.close()

    print(f"  Time parsing candidates: {len(time_rows)}")

    # ── Step 3: Process city extraction ─────────────────────────────────────
    print("\n=== Phase 1: City Extraction ===")
    write_db = sqlite3.connect(DB_PATH)
    write_db.execute("PRAGMA journal_mode=WAL")
    write_db.execute("PRAGMA synchronous=NORMAL")
    write_db.execute("PRAGMA cache_size=-8000")

    city_stats = {
        "batches_processed": 0,
        "total_extracted": 0,
        "total_failed": 0,
        "batch_details": [],
    }

    current_api = primary_api
    api_idx = 0

    for i in range(0, len(city_rows), BATCH_SIZE):
        batch = city_rows[i:i + BATCH_SIZE]
        batch_rows = [(r["row_pk"], r["place"]) for r in batch]

        # Try current API
        extracted, failed = process_city_batch(
            write_db, current_api, API_CONFIGS[current_api], batch_rows
        )

        # If failed, try backup APIs
        if failed > 0 and backup_apis:
            for backup_name, _ in backup_apis:
                print(f"  Retrying with backup API: {backup_name}")
                e2, f2 = process_city_batch(
                    write_db, backup_name, API_CONFIGS[backup_name], batch_rows
                )
                extracted += e2
                if f2 == 0:
                    break

        city_stats["batches_processed"] += 1
        city_stats["total_extracted"] += extracted
        city_stats["total_failed"] += (len(batch_rows) - extracted)
        city_stats["batch_details"].append({
            "batch_num": city_stats["batches_processed"],
            "rows": len(batch_rows),
            "extracted": extracted,
        })

        print(f"  City batch {city_stats['batches_processed']:>3}: "
              f"extracted={extracted:>3}/{len(batch_rows)}  "
              f"cumulative={city_stats['total_extracted']:>5}")

        # Save intermediate results
        if city_stats["batches_processed"] % 10 == 0:
            with open(os.path.join(OUTPUT_DIR, "city_intermediate.json"), "w") as f:
                json.dump(city_stats, f, ensure_ascii=False, indent=2)

        # Rate limit
        time.sleep(RATE_LIMIT_SECONDS)

        if city_stats["batches_processed"] >= MAX_BATCHES:
            break

    print(f"\n  City phase complete: {city_stats['total_extracted']} extracted, "
          f"{city_stats['total_failed']} remaining")

    # ── Step 4: Process time parsing ────────────────────────────────────────
    print("\n=== Phase 2: Time Text Parsing ===")
    time_stats = {
        "batches_processed": 0,
        "total_extracted": 0,
        "total_failed": 0,
        "batch_details": [],
    }

    for i in range(0, len(time_rows), BATCH_SIZE):
        batch = time_rows[i:i + BATCH_SIZE]
        batch_rows = [(r["row_pk"], r["time_text"], r["publish_time"]) for r in batch]

        extracted, failed = process_time_batch(
            write_db, current_api, API_CONFIGS[current_api], batch_rows
        )

        if failed > 0 and backup_apis:
            for backup_name, _ in backup_apis:
                print(f"  Retrying with backup API: {backup_name}")
                e2, f2 = process_time_batch(
                    write_db, backup_name, API_CONFIGS[backup_name], batch_rows
                )
                extracted += e2
                if f2 == 0:
                    break

        time_stats["batches_processed"] += 1
        time_stats["total_extracted"] += extracted
        time_stats["total_failed"] += (len(batch_rows) - extracted)
        time_stats["batch_details"].append({
            "batch_num": time_stats["batches_processed"],
            "rows": len(batch_rows),
            "extracted": extracted,
        })

        print(f"  Time batch {time_stats['batches_processed']:>3}: "
              f"extracted={extracted:>3}/{len(batch_rows)}  "
              f"cumulative={time_stats['total_extracted']:>5}")

        if time_stats["batches_processed"] % 10 == 0:
            with open(os.path.join(OUTPUT_DIR, "time_intermediate.json"), "w") as f:
                json.dump(time_stats, f, ensure_ascii=False, indent=2)

        time.sleep(RATE_LIMIT_SECONDS)

        if time_stats["batches_processed"] >= MAX_BATCHES:
            break

    write_db.close()
    print(f"\n  Time phase complete: {time_stats['total_extracted']} extracted, "
          f"{time_stats['total_failed']} remaining")

    # ── Step 5: Verify and save summary ─────────────────────────────────────
    print("\n=== Verifying Results ===")
    verify_db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)

    city_filled_after = verify_db.execute(
        "SELECT COUNT(*) FROM events WHERE city IS NOT NULL AND city != ''"
    ).fetchone()[0]
    city_still_empty = verify_db.execute(
        "SELECT COUNT(*) FROM events WHERE (city IS NULL OR city = '') AND place IS NOT NULL AND place != ''"
    ).fetchone()[0]

    time_filled_after = verify_db.execute(
        "SELECT COUNT(*) FROM events WHERE time_iso IS NOT NULL AND time_iso != ''"
    ).fetchone()[0]
    time_still_empty = verify_db.execute(
        "SELECT COUNT(*) FROM events WHERE (time_iso IS NULL OR time_iso = '') AND time_text IS NOT NULL AND time_text != ''"
    ).fetchone()[0]

    verify_db.close()

    print(f"  City filled: {city_filled_after} (still empty: {city_still_empty})")
    print(f"  Time filled: {time_filled_after} (still empty: {time_still_empty})")

    # ── Step 6: Save summary ────────────────────────────────────────────────
    end_time = datetime.now()
    duration_sec = (end_time - start_time).total_seconds()

    summary = {
        "generated_at": end_time.isoformat(),
        "duration_seconds": duration_sec,
        "db_path": DB_PATH,
        "primary_api": primary_api,
        "backup_apis": [name for name, _ in backup_apis] if backup_apis else [],
        "api_latencies": {name: lat for name, lat in available_apis},
        "city_extraction": {
            "batches_processed": city_stats["batches_processed"],
            "total_extracted": city_stats["total_extracted"],
            "total_remaining": city_stats["total_failed"],
            "city_filled_after": city_filled_after,
            "still_empty_after": city_still_empty,
            "batch_details": city_stats["batch_details"],
        },
        "time_parsing": {
            "batches_processed": time_stats["batches_processed"],
            "total_extracted": time_stats["total_extracted"],
            "total_remaining": time_stats["total_failed"],
            "time_filled_after": time_filled_after,
            "still_empty_after": time_still_empty,
            "batch_details": time_stats["batch_details"],
        },
        "rate_limit_seconds": RATE_LIMIT_SECONDS,
        "batch_size": BATCH_SIZE,
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n=== Summary saved to: {SUMMARY_PATH} ===")
    print(f"Duration: {duration_sec:.1f}s ({duration_sec/60:.1f}m)")
    print(f"City extracted: {city_stats['total_extracted']}")
    print(f"Time parsed: {time_stats['total_extracted']}")


if __name__ == "__main__":
    main()
