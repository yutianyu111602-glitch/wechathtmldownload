"""Summarize Stage7 sharded runs into a durable JSON/MD status report."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


STATUS_KEYS = ["pending", "running", "done", "done_with_warnings", "failed_retryable", "failed_final", "skipped"]


def sqlite_stats(db_path: Path, mode: str) -> dict[str, Any]:
    if not db_path.exists():
        return {"db_exists": False, **{key: 0 for key in STATUS_KEYS}, "total": 0}
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status='pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status='running' THEN 1 ELSE 0 END) as running,
                SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
                SUM(CASE WHEN status='done_with_warnings' THEN 1 ELSE 0 END) as done_with_warnings,
                SUM(CASE WHEN status='failed_retryable' THEN 1 ELSE 0 END) as failed_retryable,
                SUM(CASE WHEN status='failed_final' THEN 1 ELSE 0 END) as failed_final,
                SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) as skipped,
                SUM(json_valid) as json_valid_count,
                SUM(schema_valid) as schema_valid_count,
                SUM(entity_count) as entity_count,
                SUM(event_count) as event_count
            FROM article_status WHERE mode = ?
            """,
            (mode,),
        ).fetchone()
    return {
        "db_exists": True,
        "total": row[0] or 0,
        "pending": row[1] or 0,
        "running": row[2] or 0,
        "done": row[3] or 0,
        "done_with_warnings": row[4] or 0,
        "failed_retryable": row[5] or 0,
        "failed_final": row[6] or 0,
        "skipped": row[7] or 0,
        "json_valid_count": row[8] or 0,
        "schema_valid_count": row[9] or 0,
        "entity_count": row[10] or 0,
        "event_count": row[11] or 0,
    }


def read_tail(path: Path, max_lines: int = 8) -> list[str]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:]


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def find_shard_roots(parent: Path) -> list[Path]:
    if (parent / "state" / "pipeline.sqlite").exists() or (parent / "manifests" / "article_manifest.v1.jsonl").exists():
        return [parent]
    return [child for child in sorted(parent.iterdir()) if child.is_dir() and (child / "manifests").exists()]


def summarize(parent: Path, mode: str) -> dict[str, Any]:
    shard_roots = find_shard_roots(parent)
    shards: list[dict[str, Any]] = []
    totals = {key: 0 for key in STATUS_KEYS}
    totals.update({"total": 0, "manifest_records": 0, "extract_count": 0, "json_valid_count": 0, "schema_valid_count": 0, "entity_count": 0, "event_count": 0})

    for shard_root in shard_roots:
        stats = sqlite_stats(shard_root / "state" / "pipeline.sqlite", mode)
        manifest_records = count_jsonl(shard_root / "manifests" / "article_manifest.v1.jsonl")
        extract_count = len(list((shard_root / "llm_extract").rglob("extract.article.v1.json"))) if (shard_root / "llm_extract").exists() else 0
        stdout_candidates = sorted((shard_root / "logs").glob("RUN_*.stdout.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        stderr_candidates = sorted((shard_root / "logs").glob("RUN_*.stderr.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        item = {
            "name": shard_root.name,
            "root": str(shard_root),
            "manifest_records": manifest_records,
            "extract_count": extract_count,
            "stats": stats,
            "latest_stdout": str(stdout_candidates[0]) if stdout_candidates else "",
            "latest_stdout_tail": read_tail(stdout_candidates[0]) if stdout_candidates else [],
            "latest_stderr": str(stderr_candidates[0]) if stderr_candidates else "",
            "latest_stderr_tail": read_tail(stderr_candidates[0]) if stderr_candidates else [],
        }
        shards.append(item)
        totals["manifest_records"] += manifest_records
        totals["extract_count"] += extract_count
        for key in STATUS_KEYS + ["total", "json_valid_count", "schema_valid_count", "entity_count", "event_count"]:
            totals[key] += int(stats.get(key) or 0)

    successful = totals["done"] + totals["done_with_warnings"]
    failed = totals["failed_retryable"] + totals["failed_final"]
    processed = successful + failed + totals["skipped"]
    remaining_estimate = max(totals["manifest_records"] - processed, 0)
    return {
        "generated_at": datetime.now().isoformat(),
        "parent": str(parent),
        "mode": mode,
        "shard_count": len(shards),
        "totals": {**totals, "successful": successful, "failed": failed, "processed": processed, "remaining_estimate": remaining_estimate},
        "shards": shards,
    }


def add_throughput(report: dict[str, Any], history_jsonl: Path | None) -> None:
    if history_jsonl is None or not history_jsonl.exists():
        report["throughput"] = {"previous_found": False}
        return
    previous = None
    with history_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                previous = json.loads(stripped)
    if not previous:
        report["throughput"] = {"previous_found": False}
        return
    previous_time = datetime.fromisoformat(previous["generated_at"])
    current_time = datetime.fromisoformat(report["generated_at"])
    elapsed_minutes = max((current_time - previous_time).total_seconds() / 60.0, 0.0)
    previous_extracts = int(previous.get("totals", {}).get("extract_count") or 0)
    current_extracts = int(report.get("totals", {}).get("extract_count") or 0)
    delta_extracts = current_extracts - previous_extracts
    report["throughput"] = {
        "previous_found": True,
        "previous_generated_at": previous["generated_at"],
        "elapsed_minutes": elapsed_minutes,
        "delta_extract_count": delta_extracts,
        "extracts_per_minute": (delta_extracts / elapsed_minutes) if elapsed_minutes > 0 else 0.0,
    }


def append_history(history_jsonl: Path | None, report: dict[str, Any]) -> None:
    if history_jsonl is None:
        return
    history_jsonl.parent.mkdir(parents=True, exist_ok=True)
    compact = {
        "generated_at": report["generated_at"],
        "parent": report["parent"],
        "mode": report["mode"],
        "totals": report["totals"],
        "throughput": report.get("throughput", {}),
    }
    with history_jsonl.open("a", encoding="utf-8") as f:
        f.write(json.dumps(compact, ensure_ascii=False) + "\n")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    totals = report["totals"]
    throughput = report.get("throughput", {})
    lines = [
        "# Stage7 Sharded Run Status",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- parent: {report['parent']}",
        f"- mode: {report['mode']}",
        f"- shard_count: {report['shard_count']}",
        f"- manifest_records: {totals['manifest_records']}",
        f"- extract_count: {totals['extract_count']}",
        f"- successful: {totals['successful']}",
        f"- failed: {totals['failed']}",
        f"- running: {totals['running']}",
        f"- remaining_estimate: {totals['remaining_estimate']}",
        f"- json_valid_count: {totals['json_valid_count']}",
        f"- schema_valid_count: {totals['schema_valid_count']}",
        f"- entity_count: {totals['entity_count']}",
        f"- event_count: {totals['event_count']}",
        f"- throughput_extracts_per_minute: {throughput.get('extracts_per_minute', '')}",
        f"- throughput_delta_extract_count: {throughput.get('delta_extract_count', '')}",
        "",
        "## Shards",
        "",
    ]
    for shard in report["shards"]:
        stats = shard["stats"]
        lines.extend(
            [
                f"### {shard['name']}",
                f"- root: {shard['root']}",
                f"- manifest_records: {shard['manifest_records']}",
                f"- extract_count: {shard['extract_count']}",
                f"- successful: {(stats.get('done') or 0) + (stats.get('done_with_warnings') or 0)}",
                f"- failed: {(stats.get('failed_retryable') or 0) + (stats.get('failed_final') or 0)}",
                f"- running: {stats.get('running') or 0}",
                f"- latest_stdout: {shard['latest_stdout']}",
                f"- latest_stderr: {shard['latest_stderr']}",
                "",
            ]
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent", required=True)
    parser.add_argument("--mode", required=True)
    parser.add_argument("--out-json", required=True)
    parser.add_argument("--out-md", required=True)
    parser.add_argument("--history-jsonl", default="")
    args = parser.parse_args()

    report = summarize(Path(args.parent), args.mode)
    history_jsonl = Path(args.history_jsonl) if args.history_jsonl else None
    add_throughput(report, history_jsonl)
    out_json = Path(args.out_json)
    out_md = Path(args.out_md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(out_md, report)
    append_history(history_jsonl, report)
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
