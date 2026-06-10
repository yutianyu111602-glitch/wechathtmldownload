#!/usr/bin/env python3
"""Fill weekly activity candidate gaps from the local WeChat exporter download API.

This is a bounded product-layer enrichment pass. It reads the weekly candidate
pack, downloads source article text through the local exporter endpoint, and
only fills fields the mini-program needs to publish: date, city, address, and
running hours. It does not call Qwen, Stage7, vector stores, Dajiala, or paid
APIs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_weekly_activity_pack_from_exporter_queue as pack_rules  # noqa: E402


LONGRUN_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")
DEFAULT_ENDPOINT = "http://127.0.0.1:17300/api/public/v1/download"
DEFAULT_CACHE_DIR = LONGRUN_ROOT / "wechat_download_text_cache"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def list_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def parse_iso(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def date_values_for_row(row: dict[str, Any]) -> list[str]:
    return list_strings(row.get("event_date_text")) or list_strings(row.get("date_text"))


def row_in_window(row: dict[str, Any], window_start: date | None, window_end: date | None) -> bool:
    if not window_start or not window_end:
        return True
    for value in date_values_for_row(row):
        parsed = parse_iso(value)
        if parsed and window_start <= parsed <= window_end:
            return True
    return False


def should_fetch(row: dict[str, Any], window_start: date | None, window_end: date | None) -> bool:
    if not first_string(row.get("source_url")):
        return False
    if not row_in_window(row, window_start, window_end):
        return False
    return not (
        list_strings(row.get("city"))
        and first_string(row.get("address"))
        and first_string(row.get("event_time_text"), row.get("running_hours_text"))
    )


def cache_path(cache_dir: Path, url: str) -> Path:
    return cache_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()[:24]}.txt"


def download_text(url: str, endpoint: str, cache_dir: Path, timeout_sec: int) -> tuple[str, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached = cache_path(cache_dir, url)
    if cached.exists():
        return cached.read_text(encoding="utf-8", errors="ignore"), "cache"
    request_url = endpoint + "?" + urlencode({"format": "text", "url": url})
    with urlopen(request_url, timeout=timeout_sec) as response:
        text = response.read().decode("utf-8", errors="ignore")
    cached.write_text(text, encoding="utf-8")
    return text, "download"


def merge_unique(existing: list[str], incoming: list[str], limit: int = 12) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in [*existing, *incoming]:
        key = pack_rules.normalize_subject(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
        if len(out) >= limit:
            break
    return out


def prefer_article_time(existing: str, candidate: str) -> bool:
    if not candidate:
        return False
    if not existing:
        return True
    existing_norm = existing.lower()
    candidate_norm = candidate.lower()
    if "late" in candidate_norm and "late" not in existing_norm:
        return True
    return False


def prefer_article_address(existing: str, candidate: str) -> bool:
    if not candidate:
        return False
    if not existing:
        return True
    existing_key = pack_rules.normalize_subject(existing)
    candidate_key = pack_rules.normalize_subject(candidate)
    if not existing_key or not candidate_key or existing_key == candidate_key:
        return False
    dirty_existing = any(token in existing for token in ("加群", "咨询", "客服", "二维码"))
    if dirty_existing and candidate_key in existing_key:
        return True
    if candidate_key in existing_key and len(candidate) + 8 < len(existing):
        return True
    return False


def enrich_row(row: dict[str, Any], article_text: str) -> tuple[dict[str, Any], list[str]]:
    out = dict(row)
    changed: list[str] = []
    title = first_string(out.get("title"))
    account = first_string(out.get("account_key"), out.get("account"))
    text = pack_rules.clean_text("\n".join([title, article_text]))

    if not date_values_for_row(out):
        dates = pack_rules.date_values(text, first_string(out.get("post_date"), out.get("post_time")))
        if dates:
            out["event_date_text"] = dates
            out["date_text"] = dates
            changed.append("date")

    current_time = first_string(out.get("event_time_text"), out.get("running_hours_text"))
    event_time = pack_rules.extract_event_time(text)
    if prefer_article_time(current_time, event_time):
        out["event_time_text"] = event_time
        changed.append("time")

    current_address = first_string(out.get("address"))
    address = pack_rules.extract_address_from_text(text)
    if prefer_article_address(current_address, address):
        out["address"] = address
        changed.append("address")

    if not list_strings(out.get("city")):
        city = pack_rules.city_from_text(first_string(out.get("address"))) or pack_rules.city_from_text(
            " ".join([account, title, text])
        )
        if city:
            out["city"] = [city["label"]]
            changed.append("city")

    if not list_strings(out.get("lineup")):
        lineup = pack_rules.extract_lineup(text, title, account, first_string(*(list_strings(out.get("venue")) or [""])))
        if lineup:
            out["lineup"] = lineup
            changed.append("lineup")

    if not list_strings(out.get("genres")):
        styles = pack_rules.infer_styles(text)
        if styles:
            out["genres"] = styles
            changed.append("genres")

    if changed:
        evidence = pack_rules.evidence_lines(
            title,
            text,
            {},
            date_values_for_row(out),
            first_string(out.get("event_time_text")),
            first_string(out.get("address")),
        )
        out["evidence"] = merge_unique(list_strings(out.get("evidence")), evidence)
        reasons = list_strings(out.get("recommendation_reason"))
        out["recommendation_reason"] = merge_unique(reasons, [f"wechat_download_{field}_filled" for field in changed])
        try:
            out["confidence"] = round(min(float(out.get("confidence") or 0) + 0.08, 1.0), 3)
        except (TypeError, ValueError):
            out["confidence"] = 0.55
    return out, changed


def write_summary(path: Path, summary: dict[str, Any]) -> None:
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Weekly Activity WeChat Download Enrichment",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source_pack_dir: `{summary['source_pack_dir']}`",
        f"- out_dir: `{summary['out_dir']}`",
        f"- rows_seen: `{summary['rows_seen']}`",
        f"- fetched: `{summary['fetched']}`",
        f"- enriched: `{summary['enriched']}`",
        f"- failed: `{summary['failed']}`",
        f"- skipped: `{summary['skipped']}`",
        "",
        "## Changed Fields",
        "",
    ]
    for key, value in sorted(summary["changed_fields"].items()):
        lines.append(f"- `{key}`: `{value}`")
    (path.parent / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enrich weekly activity pack from local WeChat download API")
    parser.add_argument("--pack-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--window-start", default="")
    parser.add_argument("--window-days", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout-sec", type=int, default=45)
    parser.add_argument("--sleep-sec", type=float, default=0.2)
    args = parser.parse_args(argv)

    pack_dir = Path(args.pack_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if (pack_dir / "summary.json").exists():
        shutil.copy2(pack_dir / "summary.json", out_dir / "source_summary.json")

    window_start = parse_iso(args.window_start) if args.window_start else None
    window_end = window_start + timedelta(days=max(args.window_days - 1, 0)) if window_start and args.window_days else None
    cache_dir = Path(args.cache_dir)
    files = [
        "weekly_activity_recommendation_candidates.jsonl",
        "weekly_activity_recommendation_review_candidates.jsonl",
    ]
    summary: dict[str, Any] = {
        "schema_version": "weekly_activity_wechat_download_enrichment.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_pack_dir": str(pack_dir),
        "out_dir": str(out_dir),
        "endpoint": args.endpoint,
        "cache_dir": str(cache_dir),
        "window_start": args.window_start,
        "window_days": args.window_days,
        "limit": args.limit,
        "rows_seen": 0,
        "fetched": 0,
        "enriched": 0,
        "failed": 0,
        "skipped": 0,
        "changed_fields": {},
        "failures": [],
    }
    changed_counter: dict[str, int] = {}
    fetched_count = 0

    for filename in files:
        rows = read_jsonl(pack_dir / filename)
        out_rows: list[dict[str, Any]] = []
        for row in rows:
            summary["rows_seen"] += 1
            if args.limit and fetched_count >= args.limit:
                summary["skipped"] += 1
                out_rows.append(row)
                continue
            if not should_fetch(row, window_start, window_end):
                summary["skipped"] += 1
                out_rows.append(row)
                continue
            source_url = first_string(row.get("source_url"))
            try:
                article_text, _source = download_text(source_url, args.endpoint, cache_dir, args.timeout_sec)
                fetched_count += 1
                summary["fetched"] += 1
                enriched, changed = enrich_row(row, article_text)
                if changed:
                    summary["enriched"] += 1
                    for field in changed:
                        changed_counter[field] = changed_counter.get(field, 0) + 1
                out_rows.append(enriched)
                if args.sleep_sec:
                    time.sleep(args.sleep_sec)
            except (OSError, URLError, TimeoutError, UnicodeError) as exc:
                summary["failed"] += 1
                if len(summary["failures"]) < 20:
                    summary["failures"].append({"source_url": source_url, "error": str(exc)})
                out_rows.append(row)
        write_jsonl(out_dir / filename, out_rows)

    summary["changed_fields"] = changed_counter
    write_summary(out_dir / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
