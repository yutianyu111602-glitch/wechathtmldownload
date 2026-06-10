#!/usr/bin/env python3
"""Build a report-only PRD-06 Dajiala ROI/budget gate packet.

This packet uses existing Dajiala canary, verified OCR index, and downstream
gate artifacts to decide whether more paid waves should run. It does not query
Dajiala balance and does not call any paid API.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CANARY = Path(
    "reports/ocr_root_cause_20260515/empty_no_local_image_dajiala_canary_20260515/dajiala_canary_report.json"
)
DEFAULT_ASSET_SYNTHESIS = Path("reports/ocr_asset_blocker_synthesis_20260515/ocr_asset_blocker_synthesis.json")
DEFAULT_VERIFIED_INDEX = Path(
    "reports/dajiala_paid_wave01_07_verified_combined_ocr_index_20260518/ocr_file_index_summary.json"
)
DEFAULT_POSTER_VECTOR_GATE = Path("reports/poster_vector_write_gate_packet_wave01_07_20260518/poster_vector_write_gate_packet.json")
DEFAULT_OCR_ENTITY_GATE = Path(
    "reports/ocr_entity_merge_write_gate_packet_wave01_07_20260518/ocr_entity_merge_write_gate_packet.json"
)
DEFAULT_PAID_EXECUTION_PACKET = Path(
    "reports/dajiala_paid_wave07_execution_packet_20260518/dajiala_paid_wave_execution_packet.json"
)
DEFAULT_UNFINISHED_AUDIT = Path("reports/unfinished_longrun_audit_20260518/unfinished_plan_audit.json")
DEFAULT_OUT_DIR = Path("reports/dajiala_roi_budget_gate_packet_20260518")
SCHEMA_VERSION = "stage7_dajiala_roi_budget_gate_packet.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Dajiala ROI budget gate: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def unique_nonempty(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def recursive_string_contains(value: Any, needles: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        low = value.casefold()
        return any(needle.casefold() in low for needle in needles)
    if isinstance(value, dict):
        return any(recursive_string_contains(item, needles) for item in value.values())
    if isinstance(value, list):
        return any(recursive_string_contains(item, needles) for item in value)
    return False


def rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def build_packet(
    *,
    canary_path: Path,
    asset_synthesis_path: Path,
    verified_index_path: Path,
    poster_vector_gate_path: Path,
    ocr_entity_gate_path: Path,
    paid_execution_packet_path: Path,
    unfinished_audit_path: Path,
    out_dir: Path,
    min_verified_rows_before_more_paid: int,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    canary = read_json(canary_path)
    asset = read_json(asset_synthesis_path)
    verified = read_json(verified_index_path)
    poster_gate = read_json(poster_vector_gate_path)
    entity_gate = read_json(ocr_entity_gate_path)
    paid_execution = read_json(paid_execution_packet_path)
    latest_archive_status_text = str(paid_execution.get("status_path") or "").strip()
    latest_archive_status_path = Path(latest_archive_status_text) if latest_archive_status_text else None
    if latest_archive_status_path and not latest_archive_status_path.is_absolute():
        latest_archive_status_path = Path.cwd() / latest_archive_status_path
    latest_archive_status = read_json(latest_archive_status_path) if latest_archive_status_path else {}
    unfinished_audit = read_json(unfinished_audit_path)

    unit_cost = float(canary.get("unit_cost") or 0.0)
    execution_unit_cost = float(paid_execution.get("unit_cost") or unit_cost or 0.0)
    success_rate = float(canary.get("success_rate") or 0.0)
    fixed_missing = int(asset.get("fixed_route_missing") or 0)
    known_unconsumed_queue_rows = int(
        (((unfinished_audit.get("current_status") or {}).get("dajiala") or {}).get("known_unconsumed_queue_rows"))
        or 0
    )
    verified_rows = int(verified.get("record_count") or 0)
    estimated_all_remaining_request_cost = unit_cost * fixed_missing if unit_cost and fixed_missing else None
    estimated_all_missing_cost_from_execution = (
        execution_unit_cost * fixed_missing if execution_unit_cost and fixed_missing else None
    )
    estimated_unconsumed_cost_from_execution = (
        execution_unit_cost * known_unconsumed_queue_rows
        if execution_unit_cost and known_unconsumed_queue_rows
        else None
    )
    estimated_successes_if_same_rate = fixed_missing * success_rate if fixed_missing and success_rate else None
    poster_gate_ready = poster_gate.get("decision") in {
        "poster_vector_write_gate_packet_ready_report_only",
        "poster_vectors_qdrant_staging_written",
    }
    entity_gate_ready = entity_gate.get("decision") in {
        "ocr_entity_merge_write_gate_packet_ready_report_only",
        "ocr_entity_merge_staging_written",
    }
    poster_hard_gates = list(poster_gate.get("hard_gates_remaining") or [])
    entity_hard_gates = list(entity_gate.get("hard_gates_remaining") or [])
    downstream_consumed = poster_gate_ready and entity_gate_ready and not poster_hard_gates and not entity_hard_gates
    historical_amount_not_enough = bool((asset.get("dajiala_wave") or {}).get("amount_not_enough"))
    latest_archive_completed = latest_archive_status.get("status") == "completed"
    latest_archive_amount_not_enough = recursive_string_contains(
        latest_archive_status,
        ("amount_not_enough", "not enough", "金额不足", "余额不足", "请充值", "recharge"),
    )
    current_amount_not_enough_blocker = historical_amount_not_enough and (
        not latest_archive_completed or latest_archive_amount_not_enough
    )
    local_ready_gates = {
        "canary_has_unit_cost": unit_cost > 0,
        "canary_has_success_rate": success_rate > 0,
        "verified_wave_rows_present": verified_rows >= min_verified_rows_before_more_paid,
        "verified_rows_consumed_by_prd12_prd13": downstream_consumed,
        "remaining_missing_count_known": fixed_missing > 0,
        "nonpaid_recovery_blocked": not bool(asset.get("recovery_can_continue_without_new_source")),
        "paid_api_not_called_in_this_packet": True,
    }
    hard_gates_remaining = unique_nonempty(
        [
            *(
                ["do not run more paid Dajiala waves until PRD-12/PRD-13 write gates are resolved or explicitly deferred"]
                if not downstream_consumed
                else []
            ),
            "Dajiala balance was not queried in this report-only packet",
            "fresh paid-wave budget cap is required before any next paid wave",
            "next paid wave must use signed long-link candidates only",
            "remaining non-Dajiala lane has no source-backed local/remote/archive image evidence",
            *(
                ["prior Dajiala wave had amount-not-enough failures"]
                if current_amount_not_enough_blocker
                else []
            ),
            *(
                ["poster vector write gate remains blocked"]
                if poster_gate_ready and poster_hard_gates
                else []
            ),
            *(
                ["OCR entity Neo4j write gate remains blocked"]
                if entity_gate_ready and entity_hard_gates
                else []
            ),
        ]
    )
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "dajiala_roi_budget_gate_packet_ready_report_only",
        "canary_path": str(canary_path),
        "asset_synthesis_path": str(asset_synthesis_path),
        "verified_index_path": str(verified_index_path),
        "poster_vector_gate_path": str(poster_vector_gate_path),
        "ocr_entity_gate_path": str(ocr_entity_gate_path),
        "paid_execution_packet_path": str(paid_execution_packet_path),
        "unfinished_audit_path": str(unfinished_audit_path),
        "paid_api_used": False,
        "balance_query_executed": False,
        "next_paid_wave_allowed": False,
        "roi_metrics": {
            "canary_total_requests": canary.get("total_requests"),
            "canary_success_count": canary.get("success_count"),
            "canary_failed_count": canary.get("failed_count"),
            "canary_success_rate": success_rate,
            "canary_unit_cost": unit_cost,
            "last_execution_unit_cost": execution_unit_cost,
            "verified_wave_rows": verified_rows,
            "verified_complete_rows": (verified.get("ocr_status_counts") or {}).get("complete"),
            "fixed_route_missing": fixed_missing,
            "known_unconsumed_queue_rows": known_unconsumed_queue_rows,
            "latest_archive_status": latest_archive_status.get("status"),
            "latest_archive_total": latest_archive_status.get("totalItems"),
            "latest_archive_succeeded": latest_archive_status.get("succeededCount"),
            "latest_archive_failed": latest_archive_status.get("failedCount"),
            "historical_amount_not_enough": historical_amount_not_enough,
            "latest_archive_amount_not_enough": latest_archive_amount_not_enough,
            "estimated_all_remaining_request_cost_from_canary_unit_cost": rounded(
                estimated_all_remaining_request_cost
            ),
            "estimated_all_missing_request_cost_from_execution_unit_cost": rounded(
                estimated_all_missing_cost_from_execution
            ),
            "estimated_unconsumed_request_cost_from_execution_unit_cost": rounded(
                estimated_unconsumed_cost_from_execution
            ),
            "estimated_successes_if_canary_rate_repeats": rounded(estimated_successes_if_same_rate),
        },
        "downstream_consumption": {
            "poster_vector_gate_ready": poster_gate_ready,
            "poster_vector_hard_gates_remaining": len(poster_hard_gates),
            "ocr_entity_gate_ready": entity_gate_ready,
            "ocr_entity_hard_gates_remaining": len(entity_hard_gates),
            "verified_rows_consumed_by_prd12_prd13": downstream_consumed,
        },
        "local_ready_gates": local_ready_gates,
        "local_ready_gate_count": sum(1 for value in local_ready_gates.values() if value),
        "hard_gates_remaining": hard_gates_remaining,
        "roi_policy_before_next_paid_wave": [
            f"consume or explicitly defer current verified {verified_rows} OCR rows in PRD-12/PRD-13 downstream write gates",
            "set a fresh max spend cap and stop-loss threshold before any paid request",
            "run a small signed-long-link-only sample first; stop if success rate drops below canary baseline",
            "do not spend on rows without source-backed image or signed long-link evidence",
        ],
        "forbidden_next_actions": [
            "do_not_call_dajiala_from_this_packet",
            "do_not_query_or_print_dajiala_key_or_balance",
            "do_not_spend_paid_budget_without_fresh_cap",
            "do_not_repair_non_signed_or_non_candidate_rows",
            "do_not_fake_ocr_from_article_text",
        ],
        "allowed_next_actions": [
            "use this packet as PRD-06 budget/ROI evidence",
            "defer more paid waves until write gates are resolved or an explicit ROI gate is opened",
            "prepare a future small paid sample only with signed long-link candidates and a hard cost cap",
        ],
        "safety": {
            "reports_only": True,
            "paid_api_used": False,
            "balance_query_executed": False,
            "secret_read_executed": False,
            "ocr_execution": False,
            "neo4j_write": False,
            "qdrant_write": False,
            "mem0_write": False,
            "d_scan": False,
            "publish": False,
        },
        "writes": "reports_only",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "dajiala_roi_budget_gate_packet.json", packet)
    write_markdown(out_dir / "dajiala_roi_budget_gate_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# Dajiala ROI Budget Gate Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- next_paid_wave_allowed: `{packet['next_paid_wave_allowed']}`",
        f"- paid_api_used: `{packet['paid_api_used']}`",
        f"- balance_query_executed: `{packet['balance_query_executed']}`",
        f"- local_ready_gate_count: `{packet['local_ready_gate_count']}`",
        "",
        "## ROI Metrics",
        "",
    ]
    for key, value in packet["roi_metrics"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Hard Gates Remaining", ""])
    for item in packet["hard_gates_remaining"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--canary", type=Path, default=DEFAULT_CANARY)
    parser.add_argument("--asset-synthesis", type=Path, default=DEFAULT_ASSET_SYNTHESIS)
    parser.add_argument("--verified-index", type=Path, default=DEFAULT_VERIFIED_INDEX)
    parser.add_argument("--poster-vector-gate", type=Path, default=DEFAULT_POSTER_VECTOR_GATE)
    parser.add_argument("--ocr-entity-gate", type=Path, default=DEFAULT_OCR_ENTITY_GATE)
    parser.add_argument("--paid-execution-packet", type=Path, default=DEFAULT_PAID_EXECUTION_PACKET)
    parser.add_argument("--unfinished-audit", type=Path, default=DEFAULT_UNFINISHED_AUDIT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--min-verified-rows-before-more-paid", type=int, default=20)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(
        canary_path=args.canary,
        asset_synthesis_path=args.asset_synthesis,
        verified_index_path=args.verified_index,
        poster_vector_gate_path=args.poster_vector_gate,
        ocr_entity_gate_path=args.ocr_entity_gate,
        paid_execution_packet_path=args.paid_execution_packet,
        unfinished_audit_path=args.unfinished_audit,
        out_dir=args.out_dir,
        min_verified_rows_before_more_paid=args.min_verified_rows_before_more_paid,
    )
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "next_paid_wave_allowed": packet["next_paid_wave_allowed"],
                "verified_wave_rows": packet["roi_metrics"]["verified_wave_rows"],
                "estimated_all_remaining_request_cost": packet["roi_metrics"][
                    "estimated_all_remaining_request_cost_from_canary_unit_cost"
                ],
                "hard_gates_remaining": len(packet["hard_gates_remaining"]),
                "summary": str(args.out_dir / "dajiala_roi_budget_gate_packet.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
