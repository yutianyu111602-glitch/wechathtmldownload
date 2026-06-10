#!/usr/bin/env python3
"""Audit count loss across the HUAIDJ weekly mini-program data pipeline."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
ARCHIVE_SCRIPT_DIR = SCRIPT_DIR / "archive_old"
if ARCHIVE_SCRIPT_DIR.exists() and str(ARCHIVE_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(ARCHIVE_SCRIPT_DIR))

try:
    import build_weekly_activity_miniprogram_api as mini_api
except Exception:  # pragma: no cover - audit remains useful without classifier details.
    mini_api = None


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def read_jsonl_count(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def read_jsonl_rows(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
            if limit and len(rows) >= limit:
                break
    return rows


def first_string(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def first_nonempty(*values: Any) -> str:
    for value in values:
        text = first_string(value)
        if text:
            return text
    return ""


def iso_date_prefix(value: Any) -> str:
    text = first_string(value)
    if len(text) >= 10 and text[:4].isdigit() and text[4] == "-" and text[7] == "-":
        return text[:10]
    return ""


def row_post_date(row: dict[str, Any]) -> str:
    for key in ("post_date", "publish_date", "source_date", "date", "datetime", "publish_time"):
        value = iso_date_prefix(row.get(key))
        if value:
            return value
    return ""


def account_latest_dates(path: Path) -> dict[str, str]:
    latest: dict[str, str] = {}
    for row in read_jsonl_rows(path, limit=None):
        account_id = first_nonempty(row.get("account_key"), row.get("account_id"), row.get("account"), row.get("source_account_key"))
        post_date = row_post_date(row)
        if account_id and post_date and post_date > latest.get(account_id, ""):
            latest[account_id] = post_date
    return latest


def list_strings(value: Any, limit: int = 12) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            if len(out) >= limit:
                break
        return out
    return []


def registry_counts(path: Path) -> dict[str, Any]:
    payload = read_json(path)
    rows = payload.get("accounts") if isinstance(payload.get("accounts"), list) else []
    statuses = Counter(first_string(row.get("status")) or "unknown" for row in rows if isinstance(row, dict))
    return {
        "path": str(path),
        "total": len(rows),
        "status_counts": dict(sorted(statuses.items())),
        "active": statuses.get("active", 0),
    }


def registry_accounts(path: Path) -> list[dict[str, Any]]:
    payload = read_json(path)
    rows = payload.get("accounts") if isinstance(payload.get("accounts"), list) else []
    accounts: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or first_string(row.get("status")) != "active":
            continue
        account_id = first_string(row.get("account_id")) or first_string(row.get("id")) or first_string(row.get("key"))
        if not account_id:
            continue
        accounts.append(
            {
                "account_id": account_id,
                "account_name": first_string(row.get("account_name")) or first_string(row.get("name")) or account_id,
                "city_key": first_string(row.get("city_key")),
                "sync_priority": row.get("sync_priority", 0),
            }
        )
    return accounts


def current_counts(api_dir: Path) -> dict[str, Any]:
    manifest = read_json(api_dir / "manifest.json")
    current = read_json(api_dir / "current.json")
    items = current.get("items") if isinstance(current.get("items"), list) else []
    city_counts = Counter(first_string(item.get("city_name")) or "unknown" for item in items if isinstance(item, dict))
    date_counts = Counter(first_string(item.get("event_date_start")) or "unknown" for item in items if isinstance(item, dict))
    source_accounts = Counter(first_string(item.get("source_account_name")) or "unknown" for item in items if isinstance(item, dict))
    return {
        "api_dir": str(api_dir),
        "manifest_item_count": manifest.get("item_count"),
        "current_item_count": current.get("item_count", len(items)),
        "city_counts": dict(city_counts.most_common()),
        "date_counts": dict(sorted(date_counts.items())),
        "source_account_count": len(source_accounts),
        "top_source_accounts": dict(source_accounts.most_common(20)),
        "filtered_counts": manifest.get("filtered_counts") or {},
    }


def api_account_counts(api_dir: Path) -> Counter[str]:
    current = read_json(api_dir / "current.json")
    items = current.get("items") if isinstance(current.get("items"), list) else []
    counts: Counter[str] = Counter()
    for item in items:
        if not isinstance(item, dict):
            continue
        event_id = first_string(item.get("id")) or first_string(item.get("event_id"))
        key = event_id.split(":", 1)[0] if ":" in event_id else ""
        key = key or first_string(item.get("promoter")) or first_string(item.get("account")) or first_string(item.get("source_account_name"))
        if key:
            counts[key] += 1
    return counts


def load_pack_rows(pack_dir: Path) -> list[dict[str, Any]]:
    rows = read_jsonl_rows(pack_dir / "weekly_activity_recommendation_candidates.jsonl", limit=None)
    rows += read_jsonl_rows(pack_dir / "weekly_activity_recommendation_review_candidates.jsonl", limit=None)
    return rows


def classify_pack_row(
    row: dict[str, Any],
    *,
    window_start: date,
    window_end: date,
    venue_registry: list[dict[str, Any]],
    account_registry: list[dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    if mini_api is None:
        return "unclassified", {}
    try:
        if mini_api.row_needs_ocr_review(row):
            return "needs_ocr_review", {}
        if mini_api.row_is_publish_blocked(row):
            return "publish_blocked", {}
        item = mini_api.build_item(
            row,
            evidence_limit=3,
            base_url="",
            venue_registry=venue_registry,
            account_registry=account_registry,
        )
        if not item.get("event_date_text"):
            return "missing_source_date", item
        in_window_dates = mini_api.windowed_date_guesses(item, window_start, window_end)
        if not in_window_dates:
            return "outside_date_window", item
        if not item.get("city_keys"):
            return "missing_city", item
        if not item.get("address_full"):
            reason = mini_api.non_local_announcement_reason(row, item)
            return reason or "publishable_missing_address_warning", item
        return "publishable", item
    except Exception as exc:  # pragma: no cover - diagnostic path.
        return f"classify_exception:{str(exc)[:80]}", {}


def pack_filter_breakdown(
    pack_dir: Path,
    *,
    window_start: date,
    window_end: date,
    venue_registry_path: Path | None,
    account_registry_path: Path | None,
) -> dict[str, Any]:
    rows = load_pack_rows(pack_dir)
    venue_registry = mini_api.load_venue_registry(venue_registry_path) if mini_api is not None and venue_registry_path else []
    account_registry = mini_api.load_account_registry(account_registry_path) if mini_api is not None and account_registry_path else []
    reason_counts: Counter[str] = Counter()
    account_reason_counts: dict[str, Counter[str]] = {}
    risky_window_recovery: list[dict[str, Any]] = []
    for row in rows:
        account = first_nonempty(row.get("account_key"), row.get("account"), "unknown")
        reason, item = classify_pack_row(
            row,
            window_start=window_start,
            window_end=window_end,
            venue_registry=venue_registry,
            account_registry=account_registry,
        )
        reason_counts[reason] += 1
        account_reason_counts.setdefault(account, Counter())[reason] += 1
        if reason == "outside_date_window" and item:
            all_dates = [
                value
                for value in (item.get("event_date_iso_guesses") if isinstance(item.get("event_date_iso_guesses"), list) else [])
                if isinstance(value, str)
            ]
            in_window = []
            for value in all_dates:
                parsed = mini_api.parse_iso_date(value) if mini_api is not None else None
                if parsed is not None and window_start <= parsed <= window_end:
                    in_window.append(value)
            if in_window and len(risky_window_recovery) < 80:
                risky_window_recovery.append(
                    {
                        "account_key": account,
                        "title": first_nonempty(item.get("title"), row.get("title")),
                        "post_date": first_nonempty(row.get("post_date"), row.get("publish_date")),
                        "event_date_text": item.get("event_date_text") or [],
                        "event_date_iso_guesses": all_dates,
                        "in_window_dates": in_window,
                        "city_name": first_string(item.get("city_name")),
                        "venue_name": first_string(item.get("venue_name")),
                        "recommendation_reason": list_strings(row.get("recommendation_reason"), 8),
                        "review_flags": list_strings(row.get("review_flags"), 8),
                    }
                )
    return {
        "reason_counts": dict(reason_counts.most_common()),
        "account_reason_counts": {key: dict(value.most_common()) for key, value in sorted(account_reason_counts.items())},
        "risky_window_recovery_sample": risky_window_recovery,
    }


def pack_counts(pack_dir: Path) -> dict[str, Any]:
    pack_summary = read_json(pack_dir / "source_summary.json")
    ocr_summary = read_json(pack_dir / "summary.json")
    aggregate = read_json(pack_dir / "aggregate_expansion_report.json")
    deepseek = read_json(pack_dir / "deepseek_enrichment_summary.json")
    candidates_path = pack_dir / "weekly_activity_recommendation_candidates.jsonl"
    reviews_path = pack_dir / "weekly_activity_recommendation_review_candidates.jsonl"
    rows = read_jsonl_rows(candidates_path, limit=None)
    review_rows = read_jsonl_rows(reviews_path, limit=None)
    account_counts = Counter(first_string(row.get("account_key")) or "unknown" for row in rows + review_rows)
    flag_counts: Counter[str] = Counter()
    for row in rows + review_rows:
        for flag in list_strings(row.get("review_flags"), 30) + list_strings(row.get("missing_publish_fields"), 30):
            flag_counts[flag] += 1
    return {
        "pack_dir": str(pack_dir),
        "source_summary": {
            "weekly_queue_total": pack_summary.get("weekly_queue_total"),
            "matched_articles": pack_summary.get("matched_articles"),
            "candidates": pack_summary.get("candidates"),
            "review_candidates": pack_summary.get("review_candidates"),
            "account_count": len(pack_summary.get("account_counts") or {}),
        },
        "jsonl_counts": {
            "candidates": len(rows),
            "review_candidates": len(review_rows),
            "account_count": len(account_counts),
        },
        "ocr": {
            "rows_seen": ocr_summary.get("rows_seen"),
            "limit": ocr_summary.get("limit"),
            "fetched_articles": ocr_summary.get("fetched_articles"),
            "ocr_images": ocr_summary.get("ocr_images"),
            "skipped": ocr_summary.get("skipped"),
            "ocr_preflight_required": ocr_summary.get("ocr_preflight_required"),
            "ocr_preflight_blocked": ocr_summary.get("ocr_preflight_blocked"),
        },
        "aggregate": {
            "aggregate_parent_count": aggregate.get("aggregate_parent_count"),
            "processed_secondary_count": aggregate.get("processed_secondary_count"),
            "child_candidate_count": aggregate.get("child_candidate_count"),
            "child_review_count": aggregate.get("child_review_count"),
            "future_child_cache_count": aggregate.get("future_child_cache_count"),
            "counters": aggregate.get("counters") or {},
        },
        "deepseek": {
            "input_rows": deepseek.get("input_rows"),
            "enriched_rows": deepseek.get("enriched_rows"),
            "failed_rows": deepseek.get("failed_rows"),
            "risk_flag_counts": deepseek.get("risk_flag_counts") or {},
        },
        "top_accounts": dict(account_counts.most_common(20)),
        "top_flags": dict(flag_counts.most_common(30)),
    }


def queue_counts(queue_dir: Path) -> dict[str, Any]:
    summary = read_json(queue_dir / "summary.json")
    queue_path = queue_dir / "weekly_activity_queue.jsonl"
    return {
        "queue_dir": str(queue_dir),
        "summary": {
            "history_queue": summary.get("history_queue"),
            "prefetch_queue": summary.get("prefetch_queue"),
            "historical_total": summary.get("historical_total"),
            "prefetch_total": summary.get("prefetch_total"),
            "new_count": summary.get("new_count"),
            "account_count": summary.get("account_count"),
            "excluded_counts": summary.get("excluded_counts") or {},
            "since_date": summary.get("since_date"),
            "until_date": summary.get("until_date"),
        },
        "jsonl_count": read_jsonl_count(queue_path),
    }


def queue_account_counts(queue_dir: Path) -> Counter[str]:
    rows = read_jsonl_rows(queue_dir / "weekly_activity_queue.jsonl", limit=None)
    return Counter(first_string(row.get("account_key")) or "unknown" for row in rows if isinstance(row, dict))


def pack_account_counts(pack_dir: Path) -> Counter[str]:
    rows = read_jsonl_rows(pack_dir / "weekly_activity_recommendation_candidates.jsonl", limit=None)
    rows += read_jsonl_rows(pack_dir / "weekly_activity_recommendation_review_candidates.jsonl", limit=None)
    return Counter(first_string(row.get("account_key")) or "unknown" for row in rows if isinstance(row, dict))


def prefetch_counts(prefetch_dir: Path) -> dict[str, Any]:
    summary = read_json(prefetch_dir / "summary.json")
    return {
        "prefetch_dir": str(prefetch_dir),
        "summary": {
            "accounts_requested": summary.get("accounts_requested"),
            "account_dirs_missing": summary.get("account_dirs_missing"),
            "rows_written": summary.get("rows_written"),
            "exporter_refresh_requested": summary.get("exporter_refresh_requested"),
            "exporter_articles_per_account": summary.get("exporter_articles_per_account"),
            "exporter_accounts_ok": summary.get("exporter_accounts_ok"),
            "exporter_accounts_failed": summary.get("exporter_accounts_failed"),
            "exporter_article_rows": summary.get("exporter_article_rows"),
        },
        "jsonl_count": read_jsonl_count(prefetch_dir / "latest_queue.jsonl"),
    }


def account_coverage(registry: Path, prefetch_dir: Path, queue_dir: Path, pack_dir: Path, api_dir: Path) -> dict[str, Any]:
    accounts = registry_accounts(registry)
    prefetch_summary = read_json(prefetch_dir / "summary.json")
    queue_summary = read_json(queue_dir / "summary.json")
    prefetch_account_counts = Counter({str(k): int(v) for k, v in (prefetch_summary.get("account_counts") or {}).items()})
    exporter_account_counts = Counter({str(k): int(v) for k, v in (prefetch_summary.get("exporter_account_counts") or {}).items()})
    queue_counts_by_account = queue_account_counts(queue_dir)
    pack_counts_by_account = pack_account_counts(pack_dir)
    published_counts = api_account_counts(api_dir)
    prefetch_latest_dates = account_latest_dates(prefetch_dir / "latest_queue.jsonl")
    queue_latest_dates = account_latest_dates(queue_dir / "weekly_activity_queue.jsonl")
    stale_cutoff_date = first_string(queue_summary.get("since_date"))
    rows: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    exporter_status_counts: Counter[str] = Counter()
    city_status_counts: dict[str, Counter[str]] = {}
    for account in accounts:
        account_id = account["account_id"]
        prefetch_count = int(prefetch_account_counts.get(account_id, 0))
        exporter_count = int(exporter_account_counts.get(account_id, 0))
        queue_count = int(queue_counts_by_account.get(account_id, 0))
        pack_count = int(pack_counts_by_account.get(account_id, 0))
        published_count = int(published_counts.get(account_id, 0))
        latest_post_date = max(prefetch_latest_dates.get(account_id, ""), queue_latest_dates.get(account_id, ""))
        stale_for_window = bool(stale_cutoff_date and latest_post_date and latest_post_date < stale_cutoff_date and queue_count <= 0)
        if prefetch_count <= 0:
            exporter_status = "no_prefetch"
        elif exporter_count > 0:
            exporter_status = "exporter_ok"
        elif stale_for_window:
            exporter_status = "exporter_failed_stale_or_quiet"
        elif prefetch_count <= 20:
            exporter_status = "exporter_failed_recent_local_cache_capped"
        else:
            exporter_status = "exporter_failed_recent_local_cache_uncapped"
        exporter_status_counts[exporter_status] += 1
        if published_count > 0:
            status = "published"
        elif pack_count > 0:
            status = "blocked_before_publish"
        elif queue_count > 0:
            status = "dropped_before_pack"
        elif stale_for_window:
            status = "stale_no_recent_posts"
        elif prefetch_count <= 0:
            status = "missing_prefetch"
        else:
            status = "no_post_in_article_cache_window"
        status_counts[status] += 1
        city_key = first_string(account.get("city_key")) or "unknown"
        city_status_counts.setdefault(city_key, Counter())[status] += 1
        rows.append(
            {
                **account,
                "prefetch_count": prefetch_count,
                "exporter_count": exporter_count,
                "queue_count": queue_count,
                "pack_count": pack_count,
                "published_count": published_count,
                "latest_post_date": latest_post_date,
                "stale_cutoff_date": stale_cutoff_date,
                "exporter_status": exporter_status,
                "coverage_status": status,
            }
        )
    problem_order = {
        "missing_prefetch": 0,
        "no_post_in_article_cache_window": 1,
        "dropped_before_pack": 2,
        "blocked_before_publish": 3,
        "stale_no_recent_posts": 4,
        "published": 5,
    }
    stale_rows = [row for row in rows if row["coverage_status"] == "stale_no_recent_posts"]
    problem_rows = sorted(
        [row for row in rows if row["coverage_status"] not in {"published", "stale_no_recent_posts"}],
        key=lambda row: (
            problem_order.get(str(row.get("coverage_status")), 99),
            -int(row.get("sync_priority") or 0),
            str(row.get("city_key") or ""),
            str(row.get("account_id") or ""),
        ),
    )
    return {
        "active_accounts": len(accounts),
        "stale_cutoff_date": stale_cutoff_date,
        "stale_no_recent_posts": len(stale_rows),
        "queue_relevant_active_accounts": max(0, len(accounts) - len(stale_rows)),
        "status_counts": dict(status_counts.most_common()),
        "exporter_status_counts": dict(exporter_status_counts.most_common()),
        "city_status_counts": {key: dict(value.most_common()) for key, value in sorted(city_status_counts.items())},
        "accounts": rows,
        "problem_accounts_sample": problem_rows[:80],
        "stale_accounts_sample": sorted(
            stale_rows,
            key=lambda row: (str(row.get("latest_post_date") or ""), str(row.get("account_id") or "")),
        )[:80],
    }


def build_findings(report: dict[str, Any], min_items: int) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    active = int((report.get("registry") or {}).get("active") or 0)
    prefetch = ((report.get("prefetch") or {}).get("summary") or {})
    queue = ((report.get("queue") or {}).get("summary") or {})
    pack = report.get("pack") or {}
    ocr = pack.get("ocr") or {}
    aggregate = pack.get("aggregate") or {}
    api = report.get("api") or {}
    item_count = int(api.get("current_item_count") or api.get("manifest_item_count") or 0)
    if item_count < min_items:
        findings.append({"severity": "error", "code": "LOW_PUBLISHED_COUNT", "message": f"published {item_count} < min_expected {min_items}"})
    if active and int(prefetch.get("accounts_requested") or 0) < active:
        findings.append({"severity": "error", "code": "PREFETCH_ACCOUNT_GAP", "message": "prefetch did not request all active accounts"})
    if prefetch.get("exporter_refresh_requested") is not True:
        findings.append({"severity": "warning", "code": "NO_EXPORTER_REFRESH", "message": "prefetch used only local _articles.json; high-volume accounts may be capped at first page"})
    coverage = report.get("account_coverage") or {}
    queue_relevant_active = int(coverage.get("queue_relevant_active_accounts") or active)
    stale_accounts = int(coverage.get("stale_no_recent_posts") or 0)
    if stale_accounts:
        findings.append(
            {
                "severity": "info",
                "code": "STALE_ACCOUNTS_SKIPPED",
                "message": f"{stale_accounts} active accounts had no posts since {coverage.get('stale_cutoff_date')}; skipped from queue coverage expectation",
            }
        )
    if queue_relevant_active and int(queue.get("account_count") or 0) < max(1, int(queue_relevant_active * 0.75)):
        findings.append(
            {
                "severity": "warning",
                "code": "QUEUE_ACCOUNT_GAP",
                "message": f"post-date queue accounts {queue.get('account_count')} is far below release-relevant active {queue_relevant_active}",
            }
        )
    if int(ocr.get("limit") or 0) > 0:
        findings.append({"severity": "error", "code": "OCR_LIMITED", "message": f"poster OCR ran with limit {ocr.get('limit')}"})
    if int(aggregate.get("child_review_count") or 0) > 0 and int(aggregate.get("child_candidate_count") or 0) == 0:
        findings.append({"severity": "warning", "code": "AGGREGATE_CHILDREN_ALL_BLOCKED", "message": "aggregate extraction produced review children but no publish candidates"})
    filtered = api.get("filtered_counts") or {}
    coverage_counts = (coverage.get("status_counts") or {})
    exporter_status_counts = coverage.get("exporter_status_counts") or {}
    capped = int(exporter_status_counts.get("exporter_failed_recent_local_cache_capped") or 0)
    if capped:
        findings.append({"severity": "warning", "code": "ACCOUNT_LOCAL_CACHE_CAPPED", "message": f"{capped} release-relevant accounts still look capped by local _articles cache or exporter freq control"})
    blocked_accounts = int(coverage_counts.get("blocked_before_publish") or 0)
    if blocked_accounts:
        findings.append({"severity": "info", "code": "ACCOUNTS_BLOCKED_BEFORE_PUBLISH", "message": f"{blocked_accounts} active accounts reached pack but published 0 items"})
    outside = int(filtered.get("outside_date_window") or 0)
    source_rows = int(read_json(Path(api.get("api_dir", "")) / "manifest.json").get("source_rows_loaded") or 0) if api.get("api_dir") else 0
    if source_rows and outside > int(source_rows * 0.75):
        findings.append({"severity": "info", "code": "MOST_ROWS_OUTSIDE_EVENT_WINDOW", "message": f"{outside}/{source_rows} rows are outside display window after event-date parsing"})
    return findings


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    findings = report.get("findings") or []
    lines = [
        "# Weekly Pipeline Loss Chain Audit",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- window: `{report.get('window_start')}` .. `{report.get('window_end')}`",
        f"- registry active: `{((report.get('registry') or {}).get('active'))}`",
        f"- release-relevant active: `{((report.get('account_coverage') or {}).get('queue_relevant_active_accounts'))}`",
        f"- stale/no-recent-post accounts skipped: `{((report.get('account_coverage') or {}).get('stale_no_recent_posts'))}`",
        f"- prefetch rows: `{(((report.get('prefetch') or {}).get('summary') or {}).get('rows_written'))}`",
        f"- queue rows: `{(((report.get('queue') or {}).get('summary') or {}).get('new_count'))}`",
        f"- pack candidates/review: `{(((report.get('pack') or {}).get('jsonl_counts') or {}).get('candidates'))}` / `{(((report.get('pack') or {}).get('jsonl_counts') or {}).get('review_candidates'))}`",
        f"- OCR fetched/skipped/images: `{(((report.get('pack') or {}).get('ocr') or {}).get('fetched_articles'))}` / `{(((report.get('pack') or {}).get('ocr') or {}).get('skipped'))}` / `{(((report.get('pack') or {}).get('ocr') or {}).get('ocr_images'))}`",
        f"- aggregate child publish/review: `{(((report.get('pack') or {}).get('aggregate') or {}).get('child_candidate_count'))}` / `{(((report.get('pack') or {}).get('aggregate') or {}).get('child_review_count'))}`",
        f"- published items: `{((report.get('api') or {}).get('current_item_count'))}`",
        "",
        "## Findings",
    ]
    if findings:
        lines.extend(f"- `{item.get('severity')}` `{item.get('code')}`: {item.get('message')}" for item in findings)
    else:
        lines.append("- none")
    lines.extend(["", "## API Filtered Counts", "```json", json.dumps((report.get("api") or {}).get("filtered_counts") or {}, ensure_ascii=False, indent=2), "```"])
    coverage = report.get("account_coverage") or {}
    lines.extend(
        [
            "",
            "## Account Coverage",
            "",
            "```json",
            json.dumps(
                {
                    "status_counts": coverage.get("status_counts") or {},
                    "exporter_status_counts": coverage.get("exporter_status_counts") or {},
                    "city_status_counts": coverage.get("city_status_counts") or {},
                    "problem_accounts_sample": coverage.get("problem_accounts_sample") or [],
                    "stale_accounts_sample": coverage.get("stale_accounts_sample") or [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
        ]
    )
    if report.get("pack_filter_breakdown"):
        lines.extend(
            [
                "",
                "## Pack Filter Breakdown",
                "```json",
                json.dumps(report.get("pack_filter_breakdown") or {}, ensure_ascii=False, indent=2),
                "```",
            ]
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit weekly mini-program pipeline count loss")
    parser.add_argument("--registry", required=True)
    parser.add_argument("--prefetch-dir", required=True)
    parser.add_argument("--queue-dir", required=True)
    parser.add_argument("--pack-dir", required=True)
    parser.add_argument("--api-dir", required=True)
    parser.add_argument("--venue-registry", default="")
    parser.add_argument("--account-registry", default="")
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-days", type=int, default=15)
    parser.add_argument("--min-items", type=int, default=80)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args(argv)

    start = date.fromisoformat(args.window_start)
    end = start + timedelta(days=max(1, args.window_days) - 1)
    report = {
        "schema_version": "weekly_pipeline_loss_chain_audit.v1",
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "min_items": args.min_items,
        "registry": registry_counts(Path(args.registry)),
        "prefetch": prefetch_counts(Path(args.prefetch_dir)),
        "queue": queue_counts(Path(args.queue_dir)),
        "pack": pack_counts(Path(args.pack_dir)),
        "api": current_counts(Path(args.api_dir)),
    }
    report["account_coverage"] = account_coverage(
        Path(args.registry),
        Path(args.prefetch_dir),
        Path(args.queue_dir),
        Path(args.pack_dir),
        Path(args.api_dir),
    )
    report["pack_filter_breakdown"] = pack_filter_breakdown(
        Path(args.pack_dir),
        window_start=start,
        window_end=end,
        venue_registry_path=Path(args.venue_registry) if args.venue_registry else None,
        account_registry_path=Path(args.account_registry) if args.account_registry else Path(args.registry),
    )
    report["findings"] = build_findings(report, args.min_items)
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(Path(args.out_md), report)
    print(json.dumps({"ok": not any(item.get("severity") == "error" for item in report["findings"]), "findings": report["findings"]}, ensure_ascii=False, indent=2))
    if args.fail_on_error and any(item.get("severity") == "error" for item in report["findings"]):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
