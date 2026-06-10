#!/usr/bin/env python3
"""Build a report-only review packet from the Atlas DJ repair queue.

The priority queue is evidence, not a write input. This script turns it into
bounded work orders for the next graph-completion lanes and explicitly records
whether any item is safe enough to trigger a serving rebuild. It performs no
network calls, LLM calls, source SQLite writes, Neo4j writes, Qdrant writes, or
production writes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUEUE = (
    REPO_ROOT
    / "reports"
    / "atlas_dj_repair_priority_queue_activity_current_20260525_1526"
    / "repair_priority_queue.jsonl"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_dj_repair_queue_review_packet_20260525"

QUEUE_TO_DECISION = {
    "dj_entity_no_event_article": (
        "route_source_context_reextract",
        "source_context_reextract_work_order.jsonl",
        "Article has DJ-like entities but no event; re-extract source context before graph promotion.",
    ),
    "image_or_poster_no_event_article": (
        "route_ocr_markdown_repair",
        "ocr_markdown_repair_work_order.jsonl",
        "Poster/image-heavy article has no event; OCR/Markdown repair is required before graph promotion.",
    ),
    "participant_empty_music_event": (
        "route_participant_repair_review",
        "participant_repair_review_work_order.jsonl",
        "Music-looking event has empty participants; review same-article entities before promotion.",
    ),
    "missing_place_with_participants": (
        "route_venue_source_account_review",
        "venue_repair_review_work_order.jsonl",
        "Event has participants but no place; review source-account or same-article venue evidence.",
    ),
    "time_iso_normalization_candidate": (
        "route_time_normalization_sidecar",
        "time_normalization_work_order.jsonl",
        "Event has raw time text but no normalized ISO time; run deterministic time sidecar first.",
    ),
    "noise_quarantine_candidate": (
        "reject_or_quarantine_noise",
        "accepted_noise_quarantine.jsonl",
        "Non-music/product/menu/drink signal should be kept out of the DJ graph.",
    ),
}

VENUE_HINTS = [
    "oil",
    "dada",
    "all",
    "tag",
    "zhaodai",
    "招待",
    "heim",
    "hum",
    "44kw",
    "dong",
    "bo live",
    "elevator",
    "window",
    "vervo",
    "axis",
    "jar",
    "foundation",
    "system",
    "live",
    "club",
    "bar",
    "俱乐部",
    "院吧",
]

URL_OR_ARCHIVE_RE = re.compile(r"https?://|mp\.weixin|raw\.html|archive_", re.IGNORECASE)
SECRET_WORD_RE = re.compile(r"\b(openid|fakeid|unionid|secret|token|cookie|password)\b", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def lower_blob(*values: Any) -> str:
    return " ".join(text(value).casefold() for value in values if text(value))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL row: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(payload)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    tmp.replace(path)


def dedupe_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        text(row.get("queue")),
        text(row.get("article_uid")),
        text(row.get("event_id")),
        text(row.get("entity_id")),
        text(row.get("title")),
        text(row.get("name")),
        text(row.get("place")),
        text(row.get("time_text")),
        text(row.get("source_account")),
    )


def item_id(row: dict[str, Any]) -> str:
    normalized = json.dumps(dedupe_key(row), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:16]


def has_venue_source_hint(row: dict[str, Any]) -> bool:
    blob = lower_blob(row.get("source_account"), row.get("title"), row.get("place"))
    return any(hint in blob for hint in VENUE_HINTS)


def classify(row: dict[str, Any]) -> tuple[str, str, str]:
    queue = text(row.get("queue"))
    decision, output_file, reason = QUEUE_TO_DECISION.get(
        queue,
        (
            "route_manual_review",
            "manual_review_work_order.jsonl",
            "Unknown queue; keep in manual review and do not promote to graph.",
        ),
    )
    if queue == "missing_place_with_participants" and not has_venue_source_hint(row):
        return (
            "route_venue_geocode_review",
            output_file,
            "Event has participants but no place; source account lacks venue hint, so geocode/manual evidence is required.",
        )
    return decision, output_file, reason


def public_leak_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        counts["url_or_archive_hits"] += len(URL_OR_ARCHIVE_RE.findall(payload))
        counts["secret_word_hits"] += len(SECRET_WORD_RE.findall(payload))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(payload))
    return dict(counts)


def build_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas DJ Repair Queue Review Packet",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Source queue: `{summary['source_queue']}`",
        f"- Input rows: {summary['counts']['input_rows']}",
        f"- Unique work items: {summary['counts']['unique_work_items']}",
        f"- Duplicate rows removed: {summary['counts']['duplicate_rows_removed']}",
        f"- Direct serving rebuild triggered: {summary['decision']['serving_rebuild_triggered']}",
        f"- Decision: {summary['decision']['status']}",
        f"- Reason: {summary['decision']['reason']}",
        "",
        "## Decision Counts",
    ]
    for decision, count in sorted(summary["decision_counts"].items()):
        lines.append(f"- {decision}: {count}")
    lines.extend(["", "## Queue Counts"])
    for queue, count in sorted(summary["queue_counts_unique"].items()):
        dup_count = summary["duplicates_by_queue"].get(queue, 0)
        lines.append(f"- {queue}: {count} unique, {dup_count} duplicate removed")
    lines.extend(["", "## Outputs"])
    for name, path in sorted(summary["outputs"].items()):
        lines.append(f"- {name}: `{path}`")
    lines.extend(["", "## Safety"])
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Public Leak Scan"])
    for key, value in sorted(summary["public_leak_scan"].items()):
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def build_review_packet(queue_path: Path, out_dir: Path, limit: int | None = None) -> dict[str, Any]:
    rows = read_jsonl(queue_path)
    if limit is not None:
        rows = rows[:limit]

    input_counts = Counter(text(row.get("queue")) for row in rows)
    seen: set[tuple[str, ...]] = set()
    duplicates_by_queue = Counter()
    work_items: list[dict[str, Any]] = []
    routed: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for input_index, row in enumerate(rows, start=1):
        key = dedupe_key(row)
        queue = text(row.get("queue"))
        if key in seen:
            duplicates_by_queue[queue] += 1
            continue
        seen.add(key)
        decision, output_file, decision_reason = classify(row)
        work_item = {
            "schema_version": "atlas_dj_repair_queue_review_packet.work_order.v1",
            "work_item_id": item_id(row),
            "input_index": input_index,
            "queue": queue,
            "decision": decision,
            "decision_reason": decision_reason,
            "serving_rebuild_eligible": False,
            "serving_rebuild_blocker": "Queue row requires repair/review sidecar before it can become a graph fact.",
            "article_uid": text(row.get("article_uid")),
            "event_id": text(row.get("event_id")),
            "entity_id": text(row.get("entity_id")),
            "source_account": text(row.get("source_account")),
            "title": text(row.get("title")),
            "name": text(row.get("name")),
            "place": text(row.get("place")),
            "time_text": text(row.get("time_text")),
            "priority_score": row.get("priority_score"),
            "recommended_action": text(row.get("recommended_action")),
            "evidence": row.get("evidence") if isinstance(row.get("evidence"), dict) else row,
            "write_status": "report_only",
        }
        work_items.append(work_item)
        routed[output_file].append(work_item)

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "review_work_order_jsonl": str(out_dir / "review_work_order.jsonl"),
        "summary_json": str(out_dir / "summary.json"),
        "summary_md": str(out_dir / "summary.md"),
    }
    write_jsonl(out_dir / "review_work_order.jsonl", work_items)
    for output_file, output_rows in sorted(routed.items()):
        path = out_dir / output_file
        outputs[output_file.replace(".jsonl", "_jsonl")] = str(path)
        write_jsonl(path, output_rows)

    leak_counts = public_leak_counts(work_items)
    decision_counts = Counter(item["decision"] for item in work_items)
    queue_counts_unique = Counter(item["queue"] for item in work_items)

    summary = {
        "schema_version": "atlas_dj_repair_queue_review_packet.summary.v1",
        "generated_at": now_iso(),
        "source_queue": str(queue_path),
        "out_dir": str(out_dir),
        "counts": {
            "input_rows": len(rows),
            "unique_work_items": len(work_items),
            "duplicate_rows_removed": sum(duplicates_by_queue.values()),
            "serving_rebuild_eligible_items": 0,
        },
        "input_queue_counts": dict(sorted(input_counts.items())),
        "queue_counts_unique": dict(sorted(queue_counts_unique.items())),
        "duplicates_by_queue": dict(sorted(duplicates_by_queue.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "top_sources_by_decision": top_sources_by_decision(work_items),
        "decision": {
            "status": "atlas_dj_repair_queue_review_packet_materialized_no_serving_rebuild",
            "serving_rebuild_triggered": False,
            "reason": "All deduped queue rows are repair/review work orders, not direct graph facts; serving rebuild is intentionally not triggered.",
        },
        "outputs": outputs,
        "public_leak_scan": leak_counts,
        "safety": {
            "llm_call_executed": False,
            "network_call_executed": False,
            "neo4j_write_executed": False,
            "paid_api_call_executed": False,
            "production_write_executed": False,
            "qdrant_write_executed": False,
            "report_only": True,
            "serving_sqlite_rebuild_executed": False,
            "source_sqlite_write_executed": False,
        },
    }
    write_json(out_dir / "summary.json", summary)
    (out_dir / "summary.md").write_text(build_summary_md(summary), encoding="utf-8")
    return {"summary": summary, "work_items": work_items, "routed": routed}


def top_sources_by_decision(work_items: list[dict[str, Any]], limit: int = 10) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, Counter[str]] = defaultdict(Counter)
    for item in work_items:
        grouped[text(item.get("decision"))][text(item.get("source_account")) or "(blank)"] += 1
    return {
        decision: [
            {"source_account": source, "count": count}
            for source, count in counter.most_common(limit)
        ]
        for decision, counter in sorted(grouped.items())
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_review_packet(args.queue, args.out_dir, limit=args.limit)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
