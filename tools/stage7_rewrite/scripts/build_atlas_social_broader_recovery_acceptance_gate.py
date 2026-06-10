#!/usr/bin/env python3
"""Build a report-only acceptance gate for the Q6 broader recovery slice."""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_INPUT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_broader_source_context_recovery_q6_20260526"
    / "combined_broader_recovery_review_slice.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_broader_recovery_acceptance_gate_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_BROADER_RECOVERY_ACCEPTANCE_GATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_broader_recovery_acceptance_gate.v1"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for broader recovery acceptance gate: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "input_jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def classify(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    lane = compact(row.get("lane"), 120)
    has_event_shell = bool(compact(row.get("event_id")) and compact(row.get("name")))
    has_time_place = bool(compact(row.get("time_text")) and compact(row.get("place")))
    has_source_context = number(row.get("event_count")) > 0 or number(row.get("dj_entity_count")) > 0
    source_review_only = not bool(row.get("accepted_for_graph")) and not bool(row.get("graph_write_allowed"))

    if lane == "participant_repair_review" and has_event_shell and has_time_place and has_source_context:
        gate_status = "manual_participant_review_candidate"
        blocker = "participant evidence still needs source/OCR review before deterministic acceptance"
    elif lane == "ocr_markdown_repair":
        gate_status = "blocked_ocr_markdown_evidence_required"
        blocker = "OCR/Markdown repair is required before fact acceptance"
    elif lane == "source_context_reextract":
        gate_status = "blocked_source_context_reextract_required"
        blocker = "source-context re-extract is required before fact acceptance"
    else:
        gate_status = "blocked_unclassified_review_only"
        blocker = "row remains review-only and lacks deterministic acceptance evidence"

    deterministic_ready = False
    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "rank": int(number(row.get("rank"))),
        "work_item_id": compact(row.get("work_item_id"), 100),
        "article_uid": compact(row.get("article_uid"), 220),
        "lane": lane,
        "source_account": compact(row.get("source_account"), 220),
        "title": compact(row.get("title"), 520),
        "name": compact(row.get("name"), 320),
        "event_id_present": bool(compact(row.get("event_id"))),
        "time_text_present": bool(compact(row.get("time_text"))),
        "place_present": bool(compact(row.get("place"))),
        "local_image_count": int(number(row.get("local_image_count"))),
        "entity_count": int(number(row.get("entity_count"))),
        "event_count": int(number(row.get("event_count"))),
        "dj_entity_count": int(number(row.get("dj_entity_count"))),
        "input_review_only": source_review_only,
        "gate_status": gate_status,
        "blocking_reason": blocker,
        "deterministic_acceptance_ready": deterministic_ready,
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "write_status": "report_only",
        "next_gate": "Run bounded source/OCR/manual evidence review before any source, serving, graph, vector, public, or memory promotion.",
    }


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        text = json.dumps(row, ensure_ascii=False, sort_keys=True)
        counts["public_url_hits"] += len(URL_RE.findall(text))
        counts["secret_word_hits"] += len(SECRET_RE.findall(text))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    return dict(counts)


def markdown_report(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas T6 Broader Recovery Acceptance Gate",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Input rows: `{summary['counts']['input_rows']}`",
        f"- Deterministic acceptance-ready rows: `{summary['counts']['deterministic_acceptance_ready_rows']}`",
        f"- Manual participant review candidates: `{summary['counts']['manual_participant_review_candidate_rows']}`",
        f"- Public URL / secret / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['secret_word_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Gate Status Counts",
        "",
    ]
    for key, value in sorted(summary["gate_status_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only local acceptance gate.",
            "- No source/raw Atlas DB mutation, serving SQLite rebuild/write, graph/vector/DB production write, public pointer, deploy, upload/review, memory write, credential read, network/model/paid API, destructive Git, 9router use, or D: root scan occurred.",
            "- Rows remain closed for graph/public promotion until source/OCR/manual evidence review produces deterministic facts.",
            "",
        ]
    )
    return "\n".join(lines)


def build_gate(input_path: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    generated_at = now_iso()
    inputs = read_jsonl(input_path)
    rows = [classify(row, generated_at) for row in inputs]
    deterministic_ready = [row for row in rows if row["deterministic_acceptance_ready"]]
    manual_candidates = [row for row in rows if row["gate_status"] == "manual_participant_review_candidate"]
    blocked_rows = [row for row in rows if not row["deterministic_acceptance_ready"]]
    leaks = leak_scan(rows)
    failed_checks = [key for key, value in leaks.items() if value]
    status_counts = Counter(row["gate_status"] for row in rows)
    lane_counts = Counter(row["lane"] for row in rows)
    decision = (
        "atlas_social_broader_recovery_acceptance_blocked_report_only"
        if rows and not deterministic_ready and not failed_checks
        else "atlas_social_broader_recovery_acceptance_ready_report_only"
        if not failed_checks
        else "atlas_social_broader_recovery_acceptance_failed_safety_scan"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "input_jsonl": display_path(input_path),
        "outputs": {
            "summary_json": display_path(out_dir / "broader_recovery_acceptance_gate_summary.json"),
            "gate_rows_jsonl": display_path(out_dir / "broader_recovery_acceptance_gate_rows.jsonl"),
            "manual_participant_review_candidates_jsonl": display_path(out_dir / "manual_participant_review_candidates.jsonl"),
            "blocked_rows_jsonl": display_path(out_dir / "blocked_rows.jsonl"),
            "report_md": display_path(report_path),
        },
        "counts": {
            "input_rows": len(inputs),
            "deterministic_acceptance_ready_rows": len(deterministic_ready),
            "manual_participant_review_candidate_rows": len(manual_candidates),
            "blocked_rows": len(blocked_rows),
        },
        "lane_counts": dict(sorted(lane_counts.items())),
        "gate_status_counts": dict(sorted(status_counts.items())),
        "leak_scan": leaks,
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "llm_call_executed": False,
            "paid_api_call_executed": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "none" if not failed_checks else "safety_scan_failed",
        "wait_reason": (
            "combined recovery slice has no deterministic acceptance-ready rows; source/OCR/manual evidence review remains required."
            if rows and not deterministic_ready
            else "none"
        ),
        "next_resume_cursor": "Review manual_participant_review_candidates.jsonl first, then route blocked OCR/source-context rows back into bounded source/OCR evidence repair before any acceptance precheck.",
    }
    write_jsonl(out_dir / "broader_recovery_acceptance_gate_rows.jsonl", rows)
    write_jsonl(out_dir / "manual_participant_review_candidates.jsonl", manual_candidates)
    write_jsonl(out_dir / "blocked_rows.jsonl", blocked_rows)
    write_json(out_dir / "broader_recovery_acceptance_gate_summary.json", summary)
    write_text(report_path, markdown_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_gate(args.input, args.out_dir, args.report)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
