#!/usr/bin/env python3
"""P0 baseline report: release metrics + golden-set coverage (verified rows scored).

Does not call DeepSeek. Safe to run on current release packages.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from weekly_golden_lib import (  # noqa: E402
    backend_url_lines,
    compare_lineup,
    lineup_values,
    load_current_items,
    read_jsonl,
    squash,
    write_jsonl,
)


def release_metrics(items: list[dict[str, Any]]) -> dict[str, Any]:
    lineup_nonempty = 0
    backend_url_lines_total = 0
    backend_url_events = 0
    cities: set[str] = set()
    for item in items:
        lineup = lineup_values(item)
        if lineup:
            lineup_nonempty += 1
        url_lines = backend_url_lines(item)
        if url_lines:
            backend_url_events += 1
            backend_url_lines_total += len(url_lines)
        cities.add(squash(item.get("city_key") or item.get("city")) or "unknown")

    total = len(items)
    return {
        "published_items": total,
        "lineup_nonempty": lineup_nonempty,
        "lineup_nonempty_rate": round(lineup_nonempty / total, 4) if total else 0.0,
        "missing_lineup_count": total - lineup_nonempty,
        "backend_url_line_hits": backend_url_lines_total,
        "backend_url_event_count": backend_url_events,
        "backend_url_event_rate": round(backend_url_events / total, 4) if total else 0.0,
        "city_count": len(cities),
    }


def golden_metrics(rows: list[dict[str, Any]], items_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    stratum_counts: dict[str, int] = {}
    verified_rows: list[dict[str, Any]] = []

    for row in rows:
        status = squash(row.get("annotation_status")) or "pending"
        status_counts[status] = status_counts.get(status, 0) + 1
        stratum = squash(row.get("stratum")) or "unknown"
        stratum_counts[stratum] = stratum_counts.get(stratum, 0) + 1
        if status == "verified":
            verified_rows.append(row)

    lineup_scores: list[float] = []
    lineup_recalls: list[float] = []
    hard_errors = 0

    per_row: list[dict[str, Any]] = []
    for row in verified_rows:
        gold = row.get("gold") if isinstance(row.get("gold"), dict) else {}
        snap = row.get("pipeline_snapshot") if isinstance(row.get("pipeline_snapshot"), dict) else {}
        shown = snap.get("lineup") if isinstance(snap.get("lineup"), list) else []
        gold_lineup = gold.get("lineup") if isinstance(gold.get("lineup"), list) else None
        metrics = compare_lineup([squash(v) for v in shown], [squash(v) for v in (gold_lineup or [])])
        lineup_scores.append(metrics["precision"])
        lineup_recalls.append(metrics["recall"])
        if gold.get("hard_error"):
            hard_errors += 1
        per_row.append(
            {
                "event_id": row.get("event_id"),
                "lineup_metrics": metrics,
                "hard_error": bool(gold.get("hard_error")),
            }
        )

    scored = {
        "verified_count": len(verified_rows),
        "pending_count": status_counts.get("pending", 0),
        "lineup_precision_mean": round(sum(lineup_scores) / len(lineup_scores), 4) if lineup_scores else None,
        "lineup_recall_mean": round(sum(lineup_recalls) / len(lineup_recalls), 4) if lineup_recalls else None,
        "hard_error_count": hard_errors,
        "hard_error_rate": round(hard_errors / len(verified_rows), 4) if verified_rows else None,
        "per_row": per_row,
    }

    # Align golden snapshots with live current (drift check)
    drift: list[dict[str, str]] = []
    for row in rows:
        eid = squash(row.get("event_id"))
        live = items_by_id.get(eid)
        if not live:
            drift.append({"event_id": eid, "issue": "missing_in_current"})
            continue
        live_lineup = lineup_values(live)
        snap = row.get("pipeline_snapshot") if isinstance(row.get("pipeline_snapshot"), dict) else {}
        snap_lineup = snap.get("lineup") if isinstance(snap.get("lineup"), list) else []
        if {squash(v) for v in live_lineup} != {squash(v) for v in snap_lineup}:
            drift.append({"event_id": eid, "issue": "lineup_snapshot_drift"})

    return {
        "golden_total": len(rows),
        "status_counts": status_counts,
        "stratum_counts": stratum_counts,
        "scored": scored,
        "snapshot_drift": drift[:20],
        "snapshot_drift_count": len(drift),
    }


def render_markdown(report: dict[str, Any]) -> str:
    rel = report["release_metrics"]
    gold = report["golden_metrics"]
    scored = gold["scored"]
    lines = [
        "# P0 Weekly Baseline Report",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Release metrics (current.json)",
        "",
        f"| 指标 | 值 |",
        f"|------|-----|",
        f"| 发布条数 | {rel['published_items']} |",
        f"| 有 lineup | {rel['lineup_nonempty']} ({rel['lineup_nonempty_rate']:.1%}) |",
        f"| missing_lineup（粗算） | {rel['missing_lineup_count']} |",
        f"| backend URL 行数 | {rel['backend_url_line_hits']} |",
        f"| 含 URL 活动数 | {rel['backend_url_event_count']} ({rel['backend_url_event_rate']:.1%}) |",
        f"| 城市数 | {rel['city_count']} |",
        "",
        "## Golden set",
        "",
        f"| 项 | 值 |",
        f"|----|-----|",
        f"| 金标条数 | {gold['golden_total']} |",
        f"| pending | {gold['status_counts'].get('pending', 0)} |",
        f"| verified | {gold['status_counts'].get('verified', 0)} |",
        "",
        "### Stratum",
        "",
    ]
    for key, count in sorted(gold["stratum_counts"].items()):
        lines.append(f"- `{key}`: {count}")
    lines.extend(
        [
            "",
            "## Scored metrics (verified only)",
            "",
            f"- lineup precision (mean): {scored['lineup_precision_mean']}",
            f"- lineup recall (mean): {scored['lineup_recall_mean']}",
            f"- hard_error_rate: {scored['hard_error_rate']}",
            "",
            "## P0 exit gate",
            "",
            "- [ ] Golden ≥80 条（已引导）",
            "- [ ] 人工 verified ≥80 且 inter-annotator 待做",
            "- [ ] baseline 报告 review 通过",
            "",
            "## Next",
            "",
            "1. 人工填写 `gold.*`，将 `annotation_status` 改为 `verified`",
            "2. 重跑本脚本更新 P/R",
            "3. P1：URL build 清洗 + field_evidence",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    default_release = Path(
        r"D:\downstream_results\stage7_rewrite\longrun\WEEKLY_ACTIVITY_MINIPROGRAM_API_20260519"
    )
    parser.add_argument("--current", type=Path, default=default_release / "current.json")
    parser.add_argument(
        "--golden-file",
        type=Path,
        default=Path(r"D:\downstream_results\golden\golden_set_v1.jsonl"),
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=Path("tools/stage7_rewrite/reports/golden_baseline_20260519.json"),
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=Path("tools/stage7_rewrite/reports/golden_baseline_20260519.md"),
    )
    parser.add_argument(
        "--no-handoff-write",
        action="store_true",
        help="Do not update the maintained handoff baseline Markdown.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    items = load_current_items(args.current)
    rows = read_jsonl(args.golden_file)
    items_by_id = {squash(i.get("event_id") or i.get("id")): i for i in items}

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current_path": str(args.current),
        "golden_path": str(args.golden_file),
        "release_metrics": release_metrics(items),
        "golden_metrics": golden_metrics(rows, items_by_id),
        "p0_targets": {
            "lineup_precision": 0.92,
            "lineup_recall": 0.75,
            "backend_url_line_hits": 0,
        },
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    args.out_md.write_text(render_markdown(report), encoding="utf-8")
    handoff_md = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / "weekly-miniprogram-handoff-20260519"
        / "P0_BASELINE_REPORT_20260519.md"
    )
    if not args.no_handoff_write and handoff_md.parent.exists():
        handoff_md.write_text(render_markdown(report), encoding="utf-8")

    print(json.dumps({"ok": True, "out_json": str(args.out_json), "out_md": str(args.out_md)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
