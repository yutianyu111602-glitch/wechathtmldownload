#!/usr/bin/env python3
"""Trace why Stage7 consumer events cannot satisfy weekly publish dates.

This is an evidence report, not a repair. It compares:
* Stage7 stable extract events.
* Stage7 consumer release-pack events.
* The older weekly recommendation pack that produced the current mini-program API.
* The current packaged weekly API release.

No writes outside reports, no DB access, no paid API, no D: root scan.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_STABLE_ARTICLES = Path(
    "reports/fullmap_47k_ready_text_authok_20260513_174006/stable_extract_v1/stable_articles.jsonl"
)
DEFAULT_CONSUMER_EVENTS = Path("reports/consumer_release_pack_full_unknown_time_20260514/events.jsonl")
DEFAULT_WEEKLY_CANDIDATES = Path(
    "D:/downstream_results/stage7_rewrite/longrun/"
    "WEEKLY_ACTIVITY_RECOMMENDATION_PACK_ENTITY_20260514/weekly_activity_recommendation_candidates.jsonl"
)
DEFAULT_WEEKLY_CURRENT = Path(
    "../../services/weekly_activity_cloudrun/data/current_release/current.json"
)
DEFAULT_OUT_DIR = Path("reports/weekly_time_iso_gap_trace_20260515")
ISO_DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
YEAR_IN_TEXT_RE = re.compile(r"\b20\d{2}[./-]?\d{0,2}[./-]?\d{0,2}\b")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_unbounded_d_root(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    banned = {"d:/", "d:/ddownload", "d:/aidata", "/mnt/d", "/mnt/d/ddownload", "/mnt/d/aidata"}
    if raw in banned:
        raise ValueError(f"{label} must not be an unbounded D: root: {path}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def iter_jsonl(path: Path, limit: int):
    with path.open("r", encoding="utf-8") as handle:
        count = 0
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
                yield row
                count += 1
            if limit > 0 and count >= limit:
                break


def list_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    raw = str(value or "").strip()
    return [raw] if raw else []


def count_stage7_stable_events(path: Path, limit: int) -> dict[str, Any]:
    reject_unbounded_d_root(path, "stable_articles")
    stats = {
        "articles_seen": 0,
        "events_seen": 0,
        "events_with_time_text": 0,
        "events_with_time_iso": 0,
        "events_with_date_iso": 0,
        "events_with_year_in_time_text": 0,
        "event_examples": [],
    }
    for article in iter_jsonl(path, limit):
        stats["articles_seen"] += 1
        for event in article.get("events") if isinstance(article.get("events"), list) else []:
            if not isinstance(event, dict):
                continue
            stats["events_seen"] += 1
            time_text = str(event.get("time") or event.get("time_text") or "").strip()
            time_iso = str(event.get("time_iso") or "").strip()
            date_iso = str(event.get("date_iso") or "").strip()
            stats["events_with_time_text"] += int(bool(time_text))
            stats["events_with_time_iso"] += int(bool(time_iso))
            stats["events_with_date_iso"] += int(bool(date_iso))
            stats["events_with_year_in_time_text"] += int(bool(YEAR_IN_TEXT_RE.search(time_text)))
            if len(stats["event_examples"]) < 5:
                stats["event_examples"].append(
                    {
                        "article_uid": article.get("article_uid"),
                        "name": event.get("name") or event.get("title"),
                        "time": time_text,
                        "time_iso": time_iso,
                        "date_iso": date_iso,
                    }
                )
    return stats


def count_consumer_events(path: Path, limit: int) -> dict[str, Any]:
    reject_unbounded_d_root(path, "consumer_events")
    stats = {
        "events_seen": 0,
        "events_with_time_text": 0,
        "events_with_time_iso": 0,
        "events_with_iso_date": 0,
        "events_with_year_in_time_text": 0,
        "event_examples": [],
    }
    for row in iter_jsonl(path, limit):
        stats["events_seen"] += 1
        time_text = str(row.get("time_text") or "").strip()
        time_iso = str(row.get("time_iso") or "").strip()
        stats["events_with_time_text"] += int(bool(time_text))
        stats["events_with_time_iso"] += int(bool(time_iso))
        stats["events_with_iso_date"] += int(bool(ISO_DATE_RE.match(time_iso)))
        stats["events_with_year_in_time_text"] += int(bool(YEAR_IN_TEXT_RE.search(time_text)))
        if len(stats["event_examples"]) < 5:
            stats["event_examples"].append(
                {
                    "source_article_uid": row.get("source_article_uid"),
                    "name": row.get("name"),
                    "time_text": time_text,
                    "time_iso": time_iso,
                    "place": row.get("place"),
                }
            )
    return stats


def count_weekly_candidates(path: Path, limit: int) -> dict[str, Any]:
    reject_unbounded_d_root(path, "weekly_candidates")
    stats = {
        "rows_seen": 0,
        "rows_with_event_date_text": 0,
        "rows_with_iso_event_date_text": 0,
        "rows_with_source_url": 0,
        "rows_with_address": 0,
        "rows_with_event_time_text": 0,
        "examples": [],
    }
    for row in iter_jsonl(path, limit):
        stats["rows_seen"] += 1
        dates = list_strings(row.get("event_date_text")) or list_strings(row.get("date_text"))
        stats["rows_with_event_date_text"] += int(bool(dates))
        stats["rows_with_iso_event_date_text"] += int(any(ISO_DATE_RE.match(item) for item in dates))
        stats["rows_with_source_url"] += int(bool(str(row.get("source_url") or "").strip()))
        stats["rows_with_address"] += int(bool(str(row.get("address") or "").strip()))
        stats["rows_with_event_time_text"] += int(bool(str(row.get("event_time_text") or "").strip()))
        if len(stats["examples"]) < 5:
            stats["examples"].append(
                {
                    "queue_id": row.get("queue_id"),
                    "title": row.get("title"),
                    "event_date_text": dates,
                    "event_time_text": row.get("event_time_text"),
                    "address": row.get("address"),
                    "source_url_present": bool(str(row.get("source_url") or "").strip()),
                }
            )
    return stats


def count_weekly_current(path: Path) -> dict[str, Any]:
    reject_unbounded_d_root(path, "weekly_current")
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else []
    rows = [item for item in items if isinstance(item, dict)]
    stats = {
        "items_seen": len(rows),
        "items_with_event_date_start": 0,
        "items_with_iso_event_date_start": 0,
        "items_with_address_full": 0,
        "items_with_source_action": 0,
        "schema_versions": sorted({str(item.get("schema_version") or "") for item in rows}),
        "examples": [],
    }
    for item in rows:
        event_date = str(item.get("event_date_start") or item.get("event_date_iso_guess") or "").strip()
        stats["items_with_event_date_start"] += int(bool(event_date))
        stats["items_with_iso_event_date_start"] += int(bool(ISO_DATE_RE.match(event_date)))
        stats["items_with_address_full"] += int(bool(str(item.get("address_full") or "").strip()))
        stats["items_with_source_action"] += int(isinstance(item.get("source_action"), dict))
        if len(stats["examples"]) < 5:
            stats["examples"].append(
                {
                    "id": item.get("id") or item.get("event_id"),
                    "title": item.get("title_display") or item.get("title"),
                    "event_date_start": event_date,
                    "address_full": item.get("address_full"),
                    "source_action_available": (item.get("source_action") or {}).get("available")
                    if isinstance(item.get("source_action"), dict)
                    else None,
                }
            )
    return stats


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / max(denominator, 1), 4)


def add_rates(stats: dict[str, Any], denominator_key: str) -> dict[str, Any]:
    denominator = int(stats.get(denominator_key) or 0)
    out = dict(stats)
    for key, value in list(stats.items()):
        if key == denominator_key or not key.startswith(("events_with_", "rows_with_", "items_with_")):
            continue
        if isinstance(value, int):
            out[f"{key}_rate"] = ratio(value, denominator)
    return out


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    stable = add_rates(count_stage7_stable_events(args.stable_articles, args.limit), "events_seen")
    consumer = add_rates(count_consumer_events(args.consumer_events, args.limit), "events_seen")
    weekly_candidates = add_rates(count_weekly_candidates(args.weekly_candidates, args.limit), "rows_seen")
    weekly_current = add_rates(count_weekly_current(args.weekly_current), "items_seen")
    root_cause = []
    if stable["events_seen"] and stable["events_with_time_iso"] == 0:
        root_cause.append("stage7_stable_events_have_no_time_iso")
    if consumer["events_seen"] and consumer["events_with_iso_date"] == 0:
        root_cause.append("consumer_release_events_have_no_iso_event_date")
    if weekly_candidates["rows_with_iso_event_date_text"] > 0 and weekly_current["items_with_iso_event_date_start"] > 0:
        root_cause.append("weekly_publish_dates_came_from_separate_weekly_candidate_pipeline")
    decision = "time_iso_gap_traced_to_pipeline_contract_mismatch" if root_cause else "time_iso_gap_requires_more_evidence"
    return {
        "schema_version": "stage7_weekly_time_iso_gap_trace.v1",
        "generated_at": now_iso(),
        "ok": bool(root_cause),
        "decision": decision,
        "limit": args.limit,
        "inputs": {
            "stable_articles": str(args.stable_articles),
            "consumer_events": str(args.consumer_events),
            "weekly_candidates": str(args.weekly_candidates),
            "weekly_current": str(args.weekly_current),
        },
        "stage7_stable": stable,
        "consumer_release_pack": consumer,
        "weekly_candidate_pack": weekly_candidates,
        "weekly_current_release": weekly_current,
        "root_cause": root_cause,
        "conclusion": (
            "Stage7 consumer release-pack preserves event.time_iso from stable extracts, "
            "but the stable extract does not populate that field. The current mini-program "
            "weekly release was produced by the separate weekly recommendation pipeline, "
            "which has event_date_text/source_url/address fields."
        ),
        "writes": "reports_only",
        "safety": [
            "no production publish",
            "no production SQLite write",
            "no Qdrant or Neo4j write",
            "no paid API call",
            "no D: root scan",
        ],
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Weekly Time ISO Gap Trace",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- limit: `{report['limit']}`",
        f"- root_cause: `{json.dumps(report['root_cause'], ensure_ascii=False)}`",
        "",
        "## Counts",
        "",
        f"- stage7_stable events_seen: `{report['stage7_stable']['events_seen']}`",
        f"- stage7_stable events_with_time_iso: `{report['stage7_stable']['events_with_time_iso']}`",
        f"- consumer events_seen: `{report['consumer_release_pack']['events_seen']}`",
        f"- consumer events_with_iso_date: `{report['consumer_release_pack']['events_with_iso_date']}`",
        f"- weekly candidate rows_seen: `{report['weekly_candidate_pack']['rows_seen']}`",
        f"- weekly candidate rows_with_iso_event_date_text: `{report['weekly_candidate_pack']['rows_with_iso_event_date_text']}`",
        f"- weekly current items_seen: `{report['weekly_current_release']['items_seen']}`",
        f"- weekly current items_with_iso_event_date_start: `{report['weekly_current_release']['items_with_iso_event_date_start']}`",
        "",
        "## Conclusion",
        "",
        report["conclusion"],
        "",
        "## Safety",
        "",
        "- Reports only.",
        "- No production publish.",
        "- No production SQLite write.",
        "- No Qdrant or Neo4j write.",
        "- No paid API call.",
        "- No D: root scan.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report = build_report(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "weekly_time_iso_gap_trace.json", report)
    write_markdown(args.out_dir / "weekly_time_iso_gap_trace.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "root_cause": report["root_cause"],
                "report": str(args.out_dir / "weekly_time_iso_gap_trace.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-articles", type=Path, default=DEFAULT_STABLE_ARTICLES)
    parser.add_argument("--consumer-events", type=Path, default=DEFAULT_CONSUMER_EVENTS)
    parser.add_argument("--weekly-candidates", type=Path, default=DEFAULT_WEEKLY_CANDIDATES)
    parser.add_argument("--weekly-current", type=Path, default=DEFAULT_WEEKLY_CURRENT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=0, help="0 means full scan of JSONL inputs")
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
