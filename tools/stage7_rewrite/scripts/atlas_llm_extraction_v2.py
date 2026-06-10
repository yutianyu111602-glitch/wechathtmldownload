#!/usr/bin/env python3
"""
Atlas LLM Extraction v2 - Comprehensive missing field fill.

Strategy:
  1. Fill cities from map_geocode_places table (venue name matching)
  2. LLM batch city extraction for remaining ambiguous places
  3. LLM batch time_text parsing with article context

Uses WAL+checkpoint for all writes.
"""

import sqlite3
import json
import os
import re
import sys
import time
import threading
import requests
from datetime import datetime

# ── Configuration ──────────────────────────────────────────────────────────
DB_PATH = "/tmp/atlas_work.sqlite"
OUTPUT_DIR = "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_llm_extraction_20260528"
SUMMARY_PATH = os.path.join(OUTPUT_DIR, "llm_extraction_summary.json")
BATCH_SIZE = 20
RATE_LIMIT_SECONDS = 6.0  # 10 calls/min
MAX_LLM_BATCHES = 50  # per phase per run
GEOCODE_BATCH = 5000

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


def get_api_key(config):
    return os.environ.get(config["key_env"], "")


def test_api_with_timeout(api_name, config, timeout_seconds=15):
    """Test API connectivity with thread-based timeout."""
    result = [False, 0, ""]

    def _do_test():
        try:
            key = get_api_key(config)
            if not key:
                result[0], result[1], result[2] = False, 0, "no API key"
                return
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
            payload = {
                "model": config["model"],
                "messages": [{"role": "user", "content": "回复: 你好"}],
                "max_tokens": 20, "temperature": 0.1,
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
                result[0], result[1], result[2] = False, latency, f"HTTP {resp.status_code}"
        except Exception as e:
            result[0], result[1], result[2] = False, 0, str(e)[:200]

    t = threading.Thread(target=_do_test, daemon=True)
    t.start()
    t.join(timeout=timeout_seconds)
    if t.is_alive():
        return False, timeout_seconds * 1000, f"timeout after {timeout_seconds}s"
    return tuple(result)


# ── Phase 1: Geocode table fill ───────────────────────────────────────────
def fill_cities_from_geocode(db_path):
    """Fill city from map_geocode_places table by venue name matching."""
    print("\n=== Phase 0: Geocode Table City Fill ===")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # Build mapping from geocode table
    gmap = {}
    for row in conn.execute("""
        SELECT label, city FROM map_geocode_places
        WHERE city IS NOT NULL AND city != ''
    """).fetchall():
        key = row[0].strip().lower() if row[0] else ""
        if key:
            gmap[key] = row[1]

    print(f"  Geocode venue map: {len(gmap)} entries")

    # Process in batches
    total_updated = 0
    offset = 0
    while True:
        rows = conn.execute("""
            SELECT row_pk, place FROM events
            WHERE (city IS NULL OR city = '')
              AND place IS NOT NULL AND place != ''
            ORDER BY row_pk
            LIMIT ? OFFSET ?
        """, (GEOCODE_BATCH, offset)).fetchall()

        if not rows:
            break

        updates = []
        for pk, place in rows:
            key = place.strip().lower()
            if key in gmap:
                updates.append((gmap[key], pk))

        if updates:
            conn.execute("BEGIN IMMEDIATE")
            conn.executemany("UPDATE events SET city = ? WHERE row_pk = ?", updates)
            conn.execute("COMMIT")
            total_updated += len(updates)

        offset += GEOCODE_BATCH
        if offset % 50000 == 0:
            print(f"  Geocode progress: {offset} rows scanned, {total_updated} filled")

    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    print(f"  Geocode fill complete: {total_updated} cities filled")
    return total_updated


# ── LLM API functions ──────────────────────────────────────────────────────
def call_llm(api_name, config, system_prompt, user_prompt, max_tokens=2048):
    """Call an LLM API and return the response text."""
    key = get_api_key(config)
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    payload = {
        "model": config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    resp = requests.post(config["url"], headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"API error {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def parse_json_response(content):
    """Parse JSON from LLM response, handling markdown wrapping."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r'```(?:json)?\s*', '', content)
        content = re.sub(r'```\s*$', '', content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r'\[.*\]', content, re.DOTALL)
        if match:
            return json.loads(match.group(0))
    return None


def extract_cities_llm(api_name, config, batch_rows):
    """LLM city extraction. batch_rows: [(pk, place), ...]. Returns: [(city, pk), ...]"""
    items = [f"{pk}: {place}" for pk, place in batch_rows]
    prompt = f"""Extract the Chinese city name from each venue address below.
Return ONLY a JSON array: [{{"row_pk": number, "city": "城市名"}}, ...]
If no city can be identified, use empty string "" for city.
Chinese cities only (北京/上海/深圳/广州/成都/杭州/昆明/武汉/西安/重庆/长沙/郑州 etc.)

Venues:
{chr(10).join(items)}

Example: [{{"row_pk": 1, "city": "上海"}}, {{"row_pk": 2, "city": ""}}]"""

    content = call_llm(api_name, config,
                       "You are a Chinese address parser. Return only valid JSON array.",
                       prompt)
    results = parse_json_response(content)
    if not results:
        return []

    output = []
    for item in results:
        if isinstance(item, dict) and "row_pk" in item:
            city = item.get("city", "").strip()
            if city:
                output.append((city, int(item["row_pk"])))
    return output


def parse_time_llm(api_name, config, batch_rows):
    """LLM time parsing. batch_rows: [(pk, time_text, article_date), ...]. Returns: [(time_iso, pk), ...]"""
    items = []
    for pk, time_text, article_date in batch_rows:
        ctx = f" [article date: {article_date}]" if article_date else ""
        items.append(f"{pk}: {time_text}{ctx}")

    prompt = f"""Parse event time expressions into YYYY-MM-DD dates.
For relative dates (今晚/明天/本周五), use article date as reference.
For "7/19" format, use the article year or most recent year.
For recurring patterns (每周末/每周三) or ambiguous expressions, return empty string.
Return ONLY a JSON array: [{{"row_pk": number, "time_iso": "YYYY-MM-DD"}}]

Expressions:
{chr(10).join(items)}

Example: [{{"row_pk": 1, "time_iso": "2024-07-19"}}, {{"row_pk": 2, "time_iso": ""}}]"""

    content = call_llm(api_name, config,
                       "You are a date parser. Return only valid JSON array.",
                       prompt)
    results = parse_json_response(content)
    if not results:
        return []

    date_pattern = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    output = []
    for item in results:
        if isinstance(item, dict) and "row_pk" in item:
            time_iso = item.get("time_iso", "").strip()
            if time_iso and date_pattern.match(time_iso):
                output.append((time_iso, int(item["row_pk"])))
    return output


def run_llm_phase(write_db, api_name, config, phase_name, query, extract_fn, max_batches):
    """Generic LLM batch processing loop."""
    print(f"\n=== Phase: {phase_name} ===")

    # Read candidates
    read_db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    read_db.row_factory = sqlite3.Row
    rows = read_db.execute(query, (BATCH_SIZE * max_batches,)).fetchall()
    read_db.close()

    print(f"  Candidates: {len(rows)}")

    stats = {"batches": 0, "extracted": 0, "failed": 0}

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        batch_rows = [tuple(r) for r in batch]

        try:
            results = extract_fn(api_name, config, batch_rows)
            if results:
                write_db.execute("BEGIN IMMEDIATE")
                write_db.executemany(
                    f"UPDATE events SET {phase_name.split()[0]} = ? WHERE row_pk = ?",
                    results
                )
                write_db.execute("COMMIT")
                write_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            extracted = len(results)
            failed = len(batch_rows) - extracted
        except Exception as e:
            print(f"  ERROR batch {stats['batches']+1}: {e}")
            extracted = 0
            failed = len(batch_rows)

        stats["batches"] += 1
        stats["extracted"] += extracted
        stats["failed"] += failed

        print(f"  Batch {stats['batches']:>3}: extracted={extracted:>3}/{len(batch_rows)}  "
              f"cumulative={stats['extracted']:>5}")

        # Save intermediate
        if stats["batches"] % 10 == 0:
            mid_path = os.path.join(OUTPUT_DIR, f"intermediate_{phase_name.replace(' ','_')}.json")
            with open(mid_path, "w") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)

        time.sleep(RATE_LIMIT_SECONDS)

        if stats["batches"] >= max_batches:
            break

    print(f"  {phase_name} complete: {stats['extracted']} extracted, {stats['failed']} remaining")
    return stats


# ── Main ───────────────────────────────────────────────────────────────────
def main():
    start_time = datetime.now()
    print(f"=== Atlas LLM Extraction v2 ===")
    print(f"Started: {start_time.isoformat()}")
    print(f"DB: {DB_PATH}")

    # Test APIs
    print("\n=== Testing APIs ===")
    available = []
    for name, config in API_CONFIGS.items():
        print(f"  Testing {name}...", end=" ", flush=True)
        ok, lat, msg = test_api_with_timeout(name, config)
        if ok:
            available.append((name, lat))
            print(f"OK ({lat:.0f}ms)")
        else:
            print(f"FAIL: {msg[:80]}")

    if not available:
        print("FATAL: No APIs available!"); sys.exit(1)

    available.sort(key=lambda x: x[1])
    primary = available[0][0]
    print(f"\n  Primary: {primary} ({available[0][1]:.0f}ms)")

    # Phase 0: Geocode fill
    geo_filled = fill_cities_from_geocode(DB_PATH)

    # Open write connection for LLM phases
    write_db = sqlite3.connect(DB_PATH)
    write_db.execute("PRAGMA journal_mode=WAL")
    write_db.execute("PRAGMA synchronous=NORMAL")
    write_db.execute("PRAGMA cache_size=-8000")

    # Phase 1: LLM city extraction
    city_stats = run_llm_phase(
        write_db, primary, API_CONFIGS[primary],
        "city extraction",
        """SELECT row_pk, place FROM events
           WHERE (city IS NULL OR city = '')
             AND place IS NOT NULL AND place != ''
           ORDER BY row_pk LIMIT ?""",
        extract_cities_llm,
        MAX_LLM_BATCHES
    )

    # Phase 2: LLM time parsing
    time_stats = run_llm_phase(
        write_db, primary, API_CONFIGS[primary],
        "time_iso parsing",
        """SELECT e.row_pk, e.time_text, a.publish_time
           FROM events e
           LEFT JOIN articles a ON e.source_article_uid = a.article_uid
           WHERE (e.time_iso IS NULL OR e.time_iso = '')
             AND e.time_text IS NOT NULL AND e.time_text != ''
           ORDER BY e.row_pk LIMIT ?""",
        parse_time_llm,
        MAX_LLM_BATCHES
    )

    write_db.close()

    # Verification
    print("\n=== Verification ===")
    vdb = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    city_filled = vdb.execute("SELECT COUNT(*) FROM events WHERE city IS NOT NULL AND city != ''").fetchone()[0]
    city_empty = vdb.execute("SELECT COUNT(*) FROM events WHERE (city IS NULL OR city = '') AND place IS NOT NULL AND place != ''").fetchone()[0]
    time_filled = vdb.execute("SELECT COUNT(*) FROM events WHERE time_iso IS NOT NULL AND time_iso != ''").fetchone()[0]
    time_empty = vdb.execute("SELECT COUNT(*) FROM events WHERE (time_iso IS NULL OR time_iso = '') AND time_text IS NOT NULL AND time_text != ''").fetchone()[0]
    vdb.close()

    print(f"  City filled: {city_filled} (empty: {city_empty})")
    print(f"  Time filled: {time_filled} (empty: {time_empty})")

    # Save summary
    end_time = datetime.now()
    summary = {
        "generated_at": end_time.isoformat(),
        "duration_seconds": (end_time - start_time).total_seconds(),
        "db_path": DB_PATH,
        "primary_api": primary,
        "geocode_fill": geo_filled,
        "city_extraction": {"extracted": city_stats["extracted"], "remaining": city_stats["failed"]},
        "time_parsing": {"extracted": time_stats["extracted"], "remaining": time_stats["failed"]},
        "final_state": {
            "city_filled": city_filled, "city_empty": city_empty,
            "time_filled": time_filled, "time_empty": time_empty,
        }
    }

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"\n=== Summary: {SUMMARY_PATH} ===")
    print(f"Geocode filled: {geo_filled}")
    print(f"LLM city extracted: {city_stats['extracted']}")
    print(f"LLM time parsed: {time_stats['extracted']}")
    print(f"Duration: {(end_time - start_time).total_seconds():.0f}s")


if __name__ == "__main__":
    main()
