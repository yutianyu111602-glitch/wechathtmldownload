"""Build a report-only trending index from Stage7 consumer event cards."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable


DEFAULT_EVENTS_JSONL = Path("reports/consumer_release_pack_full_unknown_time_20260514/events.jsonl")
DEFAULT_OUT_DIR = Path("reports/trending_index_20260515")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def norm_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def iter_jsonl(path: Path, limit: int = 0) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle, start=1):
            if limit and idx > limit:
                break
            line = line.strip()
            if line:
                yield json.loads(line)


def parse_iso_date(value: Any) -> date | None:
    text = norm_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def decay_factor(event_date: date | None, as_of: date, half_life_days: float) -> tuple[float, str, int | None]:
    if event_date is None:
        return 0.15, "missing_time_penalty", None
    days = max((as_of - event_date).days, 0)
    factor = math.exp(-math.log(2) * days / max(half_life_days, 1.0))
    return factor, "iso_time_decay", days


def aggregate_events(rows: Iterable[dict[str, Any]], as_of: date, half_life_days: float) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        name = norm_text(row.get("name"))
        if not name:
            continue
        place = norm_text(row.get("place"))
        key = (name.casefold(), place.casefold())
        item = buckets.setdefault(
            key,
            {
                "name": name,
                "place": place,
                "event_count": 0,
                "source_articles": set(),
                "participants": set(),
                "time_texts": set(),
                "iso_dates": [],
                "confidence_sum": 0.0,
                "decay_status_counts": defaultdict(int),
            },
        )
        item["event_count"] += 1
        article_uid = norm_text(row.get("source_article_uid"))
        if article_uid:
            item["source_articles"].add(article_uid)
        for participant in row.get("participants") or []:
            value = norm_text(participant)
            if value:
                item["participants"].add(value)
        time_text = norm_text(row.get("time_iso") or row.get("time_text"))
        if time_text:
            item["time_texts"].add(time_text)
        iso_date = parse_iso_date(row.get("time_iso"))
        if iso_date:
            item["iso_dates"].append(iso_date)
        try:
            item["confidence_sum"] += float(row.get("confidence") or 0.0)
        except (TypeError, ValueError):
            pass
    results = []
    for item in buckets.values():
        latest = max(item["iso_dates"]) if item["iso_dates"] else None
        factor, status, days = decay_factor(latest, as_of, half_life_days)
        item["decay_status_counts"][status] += 1
        avg_conf = item["confidence_sum"] / max(item["event_count"], 1)
        base_score = item["event_count"] + 0.15 * len(item["participants"]) + 0.1 * len(item["source_articles"]) + avg_conf
        score = base_score * factor
        results.append(
            {
                "name": item["name"],
                "place": item["place"],
                "trending_score": round(score, 6),
                "base_score": round(base_score, 6),
                "decay_factor": round(factor, 6),
                "decay_status": status,
                "days_since_latest_iso": days,
                "event_count": item["event_count"],
                "source_article_count": len(item["source_articles"]),
                "participant_count": len(item["participants"]),
                "participants": sorted(item["participants"])[:12],
                "time_texts": sorted(item["time_texts"])[:8],
                "latest_time_iso": latest.isoformat() if latest else "",
            }
        )
    results.sort(key=lambda row: (-row["trending_score"], -row["event_count"], row["name"]))
    return results


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_markdown(path: Path, summary: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Trending Index",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- as_of: `{summary['as_of']}`",
        f"- event_group_count: `{summary['event_group_count']}`",
        f"- iso_time_groups: `{summary['iso_time_groups']}`",
        f"- missing_time_groups: `{summary['missing_time_groups']}`",
        "",
        "| Event | Place | Score | Decay | Count |",
        "|---|---|---:|---|---:|",
    ]
    for row in rows[:20]:
        lines.append(f"| `{row['name']}` | `{row['place']}` | {row['trending_score']} | `{row['decay_status']}` | {row['event_count']} |")
    lines.extend(["", "## Safety", "", "- Report-only. No mem0, Neo4j, Qdrant, SQLite, cloud, or production writes."])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    rows = aggregate_events(iter_jsonl(args.events_jsonl, limit=args.limit), as_of, args.half_life_days)
    summary = {
        "schema_version": "stage7_trending_index.v1",
        "generated_at": now_iso(),
        "as_of": as_of.isoformat(),
        "half_life_days": args.half_life_days,
        "event_group_count": len(rows),
        "iso_time_groups": sum(1 for row in rows if row["decay_status"] == "iso_time_decay"),
        "missing_time_groups": sum(1 for row in rows if row["decay_status"] == "missing_time_penalty"),
        "top_score": rows[0]["trending_score"] if rows else 0,
        "safety": {
            "report_only": True,
            "mem0_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
        },
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(args.out_dir / "trending_index.jsonl", rows[: args.top_n])
    write_json(args.out_dir / "trending_index_summary.json", summary)
    write_markdown(args.out_dir / "trending_index_summary.md", summary, rows)
    print(json.dumps({"ok": True, "event_group_count": len(rows), "summary": str(args.out_dir / "trending_index_summary.json")}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events-jsonl", type=Path, default=DEFAULT_EVENTS_JSONL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--top-n", type=int, default=500)
    parser.add_argument("--as-of", default="2026-05-15")
    parser.add_argument("--half-life-days", type=float, default=14.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
