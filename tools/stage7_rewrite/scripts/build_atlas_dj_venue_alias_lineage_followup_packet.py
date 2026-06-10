#!/usr/bin/env python3
"""Build a report-only follow-up packet for venue alias and serving-lineage queues."""

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


DEFAULT_INPUT_DIR = REPO_ROOT / "reports" / "atlas_dj_venue_conflict_review_packet_activity_current_20260525_1908"
DEFAULT_ALIAS_QUEUE = DEFAULT_INPUT_DIR / "existing_venue_alias_review_queue.jsonl"
DEFAULT_LINEAGE_QUEUE = DEFAULT_INPUT_DIR / "serving_event_lineage_gap_queue.jsonl"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_dj_venue_alias_lineage_followup_activity_current_20260525_2009"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_VENUE_ALIAS_LINEAGE_FOLLOWUP_PACKET_20260525.md"

URL_OR_ARCHIVE_RE = re.compile(r"https?://|mp\.weixin|raw\.html|archive_", re.IGNORECASE)
SECRET_WORD_RE = re.compile(r"\b(openid|fakeid|unionid|secret|token|cookie|password)\b", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.IGNORECASE,
)


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for venue alias/lineage follow-up: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def compact(value: Any, limit: int = 240) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def stable_id(prefix: str, payload: dict[str, Any]) -> str:
    digest = hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


def public_leak_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        counts["url_or_archive_hits"] += len(URL_OR_ARCHIVE_RE.findall(payload))
        counts["secret_word_hits"] += len(SECRET_WORD_RE.findall(payload))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(payload))
    return dict(counts)


def sample_append(samples: dict[tuple[str, ...], list[str]], key: tuple[str, ...], event_name: Any) -> None:
    if len(samples[key]) < 5:
        samples[key].append(compact(event_name, 120))


def build_alias_candidates(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    samples: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for row in rows:
        key = (
            text(row.get("current_venue_id")),
            text(row.get("proposed_venue_id")),
            compact(row.get("proposed_city")),
        )
        grouped[key].append(row)
        sample_append(samples, key, row.get("event_name"))

    candidates: list[dict[str, Any]] = []
    for key, group_rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        current_venue_id, proposed_venue_id, proposed_city = key
        current_names = sorted({compact(row.get("current_venue_name")) for row in group_rows if compact(row.get("current_venue_name"))})
        proposed_names = sorted({compact(row.get("proposed_venue_name")) for row in group_rows if compact(row.get("proposed_venue_name"))})
        current_venue_name = current_names[0] if current_names else ""
        proposed_venue_name = proposed_names[0] if proposed_names else ""
        normalized_match = bool(current_names and proposed_names) and all(
            norm(current_name) == norm(proposed_name)
            for current_name in current_names
            for proposed_name in proposed_names
        )
        candidate_key = {
            "current_venue_id": current_venue_id,
            "proposed_venue_id": proposed_venue_id,
            "proposed_city": proposed_city,
        }
        candidates.append(
            {
                "schema_version": "atlas_dj_venue_alias_lineage_followup.alias_candidate.v1",
                "generated_at": generated_at,
                "alias_candidate_id": stable_id("venue_alias", candidate_key),
                "current_venue_id": current_venue_id,
                "current_venue_name": current_venue_name,
                "current_venue_name_variants": current_names,
                "proposed_venue_id": proposed_venue_id,
                "proposed_venue_name": proposed_venue_name,
                "proposed_venue_name_variants": proposed_names,
                "proposed_city": proposed_city,
                "row_count": len(group_rows),
                "normalized_name_match": normalized_match,
                "confidence_min": min(float(row.get("confidence") or 0) for row in group_rows),
                "confidence_max": max(float(row.get("confidence") or 0) for row in group_rows),
                "sample_event_names": samples[key],
                "decision": "alias_review_candidate_report_only",
                "serving_patch_eligible": False,
                "serving_patch_blocker": "Alias candidates need an explicit venue-id alias/merge decision before any serving patch.",
                "write_status": "report_only",
            }
        )
    return candidates


def build_lineage_groups(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    samples: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for row in rows:
        key = (
            compact(row.get("source_account")),
            text(row.get("proposed_venue_id")),
            compact(row.get("proposed_venue_name")),
            compact(row.get("proposed_city")),
        )
        grouped[key].append(row)
        sample_append(samples, key, row.get("event_name"))

    groups: list[dict[str, Any]] = []
    for key, group_rows in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        source_account, proposed_venue_id, proposed_venue_name, proposed_city = key
        lineage_key = {
            "source_account": source_account,
            "proposed_venue_id": proposed_venue_id,
            "proposed_city": proposed_city,
        }
        groups.append(
            {
                "schema_version": "atlas_dj_venue_alias_lineage_followup.lineage_group.v1",
                "generated_at": generated_at,
                "lineage_group_id": stable_id("venue_lineage", lineage_key),
                "source_account": source_account,
                "proposed_venue_id": proposed_venue_id,
                "proposed_venue_name": proposed_venue_name,
                "proposed_city": proposed_city,
                "row_count": len(group_rows),
                "sample_event_names": samples[key],
                "decision": "serving_event_lineage_review_report_only",
                "next_action": "reconcile source event id against selected serving read-model lineage before venue promotion",
                "serving_patch_eligible": False,
                "serving_patch_blocker": "Selected serving DB has no matching event_id for these source events.",
                "write_status": "report_only",
            }
        )
    return groups


def build_lineage_work_orders(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    work_orders: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        key = {
            "article_uid": text(row.get("article_uid")),
            "source_event_id": text(row.get("source_event_id")),
            "serving_event_id": text(row.get("serving_event_id")),
            "proposed_venue_id": text(row.get("proposed_venue_id")),
        }
        work_orders.append(
            {
                "schema_version": "atlas_dj_venue_alias_lineage_followup.lineage_work_order.v1",
                "generated_at": generated_at,
                "lineage_work_order_id": stable_id("lineage_work", key),
                "input_index": index,
                "article_uid": text(row.get("article_uid")),
                "source_event_id": text(row.get("source_event_id")),
                "serving_event_id": text(row.get("serving_event_id")),
                "event_name": compact(row.get("event_name")),
                "source_account": compact(row.get("source_account")),
                "proposed_venue_id": text(row.get("proposed_venue_id")),
                "proposed_venue_name": compact(row.get("proposed_venue_name")),
                "proposed_city": compact(row.get("proposed_city")),
                "decision": "lineage_gap_source_context_recheck_report_only",
                "serving_patch_eligible": False,
                "serving_patch_blocker": "Venue cannot be patched until source event and selected serving event lineage are reconciled.",
                "write_status": "report_only",
            }
        )
    return work_orders


def build_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas DJ Venue Alias / Lineage Follow-up Packet",
        "",
        f"- Generated at: {summary['generated_at']}",
        f"- Decision: {summary['decision']['status']}",
        f"- Alias rows: {summary['counts']['alias_rows']}",
        f"- Alias candidate groups: {summary['counts']['alias_candidate_groups']}",
        f"- Lineage rows: {summary['counts']['lineage_rows']}",
        f"- Lineage groups: {summary['counts']['lineage_groups']}",
        "",
        "## Outputs",
    ]
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
        "# ATLAS T5 Venue Alias / Lineage Follow-up Packet",
        "",
        f"Generated: {summary['generated_at']}",
        "",
        "## Result",
        "",
        f"- Decision: `{summary['decision']['status']}`.",
        f"- Alias review input rows: `{summary['counts']['alias_rows']}`.",
        f"- Alias candidate groups: `{summary['counts']['alias_candidate_groups']}`.",
        f"- Serving-lineage gap rows: `{summary['counts']['lineage_rows']}`.",
        f"- Serving-lineage groups: `{summary['counts']['lineage_groups']}`.",
        f"- Serving patch candidates: `{summary['counts']['serving_patch_candidates']}`.",
        "",
        "## Interpretation",
        "",
        "- Alias rows collapsed into review candidates, but they remain report-only until an explicit venue-id alias/merge decision exists.",
        "- Serving-lineage rows remain blocked because the selected serving DB does not expose matching event lineage for those source events.",
        "- No serving rebuild is warranted from this packet alone.",
        "",
        "## Boundary",
        "",
        "- Report-only follow-up packet.",
        "- No source/raw Atlas DB mutation.",
        "- No serving SQLite rebuild or write.",
        "- No public pointer, CloudRun/VPS deploy, Neo4j/Qdrant/SQLite production write, mini-program upload/review, memory write, credential read/print, network/model/paid API call, 9router action, or D: root scan.",
        "",
        "## Evidence",
        "",
    ]
    for name, path in sorted(summary["outputs"].items()):
        lines.append(f"- `{name}`: `{path}`")
    lines.append("")
    return "\n".join(lines)


def build_followup_packet(alias_queue: Path, lineage_queue: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    for label, path in {
        "alias_queue": alias_queue,
        "lineage_queue": lineage_queue,
        "out_dir": out_dir,
        "report_path": report_path,
    }.items():
        reject_d_path(path, label)

    alias_rows = read_jsonl(alias_queue)
    lineage_rows = read_jsonl(lineage_queue)
    generated_at = now_iso()
    alias_candidates = build_alias_candidates(alias_rows, generated_at)
    lineage_groups = build_lineage_groups(lineage_rows, generated_at)
    lineage_work_orders = build_lineage_work_orders(lineage_rows, generated_at)

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "summary_json": display_path(out_dir / "summary.json"),
        "summary_md": display_path(out_dir / "summary.md"),
        "report_md": display_path(report_path),
        "alias_candidates_jsonl": display_path(out_dir / "alias_candidates.jsonl"),
        "lineage_groups_jsonl": display_path(out_dir / "lineage_groups.jsonl"),
        "lineage_work_order_jsonl": display_path(out_dir / "lineage_work_order.jsonl"),
    }
    write_jsonl(out_dir / "alias_candidates.jsonl", alias_candidates)
    write_jsonl(out_dir / "lineage_groups.jsonl", lineage_groups)
    write_jsonl(out_dir / "lineage_work_order.jsonl", lineage_work_orders)

    leak_rows = [*alias_candidates, *lineage_groups, *lineage_work_orders]
    summary = {
        "schema_version": "atlas_dj_venue_alias_lineage_followup.summary.v1",
        "generated_at": generated_at,
        "alias_queue": display_path(alias_queue),
        "lineage_queue": display_path(lineage_queue),
        "out_dir": display_path(out_dir),
        "report": display_path(report_path),
        "counts": {
            "alias_rows": len(alias_rows),
            "alias_candidate_groups": len(alias_candidates),
            "lineage_rows": len(lineage_rows),
            "lineage_groups": len(lineage_groups),
            "lineage_work_orders": len(lineage_work_orders),
            "serving_patch_candidates": 0,
        },
        "top_alias_candidates": alias_candidates[:10],
        "top_lineage_groups": lineage_groups[:10],
        "decision": {
            "status": "atlas_dj_venue_alias_lineage_followup_ready_report_only",
            "serving_rebuild_triggered": False,
            "reason": "Alias and lineage queues are grouped for review; neither queue can produce a deterministic serving patch without a separate alias/lineage acceptance gate.",
        },
        "outputs": outputs,
        "public_leak_scan": public_leak_counts(leak_rows),
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
    return {
        "summary": summary,
        "alias_candidates": alias_candidates,
        "lineage_groups": lineage_groups,
        "lineage_work_orders": lineage_work_orders,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias-queue", type=Path, default=DEFAULT_ALIAS_QUEUE)
    parser.add_argument("--lineage-queue", type=Path, default=DEFAULT_LINEAGE_QUEUE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_followup_packet(args.alias_queue, args.lineage_queue, args.out_dir, args.report)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
