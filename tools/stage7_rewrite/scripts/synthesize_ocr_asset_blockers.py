#!/usr/bin/env python3
"""Synthesize remaining PRD-05a OCR asset-source blockers.

This report-only script reads existing Stage7 OCR recovery reports and separates
external paid Dajiala blockers from non-paid/local image-source blockers.

No Dajiala calls, OCR execution, graph/vector/DB writes, paid API calls, D: scan,
publish, or source/archive mutation.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_COVERAGE = Path(
    "reports/ocr_root_cause_20260515/"
    "corrected_full_stable_extract_v30_deepseek_recovered1217_20260515/"
    "coverage_vs_fixed_routes.json"
)
DEFAULT_STABLE_MERGE = Path(
    "reports/ocr_root_cause_20260515/"
    "corrected_full_stable_extract_v30_deepseek_recovered1217_20260515/"
    "stable_merge_summary.json"
)
DEFAULT_NON_DAJIALA = Path("reports/ocr_root_cause_20260515/non_dajiala_recoverability_audit_v30_20260515/summary.json")
DEFAULT_DAJIALA_WAVE = Path(
    "reports/ocr_root_cause_20260515/empty_no_local_image_dajiala_repair_archive_wave029_20260515"
)
DEFAULT_OUT_DIR = Path("reports/ocr_asset_blocker_synthesis_20260515")
SCHEMA_VERSION = "stage7_ocr_asset_blocker_synthesis.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_broad_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} refuses broad D root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses banned D subtree: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_broad_d_path(path, "json")
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_broad_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def nested_get(value: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def summarize_dajiala_wave(wave_dir: Path) -> dict[str, Any]:
    reject_broad_d_path(wave_dir, "wave_dir")
    status_path = wave_dir / "dajiala-repair-status.json"
    results_path = wave_dir / "dajiala-repair-results.jsonl"
    status = read_json(status_path) if status_path.exists() else {}
    rows = read_jsonl(results_path)
    status_counts = Counter(str(row.get("status") or "unknown") for row in rows)
    error_types = Counter(str(row.get("error_type") or "unknown") for row in rows if row.get("error_type"))
    error_messages = Counter(str(row.get("error_message") or row.get("message") or "") for row in rows)
    error_messages.pop("", None)
    amount_not_enough = any("金额不足" in msg for msg in error_messages)
    status_items = status.get("items") if isinstance(status.get("items"), list) else []
    status_failed = sum(1 for item in status_items if item.get("status") == "failed")
    return {
        "wave_dir": str(wave_dir),
        "status_path": str(status_path),
        "results_path": str(results_path),
        "status_file_status": status.get("status"),
        "status_items": len(status_items),
        "status_failed_items": status_failed,
        "result_rows": len(rows),
        "result_status_counts": dict(status_counts),
        "error_type_counts": dict(error_types),
        "error_message_counts": dict(error_messages.most_common(5)),
        "amount_not_enough": amount_not_enough,
        "status_file_stale_running_with_failed_results": status.get("status") == "running" and status_failed > 0,
    }


def build_report(
    coverage: dict[str, Any],
    stable_merge: dict[str, Any],
    non_dajiala: dict[str, Any],
    dajiala_wave: dict[str, Any],
) -> dict[str, Any]:
    missing = int(nested_get(coverage, ("totals", "fixed_route_missing_from_v30_unique"), 0) or 0)
    stable_unique = int(coverage.get("stable_unique") or stable_merge.get("articles") or 0)
    empty_lane = coverage.get("lanes", {}).get("empty_no_local_image") or {}
    recovered_empty = int((stable_merge.get("lane_counts") or {}).get("empty_no_local_image") or 0)
    field_counts = non_dajiala.get("field_positive_counts") or {}
    non_paid_image_fields = [
        "existing_local_image_count_gt0",
        "local_image_count_gt0",
        "remote_image_count_gt0",
        "archive_asset_image_count_gt0",
        "processed_asset_image_count_gt0",
        "sidecar_image_count_gt0",
    ]
    non_paid_image_evidence = any(int(field_counts.get(key) or 0) > 0 for key in non_paid_image_fields)
    paid_blocked = bool(dajiala_wave.get("amount_not_enough"))
    blockers: list[str] = []
    if missing > 0:
        blockers.append(f"{missing} fixed-route rows remain missing after v30")
    if not non_paid_image_evidence:
        blockers.append("non-Dajiala remaining lane has no source-backed local/remote/archive image evidence")
    if paid_blocked:
        blockers.append("Dajiala paid repair wave is blocked by external account balance")
    if dajiala_wave.get("status_file_stale_running_with_failed_results"):
        blockers.append("wave029 status file is stale/running while result rows show failed balance errors")

    non_paid_unblock_options = []
    if non_paid_image_evidence:
        non_paid_unblock_options.append("build a bounded local image rebuild canary from positive image evidence")
    else:
        non_paid_unblock_options.extend(
            [
                "do not run OCR on article text or empty assets",
                "only reopen local-image OCR if a new source-backed image field appears",
                "sidecar OCR text/entity reports may support review contracts but do not repair missing local images",
            ]
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "ocr_asset_recovery_blocked_external_paid_and_no_nonpaid_image_source",
        "recovery_can_continue_without_new_source": False,
        "stable_unique": stable_unique,
        "fixed_route_missing": missing,
        "empty_no_local_image": {
            "all_unique": empty_lane.get("all_unique"),
            "remaining_unique": empty_lane.get("remaining_unique"),
            "covered_by_v30_unique": empty_lane.get("covered_by_v30_unique"),
            "missing_from_v30_unique": empty_lane.get("missing_from_v30_unique"),
            "recovered_empty_no_local_image": recovered_empty,
            "sample_missing": empty_lane.get("sample_missing"),
        },
        "non_dajiala": {
            "missing_count": non_dajiala.get("missing_count"),
            "field_positive_counts": field_counts,
            "image_evidence_present": non_paid_image_evidence,
            "top_accounts": non_dajiala.get("top_accounts"),
        },
        "dajiala_wave": dajiala_wave,
        "blockers": blockers,
        "non_paid_unblock_options": non_paid_unblock_options,
        "allowed_next_actions": [
            "keep OCR/vector stages blocked until a source-backed image or explicit sidecar bridge contract exists",
            "resume paid Dajiala waves only after balance/key gate is green",
            "use sidecar OCR text/entity reports as review evidence only, not as image-asset recovery",
        ],
        "forbidden_next_actions": [
            "do_not_continue_paid_dajiala_waves_while_amount_not_enough",
            "do_not_fake_ocr_from_article_text",
            "do_not_run_ocr_without_source_backed_images",
            "do_not_scan_broad_d_drive",
            "do_not_write_source_archive_or_production_outputs",
        ],
        "safety": [
            "reports_only",
            "existing_stage7_reports_only",
            "no_dajiala_call",
            "no_ocr_execution",
            "no_graph_vector_db_write",
            "no_source_archive_mutation",
            "no_paid_api",
            "no_d_scan",
            "no_publish",
        ],
        "writes": "reports_only",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# PRD-05a OCR Asset Blocker Synthesis",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- stable_unique: `{report['stable_unique']}`",
        f"- fixed_route_missing: `{report['fixed_route_missing']}`",
        f"- recovery_can_continue_without_new_source: `{report['recovery_can_continue_without_new_source']}`",
        "",
        "## Empty No Local Image",
        "",
    ]
    for key, value in report["empty_no_local_image"].items():
        if key != "sample_missing":
            lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Non-Dajiala", ""])
    lines.append(f"- missing_count: `{report['non_dajiala']['missing_count']}`")
    lines.append(f"- image_evidence_present: `{report['non_dajiala']['image_evidence_present']}`")
    lines.extend(["", "## Dajiala Wave", ""])
    wave = report["dajiala_wave"]
    for key in (
        "status_file_status",
        "status_items",
        "status_failed_items",
        "result_rows",
        "result_status_counts",
        "amount_not_enough",
        "status_file_stale_running_with_failed_results",
    ):
        lines.append(f"- {key}: `{wave.get(key)}`")
    lines.extend(["", "## Blockers", ""])
    for blocker in report["blockers"]:
        lines.append(f"- {blocker}")
    lines.extend(["", "## Non-Paid Options", ""])
    for item in report["non_paid_unblock_options"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Forbidden Next Actions", ""])
    for item in report["forbidden_next_actions"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Safety", ""])
    for item in report["safety"]:
        lines.append(f"- {item}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report = build_report(
        coverage=read_json(args.coverage),
        stable_merge=read_json(args.stable_merge),
        non_dajiala=read_json(args.non_dajiala),
        dajiala_wave=summarize_dajiala_wave(args.dajiala_wave_dir),
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "ocr_asset_blocker_synthesis.json", report)
    write_markdown(args.out_dir / "ocr_asset_blocker_synthesis.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "fixed_route_missing": report["fixed_route_missing"],
                "recovery_can_continue_without_new_source": report["recovery_can_continue_without_new_source"],
                "report": str(args.out_dir / "ocr_asset_blocker_synthesis.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--stable-merge", type=Path, default=DEFAULT_STABLE_MERGE)
    parser.add_argument("--non-dajiala", type=Path, default=DEFAULT_NON_DAJIALA)
    parser.add_argument("--dajiala-wave-dir", type=Path, default=DEFAULT_DAJIALA_WAVE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
