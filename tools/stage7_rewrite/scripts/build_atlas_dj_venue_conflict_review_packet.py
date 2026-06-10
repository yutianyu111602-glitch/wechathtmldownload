#!/usr/bin/env python3
"""Build a report-only conflict review packet for blocked Atlas DJ venue rows."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_atlas_dj_venue_work_order_sidecar import norm, read_jsonl, write_json, write_jsonl  # noqa: E402
from build_atlas_event_time_normalized_sidecar import now_iso, text  # noqa: E402


DEFAULT_BLOCKED_ROWS = (
    REPO_ROOT
    / "reports"
    / "atlas_dj_venue_acceptance_gate_activity_current_20260525_1809"
    / "venue_acceptance_blocked.jsonl"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_dj_venue_conflict_review_packet_20260525"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_VENUE_CONFLICT_REVIEW_PACKET_20260525.md"

URL_OR_ARCHIVE_RE = re.compile(r"https?://|mp\.weixin|raw\.html|archive_", re.IGNORECASE)
SECRET_WORD_RE = re.compile(r"\b(openid|fakeid|unionid|secret|token|cookie|password)\b", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.IGNORECASE,
)


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for venue conflict review: {path}")


def compact(value: Any, limit: int = 300) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def stable_id(row: dict[str, Any]) -> str:
    key = {
        "work_item_id": text(row.get("work_item_id")),
        "article_uid": text(row.get("article_uid")),
        "source_event_id": text(row.get("source_event_id")),
        "serving_event_id": text(row.get("serving_event_id")),
        "current_venue_id": text(row.get("current_venue_id")),
        "proposed_venue_id": text(row.get("proposed_venue_id")),
    }
    return hashlib.sha1(json.dumps(key, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def classify(row: dict[str, Any]) -> tuple[str, str, str]:
    status = text(row.get("status"))
    current_venue_id = text(row.get("current_venue_id"))
    current_venue_name = text(row.get("current_venue_name"))
    proposed_venue_id = text(row.get("proposed_venue_id"))
    proposed_venue_name = text(row.get("proposed_venue_name"))

    if status == "blocked_serving_event_not_found":
        return (
            "route_serving_event_lineage_gap",
            "serving_event_lineage_gap_queue.jsonl",
            "Source event exists but selected serving DB has no matching event_id; reconcile serving lineage before venue promotion.",
        )
    if status == "blocked_existing_venue_id_conflict":
        if norm(current_venue_name) == norm(proposed_venue_name):
            return (
                "route_existing_venue_alias_review",
                "existing_venue_alias_review_queue.jsonl",
                "Existing serving venue id differs but names normalize equally; review venue-id alias mapping before any patch.",
            )
        return (
            "route_existing_venue_conflict_review",
            "existing_venue_conflict_review_queue.jsonl",
            "Serving event already has a different venue id/name; source-account venue inference is not sufficient for auto patch.",
        )
    if status == "blocked_existing_venue_name_conflict":
        return (
            "route_existing_venue_name_conflict_review",
            "existing_venue_name_conflict_review_queue.jsonl",
            "Serving event has venue text that conflicts with proposed source-account venue; manual/source evidence is required.",
        )
    if not proposed_venue_id or not proposed_venue_name:
        return (
            "route_candidate_missing_venue_review",
            "candidate_missing_venue_review_queue.jsonl",
            "Candidate row lacks a complete venue id/name and cannot be promoted.",
        )
    return (
        "route_manual_blocked_review",
        "manual_blocked_review_queue.jsonl",
        "Blocked status is not handled by deterministic venue conflict rules.",
    )


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
        "# Atlas DJ Venue Conflict Review Packet",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Blocked rows: `{summary['blocked_rows']}`",
        f"- Input rows: {summary['counts']['input_rows']}",
        f"- Review work orders: {summary['counts']['review_work_orders']}",
        f"- Conflict groups: {summary['counts']['conflict_groups']}",
        f"- Decision: {summary['decision']['status']}",
        f"- Reason: {summary['decision']['reason']}",
        "",
        "## Decision Counts",
    ]
    for decision, count in sorted(summary["decision_counts"].items()):
        lines.append(f"- {decision}: {count}")
    lines.extend(["", "## Status Counts"])
    for status, count in sorted(summary["status_counts"].items()):
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Top Conflict Groups"])
    for group in summary["top_conflict_groups"]:
        lines.append(
            f"- {group['status']} / current `{group['current_venue_name']}` -> proposed `{group['proposed_venue_name']}`: {group['count']}"
        )
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


def build_report_md(summary: dict[str, Any]) -> str:
    lines = [
        "# ATLAS T5 Venue Conflict Review Packet",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "## Result",
        "",
        f"- Decision: `{summary['decision']['status']}`.",
        f"- Input blocked rows: `{summary['counts']['input_rows']}`.",
        f"- Review work orders: `{summary['counts']['review_work_orders']}`.",
        f"- Conflict groups: `{summary['counts']['conflict_groups']}`.",
        "",
        "## Decision Counts",
        "",
    ]
    for decision, count in sorted(summary["decision_counts"].items()):
        lines.append(f"- `{decision}`: `{count}`")
    lines.extend(["", "## Status Counts", ""])
    for status, count in sorted(summary["status_counts"].items()):
        lines.append(f"- `{status}`: `{count}`")
    lines.extend(["", "## Boundary", ""])
    lines.extend(
        [
            "- Report-only review packet.",
            "- No source/raw Atlas DB mutation.",
            "- No serving SQLite rebuild or write.",
            "- No public pointer, CloudRun/VPS deploy, Neo4j/Qdrant/SQLite production write, mini-program upload/review, memory write, credential read/print, network/model/paid API call, 9router action, or D: root scan.",
            "",
            "## Evidence",
            "",
        ]
    )
    for name, path in sorted(summary["outputs"].items()):
        lines.append(f"- `{name}`: `{path}`")
    lines.append("")
    return "\n".join(lines)


def build_conflict_review_packet(blocked_rows_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    reject_d_path(blocked_rows_path, "blocked_rows")
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")

    rows = read_jsonl(blocked_rows_path)
    work_orders: list[dict[str, Any]] = []
    routed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    group_samples: dict[tuple[str, str, str, str, str], list[str]] = defaultdict(list)
    group_counts = Counter()
    decision_counts = Counter()
    status_counts = Counter()

    generated_at = now_iso()
    for input_index, row in enumerate(rows, start=1):
        decision, output_file, reason = classify(row)
        status = text(row.get("status"))
        status_counts[status] += 1
        decision_counts[decision] += 1
        key = (
            status,
            text(row.get("current_venue_id")),
            text(row.get("current_venue_name")),
            text(row.get("proposed_venue_id")),
            text(row.get("proposed_venue_name")),
        )
        group_counts[key] += 1
        if len(group_samples[key]) < 5:
            group_samples[key].append(compact(row.get("event_name"), 120))
        work_order = {
            "schema_version": "atlas_dj_venue_conflict_review_packet.work_order.v1",
            "generated_at": generated_at,
            "review_item_id": stable_id(row),
            "input_index": input_index,
            "decision": decision,
            "decision_reason": reason,
            "serving_rebuild_eligible": False,
            "serving_rebuild_blocker": "Venue conflict rows require source/alias/lineage review before any serving patch.",
            "status": status,
            "article_uid": text(row.get("article_uid")),
            "source_event_id": text(row.get("source_event_id")),
            "serving_event_id": text(row.get("serving_event_id")),
            "event_name": compact(row.get("event_name")),
            "source_account": compact(row.get("source_account")),
            "current_venue_id": text(row.get("current_venue_id")),
            "current_venue_name": compact(row.get("current_venue_name")),
            "proposed_venue_id": text(row.get("proposed_venue_id")),
            "proposed_venue_name": compact(row.get("proposed_venue_name")),
            "proposed_city": compact(row.get("proposed_city")),
            "match_kind": text(row.get("match_kind")),
            "confidence": row.get("confidence"),
            "write_status": "report_only",
        }
        work_orders.append(work_order)
        routed[output_file].append(work_order)

    conflict_groups = [
        {
            "schema_version": "atlas_dj_venue_conflict_review_packet.group.v1",
            "status": status,
            "current_venue_id": current_venue_id,
            "current_venue_name": current_venue_name,
            "proposed_venue_id": proposed_venue_id,
            "proposed_venue_name": proposed_venue_name,
            "count": count,
            "sample_event_names": group_samples[(status, current_venue_id, current_venue_name, proposed_venue_id, proposed_venue_name)],
        }
        for (status, current_venue_id, current_venue_name, proposed_venue_id, proposed_venue_name), count in group_counts.most_common()
    ]

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "summary_json": str(out_dir / "summary.json"),
        "summary_md": str(out_dir / "summary.md"),
        "report_md": str(report_path),
        "review_work_order_jsonl": str(out_dir / "review_work_order.jsonl"),
        "conflict_groups_jsonl": str(out_dir / "conflict_groups.jsonl"),
    }
    for output_file in sorted(routed):
        outputs[output_file.removesuffix(".jsonl")] = str(out_dir / output_file)

    write_jsonl(out_dir / "review_work_order.jsonl", work_orders)
    write_jsonl(out_dir / "conflict_groups.jsonl", conflict_groups)
    for output_file, output_rows in routed.items():
        write_jsonl(out_dir / output_file, output_rows)

    summary = {
        "schema_version": "atlas_dj_venue_conflict_review_packet.summary.v1",
        "generated_at": generated_at,
        "blocked_rows": str(blocked_rows_path),
        "out_dir": str(out_dir),
        "report": str(report_path),
        "counts": {
            "input_rows": len(rows),
            "review_work_orders": len(work_orders),
            "conflict_groups": len(conflict_groups),
        },
        "status_counts": dict(sorted(status_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "top_conflict_groups": conflict_groups[:20],
        "decision": {
            "status": "atlas_dj_venue_conflict_review_ready_report_only",
            "serving_rebuild_triggered": False,
            "reason": "Blocked venue rows are routed to source, alias, or serving-lineage review; none are direct serving patch inputs.",
        },
        "outputs": outputs,
        "public_leak_scan": public_leak_counts(work_orders),
        "safety": {
            "llm_call_executed": False,
            "network_call_executed": False,
            "neo4j_write_executed": False,
            "paid_api_call_executed": False,
            "production_write_executed": False,
            "qdrant_write_executed": False,
            "report_only": True,
            "serving_sqlite_rebuild_executed": False,
            "serving_sqlite_write_executed": False,
            "source_sqlite_write_executed": False,
        },
    }
    write_json(out_dir / "summary.json", summary)
    (out_dir / "summary.md").write_text(build_summary_md(summary), encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_report_md(summary), encoding="utf-8")
    return {"summary": summary, "work_orders": work_orders, "conflict_groups": conflict_groups}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blocked-rows", type=Path, default=DEFAULT_BLOCKED_ROWS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_conflict_review_packet(args.blocked_rows, args.out_dir, args.report)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
