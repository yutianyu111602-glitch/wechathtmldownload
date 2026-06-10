#!/usr/bin/env python3
"""LLM Deep Parse Time Text -- Use DeepSeek V4 Pro to resolve hard time_text cases.

After regex parsers (parse_time_text_to_iso.py) handle straightforward
year-month-day patterns, ~239K events still lack time_iso. This script samples
the most common unique time_text values, sends them to DeepSeek for semantic
parsing -- Chinese relative dates, recurring patterns, and dates missing year
context -- then writes back high/medium confidence, non-recurring results.

Architecture:
  1. Read unique time_text values from DB, sorted by frequency (max 5000)
  2. Attach a sample article publish_time as reference for relative dates
  3. Call DeepSeek API in parallel (max 10 concurrent) with retry on 429
  4. Parse JSON responses; validate year/month/day sanity
  5. For high/medium confidence non-recurring dates: map back to all matching
     rows and write time_iso via WAL+checkpoint (WSL-safe)
  6. Save all LLM responses + write summary to a JSON audit file

Cost awareness:
  - Deduplication: only sends unique time_text values, not individual rows
  - Max 5000 unique values, roughly 0.5-1M tokens depending on article context
  - ~$0.50-$1.00 at DeepSeek pricing (much less than processing all 239K rows)

Dry-run (default) reports what would be written without touching the DB.
Use --execute --confirm-token <TOKEN> to commit writes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TZ = timezone(timedelta(hours=8))  # Beijing time

DB_PATH = (
    "/mnt/c/code/githubstar/wechathtmldownload/reports/"
    "atlas_incremental_wechat_refresh_20260522_1438/"
    "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435/"
    "atlas_recovered_20260528.sqlite"
)

OUTPUT_DIR = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports/"
    "atlas_time_text_llm_parse_20260528"
)

DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_CHAT_URL = f"{DEEPSEEK_BASE_URL}/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"            # fast/cheap primary
DEEPSEEK_REASONER = "deepseek-reasoner"     # harder cases (not used by default)

MAX_CONCURRENT = 10
MAX_RETRIES = 3
RETRY_BACKOFF_S = 2.0
REQUEST_TIMEOUT_S = 60
RATE_LIMIT_COOLDOWN_S = 1.0                 # polite floor between calls

MAX_UNIQUE_TIME_TEXT = 5000
MAX_ARTICLE_CONTEXT_CHARS = 400

CONFIRM_TOKEN = "ENABLE_LLM_TIME_TEXT_PARSE_BULK_WRITE"

# Log progress every N LLM calls
PROGRESS_EVERY = 25

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _load_json(text: str) -> dict:
    """Safely parse a JSON string, returning {} on any failure."""
    if not text:
        return {}
    try:
        val = json.loads(text)
        return val if isinstance(val, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _extract_article_publish_time(raw_json_str: str | None) -> str | None:
    """Try to extract a publish-time string from raw_json."""
    if not raw_json_str:
        return None
    obj = _load_json(raw_json_str)
    # Common field names across this project's article shapes
    for key in (
        "publish_time", "post_date", "created_at", "pub_time",
        "article_publish_time", "source_publish_time",
        "publishTime", "postDate", "createdAt",
    ):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Nested article object
    article = obj.get("article") or obj.get("source_article") or {}
    if isinstance(article, dict):
        for key in ("publish_time", "post_date", "created_at"):
            val = article.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return None


def _extract_article_title(raw_json_str: str | None) -> str:
    """Try to extract a title from raw_json for LLM context."""
    if not raw_json_str:
        return ""
    obj = _load_json(raw_json_str)
    for key in ("title", "article_title", "name"):
        val = obj.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:MAX_ARTICLE_CONTEXT_CHARS]
    return ""


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


def fetch_unique_time_texts(
    db_path: str,
    max_unique: int = MAX_UNIQUE_TIME_TEXT,
) -> list[dict]:
    """Return the most common unique time_text values with sample article context.

    Each item: {
        "time_text": str,
        "count": int,
        "sample_row_pk": int,
        "sample_article_uid": str | None,
        "sample_publish_time": str | None,
        "sample_title": str,
        "sample_event_name": str,
    }
    """
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)

    # 1. Get unique time_text with counts, ordered by frequency
    freq_rows = db.execute(
        """
        SELECT time_text, COUNT(*) AS cnt
        FROM events
        WHERE time_text IS NOT NULL
          AND time_text != ''
          AND (time_iso IS NULL OR time_iso = '')
        GROUP BY time_text
        ORDER BY cnt DESC
        LIMIT ?
        """,
        (max_unique,),
    ).fetchall()

    if not freq_rows:
        db.close()
        return []

    time_texts = [row[0] for row in freq_rows]
    count_map = {row[0]: row[1] for row in freq_rows}

    # 2. For each unique time_text, grab ONE sample row for context
    #    Use a single query with GROUP BY to avoid N+1
    placeholders = ",".join("?" for _ in time_texts)
    sample_rows = db.execute(
        f"""
        SELECT time_text, row_pk, source_article_uid, raw_json, name
        FROM events
        WHERE time_text IN ({placeholders})
          AND (time_iso IS NULL OR time_iso = '')
        GROUP BY time_text
        """,
        time_texts,
    ).fetchall()

    db.close()

    sample_map: dict[str, dict] = {}
    for tt, rpk, uid, raw, name in sample_rows:
        pub_time = _extract_article_publish_time(raw)
        title = _extract_article_title(raw)
        sample_map[tt] = {
            "row_pk": rpk,
            "article_uid": uid,
            "publish_time": pub_time,
            "title": title,
            "event_name": (name or "")[:MAX_ARTICLE_CONTEXT_CHARS],
        }

    # 3. Build output list preserving frequency order
    results: list[dict] = []
    for tt, cnt in freq_rows:
        sample = sample_map.get(tt, {})
        results.append({
            "time_text": tt,
            "count": cnt,
            "sample_row_pk": sample.get("row_pk"),
            "sample_article_uid": sample.get("article_uid"),
            "sample_publish_time": sample.get("publish_time"),
            "sample_title": sample.get("title", ""),
            "sample_event_name": sample.get("event_name", ""),
        })
    return results


def fetch_row_pks_for_time_text(db_path: str, time_text: str, limit: int = 0) -> list[int]:
    """Return all row_pks with the given time_text and no time_iso."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    query = (
        "SELECT row_pk FROM events "
        "WHERE time_text = ? AND (time_iso IS NULL OR time_iso = '')"
    )
    if limit:
        query += f" LIMIT {limit}"
    rows = db.execute(query, (time_text,)).fetchall()
    db.close()
    return [r[0] for r in rows]


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


SYSTEM_PROMPT = (
    "你是一个专门解析中文活动时间文本的助手。"
    "你的任务是将微信文章中提取的 time_text 转换为具体日期或标记为周期性活动。"
    "只输出 JSON object，不要输出任何解释性文字。"
)

USER_PROMPT_TEMPLATE = """解析以下活动时间文本，提取或推断出具体的年、月、日。

## 时间文本
{time_text}

## 参考信息
- 文章发布时间: {publish_time}
- 文章标题: {article_title}
- 活动名称: {event_name}
- 该 time_text 在数据库中出现次数: {count}

## 解析规则
1. 如果文本描述的是具体日期（如"2025年4月12日"、"12月31日"、"4.30"、"跨年"），提取年月日。
   - 如果只有月日没有年，根据文章发布时间推断年份。
   - "跨年" = 12月31日到次年1月1日之间，优先取12月31日。
2. 如果文本是相对日期（如"今晚"、"明晚"、"本周六"、"下周"），
   以文章发布时间为参考点计算具体日期。
   - "今晚/今天" = 文章发布当天
   - "明晚/明天" = 文章发布次日
   - "本周X" = 文章发布当周的周X
   - "下周X" = 文章发布下一周的周X
   - "本周末" = 文章发布当周的周六或周日（取周六）
3. 如果文本描述的是周期性活动（如"每周三"、"每周五晚"、"每月最后一个周六"、
   "Every Thursday"、"每周六及周日"），设置 is_recurring = true，
   并给出一个 sample_date 作为示例日期（用文章发布时间所在的月份/周计算）。
4. 如果无法推断出任何日期，设置 confidence = "low"，日期字段填 null。

## 输出格式
严格输出以下 JSON object（不要加任何其他文字）:
{{
  "year": 2025,
  "month": 6,
  "day": 15,
  "confidence": "high|medium|low",
  "is_recurring": false,
  "explanation": "简短的解析说明"
}}

注意:
- year/month/day 字段: 如果能确定就用具体数字，不能确定就用 null
- 对于周期性事件，year/month/day 填 null（如果无法确定具体日期）或填你推断的 sample_date
- confidence 仅在日期能从文本+上下文可靠推断时填 high
- 周X映射: 周一=1...周日=7
- 不要编造日期，拿不准就填 null 并 confidence="low"
"""


def build_user_prompt(item: dict) -> str:
    return USER_PROMPT_TEMPLATE.format(
        time_text=item["time_text"],
        publish_time=item.get("sample_publish_time") or "(未知)",
        article_title=item.get("sample_title") or "(未知)",
        event_name=item.get("sample_event_name") or "(未知)",
        count=item.get("count", 0),
    )


def build_payload(item: dict, *, model: str = DEEPSEEK_MODEL) -> dict:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(item)},
        ],
        "temperature": 0,
        "max_tokens": 256,
        "response_format": {"type": "json_object"},
        "stream": False,
    }


# ---------------------------------------------------------------------------
# DeepSeek API calling
# ---------------------------------------------------------------------------


def _deepseek_chat(payload: dict, api_key: str) -> dict:
    """Single synchronous DeepSeek API call (no retry). Uses urllib to avoid
    requiring third-party packages; falls back to requests if available."""
    try:
        import requests

        resp = requests.post(
            DEEPSEEK_CHAT_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            timeout=REQUEST_TIMEOUT_S,
        )
        if resp.status_code == 429:
            raise RuntimeError("RATE_LIMITED_429")
        resp.raise_for_status()
        return resp.json()
    except ImportError:
        from urllib.error import HTTPError, URLError
        from urllib.request import Request, urlopen

        req = Request(
            DEEPSEEK_CHAT_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except HTTPError as exc:
            if exc.code == 429:
                raise RuntimeError("RATE_LIMITED_429") from exc
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[-600:]
            except Exception:
                pass
            raise RuntimeError(f"DeepSeek HTTP {exc.code}: {body}") from exc


def call_deepseek_with_retry(payload: dict, api_key: str, max_retries: int = MAX_RETRIES) -> dict:
    """Call DeepSeek API with exponential backoff on 429 / transient errors."""
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return _deepseek_chat(payload, api_key)
        except Exception as exc:
            last_err = exc
            msg = str(exc)
            is_rate_limited = "RATE_LIMITED_429" in msg or "429" in msg
            is_server_err = any(str(code) in msg for code in ("500", "502", "503", "504"))

            if attempt < max_retries and (is_rate_limited or is_server_err):
                backoff = RETRY_BACKOFF_S * (2 ** attempt)
                if is_rate_limited:
                    backoff = max(backoff, 3.0)  # at least 3s for 429
                print(f"  [retry] attempt {attempt+1}/{max_retries+1}, "
                      f"waiting {backoff:.1f}s: {msg[:120]}", file=sys.stderr)
                time.sleep(backoff)
                continue
            raise
    raise last_err  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Response parsing & validation
# ---------------------------------------------------------------------------


def parse_llm_response(response_payload: dict) -> dict:
    """Extract the JSON result from a DeepSeek chat-completion response."""
    try:
        choices = response_payload.get("choices") or []
        if not choices:
            return {}
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if not content:
            return {}
        # Try direct JSON parse
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        pass

    # Fallback: extract JSON object from text with regex
    try:
        content = (
            (response_payload.get("choices") or [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        m = re.search(r"\{[^{}]*\}", content, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception:
        pass

    return {}


def validate_result(parsed: dict) -> dict:
    """Clean and validate the LLM output, normalizing fields.

    Returns a dict with keys: year, month, day, confidence, is_recurring,
    explanation, _valid (bool), _resolved_date (str or None)
    """
    out: dict = {
        "year": parsed.get("year"),
        "month": parsed.get("month"),
        "day": parsed.get("day"),
        "confidence": str(parsed.get("confidence", "low")).lower(),
        "is_recurring": bool(parsed.get("is_recurring", False)),
        "explanation": str(parsed.get("explanation", ""))[:300],
        "_valid": False,
        "_resolved_date": None,
    }

    # Normalize confidence
    if out["confidence"] not in ("high", "medium", "low"):
        out["confidence"] = "low"

    # Check we have numeric year/month/day
    try:
        y = int(out["year"]) if out["year"] is not None else None
        m = int(out["month"]) if out["month"] is not None else None
        d = int(out["day"]) if out["day"] is not None else None
    except (ValueError, TypeError):
        y = m = d = None

    out["year"] = y
    out["month"] = m
    out["day"] = d

    if y is None or m is None or d is None:
        out["_valid"] = False
        return out

    # Sanity checks
    if not (2000 <= y <= 2035):
        out["_valid"] = False
        return out
    if not (1 <= m <= 12):
        out["_valid"] = False
        return out
    if not (1 <= d <= 31):
        out["_valid"] = False
        return out
    # Basic month-length check
    if m == 2 and d > 29:
        out["_valid"] = False
        return out
    if m in (4, 6, 9, 11) and d > 30:
        out["_valid"] = False
        return out

    out["_valid"] = True
    out["_resolved_date"] = f"{y:04d}-{m:02d}-{d:02d}"
    return out


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------


def _build_hashed_key(time_text: str) -> str:
    """Short hash for log-friendly identification."""
    import hashlib
    return hashlib.sha256(time_text.encode("utf-8")).hexdigest()[:8]


def run_llm_parsing(
    items: list[dict],
    api_key: str,
    *,
    model: str = DEEPSEEK_MODEL,
    max_concurrent: int = MAX_CONCURRENT,
) -> list[dict]:
    """Process all unique time_text items through DeepSeek in parallel.

    Returns the same list augmented with _llm_raw, _llm_parsed, _llm_validated fields.
    """
    results: list[dict | None] = [None] * len(items)
    total = len(items)
    success = 0
    failed = 0
    rate_limited = 0
    stats: Counter = Counter()

    # Rate-limiting: track last call time per thread isn't precise enough;
    # use a shared lock + time tracking.
    import threading
    lock = threading.Lock()
    last_call_time = [0.0]  # mutable for closure

    def process_one(idx: int, item: dict) -> tuple[int, dict, bool, str]:
        nonlocal success, failed, rate_limited

        payload = build_payload(item, model=model)

        # Polite rate limiting
        with lock:
            now_t = time.time()
            wait = RATE_LIMIT_COOLDOWN_S - (now_t - last_call_time[0])
            if wait > 0:
                time.sleep(wait)
            last_call_time[0] = time.time()

        raw: dict = {}
        error: str = ""
        ok = False

        try:
            raw = call_deepseek_with_retry(payload, api_key)
            ok = True
        except Exception as exc:
            error = str(exc)[:400]
            if "429" in error or "RATE_LIMITED" in error:
                rate_limited += 1

        with lock:
            if ok:
                success += 1
            else:
                failed += 1

        result_item = dict(item)
        result_item["_llm_raw"] = raw
        result_item["_llm_error"] = error
        result_item["_llm_parsed"] = parse_llm_response(raw) if ok else {}
        result_item["_llm_validated"] = (
            validate_result(result_item["_llm_parsed"]) if ok else {}
        )

        # Log progress
        done = success + failed
        if ok:
            v = result_item["_llm_validated"]
            stats["confidence_" + v.get("confidence", "unknown")] += 1
            if v.get("is_recurring"):
                stats["is_recurring"] += 1
            if v.get("_valid"):
                stats["resolved_valid"] += 1
            else:
                stats["resolved_invalid"] += 1
        else:
            stats["api_error"] += 1

        if done % PROGRESS_EVERY == 0 or done == total:
            print(
                f"  [llm] {done}/{total}  ok={success} fail={failed} "
                f"valid_dates={stats.get('resolved_valid', 0)} "
                f"recurring={stats.get('is_recurring', 0)}",
                file=sys.stderr,
            )

        return idx, result_item, ok, error

    print(f"\nCalling DeepSeek API ({model}) for {total} unique time_text values...",
          file=sys.stderr)
    print(f"  Max concurrent: {max_concurrent}", file=sys.stderr)
    print(f"  Retries: {MAX_RETRIES}, Backoff: {RETRY_BACKOFF_S}s",
          file=sys.stderr)

    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        futures = {
            executor.submit(process_one, i, item): i
            for i, item in enumerate(items)
        }
        for future in as_completed(futures):
            idx, result_item, ok, error = future.result()
            results[idx] = result_item

    print(f"\nLLM processing complete:", file=sys.stderr)
    print(f"  Total: {total}", file=sys.stderr)
    print(f"  Success: {success}", file=sys.stderr)
    print(f"  Failed: {failed}", file=sys.stderr)
    print(f"  Rate-limited: {rate_limited}", file=sys.stderr)
    print(f"  Valid dates: {stats.get('resolved_valid', 0)}", file=sys.stderr)
    print(f"  Recurring: {stats.get('is_recurring', 0)}", file=sys.stderr)
    for k in sorted(stats.keys()):
        if k.startswith("confidence_"):
            print(f"  {k}: {stats[k]}", file=sys.stderr)

    return [r for r in results if r is not None]


def classify_results(results: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split results into: writable, recurring, skipped (low confidence or invalid)."""
    writable: list[dict] = []   # high/medium confidence, non-recurring, valid date
    recurring: list[dict] = []  # is_recurring=True
    skipped: list[dict] = []    # everything else

    for r in results:
        v = r.get("_llm_validated", {})
        if v.get("is_recurring"):
            recurring.append(r)
            continue
        if v.get("_valid") and v.get("confidence") in ("high", "medium"):
            writable.append(r)
        else:
            skipped.append(r)

    return writable, recurring, skipped


def write_results_to_db(
    db_path: str,
    writable: list[dict],
    *,
    dry_run: bool = True,
) -> dict:
    """For each writable result, resolve all matching rows and update time_iso.

    Uses WAL + periodic checkpoint for WSL crash safety.
    Returns a summary dict.
    """
    if dry_run:
        # Count affected rows without writing
        total_rows = 0
        sample_updates: list[dict] = []
        for item in writable:
            date = item["_llm_validated"]["_resolved_date"]
            count = item.get("count", 0)
            total_rows += count
            if len(sample_updates) < 10:
                sample_updates.append({
                    "time_text": item["time_text"],
                    "resolved_date": date,
                    "confidence": item["_llm_validated"]["confidence"],
                    "affected_rows": count,
                })
        return {
            "dry_run": True,
            "unique_time_texts_to_write": len(writable),
            "total_affected_rows": total_rows,
            "sample_updates": sample_updates,
        }

    # -- Actually write --
    print(f"\nOpening DB for write: {db_path}", file=sys.stderr)
    db = sqlite3.connect(db_path, timeout=30)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("BEGIN IMMEDIATE")

    written = 0
    skipped = 0
    total_checked = 0
    batch_counter = 0

    for item in writable:
        time_text = item["time_text"]
        date = item["_llm_validated"]["_resolved_date"]

        # Fetch all matching row_pks
        rows = db.execute(
            "SELECT row_pk FROM events WHERE time_text = ? AND (time_iso IS NULL OR time_iso = '')",
            (time_text,),
        ).fetchall()

        for (rpk,) in rows:
            # Guard: re-check time_iso is still empty (avoid overwrites from concurrent runs)
            existing = db.execute(
                "SELECT time_iso FROM events WHERE row_pk = ?", (rpk,)
            ).fetchone()
            if existing and existing[0] and str(existing[0]).strip():
                skipped += 1
                total_checked += 1
                continue

            db.execute(
                "UPDATE events SET time_iso = ? WHERE row_pk = ?",
                (date, rpk),
            )
            written += 1
            total_checked += 1

        batch_counter += written
        if batch_counter >= 5000:
            db.execute("COMMIT")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            db.execute("BEGIN IMMEDIATE")
            print(f"  checkpoint: {total_checked:,} rows checked, "
                  f"{written:,} written, {skipped:,} skipped", file=sys.stderr)
            batch_counter = 0

    db.execute("COMMIT")
    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # Verify: sample check
    sample_ok = 0
    sample_total = min(100, written)
    sample_items = writable[:sample_total]
    for item in sample_items:
        time_text = item["time_text"]
        expected = item["_llm_validated"]["_resolved_date"]
        row = db.execute(
            "SELECT time_iso FROM events WHERE time_text = ? AND time_iso = ? LIMIT 1",
            (time_text, expected),
        ).fetchone()
        if row:
            sample_ok += 1

    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    # Fresh read for totals
    total_ti = db.execute(
        "SELECT COUNT(*) FROM events WHERE time_iso IS NOT NULL AND time_iso != ''"
    ).fetchone()[0]

    db.close()

    return {
        "dry_run": False,
        "unique_time_texts_written": len(writable),
        "rows_checked": total_checked,
        "rows_written": written,
        "rows_skipped": skipped,
        "verify_sample_ok": sample_ok,
        "verify_sample_total": sample_total,
        "total_time_iso_after": total_ti,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="LLM Deep Parse Time Text -- resolve hard time_text with DeepSeek"
    )
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually write results to DB (default: dry-run)",
    )
    parser.add_argument(
        "--confirm-token", default="",
        help=f"Required for --execute. Token: {CONFIRM_TOKEN}",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="Limit unique time_text values processed (for testing)",
    )
    parser.add_argument(
        "--max-unique", type=int, default=MAX_UNIQUE_TIME_TEXT,
        help=f"Max unique time_text values to sample (default: {MAX_UNIQUE_TIME_TEXT})",
    )
    parser.add_argument(
        "--model", default=DEEPSEEK_MODEL,
        help=f"DeepSeek model to use (default: {DEEPSEEK_MODEL})",
    )
    parser.add_argument(
        "--concurrency", type=int, default=MAX_CONCURRENT,
        help=f"Max parallel API calls (default: {MAX_CONCURRENT})",
    )
    parser.add_argument(
        "--db", default=DB_PATH,
        help="Path to the SQLite database",
    )
    parser.add_argument(
        "--output-dir", default=str(OUTPUT_DIR),
        help="Output directory for audit files",
    )
    args = parser.parse_args()

    # Validate execute mode
    if args.execute and args.confirm_token != CONFIRM_TOKEN:
        print(f"ERROR: --confirm-token must be '{CONFIRM_TOKEN}' to execute writes.",
              file=sys.stderr)
        sys.exit(1)

    # API key
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        print("ERROR: DEEPSEEK_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    # Output dir
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    max_unique = min(args.max_unique, args.limit) if args.limit else args.max_unique

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------
    print("=" * 65)
    print(f"LLM DEEP PARSE TIME TEXT -- {'EXECUTE' if args.execute else 'DRY-RUN'}")
    print(f"DB:     {args.db}")
    print(f"Model:  {args.model}")
    print(f"Output: {out_dir}")
    print(f"Max unique time_text values: {max_unique}")
    print(f"Concurrency: {args.concurrency}")
    print(f"Started: {now_iso()}")
    print("=" * 65)

    # ------------------------------------------------------------------
    # Step 1: Fetch unique time_text values
    # ------------------------------------------------------------------
    print("\n[1/5] Fetching unique time_text values from DB...")
    items = fetch_unique_time_texts(args.db, max_unique=max_unique)

    if not items:
        print("No time_text candidates found. Nothing to do.")
        return

    total_rows_represented = sum(it["count"] for it in items)
    print(f"  Unique time_text values: {len(items):,}")
    print(f"  Total rows represented: {total_rows_represented:,}")

    # Show top samples
    print("\n  Top 10 most common time_text values:")
    for it in items[:10]:
        pub = it.get("sample_publish_time") or "N/A"
        print(f"    [{it['count']:>6}] \"{it['time_text'][:50]}\"  pub={pub[:30]}")

    # ------------------------------------------------------------------
    # Step 2: Run LLM parsing
    # ------------------------------------------------------------------
    print(f"\n[2/5] Calling DeepSeek API for {len(items)} unique time_text values...")
    results = run_llm_parsing(
        items,
        api_key,
        model=args.model,
        max_concurrent=args.concurrency,
    )

    # ------------------------------------------------------------------
    # Step 3: Classify
    # ------------------------------------------------------------------
    print(f"\n[3/5] Classifying results...")
    writable, recurring, skipped = classify_results(results)

    print(f"  Writable (high/medium, non-recurring, valid date): {len(writable)}")
    print(f"  Recurring: {len(recurring)}")
    print(f"  Skipped (low confidence / invalid): {len(skipped)}")

    if writable:
        total_affected = sum(it.get("count", 0) for it in writable)
        print(f"  Estimated rows that would be updated: {total_affected:,}")

    # Show samples of each category
    if writable:
        print("\n  Sample writable results:")
        for it in writable[:8]:
            v = it["_llm_validated"]
            print(f"    \"{it['time_text'][:40]}\" -> {v.get('_resolved_date')} "
                  f"conf={v.get('confidence')} [{it.get('count', 0)} rows]")
    if recurring:
        print("\n  Sample recurring results:")
        for it in recurring[:5]:
            v = it["_llm_validated"]
            print(f"    \"{it['time_text'][:40]}\" recurring  [{it.get('count', 0)} rows]")
    if skipped:
        print("\n  Sample skipped results:")
        for it in skipped[:5]:
            v = it["_llm_validated"]
            err = it.get("_llm_error", "")
            status = f"conf={v.get('confidence')}" if v else f"error={err[:50]}"
            print(f"    \"{it['time_text'][:40]}\" {status}")

    # ------------------------------------------------------------------
    # Step 4: Save audit files
    # ------------------------------------------------------------------
    print(f"\n[4/5] Saving audit files to {out_dir}...")

    # Full results (with LLM responses)
    audit_path = out_dir / "llm_time_text_results.json"
    audit_data = {
        "meta": {
            "generated_at": now_iso(),
            "mode": "execute" if args.execute else "dry_run",
            "model": args.model,
            "db_path": args.db,
            "unique_time_text_sampled": len(items),
            "total_rows_represented": total_rows_represented,
            "writable": len(writable),
            "recurring": len(recurring),
            "skipped": len(skipped),
        },
        "writable": [
            {
                "time_text": r["time_text"],
                "count": r.get("count"),
                "resolved_date": r["_llm_validated"].get("_resolved_date"),
                "confidence": r["_llm_validated"].get("confidence"),
                "explanation": r["_llm_validated"].get("explanation"),
            }
            for r in writable
        ],
        "recurring": [
            {
                "time_text": r["time_text"],
                "count": r.get("count"),
                "confidence": r["_llm_validated"].get("confidence"),
                "explanation": r["_llm_validated"].get("explanation"),
            }
            for r in recurring
        ],
        "skipped": [
            {
                "time_text": r["time_text"],
                "count": r.get("count"),
                "confidence": r["_llm_validated"].get("confidence"),
                "error": r.get("_llm_error", ""),
                "explanation": r["_llm_validated"].get("explanation", ""),
            }
            for r in skipped
        ],
    }
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {audit_path}")

    # Raw LLM responses (full, for debugging)
    raw_path = out_dir / "llm_time_text_raw_responses.json"
    raw_data = {
        "generated_at": now_iso(),
        "model": args.model,
        "results": [
            {
                "time_text": r["time_text"],
                "count": r.get("count"),
                "llm_raw": r.get("_llm_raw"),
                "llm_parsed": r.get("_llm_parsed"),
                "llm_validated": r.get("_llm_validated"),
                "llm_error": r.get("_llm_error"),
            }
            for r in results
        ],
    }
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {raw_path}")

    # ------------------------------------------------------------------
    # Step 5: Write to DB (or dry-run summary)
    # ------------------------------------------------------------------
    print(f"\n[5/5] {'Writing to DB' if args.execute else 'Dry-run report'}...")

    write_summary = write_results_to_db(
        args.db,
        writable,
        dry_run=not args.execute,
    )

    summary_path = out_dir / "llm_time_text_summary.json"
    full_summary = {
        "decision": (
            "atlas_llm_time_text_parse_executed"
            if args.execute
            else "atlas_llm_time_text_parse_dry_run"
        ),
        "generated_at": now_iso(),
        "mode": "execute" if args.execute else "dry_run",
        "model": args.model,
        "db_path": args.db,
        "sampling": {
            "unique_time_text_processed": len(items),
            "total_rows_represented": total_rows_represented,
        },
        "classification": {
            "writable": len(writable),
            "recurring": len(recurring),
            "skipped": len(skipped),
        },
        "write_result": write_summary,
    }
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(full_summary, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {summary_path}")

    # ------------------------------------------------------------------
    # Done
    # ------------------------------------------------------------------
    print(f"\n{'='*65}")
    if args.execute:
        ws = write_summary
        print(f"EXECUTED: {ws.get('rows_written', 0):,} rows written, "
              f"{ws.get('rows_skipped', 0):,} skipped")
        print(f"Verify: {ws.get('verify_sample_ok', 0)}/{ws.get('verify_sample_total', 0)}")
        print(f"Total time_iso in DB: {ws.get('total_time_iso_after', 0):,}")
    else:
        ws = write_summary
        print(f"DRY-RUN: {len(writable)} unique time_text values ready, "
              f"{ws.get('total_affected_rows', 0):,} rows affected")
        print(f"To execute: --execute --confirm-token {CONFIRM_TOKEN}")
    print(f"{'='*65}")


if __name__ == "__main__":
    main()
