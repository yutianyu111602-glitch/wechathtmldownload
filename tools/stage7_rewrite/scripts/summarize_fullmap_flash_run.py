#!/usr/bin/env python3
"""Summarize a Stage7 Flash run directory.

Reads only report artifacts under one run directory. It does not call APIs,
does not scan source archives, and does not write DB/vector/graph state.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line), None
            except Exception as exc:
                yield None, {"path": str(path), "line_no": line_no, "error": str(exc)}


def mean(values: list[int | float]) -> float | None:
    return round(statistics.mean(values), 3) if values else None


def pct(part: int, total: int) -> float | None:
    return round(part * 100 / total, 3) if total else None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def compact_history_record(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at": summary.get("generated_at"),
        "rows": summary.get("rows"),
        "chunks": summary.get("chunks"),
        "estimated_cny_total": summary.get("estimated_cny_total"),
        "progress_pct": summary.get("progress_pct"),
        "selected_total": summary.get("selected_total"),
        "pending_total": summary.get("pending_total"),
        "api_bad_chunks": summary.get("api_bad_chunks"),
        "parse_bad_chunks": summary.get("parse_bad_chunks"),
        "schema_bad_chunks": summary.get("schema_bad_chunks"),
        "entity0_pct": summary.get("entity0_pct"),
        "event0_pct": summary.get("event0_pct"),
    }


def load_history(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
    return records


def add_progress_metrics(summary: dict[str, Any], previous_records: list[dict[str, Any]]) -> None:
    selected_total = 0
    pending_total = 0
    failed_total = 0
    for shard in summary["shards"]:
        if isinstance(shard.get("selected"), int):
            selected_total += int(shard["selected"])
        if isinstance(shard.get("pending"), int):
            pending_total += int(shard["pending"])
        if isinstance(shard.get("failed"), int):
            failed_total += int(shard["failed"])

    summary["selected_total"] = selected_total or None
    summary["pending_total"] = pending_total if selected_total else None
    summary["failed_total"] = failed_total
    summary["progress_pct"] = pct(int(summary["rows"]), selected_total) if selected_total else None

    current_at = parse_iso(str(summary.get("generated_at")))
    current_rows = int(summary.get("rows") or 0)
    candidates: list[tuple[datetime, int]] = []
    seen: set[tuple[str, int]] = set()
    for record in previous_records:
        at = parse_iso(str(record.get("generated_at") or ""))
        rows = record.get("rows")
        if at is None or not isinstance(rows, int):
            continue
        key = (at.isoformat(), rows)
        if key in seen:
            continue
        seen.add(key)
        if current_at and at < current_at and rows <= current_rows:
            candidates.append((at, rows))

    rows_per_hour = None
    eta_hours = None
    if current_at and candidates:
        # Prefer a point at least 20 minutes old. If unavailable, use the oldest
        # available point so early runs still expose a rough trend.
        candidates.sort(key=lambda item: item[0])
        older = [item for item in candidates if (current_at - item[0]).total_seconds() >= 20 * 60]
        base_at, base_rows = older[0] if older else candidates[0]
        elapsed_hours = (current_at - base_at).total_seconds() / 3600
        delta_rows = current_rows - base_rows
        if elapsed_hours > 0 and delta_rows > 0:
            rows_per_hour = round(delta_rows / elapsed_hours, 3)
            if pending_total and rows_per_hour > 0:
                eta_hours = round(pending_total / rows_per_hour, 3)

    summary["rows_per_hour_since_history"] = rows_per_hour
    summary["eta_hours_since_history"] = eta_hours


def summarize(run_dir: Path) -> dict[str, Any]:
    shard_dirs = sorted(run_dir.glob("flash_manifest_shard_*"))
    rows: list[dict[str, Any]] = []
    bad_json_rows: list[dict[str, Any]] = []
    shard_summaries: list[dict[str, Any]] = []

    for shard_dir in shard_dirs:
        running_summary = read_json(shard_dir / "flash_running_summary.json") or {}
        final_path = shard_dir / "flash_rows.jsonl"
        partial_path = shard_dir / "flash_rows.partial.jsonl"
        row_path = final_path if final_path.exists() else partial_path
        shard_rows = 0
        if row_path.exists():
            for row, error in iter_jsonl(row_path):
                if error:
                    bad_json_rows.append(error)
                    continue
                if row is not None:
                    rows.append(row)
                    shard_rows += 1
        shard_summaries.append(
            {
                "name": shard_dir.name,
                "status": running_summary.get("status", "unknown"),
                "rows": shard_rows,
                "selected": running_summary.get("selected_samples"),
                "processed": running_summary.get("processed_samples", running_summary.get("processed")),
                "pending": running_summary.get("pending_samples"),
                "failed": running_summary.get("failed_samples", running_summary.get("failed", 0)),
                "estimated_cny": running_summary.get("estimated_cny"),
                "source_file": row_path.name if row_path.exists() else None,
            }
        )

    chunks = 0
    api_bad = 0
    parse_bad = 0
    schema_bad = 0
    entity0 = 0
    event0 = 0
    zero_both = 0
    input_chars: list[int] = []
    entity_counts: list[int] = []
    event_counts: list[int] = []
    relation_counts: list[int] = []
    quality_grade_counts: Counter[str] = Counter()
    source_account_counts: Counter[str] = Counter()
    schema_error_kinds: Counter[str] = Counter()

    for row in rows:
        totals = row.get("totals") or {}
        entity_count = int(totals.get("entities") or 0)
        event_count = int(totals.get("events") or 0)
        relation_count = int(totals.get("relations") or 0)
        entity_counts.append(entity_count)
        event_counts.append(event_count)
        relation_counts.append(relation_count)
        if entity_count == 0:
            entity0 += 1
        if event_count == 0:
            event0 += 1
        if entity_count == 0 and event_count == 0:
            zero_both += 1
        if isinstance(row.get("input_chars"), int):
            input_chars.append(row["input_chars"])
        quality_grade_counts[str(row.get("quality_grade") or "<missing>")] += 1
        source_account_counts[str(row.get("source_account") or "<missing>")] += 1

        for chunk in row.get("chunks") or []:
            chunks += 1
            if chunk.get("api_ok") is False:
                api_bad += 1
            if chunk.get("parse_ok") is False:
                parse_bad += 1
            if chunk.get("schema_ok") is False:
                schema_bad += 1
            for error in chunk.get("validation_errors") or []:
                schema_error_kinds[str(error).split(":", 1)[0]] += 1

    total_cost = 0.0
    cost_known = False
    for item in shard_summaries:
        value = item.get("estimated_cny")
        if isinstance(value, (int, float)):
            total_cost += float(value)
            cost_known = True

    summary = {
        "schema_version": "fullmap_flash_run_summary.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_dir": str(run_dir),
        "shards": shard_summaries,
        "shard_status_counts": dict(Counter(str(s.get("status")) for s in shard_summaries)),
        "rows": len(rows),
        "bad_json_rows": len(bad_json_rows),
        "bad_json_examples": bad_json_rows[:10],
        "chunks": chunks,
        "api_bad_chunks": api_bad,
        "parse_bad_chunks": parse_bad,
        "schema_bad_chunks": schema_bad,
        "api_bad_chunk_pct": pct(api_bad, chunks),
        "parse_bad_chunk_pct": pct(parse_bad, chunks),
        "schema_bad_chunk_pct": pct(schema_bad, chunks),
        "entity0_pct": pct(entity0, len(rows)),
        "event0_pct": pct(event0, len(rows)),
        "zero_both_pct": pct(zero_both, len(rows)),
        "avg_entities_per_article": mean(entity_counts),
        "avg_events_per_article": mean(event_counts),
        "avg_relations_per_article": mean(relation_counts),
        "avg_input_chars": mean(input_chars),
        "quality_grade_counts": quality_grade_counts.most_common(),
        "top_schema_error_kinds": schema_error_kinds.most_common(10),
        "top_source_accounts": source_account_counts.most_common(20),
        "estimated_cny_total": round(total_cost, 4) if cost_known else None,
        "writes": "report summary only; no API/vector/DB/graph writes",
    }
    add_progress_metrics(summary, [])
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Fullmap Flash Run Summary",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- run_dir: `{summary['run_dir']}`",
        f"- rows: `{summary['rows']}`",
        f"- chunks: `{summary['chunks']}`",
        f"- api_bad_chunks: `{summary['api_bad_chunks']}`",
        f"- parse_bad_chunks: `{summary['parse_bad_chunks']}`",
        f"- schema_bad_chunks: `{summary['schema_bad_chunks']}`",
        f"- entity0_pct: `{summary['entity0_pct']}`",
        f"- event0_pct: `{summary['event0_pct']}`",
        f"- zero_both_pct: `{summary['zero_both_pct']}`",
        f"- avg_entities_per_article: `{summary['avg_entities_per_article']}`",
        f"- avg_events_per_article: `{summary['avg_events_per_article']}`",
        f"- avg_relations_per_article: `{summary['avg_relations_per_article']}`",
        f"- avg_input_chars: `{summary['avg_input_chars']}`",
        f"- estimated_cny_total: `{summary['estimated_cny_total']}`",
        f"- selected_total: `{summary.get('selected_total')}`",
        f"- pending_total: `{summary.get('pending_total')}`",
        f"- progress_pct: `{summary.get('progress_pct')}`",
        f"- rows_per_hour_since_history: `{summary.get('rows_per_hour_since_history')}`",
        f"- eta_hours_since_history: `{summary.get('eta_hours_since_history')}`",
        "",
        "## Shards",
        "",
        "| shard | status | rows | selected | processed | pending | failed | cny | source |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for shard in summary["shards"]:
        lines.append(
            f"| `{shard['name']}` | `{shard['status']}` | {shard['rows']} | "
            f"{shard.get('selected')} | {shard.get('processed')} | {shard.get('pending')} | "
            f"{shard.get('failed')} | {shard.get('estimated_cny')} | "
            f"`{shard.get('source_file')}` |"
        )
    lines.extend(["", "## Top Schema Error Kinds", ""])
    for kind, count in summary["top_schema_error_kinds"]:
        lines.append(f"- `{kind}`: {count}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out-json", default=None)
    parser.add_argument("--out-md", default=None)
    parser.add_argument("--history-jsonl", default=None)
    parser.add_argument("--no-history", action="store_true")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    if not run_dir.exists():
        raise SystemExit(f"run dir not found: {run_dir}")
    summary = summarize(run_dir)
    out_json = Path(args.out_json) if args.out_json else run_dir / "run_quality_summary.json"
    out_md = Path(args.out_md) if args.out_md else run_dir / "run_quality_summary.md"
    history_path = Path(args.history_jsonl) if args.history_jsonl else run_dir / "run_quality_summary.history.jsonl"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)

    previous_records: list[dict[str, Any]] = []
    if not args.no_history:
        previous_records.extend(load_history(history_path))
        old_summary = read_json(out_json)
        if old_summary:
            previous_records.append(compact_history_record(old_summary))
        add_progress_metrics(summary, previous_records)

    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(out_md, summary)
    if not args.no_history:
        with history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(compact_history_record(summary), ensure_ascii=False) + "\n")
    print(json.dumps({"ok": True, "out_json": str(out_json), "out_md": str(out_md), **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
