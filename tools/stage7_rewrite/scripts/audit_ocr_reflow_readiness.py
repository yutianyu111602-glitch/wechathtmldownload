#!/usr/bin/env python3
"""Audit PRD-13 OCR entity/event reflow readiness without graph writes.

The existing PRD-13 extractor reads only the official OCR file index. This
audit also inspects bounded local Stage7 recovered-process status directories
under reports/ocr_root_cause_20260515 to explain whether OCR never ran, or ran
outside the index/structured recovered-field contract.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUT_DIR = Path("reports/ocr_reflow_readiness_20260515")
DEFAULT_OCR_ROOT = Path("reports/ocr_root_cause_20260515")
DEFAULT_EXTRACTION = Path("reports/ocr_entity_extraction_20260515/ocr_entity_extraction_summary.json")
DEFAULT_MERGE = Path("reports/ocr_entity_merge_20260515/ocr_entity_merge_report.json")
DEFAULT_OCR_INDEX_SUMMARY = Path("reports/ocr_file_index_20260515/ocr_file_index_summary.json")
DEFAULT_POSTER_PREFLIGHT = Path("reports/poster_vector_preflight_20260515/poster_vector_preflight_summary.json")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def is_under(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def recovered_counts(recovered: Any) -> dict[str, int]:
    if not isinstance(recovered, dict):
        return {"venue": 0, "date_texts": 0, "lineup_lines": 0}
    venue = 1 if str(recovered.get("venue_name_candidate") or "").strip() else 0
    date_texts = recovered.get("date_texts")
    lineup_lines = recovered.get("lineup_lines")
    return {
        "venue": venue,
        "date_texts": len([x for x in date_texts if str(x or "").strip()]) if isinstance(date_texts, list) else 0,
        "lineup_lines": len([x for x in lineup_lines if str(x or "").strip()]) if isinstance(lineup_lines, list) else 0,
    }


def audit_process_status_dirs(ocr_root: Path, max_items: int = 0) -> dict[str, Any]:
    if not ocr_root.exists():
        return {"ok": False, "error": f"missing ocr_root: {ocr_root}"}
    status_files = sorted(ocr_root.glob("empty_no_local_image_dajiala_process_*/ocr-status.json"))
    status_summaries = []
    total_items = 0
    succeeded_items = 0
    failed_items = 0
    poster_ocr_seen = 0
    plain_text_nonempty = 0
    recovered_nonempty = 0
    recovered_type_counts: Counter[str] = Counter()
    backend_counts: Counter[str] = Counter()
    sample_plain_text = []
    sample_recovered = []
    inspected_items = 0
    root_resolved = ocr_root.resolve()
    for status_path in status_files:
        status = read_json(status_path)
        items = status.get("items") or []
        total_items += int(status.get("total_items") or len(items))
        succeeded_items += int(status.get("succeeded_count") or 0)
        failed_items += int(status.get("failed_count") or 0)
        status_summaries.append(
            {
                "path": str(status_path),
                "status": status.get("status"),
                "total_items": status.get("total_items"),
                "succeeded_count": status.get("succeeded_count"),
                "failed_count": status.get("failed_count"),
            }
        )
        for item in items:
            if max_items and inspected_items >= max_items:
                continue
            artifact_dir = Path(str(item.get("artifactDir") or ""))
            poster_path = artifact_dir / "poster_ocr.json"
            if not poster_path.exists() or not is_under(poster_path, root_resolved):
                continue
            inspected_items += 1
            poster_ocr_seen += 1
            try:
                poster = read_json(poster_path)
            except Exception:
                continue
            backend = str(poster.get("backend") or "").strip()
            if backend:
                backend_counts[backend] += 1
            plain_text = str(poster.get("plain_text") or "").strip()
            if plain_text:
                plain_text_nonempty += 1
                if len(sample_plain_text) < 5:
                    sample_plain_text.append(
                        {
                            "relative_dir": item.get("relativeDir"),
                            "poster_ocr_path": str(poster_path),
                            "plain_text_preview": plain_text[:160],
                        }
                    )
            counts = recovered_counts(poster.get("recovered"))
            if sum(counts.values()) > 0:
                recovered_nonempty += 1
                recovered_type_counts.update(counts)
                if len(sample_recovered) < 5:
                    sample_recovered.append(
                        {
                            "relative_dir": item.get("relativeDir"),
                            "poster_ocr_path": str(poster_path),
                            "recovered_counts": counts,
                        }
                    )
    return {
        "ok": True,
        "status_file_count": len(status_files),
        "status_summaries": status_summaries,
        "total_items": total_items,
        "succeeded_items": succeeded_items,
        "failed_items": failed_items,
        "poster_ocr_seen": poster_ocr_seen,
        "plain_text_nonempty": plain_text_nonempty,
        "recovered_nonempty_files": recovered_nonempty,
        "recovered_type_counts": dict(recovered_type_counts),
        "backend_counts": dict(backend_counts),
        "sample_plain_text": sample_plain_text,
        "sample_recovered": sample_recovered,
        "writes": "read-only bounded C: reports audit",
    }


def build_audit(
    extraction: dict[str, Any],
    merge: dict[str, Any],
    ocr_index: dict[str, Any],
    poster_preflight: dict[str, Any],
    process_audit: dict[str, Any],
) -> dict[str, Any]:
    official_entities = int(extraction.get("entity_count") or 0)
    official_scanned = int(extraction.get("scanned_ocr_files") or 0)
    official_index_complete = int((ocr_index.get("ocr_status_counts") or {}).get("complete") or 0)
    sidecar_success = int(process_audit.get("succeeded_items") or 0)
    sidecar_plain_text = int(process_audit.get("plain_text_nonempty") or 0)
    sidecar_structured = int(process_audit.get("recovered_nonempty_files") or 0)
    would_merge = int(merge.get("would_merge_entities") or 0)
    blockers = []
    if official_entities < 10:
        blockers.append("official PRD-13 OCR entity extraction has fewer than 10 entities")
    if official_index_complete == 0:
        blockers.append("official OCR file index has 0 complete OCR rows")
    if sidecar_success > 0 and official_scanned == 0:
        blockers.append("OCR ran in recovered sidecar process dirs but is not represented as complete rows in the official OCR index")
    if sidecar_plain_text > 0 and sidecar_structured == 0:
        blockers.append("sidecar poster OCR has plain_text but recovered venue/date/lineup fields are empty")
    if would_merge == 0:
        blockers.append("Neo4j merge dry-run has 0 OCR entities to merge")
    decision = "ocr_reflow_blocked_contract_gap" if blockers else "ocr_reflow_ready_report_only"
    return {
        "schema_version": "stage7_ocr_reflow_readiness.v1",
        "generated_at": now_iso(),
        "ok": True,
        "decision": decision,
        "reflow_allowed": False,
        "report_only": True,
        "gates": {
            "official_extraction_entity_count": official_entities,
            "official_extraction_scanned_ocr_files": official_scanned,
            "official_index_complete_ocr_rows": official_index_complete,
            "sidecar_ocr_succeeded_items": sidecar_success,
            "sidecar_plain_text_nonempty_files": sidecar_plain_text,
            "sidecar_structured_recovered_files": sidecar_structured,
            "merge_would_merge_entities": would_merge,
            "poster_text_gate_met": bool(poster_preflight.get("text_gate_met")),
        },
        "blockers": blockers,
        "root_cause": [
            "PRD-13 extractor is wired to the official OCR file index only.",
            "Recovered Dajiala sidecar process outputs prove some OCR execution occurred.",
            "Those sidecar outputs are not indexed as complete OCR rows and do not currently expose structured recovered venue/date/lineup fields.",
        ],
        "process_audit": process_audit,
        "evidence": {
            "extraction_decision": extraction.get("decision"),
            "merge_decision": merge.get("decision"),
            "poster_preflight_decision": poster_preflight.get("decision"),
            "ocr_index_status_counts": ocr_index.get("ocr_status_counts"),
        },
        "next_safe_actions": [
            "Build a report-only sidecar OCR structured-field audit/adapter before any graph write.",
            "Do not use article text or OCR plain_text as venue/date/lineup entities without a source-backed parser/review gate.",
            "Keep Neo4j merge in dry-run until at least 10 real OCR venue/date/artist rows exist.",
        ],
        "safety": {
            "report_only": True,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "ocr_execution": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "production_write_executed": False,
        },
        "writes": "reports_only",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 OCR Reflow Readiness",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- reflow_allowed: `{report['reflow_allowed']}`",
        "",
        "## Gates",
        "",
    ]
    for key, value in report["gates"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Blockers", ""])
    for blocker in report["blockers"]:
        lines.append(f"- {blocker}")
    lines.extend(["", "## Root Cause", ""])
    for item in report["root_cause"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Sidecar OCR Audit", ""])
    process = report["process_audit"]
    for key in ("status_file_count", "total_items", "succeeded_items", "poster_ocr_seen", "plain_text_nonempty", "recovered_nonempty_files"):
        lines.append(f"- {key}: `{process.get(key)}`")
    lines.extend(["", "## Next Safe Actions", ""])
    for item in report["next_safe_actions"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only.",
            "- Reads official PRD-13 reports and bounded local C: recovered-process status directories.",
            "- No OCR execution, graph/vector/DB write, paid API, publish, or D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    process_audit = audit_process_status_dirs(args.ocr_root, max_items=args.max_sidecar_items)
    report = build_audit(
        read_json(args.extraction_summary),
        read_json(args.merge_report),
        read_json(args.ocr_index_summary),
        read_json(args.poster_preflight),
        process_audit,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "ocr_reflow_readiness.json", report)
    write_markdown(args.out_dir / "ocr_reflow_readiness.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "reflow_allowed": report["reflow_allowed"],
                "blockers": report["blockers"],
                "report": str(args.out_dir / "ocr_reflow_readiness.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--ocr-root", type=Path, default=DEFAULT_OCR_ROOT)
    parser.add_argument("--extraction-summary", type=Path, default=DEFAULT_EXTRACTION)
    parser.add_argument("--merge-report", type=Path, default=DEFAULT_MERGE)
    parser.add_argument("--ocr-index-summary", type=Path, default=DEFAULT_OCR_INDEX_SUMMARY)
    parser.add_argument("--poster-preflight", type=Path, default=DEFAULT_POSTER_PREFLIGHT)
    parser.add_argument("--max-sidecar-items", type=int, default=0)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
