#!/usr/bin/env python3
"""
Atlas Time ISO Extraction - LLM batch processing for remaining time_text values.
Focused run: only time_iso parsing, maximized batch count.
"""

import sqlite3, json, os, re, sys, time, threading, requests
from datetime import datetime

DB_PATH = "/tmp/atlas_work.sqlite"
OUTPUT_DIR = "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/atlas_llm_extraction_20260528"
BATCH_SIZE = 20
RATE_LIMIT_S = 6.0
MAX_BATCHES = 150

API_CONFIGS = {
    "zhipu_glm4": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-plus", "key_env": "ZHIPUAI_API_KEY",
    },
    "qwen_plus": {
        "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-plus", "key_env": "DASHSCOPE_API_KEY",
    },
    "kimi": {
        "url": "https://api.moonshot.cn/v1/chat/completions",
        "model": "moonshot-v1-8k", "key_env": "KIMI_CODE_API_KEY",
    },
}


def get_key(cfg): return os.environ.get(cfg["key_env"], "")


def test_api(name, cfg, to=15):
    r = [False, 0, ""]
    def _t():
        try:
            k = get_key(cfg)
            if not k: r[0], r[1], r[2] = False, 0, "no key"; return
            h = {"Content-Type": "application/json", "Authorization": f"Bearer {k}"}
            p = {"model": cfg["model"], "messages": [{"role": "user", "content": "hi"}], "max_tokens": 10, "temperature": 0}
            t0 = time.time()
            resp = requests.post(cfg["url"], headers=h, json=p, timeout=10)
            lat = (time.time() - t0) * 1000
            if resp.status_code == 200:
                d = resp.json()
                r[0], r[1], r[2] = True, lat, d.get("choices", [{}])[0].get("message", {}).get("content", "")[:50]
            else:
                r[0], r[1], r[2] = False, lat, f"HTTP {resp.status_code}"
        except Exception as e:
            r[0], r[1], r[2] = False, 0, str(e)[:200]

    t = threading.Thread(target=_t, daemon=True); t.start(); t.join(timeout=to)
    if t.is_alive(): return False, to * 1000, f"timeout {to}s"
    return tuple(r)


def call_llm(name, cfg, sys_p, usr_p, mt=2048):
    k = get_key(cfg)
    h = {"Content-Type": "application/json", "Authorization": f"Bearer {k}"}
    p = {"model": cfg["model"], "messages": [{"role": "system", "content": sys_p}, {"role": "user", "content": usr_p}],
         "max_tokens": mt, "temperature": 0.1}
    resp = requests.post(cfg["url"], headers=h, json=p, timeout=60)
    if resp.status_code != 200: raise Exception(f"API {resp.status_code}: {resp.text[:200]}")
    return resp.json()["choices"][0]["message"]["content"]


def parse_json(c):
    c = c.strip()
    if c.startswith("```"): c = re.sub(r'```(?:json)?\s*', '', c); c = re.sub(r'```\s*$', '', c)
    try: return json.loads(c)
    except json.JSONDecodeError:
        m = re.search(r'\[.*\]', c, re.DOTALL)
        return json.loads(m.group(0)) if m else None


def extract_dates(api_name, cfg, rows):
    items = []
    for pk, tt, ad in rows:
        ctx = f" [article: {ad}]" if ad else ""
        items.append(f"{pk}: {tt}{ctx}")

    prompt = f"""Parse event time into YYYY-MM-DD dates.
Relative dates (今晚/明天/本周五) use article date as reference.
"7/19" -> use article year. Recurring (每周末) -> empty string.
Return ONLY JSON: [{{"row_pk": number, "time_iso": "YYYY-MM-DD"}}]

{chr(10).join(items)}"""

    content = call_llm(api_name, cfg, "You are a date parser. Return only valid JSON.", prompt)
    results = parse_json(content)
    if not results: return []

    dp = re.compile(r'^\d{4}-\d{2}-\d{2}$')
    out = []
    for item in results:
        if isinstance(item, dict) and "row_pk" in item:
            t = item.get("time_iso", "").strip()
            if t and dp.match(t):
                out.append((t, int(item["row_pk"])))
    return out


def main():
    t0 = datetime.now()
    print(f"=== Time ISO Extraction ===")
    print(f"Started: {t0.isoformat()}")
    print(f"Batches: {MAX_BATCHES}, Items/batch: {BATCH_SIZE}")

    print("\n=== Testing APIs ===")
    avail = []
    for n, c in API_CONFIGS.items():
        print(f"  Testing {n}...", end=" ", flush=True)
        ok, lat, msg = test_api(n, c)
        print(f"{'OK' if ok else 'FAIL'} ({lat:.0f}ms){' - '+msg if not ok else ''}")
        if ok: avail.append((n, lat))
    if not avail: print("FATAL"); sys.exit(1)
    avail.sort(key=lambda x: x[1])
    primary = avail[0][0]
    print(f"  Using: {primary}")

    # Read candidates
    read_db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    read_db.row_factory = sqlite3.Row
    rows = read_db.execute("""
        SELECT e.row_pk, e.time_text, a.publish_time
        FROM events e
        LEFT JOIN articles a ON e.source_article_uid = a.article_uid
        WHERE (e.time_iso IS NULL OR e.time_iso = '')
          AND e.time_text IS NOT NULL AND e.time_text != ''
        ORDER BY e.row_pk LIMIT ?
    """, (BATCH_SIZE * MAX_BATCHES,)).fetchall()
    read_db.close()
    print(f"\nCandidates: {len(rows)}")

    write_db = sqlite3.connect(DB_PATH)
    write_db.execute("PRAGMA journal_mode=WAL")
    write_db.execute("PRAGMA synchronous=NORMAL")

    extracted_total = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        batch_rows = [(r["row_pk"], r["time_text"], r["publish_time"]) for r in batch]
        try:
            results = extract_dates(primary, API_CONFIGS[primary], batch_rows)
            if results:
                write_db.execute("BEGIN IMMEDIATE")
                write_db.executemany("UPDATE events SET time_iso = ? WHERE row_pk = ?", results)
                write_db.execute("COMMIT")
                write_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            n = len(results)
        except Exception as e:
            print(f"  ERROR batch {i//BATCH_SIZE+1}: {e}")
            n = 0

        extracted_total += n
        print(f"  Batch {i//BATCH_SIZE+1:>4}: {n:>2}/{len(batch_rows)}  total={extracted_total}")
        time.sleep(RATE_LIMIT_S)

    write_db.close()

    # Verify
    vdb = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    tf = vdb.execute("SELECT COUNT(*) FROM events WHERE time_iso IS NOT NULL AND time_iso != ''").fetchone()[0]
    te = vdb.execute("SELECT COUNT(*) FROM events WHERE (time_iso IS NULL OR time_iso = '') AND time_text IS NOT NULL AND time_text != ''").fetchone()[0]
    vdb.close()

    dt = (datetime.now() - t0).total_seconds()
    print(f"\n=== Done ===")
    print(f"Extracted: {extracted_total}")
    print(f"Time filled: {tf}")
    print(f"Still empty: {te}")
    print(f"Duration: {dt:.0f}s ({dt/60:.1f}m)")

    # Save summary
    s = {"generated_at": datetime.now().isoformat(), "duration_s": dt,
         "extracted": extracted_total, "time_filled_after": tf, "still_empty_after": te}
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "time_extraction_summary.json"), "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
