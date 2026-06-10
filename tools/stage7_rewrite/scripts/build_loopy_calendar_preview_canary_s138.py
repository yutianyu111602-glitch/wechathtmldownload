#!/usr/bin/env python3
"""Build the S138 Loopy calendar-preview canary and source-refresh scorecard.

This is a local evidence builder. It does not deploy, upload, mutate DBs, read
raw cookies, or print token values. It separates two questions:

1. Is today's Loopy source article present in the local queues?
2. If source rows are shaped like weekly/monthly previews, does the mini-program
   API publish gate either suppress them from the event feed or classify them as
   `calendar_preview` without leaking from evidence-only single events?
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
LONGRUN_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun")
SCHEMA_VERSION = "loopy_calendar_preview_canary_s138.v1"
DEFAULT_REPORT_DIR = STAGE7_ROOT / "reports" / "loopy_calendar_preview_s138_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_LOOPY_CALENDAR_PREVIEW_CANARY_S138_20260601.md"
DEFAULT_SOURCE_PATHS = [
    LONGRUN_ROOT / "LATEST_HUAIDJ_DAILY_DOWNLOAD_QUEUE" / "latest_queue.jsonl",
    LONGRUN_ROOT / "WEEKLY_ACTIVITY_QUEUE_EXPORTER_API_20260601" / "weekly_activity_queue.jsonl",
    LONGRUN_ROOT / "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_20260601" / "weekly_activity_recommendation_candidates.jsonl",
    LONGRUN_ROOT / "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_DEEPSEEK_20260601" / "weekly_activity_recommendation_review_candidates.jsonl",
]
DEFAULT_OLD_LOOPY_PATHS = [
    LONGRUN_ROOT / "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_DEEPSEEK_20260601" / "weekly_activity_recommendation_review_candidates.jsonl",
    LONGRUN_ROOT / "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_20260601" / "weekly_activity_recommendation_candidates.jsonl",
    STAGE7_ROOT / "longrun" / "WEEKLY_ACTIVITY_EXPANDED_PACK_20260531" / "weekly_activity_recommendation_review_candidates.jsonl",
]
CALENDAR_TITLE_RE = re.compile(r"本周活动|活动一览|活动预览|活动预告|月活动|weekly", re.I)


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S%z")


def today_local() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def rel_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            nested = first_string(*value)
            if nested:
                return nested
    return ""


def list_strings(value: Any, *, limit: int = 12) -> list[str]:
    out: list[str] = []
    if isinstance(value, str):
        if value.strip():
            out.append(value.strip())
    elif isinstance(value, list):
        for item in value:
            out.extend(list_strings(item, limit=limit))
            if len(out) >= limit:
                break
    return out[:limit]


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def load_mini_api_module():
    path = STAGE7_ROOT / "scripts" / "archive_old" / "build_weekly_activity_miniprogram_api.py"
    spec = importlib.util.spec_from_file_location("build_weekly_activity_miniprogram_api_s138", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_validator_module():
    path = STAGE7_ROOT / "scripts" / "validate_weekly_event_published.py"
    if not path.exists():
        path = STAGE7_ROOT / "scripts" / "archive_old" / "validate_weekly_event_published.py"
    spec = importlib.util.spec_from_file_location("validate_weekly_event_published_s138", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def is_loopy_row(row: dict[str, Any]) -> bool:
    signals = " ".join(
        [
            first_string(row.get("account_key")),
            first_string(row.get("account_nickname"), row.get("source_account_name")),
            first_string(row.get("title")),
        ]
    ).lower()
    return "loopy" in signals


def source_status_for_path(path: Path, *, today_date: str) -> dict[str, Any]:
    rows = read_jsonl(path)
    loopy_rows = [row for row in rows if is_loopy_row(row)]
    today_loopy = [row for row in loopy_rows if first_string(row.get("post_date"), row.get("publish_date")) == today_date]
    today_calendar = [
        row
        for row in today_loopy
        if CALENDAR_TITLE_RE.search(first_string(row.get("title"), row.get("summary_digest"), row.get("digest")))
    ]
    latest = None
    for row in loopy_rows:
        key = first_string(row.get("post_time"), row.get("publish_time"), row.get("post_date"), row.get("publish_date"))
        if not latest or key > latest[0]:
            latest = (key, row)
    latest_row = latest[1] if latest else {}
    return {
        "path": rel_path(path),
        "exists": path.exists(),
        "row_count": len(rows),
        "loopy_row_count": len(loopy_rows),
        "today_loopy_row_count": len(today_loopy),
        "today_loopy_calendar_like_count": len(today_calendar),
        "latest_loopy": {
            "article_id": first_string(latest_row.get("article_id"), latest_row.get("queue_id")),
            "post_date": first_string(latest_row.get("post_date"), latest_row.get("publish_date")),
            "post_time": first_string(latest_row.get("post_time"), latest_row.get("publish_time")),
            "title": first_string(latest_row.get("title")),
        },
    }


def build_source_refresh_status(source_paths: list[Path], *, today_date: str) -> dict[str, Any]:
    files = [source_status_for_path(path, today_date=today_date) for path in source_paths]
    return {
        "today_date": today_date,
        "files": files,
        "today_loopy_row_count": sum(item["today_loopy_row_count"] for item in files),
        "today_loopy_calendar_like_count": sum(item["today_loopy_calendar_like_count"] for item in files),
        "latest_loopy_post_date": max(
            (item["latest_loopy"]["post_date"] for item in files if item["latest_loopy"]["post_date"]),
            default="",
        ),
    }


def find_old_loopy_weekly_row(paths: list[Path]) -> dict[str, Any]:
    for path in paths:
        for row in read_jsonl(path):
            if first_string(row.get("account_key")) == "loopy_club" and "本周活动一览" in first_string(row.get("title")):
                return row
    return {}


def compact_loopy_row(row: dict[str, Any]) -> dict[str, Any]:
    dates = [value for value in list_strings(row.get("event_date_text"), limit=8) if value != "2026-01-01"]
    return {
        "article_id": first_string(row.get("article_id"), row.get("queue_id")) or "loopy-s138-old-real",
        "queue_id": first_string(row.get("queue_id"), row.get("article_id")) or "loopy-s138-old-real",
        "account_key": "loopy_club",
        "account_nickname": "loopy Club",
        "title": first_string(row.get("title")) or "loopy Club 本周活动一览",
        "source_url": first_string(row.get("source_url")) or "https://mp.weixin.qq.com/s/loopy-s138-old-real",
        "post_date": first_string(row.get("post_date")) or "2026-05-18",
        "event_date_text": dates or ["2026-05-21", "2026-05-22", "2026-05-23", "2026-05-24"],
        "date_text": dates or ["2026-05-21", "2026-05-22", "2026-05-23", "2026-05-24"],
        "event_time_text": first_string(row.get("event_time_text")),
        "city": ["杭州"],
        "venue": ["loopy"],
        "address": first_string(row.get("address")) or "浙江省杭州市西湖区天目里B1-01",
        "geo_lng": first_string(row.get("geo_lng")),
        "geo_lat": first_string(row.get("geo_lat")),
        "evidence": list_strings(row.get("evidence"), limit=8) or ["loopy Club 本周活动一览"],
        "confidence": 0.9,
        "publish_blocked": True,
        "aggregation_parent": True,
    }


def fixture_rows(old_loopy_row: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if old_loopy_row:
        rows.append(compact_loopy_row(old_loopy_row))
    rows.extend(
        [
            {
                "article_id": "loopy-s138-weekly-fixture-20260601",
                "queue_id": "loopy-s138-weekly-fixture-20260601",
                "account_key": "loopy_club",
                "account_nickname": "loopy Club",
                "title": "loopy Club 本周活动一览",
                "source_url": "https://mp.weixin.qq.com/s/loopy-s138-weekly-fixture-20260601",
                "post_date": "2026-06-01",
                "event_date_text": ["2026-06-04", "2026-06-05", "2026-06-06", "2026-06-07"],
                "event_time_text": "",
                "city": ["杭州"],
                "venue": ["loopy"],
                "address": "浙江省杭州市西湖区天目里B1-01",
                "evidence": ["loopy Club 本周活动一览", "6月4日-6月7日 loopy Club"],
                "confidence": 0.9,
                "publish_blocked": True,
                "aggregation_parent": True,
            },
            {
                "article_id": "loopy-s138-monthly-preview-20260601",
                "queue_id": "loopy-s138-monthly-preview-20260601",
                "account_key": "loopy_club",
                "account_nickname": "loopy Club",
                "title": "loopy Club 6月活动预告",
                "source_url": "https://mp.weixin.qq.com/s/loopy-s138-monthly-preview-20260601",
                "post_date": "2026-06-01",
                "event_date_text": ["2026-06-01", "2026-06-30"],
                "event_time_text": "",
                "city": ["杭州"],
                "venue": ["loopy"],
                "address": "浙江省杭州市西湖区天目里B1-01",
                "evidence": ["6月活动预告", "6月1日-6月30日 loopy Club"],
                "confidence": 0.9,
                "publish_blocked": True,
                "aggregation_parent": True,
            },
            {
                "article_id": "loopy-s138-single-evidence-only",
                "queue_id": "loopy-s138-single-evidence-only",
                "account_key": "loopy_club",
                "account_nickname": "loopy Club",
                "title": "6.04 周四｜Jeff Mills 厂牌旗下亚洲顶级 Techno 代表，弑伪神者归来",
                "source_url": "https://mp.weixin.qq.com/s/loopy-s138-single-evidence-only",
                "post_date": "2026-06-01",
                "event_date_text": ["2026-06-04", "2026-06-08"],
                "event_time_text": "22:00",
                "city": ["杭州"],
                "venue": ["loopy"],
                "address": "浙江省杭州市西湖区天目里B1-01",
                "evidence": ["6月4日 Jeff Mills", "来源正文提到 loopy Club 本周活动一览"],
                "confidence": 0.9,
            },
        ]
    )
    return rows


def run_api_canary(report_dir: Path, old_loopy_row: dict[str, Any], *, window_start: str, window_days: int) -> dict[str, Any]:
    mini_api = load_mini_api_module()
    validator = load_validator_module()
    pack_dir = report_dir / "fixture_pack"
    out_dir = report_dir / "api_canary"
    rows = fixture_rows(old_loopy_row)
    write_json(pack_dir / "summary.json", {"schema_version": "loopy_calendar_preview_fixture_s138.v1"})
    write_jsonl(pack_dir / "weekly_activity_recommendation_candidates.jsonl", rows)
    write_jsonl(pack_dir / "weekly_activity_recommendation_review_candidates.jsonl", [])
    exit_code = mini_api.main(
        [
            "--pack-dir",
            str(pack_dir),
            "--out-dir",
            str(out_dir),
            "--window-start",
            window_start,
            "--window-days",
            str(window_days),
            "--source-queue",
            "",
        ]
    )
    manifest = read_json(out_dir / "manifest.json")
    current = read_json(out_dir / "current.json")
    items = current.get("items", []) if isinstance(current.get("items"), list) else []
    by_id = {item.get("id"): item for item in items}
    calendar_items = [item for item in items if item.get("content_type") == "calendar_preview" or item.get("is_calendar_preview")]
    filtered_counts = manifest.get("filtered_counts", {})
    if not isinstance(filtered_counts, dict):
        filtered_counts = {}
    expected_preview_row_count = 2 + (1 if old_loopy_row else 0)
    suppressed_preview_row_count = int(filtered_counts.get("publish_blocked") or 0)
    preview_rows_suppressed_or_classified_ok = (
        len(calendar_items) + suppressed_preview_row_count >= expected_preview_row_count
    )
    false_item = by_id.get("loopy-s138-single-evidence-only", {})
    validator_errors = validator.validate_current_payload(current) if current else ["current.json missing"]
    findings = []
    if exit_code != 0:
        findings.append("api_builder_exit_nonzero")
    if not preview_rows_suppressed_or_classified_ok:
        findings.append("loopy_preview_rows_neither_calendar_preview_nor_publish_blocked")
    false_positive_guard_ok = bool(false_item) and false_item.get("content_type") == "event" and not false_item.get("is_calendar_preview")
    if not false_positive_guard_ok:
        findings.append("evidence_only_single_event_calendar_preview_false_positive")
    if validator_errors:
        findings.append("published_validator_errors")
    return {
        "pack_dir": rel_path(pack_dir),
        "out_dir": rel_path(out_dir),
        "exit_code": exit_code,
        "input_rows": len(rows),
        "item_count": manifest.get("item_count", 0),
        "expected_preview_row_count": expected_preview_row_count,
        "calendar_preview_count": len(calendar_items),
        "calendar_preview_ids": [item.get("id") for item in calendar_items],
        "suppressed_preview_row_count": suppressed_preview_row_count,
        "preview_rows_suppressed_or_classified_ok": preview_rows_suppressed_or_classified_ok,
        "false_positive_guard_ok": false_positive_guard_ok,
        "validator_error_count": len(validator_errors),
        "validator_errors": validator_errors,
        "filtered_counts": filtered_counts,
        "findings": findings,
    }


def summarize_auth(status_path: Path | None, qr_path: Path | None) -> dict[str, Any]:
    status = read_json(status_path) if status_path else {}
    qr = read_json(qr_path) if qr_path else {}
    return {
        "status_report": rel_path(status_path) if status_path else "",
        "qr_report": rel_path(qr_path) if qr_path else "",
        "auth_lifecycle_decision": status.get("auth_lifecycle_decision") or status.get("decision") or "",
        "session_ok": bool(status.get("session_ok")),
        "article_count": status.get("article_count", 0),
        "qr_decision": qr.get("decision", ""),
        "qr_saved": bool(qr.get("qr_saved")),
        "qr_bytes": qr.get("qr_bytes", 0),
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    source = report["source_refresh"]
    canary = report["api_canary"]
    auth = report["exporter_auth"]
    lines = [
        "# Weekly Loopy Calendar Preview Canary S138",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Decision: `{report['decision']}`",
        f"- Today source rows: Loopy `{source['today_loopy_row_count']}`, calendar-like `{source['today_loopy_calendar_like_count']}`",
        f"- Latest local Loopy post date: `{source['latest_loopy_post_date'] or 'none'}`",
        f"- Exporter auth: `{auth['auth_lifecycle_decision'] or 'unknown'}`, QR: `{auth['qr_decision'] or 'not_run'}`",
        f"- API canary: items `{canary['item_count']}`, calendar preview `{canary['calendar_preview_count']}`, suppressed preview `{canary['suppressed_preview_row_count']}`, false-positive guard `{canary['false_positive_guard_ok']}`",
        f"- Finding count: `{summary['finding_count']}`",
        "",
        "## Boundary",
        "",
        "Local canary/report only. No DB1/DB2/DB3 mutation, no release JSON promotion, no CloudRun deploy, no mini-program upload/review, no external crawl, no model/API call, and no raw cookie/token value printing.",
        "",
        "## Next",
        "",
        summary["next_action"],
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_report(
    *,
    report_dir: Path,
    scorecard_path: Path,
    source_paths: list[Path],
    old_loopy_paths: list[Path],
    today_date: str,
    auth_status_path: Path | None,
    auth_qr_path: Path | None,
    window_start: str,
    window_days: int,
) -> dict[str, Any]:
    report_dir.mkdir(parents=True, exist_ok=True)
    source_refresh = build_source_refresh_status(source_paths, today_date=today_date)
    old_loopy = find_old_loopy_weekly_row(old_loopy_paths)
    api_canary = run_api_canary(report_dir, old_loopy, window_start=window_start, window_days=window_days)
    exporter_auth = summarize_auth(auth_status_path, auth_qr_path)
    findings = list(api_canary["findings"])
    source_refresh_blocked = source_refresh["today_loopy_calendar_like_count"] == 0
    if source_refresh_blocked and exporter_auth["auth_lifecycle_decision"] == "exporter_session_invalid":
        decision = "loopy_calendar_preview_canary_ready_source_refresh_blocked_by_exporter_session"
        next_action = (
            "Refresh the Docker exporter login through dashboard/QR, then rerun daily queue refresh and this S138 canary "
            "against the real 2026-06-01 Loopy article."
        )
    elif source_refresh_blocked:
        decision = "loopy_calendar_preview_canary_ready_source_refresh_missing_today_loopy"
        next_action = "Rerun the source refresh lane and inspect why the 2026-06-01 Loopy article is absent."
    else:
        decision = "loopy_calendar_preview_canary_ready_with_today_source_present"
        next_action = "Run the real package rebuild canary for the fetched 2026-06-01 Loopy row before deploy/upload."
    if findings:
        decision = "loopy_calendar_preview_canary_failed"
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_stamp(),
        "decision": decision,
        "summary": {
            "today_loopy_calendar_like_count": source_refresh["today_loopy_calendar_like_count"],
            "api_canary_item_count": api_canary["item_count"],
            "api_canary_calendar_preview_count": api_canary["calendar_preview_count"],
            "api_canary_suppressed_preview_count": api_canary["suppressed_preview_row_count"],
            "preview_rows_suppressed_or_classified_ok": api_canary["preview_rows_suppressed_or_classified_ok"],
            "false_positive_guard_ok": api_canary["false_positive_guard_ok"],
            "finding_count": len(findings),
            "next_action": next_action,
        },
        "source_refresh": source_refresh,
        "exporter_auth": exporter_auth,
        "old_loopy_fixture_found": bool(old_loopy),
        "api_canary": api_canary,
        "findings": findings,
        "mutability": "local_canary_report_only",
        "public_effective": False,
    }
    write_json(report_dir / "loopy_calendar_preview_canary_s138.json", report)
    write_scorecard(scorecard_path, report)
    return report


def parse_paths(values: list[str]) -> list[Path]:
    return [Path(value) for value in values if value]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    parser.add_argument("--source-path", action="append", default=[])
    parser.add_argument("--old-loopy-path", action="append", default=[])
    parser.add_argument("--today-date", default=today_local())
    parser.add_argument("--auth-status", type=Path, default=DEFAULT_REPORT_DIR / "exporter-auth-status.json")
    parser.add_argument("--auth-qr", type=Path, default=DEFAULT_REPORT_DIR / "exporter-auth-qr.json")
    parser.add_argument("--window-start", default="2026-05-18")
    parser.add_argument("--window-days", type=int, default=44)
    args = parser.parse_args(argv)

    report = build_report(
        report_dir=args.report_dir,
        scorecard_path=args.scorecard,
        source_paths=parse_paths(args.source_path) or DEFAULT_SOURCE_PATHS,
        old_loopy_paths=parse_paths(args.old_loopy_path) or DEFAULT_OLD_LOOPY_PATHS,
        today_date=args.today_date,
        auth_status_path=args.auth_status if args.auth_status.exists() else None,
        auth_qr_path=args.auth_qr if args.auth_qr.exists() else None,
        window_start=args.window_start,
        window_days=max(1, args.window_days),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["summary"]["finding_count"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
