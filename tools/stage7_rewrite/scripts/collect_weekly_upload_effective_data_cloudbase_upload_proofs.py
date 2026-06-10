#!/usr/bin/env python3
"""Collect CloudBase-current and uploaded-version proofs for weekly data.

This consumes existing hotfix/release-guard evidence. It does not sync
CloudBase, upload a mini-program, deploy CloudRun, mutate databases, call
providers/models, or read credentials.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
REPORTS_MD_ROOT = REPO_ROOT / "reports"

SCHEMA_VERSION = "weekly_upload_effective_data_cloudbase_upload_proofs.v1"
DECISION_PASS = "weekly_upload_effective_data_cloudbase_upload_proofs_collected_remote_effective_5_of_5"
DECISION_BLOCKED = "weekly_upload_effective_data_cloudbase_upload_proofs_blocked_or_incomplete"

DEFAULT_EXECUTION_GATE = (
    REPORTS_ROOT
    / "weekly_upload_effective_data_proof_execution_gate_20260603"
    / "weekly_upload_effective_data_proof_execution_gate.json"
)
DEFAULT_DEVTOOLS_PROOF = (
    REPORTS_ROOT
    / "weekly_upload_effective_data_proof_execution_20260603_devtools"
    / "weekly_upload_effective_data_devtools_render_proof.json"
)
DEFAULT_HOTFIX_CONSUMPTION = (
    REPORTS_ROOT
    / "weekly_cloudbase_ai_health_guard_20260602_20260602_154701"
    / "miniprogram_frontend_resource_hotfix_20260603_consumption_status.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_upload_effective_data_proof_execution_20260603_cloudbase_upload"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_UPLOAD_EFFECTIVE_DATA_CLOUDBASE_UPLOAD_PROOFS_20260603.md"

EXPECTED_ITEM_COUNT = 78
EXPECTED_UPLOAD_VERSION = "2026.06.03.0148"


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def analyze_cloudbase_current(hotfix: dict[str, Any]) -> dict[str, Any]:
    package = hotfix.get("package_cloudrun_cloudbase", {}) if isinstance(hotfix.get("package_cloudrun_cloudbase"), dict) else {}
    cloudbase_events = int(package.get("cloudbase_events") or 0)
    cloudbase_read_total = int(package.get("cloudbase_read_total") or 0)
    old_count = int(package.get("old_20260529_item_count") or 0)
    gates = {
        "sync_id_present": bool(str(package.get("cloudbase_syncId") or "").strip()),
        "cloudbase_events_at_least_78": cloudbase_events >= EXPECTED_ITEM_COUNT,
        "cloudbase_read_source_database": str(package.get("cloudbase_read_source") or "") == "cloudbase-database",
        "cloudbase_read_total_at_least_78": cloudbase_read_total >= EXPECTED_ITEM_COUNT,
        "old_20260529_absent": old_count == 0,
        "cities_present": int(package.get("cloudbase_cities") or 0) > 0,
        "ai_summary_present": int(package.get("cloudbase_aiSummary") or 0) > 0,
    }
    return {
        "proof_id": "remote_effective:cloudbase_database_current",
        "status": "proven" if all(gates.values()) else "blocked",
        "gates": gates,
        "cloudbase_syncId": package.get("cloudbase_syncId", ""),
        "cloudbase_events": cloudbase_events,
        "cloudbase_cities": int(package.get("cloudbase_cities") or 0),
        "cloudbase_aiSummary": int(package.get("cloudbase_aiSummary") or 0),
        "cloudbase_read_source": package.get("cloudbase_read_source", ""),
        "cloudbase_read_total": cloudbase_read_total,
        "old_20260529_item_count": old_count,
        "generated_at": package.get("generated_at", ""),
        "window_start": package.get("window_start", ""),
        "window_end": package.get("window_end", ""),
    }


def analyze_uploaded_version(hotfix: dict[str, Any]) -> dict[str, Any]:
    upload = hotfix.get("mini_program_dev_upload", {}) if isinstance(hotfix.get("mini_program_dev_upload"), dict) else {}
    version = str(upload.get("version") or "")
    upload_buffer_size = int(upload.get("upload_buffer_size") or 0)
    gates = {
        "uploaded_true": bool(upload.get("uploaded")),
        "version_present": bool(version),
        "expected_version": version == EXPECTED_UPLOAD_VERSION,
        "upload_buffer_nonzero": upload_buffer_size > 0,
        "review_not_submitted": upload.get("review_submitted") is False,
        "public_release_not_executed": upload.get("public_release_executed") is False,
    }
    return {
        "proof_id": "remote_effective:miniprogram_uploaded_version",
        "status": "proven" if all(gates.values()) else "blocked",
        "gates": gates,
        "version": version,
        "uploaded": bool(upload.get("uploaded")),
        "upload_buffer_size": upload_buffer_size,
        "review_submitted": upload.get("review_submitted"),
        "public_release_executed": upload.get("public_release_executed"),
    }


def build_report(
    *,
    execution_gate: dict[str, Any],
    devtools_proof: dict[str, Any],
    hotfix_consumption: dict[str, Any],
) -> dict[str, Any]:
    cloudbase_proof = analyze_cloudbase_current(hotfix_consumption)
    upload_proof = analyze_uploaded_version(hotfix_consumption)
    previous_proven = int(devtools_proof.get("summary", {}).get("remote_effective_total_proven_count") or 0)
    proof_delta = sum(1 for proof in (cloudbase_proof, upload_proof) if proof["status"] == "proven")
    total_proven = previous_proven + proof_delta
    release_blockers = [
        "coordinate_freshness_latest_claim: source-fetch blocker follow-up still has 12 rows pending accepted no-fetch disposition, manual source evidence review, or explicit authenticated/source-cache release",
        "coordinate_freshness_latest_claim: 59 registry rows still require manual approval/rejection artifact",
        "coordinate_freshness_latest_claim: 7 address/provider rows still require review and later provider/coordinate acceptance gate",
        "atlas_relation_field_integrity: db3_same_normalized_name_multi_id=348, approved_for_s232d4=0",
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": DECISION_PASS if total_proven == 5 else DECISION_BLOCKED,
        "source_execution_gate_decision": execution_gate.get("decision", ""),
        "source_execution_gate_release_id": execution_gate.get("release_id", ""),
        "upstream_devtools_proof": str(DEFAULT_DEVTOOLS_PROOF),
        "hotfix_consumption_status": str(DEFAULT_HOTFIX_CONSUMPTION),
        "proofs": [cloudbase_proof, upload_proof],
        "summary": {
            "remote_effective_total_required_proofs": 5,
            "remote_effective_total_proven_count": total_proven,
            "remote_effective_total_remaining_count": max(0, 5 - total_proven),
            "cloudbase_database_current_proven": cloudbase_proof["status"] == "proven",
            "miniprogram_uploaded_version_proven": upload_proof["status"] == "proven",
            "upload_effective_data_proof_complete": total_proven == 5,
            "miniprogram_upload_allowed_now": False,
            "review_release_allowed_now": False,
            "release_ready": False,
            "remaining_remote_effective_proofs": [] if total_proven == 5 else [
                proof["proof_id"] for proof in (cloudbase_proof, upload_proof) if proof["status"] != "proven"
            ],
            "remaining_release_blockers": release_blockers,
        },
        "boundary": {
            "cloudbase_evidence_consumed": True,
            "upload_metadata_consumed": True,
            "cloudbase_sync_executed_by_this_collector": False,
            "cloudbase_write_executed": False,
            "cloudrun_deployed": False,
            "database_mutations": False,
            "coordinate_writes": False,
            "package_rebuild_executed": False,
            "miniprogram_upload_executed_by_this_collector": False,
            "review_submitted": False,
            "public_release_executed": False,
            "credential_or_secret_read": False,
            "browser_cookie_or_profile_read": False,
            "docker_or_worker_started": False,
            "provider_or_model_call": False,
        },
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    summary = report["summary"]
    cloudbase = report["proofs"][0]
    upload = report["proofs"][1]
    lines = [
        "# Weekly Upload Effective Data CloudBase And Upload Proofs",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Decision: `{report['decision']}`",
        "",
        "## Summary",
        "",
        f"- Remote-effective proofs proven: `{summary['remote_effective_total_proven_count']}/5`",
        f"- Upload/effective-data proof complete: `{str(summary['upload_effective_data_proof_complete']).lower()}`",
        f"- Release ready: `{str(summary['release_ready']).lower()}`",
        f"- Remaining release blockers: `{len(summary['remaining_release_blockers'])}`",
        "",
        "## CloudBase Current",
        "",
        f"- Sync id: `{cloudbase['cloudbase_syncId']}`",
        f"- Events: `{cloudbase['cloudbase_events']}`",
        f"- Cities: `{cloudbase['cloudbase_cities']}`",
        f"- AI summary: `{cloudbase['cloudbase_aiSummary']}`",
        f"- Read source: `{cloudbase['cloudbase_read_source']}`",
        f"- Read total: `{cloudbase['cloudbase_read_total']}`",
        f"- Old 2026-05-29 item count: `{cloudbase['old_20260529_item_count']}`",
        "",
        "## Uploaded Version",
        "",
        f"- Version: `{upload['version']}`",
        f"- Uploaded: `{str(upload['uploaded']).lower()}`",
        f"- Upload buffer size: `{upload['upload_buffer_size']}`",
        f"- Review submitted: `{str(upload['review_submitted']).lower()}`",
        f"- Public release executed: `{str(upload['public_release_executed']).lower()}`",
        "",
        "## Boundary",
        "",
        "This artifact consumes existing CloudBase/current and upload metadata evidence. It does not sync CloudBase, upload, deploy, mutate DB/coordinates, start Docker/worker, call providers/models, read credentials, submit review, or release.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-gate", type=Path, default=DEFAULT_EXECUTION_GATE)
    parser.add_argument("--devtools-proof", type=Path, default=DEFAULT_DEVTOOLS_PROOF)
    parser.add_argument("--hotfix-consumption", type=Path, default=DEFAULT_HOTFIX_CONSUMPTION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    execution_gate = read_json(args.execution_gate)
    devtools_proof = read_json(args.devtools_proof)
    hotfix_consumption = read_json(args.hotfix_consumption)
    report = build_report(
        execution_gate=execution_gate,
        devtools_proof=devtools_proof,
        hotfix_consumption=hotfix_consumption,
    )
    json_path = args.out_dir / "weekly_upload_effective_data_cloudbase_upload_proofs.json"
    write_json(json_path, report)
    write_scorecard(args.scorecard, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "remote_effective_total_proven_count": report["summary"]["remote_effective_total_proven_count"],
                "remote_effective_total_remaining_count": report["summary"]["remote_effective_total_remaining_count"],
                "upload_effective_data_proof_complete": report["summary"]["upload_effective_data_proof_complete"],
                "release_ready": report["summary"]["release_ready"],
                "json": str(json_path),
                "markdown": str(args.scorecard),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["decision"] == DECISION_PASS else 1


if __name__ == "__main__":
    raise SystemExit(main())
