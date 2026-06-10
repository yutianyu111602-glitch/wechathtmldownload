#!/usr/bin/env python3
"""Review the PRD-13 OCR entity merge plan before any Neo4j staging apply."""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_ENTITY_EXTRACTION = Path(
    "reports/dajiala_paid_wave01_04_verified_ocr_entity_extraction_20260516/ocr_entity_extraction_summary.json"
)
DEFAULT_MERGE_REPORT = Path(
    "reports/dajiala_paid_wave01_04_verified_ocr_entity_merge_20260516/ocr_entity_merge_report.json"
)
DEFAULT_OUT_DIR = Path("reports/ocr_entity_merge_review_packet_20260517")
SCHEMA_VERSION = "stage7_ocr_entity_merge_review_packet.v1"
PLAN_ROW_SCHEMA = "stage7_ocr_entity_neo4j_merge.v1.plan_row"
REQUIRED_LABELS = ["Stage7Staging", "OcrPosterEntity"]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"invalid JSONL row at {path}:{line_no}")
            rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def resolve_plan_path(merge_report: dict[str, Any], root: Path) -> Path:
    raw = str(merge_report.get("plan_path") or "").strip()
    if not raw:
        return Path()
    path = Path(raw)
    return path if path.is_absolute() else root / path


def first_text(value: Any) -> str:
    return str(value or "").strip()


def validate_plan_rows(rows: list[dict[str, Any]], run_id: str, root: Path) -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = []
    merge_keys = [first_text(row.get("merge_key")) for row in rows]
    type_counts = Counter(first_text(row.get("entity_type")) for row in rows)
    label_counts = Counter(tuple(row.get("staging_labels") or []) for row in rows)
    source_exists = 0
    confidence_values: list[float] = []
    bad_rows = Counter()

    for row in rows:
        if row.get("schema_version") != PLAN_ROW_SCHEMA:
            bad_rows["schema_version"] += 1
        if first_text(row.get("run_id")) != run_id:
            bad_rows["run_id"] += 1
        if (row.get("staging_labels") or []) != REQUIRED_LABELS:
            bad_rows["staging_labels"] += 1
        if first_text(row.get("mutation_status")) != "dry_run_only":
            bad_rows["mutation_status"] += 1
        for key in ("ocr_entity_id", "merge_key", "entity_type", "entity_name", "source_article_uid", "source_account"):
            if not first_text(row.get(key)):
                bad_rows[f"missing_{key}"] += 1
        source_path = Path(first_text(row.get("source_poster_ocr_path")))
        if not source_path.is_absolute():
            source_path = root / source_path
        resolved = str(source_path.resolve()).replace("\\", "/").lower()
        root_resolved = str(root.resolve()).replace("\\", "/").lower()
        if not resolved.startswith(root_resolved + "/reports/"):
            bad_rows["source_path_outside_reports"] += 1
        if source_path.exists():
            source_exists += 1
        else:
            bad_rows["missing_source_poster_ocr_path"] += 1
        try:
            confidence_values.append(float(row.get("confidence") or 0.0))
        except (TypeError, ValueError):
            bad_rows["invalid_confidence"] += 1

    if not rows:
        blockers.append("merge plan is empty")
    if len(set(merge_keys)) != len(merge_keys):
        blockers.append("merge plan contains duplicate merge_key rows")
    if bad_rows:
        blockers.extend(f"{key}: {value}" for key, value in sorted(bad_rows.items()))
    stats = {
        "plan_rows": len(rows),
        "unique_merge_keys": len(set(merge_keys)),
        "entity_type_counts": dict(type_counts),
        "staging_label_counts": {"/".join(key): value for key, value in label_counts.items()},
        "source_poster_ocr_paths_exist": source_exists,
        "confidence_min": min(confidence_values) if confidence_values else None,
        "confidence_max": max(confidence_values) if confidence_values else None,
    }
    return stats, blockers


def build_packet(
    *,
    entity_extraction_path: Path,
    merge_report_path: Path,
    out_dir: Path,
    root: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    extraction = read_json(entity_extraction_path)
    merge = read_json(merge_report_path)
    plan_path = resolve_plan_path(merge, root)
    plan_rows = read_jsonl(plan_path) if plan_path else []
    run_id = first_text(merge.get("run_id"))
    plan_stats, row_blockers = validate_plan_rows(plan_rows, run_id, root)
    blockers: list[str] = []
    if extraction.get("decision") != "ocr_entity_extraction_ready" or not extraction.get("gate_met"):
        blockers.append("OCR entity extraction gate is not ready")
    if merge.get("decision") != "ocr_entity_merge_dry_run_ready" or merge.get("mutation_executed"):
        blockers.append("OCR entity merge dry-run gate is not ready")
    if int(merge.get("would_merge_entities") or 0) != len(plan_rows):
        blockers.append("merge report would_merge_entities does not match plan row count")
    if int(extraction.get("entity_count") or 0) != int(merge.get("entities_seen") or 0):
        blockers.append("extraction entity_count does not match merge entities_seen")
    if int((merge.get("skipped") or {}).get("duplicate_merge_key") or 0) != int(extraction.get("entity_count") or 0) - len(plan_rows):
        blockers.append("duplicate_merge_key count does not reconcile extraction rows and plan rows")
    blockers.extend(row_blockers)
    blockers = list(dict.fromkeys(blockers))
    accepted = not blockers and len(plan_rows) > 0
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": accepted,
        "decision": "ocr_entity_merge_review_accepted_for_staging" if accepted else "ocr_entity_merge_review_blocked",
        "entity_extraction_path": str(entity_extraction_path),
        "merge_report_path": str(merge_report_path),
        "plan_path": str(plan_path),
        "run_id": run_id,
        "entities_seen": int(merge.get("entities_seen") or 0),
        "would_merge_entities": int(merge.get("would_merge_entities") or 0),
        "accepted_plan_rows": len(plan_rows) if accepted else 0,
        "review_checks": {
            "extraction_ready": extraction.get("decision") == "ocr_entity_extraction_ready" and bool(extraction.get("gate_met")),
            "merge_dry_run_ready": merge.get("decision") == "ocr_entity_merge_dry_run_ready" and not bool(merge.get("mutation_executed")),
            "plan_count_matches": int(merge.get("would_merge_entities") or 0) == len(plan_rows),
            "duplicate_count_reconciles": int((merge.get("skipped") or {}).get("duplicate_merge_key") or 0)
            == int(extraction.get("entity_count") or 0) - len(plan_rows),
            "staging_labels_only": plan_stats["staging_label_counts"] == {"Stage7Staging/OcrPosterEntity": len(plan_rows)},
            "source_paths_exist": plan_stats["source_poster_ocr_paths_exist"] == len(plan_rows),
        },
        "plan_stats": plan_stats,
        "blockers": blockers,
        "safety": {
            "review_only": True,
            "neo4j_write_executed": False,
            "production_label_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "publish_executed": False,
        },
        "writes": "reports_only",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "ocr_entity_merge_review_packet.json", packet)
    write_markdown(out_dir / "ocr_entity_merge_review_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# OCR Entity Merge Review Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- run_id: `{packet['run_id']}`",
        f"- accepted_plan_rows: `{packet['accepted_plan_rows']}`",
        f"- would_merge_entities: `{packet['would_merge_entities']}`",
        "",
        "## Blockers",
        "",
    ]
    if packet["blockers"]:
        for blocker in packet["blockers"]:
            lines.append(f"- {blocker}")
    else:
        lines.append("- none")
    lines.extend(["", "## Entity Types", ""])
    for key, value in sorted((packet["plan_stats"].get("entity_type_counts") or {}).items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity-extraction", type=Path, default=DEFAULT_ENTITY_EXTRACTION)
    parser.add_argument("--merge-report", type=Path, default=DEFAULT_MERGE_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--root", type=Path, default=Path("."))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(
        entity_extraction_path=args.entity_extraction,
        merge_report_path=args.merge_report,
        out_dir=args.out_dir,
        root=args.root,
    )
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "accepted_plan_rows": packet["accepted_plan_rows"],
                "blockers": packet["blockers"],
                "summary": str(args.out_dir / "ocr_entity_merge_review_packet.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if packet["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
