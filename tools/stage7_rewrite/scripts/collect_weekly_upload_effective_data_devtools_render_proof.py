#!/usr/bin/env python3
"""Collect the DevTools rendered proof for weekly upload/effective-data state.

This consumes existing DevTools report artifacts. It does not launch DevTools,
upload a mini-program, deploy CloudRun, sync CloudBase, mutate databases, call
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

SCHEMA_VERSION = "weekly_upload_effective_data_devtools_render_proof.v1"
DECISION_PASS = "weekly_upload_effective_data_devtools_render_proof_collected_remote_effective_3_of_5"
DECISION_BLOCKED = "weekly_upload_effective_data_devtools_render_proof_blocked_or_incomplete"

DEFAULT_EXECUTION_GATE = (
    REPORTS_ROOT
    / "weekly_upload_effective_data_proof_execution_gate_20260603"
    / "weekly_upload_effective_data_proof_execution_gate.json"
)
DEFAULT_PUBLIC_PROOFS = (
    REPORTS_ROOT
    / "weekly_upload_effective_data_proof_execution_20260603_public"
    / "weekly_upload_effective_data_public_proofs.json"
)
DEFAULT_RENDERED_AUDIT = (
    REPORTS_ROOT
    / "weekly_miniprogram_devtools_rendered_coverage_s34_20260531"
    / "weekly_miniprogram_devtools_rendered_coverage_audit.json"
)
DEFAULT_SINGLE_ATTEMPT = (
    REPORTS_ROOT
    / "weekly_miniprogram_devtools_single_attempt_20260603_frontend_hotfix"
    / "weekly_miniprogram_devtools_rendered_single_attempt.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "weekly_upload_effective_data_proof_execution_20260603_devtools"
DEFAULT_SCORECARD = REPORTS_MD_ROOT / "WEEKLY_UPLOAD_EFFECTIVE_DATA_DEVTOOLS_RENDER_PROOF_20260603.md"

EXPECTED_ITEM_COUNT = 78
STALE_DATE = "2026-05-29"
REQUIRED_DATES = ["2026-06-02", "2026-06-03"]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def latest_current_package_report() -> Path:
    artifact_root = REPO_ROOT / "apps" / "weekly_activity_miniprogram" / "test-artifacts"
    candidates = [
        path / "report.json"
        for path in artifact_root.glob("devtools-current-package-rendered-*")
        if path.is_dir() and (path / "report.json").exists()
    ]
    if not candidates:
        raise FileNotFoundError("no devtools-current-package-rendered report.json found")
    return max(candidates, key=lambda path: (path.stat().st_mtime_ns, str(path)))


def first_step(report: dict[str, Any]) -> dict[str, Any]:
    steps = report.get("steps")
    if not isinstance(steps, list) or not steps or not isinstance(steps[0], dict):
        return {}
    return steps[0]


def analyze_render_report(report: dict[str, Any]) -> dict[str, Any]:
    step = first_step(report)
    dates = [str(value) for value in step.get("dates", [])] if isinstance(step.get("dates"), list) else []
    item_count = int(step.get("itemCount") or 0)
    total_items = int(step.get("totalItems") or 0)
    popular_count = int(step.get("popularItemCount") or 0)
    poster_cover_count = int(step.get("posterCoverCount") or 0)
    poster_load_count = int(step.get("posterImageLoadCount") or 0)
    poster_error_count = int(step.get("posterImageErrorCount") or 0)
    exceptions = report.get("exceptions") if isinstance(report.get("exceptions"), list) else []
    gates = {
        "item_count_at_least_78": item_count >= EXPECTED_ITEM_COUNT,
        "total_items_at_least_78": total_items >= EXPECTED_ITEM_COUNT,
        "stale_20260529_absent": STALE_DATE not in dates,
        "required_dates_present": all(date in dates for date in REQUIRED_DATES),
        "cache_notice_absent": str(step.get("cacheNotice") or "") == "",
        "poster_cover_values_present": poster_cover_count > 0 and poster_cover_count >= min(8, popular_count),
        "poster_image_load_event_present": poster_load_count >= 1,
        "poster_image_error_absent": poster_error_count == 0,
        "runtime_exceptions_absent": len(exceptions) == 0,
    }
    return {
        "proof_id": "remote_effective:miniprogram_render_after_storage_clear",
        "status": "proven" if all(gates.values()) else "blocked",
        "gates": gates,
        "item_count": item_count,
        "total_items": total_items,
        "dates": dates,
        "contains_2026_05_29": STALE_DATE in dates,
        "required_dates_present": [date for date in REQUIRED_DATES if date in dates],
        "cache_notice": str(step.get("cacheNotice") or ""),
        "popular_item_count": popular_count,
        "poster_cover_count": poster_cover_count,
        "poster_image_load_count": poster_load_count,
        "poster_image_error_count": poster_error_count,
        "poster_image_loaded_ids": step.get("posterImageLoadedIds", []) if isinstance(step.get("posterImageLoadedIds"), list) else [],
        "poster_image_error_urls": step.get("posterImageErrorUrls", []) if isinstance(step.get("posterImageErrorUrls"), list) else [],
        "console_count": int(report.get("consoleCount") or 0),
        "exception_count": len(exceptions),
    }


def analyze_audit(audit: dict[str, Any], report_path: Path) -> dict[str, Any]:
    artifacts = audit.get("artifacts") if isinstance(audit.get("artifacts"), list) else []
    current_artifact = next(
        (
            item
            for item in artifacts
            if item.get("script") == "devtools-current-package-rendered.cjs"
        ),
        {},
    )
    latest_report = Path(str(current_artifact.get("latest_report") or ""))
    return {
        "decision": audit.get("decision", ""),
        "rendered_coverage_proven": bool(audit.get("rendered_coverage_proven")),
        "finding_count": int(audit.get("finding_count") or 0),
        "blocking_count": int(audit.get("blocking_count") or 0),
        "current_artifact_pass_count": int(audit.get("current_artifact_pass_count") or 0),
        "current_script_status": current_artifact.get("status", ""),
        "current_script_reason": current_artifact.get("reason", ""),
        "current_script_latest_report": str(current_artifact.get("latest_report") or ""),
        "audit_points_to_report": latest_report == report_path,
    }


def build_report(
    *,
    execution_gate: dict[str, Any],
    public_proofs: dict[str, Any],
    render_report: dict[str, Any],
    render_report_path: Path,
    rendered_audit: dict[str, Any],
    single_attempt: dict[str, Any] | None,
) -> dict[str, Any]:
    render_proof = analyze_render_report(render_report)
    audit_summary = analyze_audit(rendered_audit, render_report_path)
    public_proven_count = int(public_proofs.get("summary", {}).get("public_proof_proven_count") or 0)
    audit_gate_ok = (
        audit_summary["rendered_coverage_proven"]
        and audit_summary["blocking_count"] == 0
        and audit_summary["current_script_status"] == "report_passed"
        and audit_summary["audit_points_to_report"]
    )
    render_gate_ok = render_proof["status"] == "proven" and audit_gate_ok
    total_proven = public_proven_count + (1 if render_gate_ok else 0)
    single_attempt_summary = {
        "present": single_attempt is not None,
        "decision": single_attempt.get("decision", "") if single_attempt else "",
        "executed": bool(single_attempt.get("executed")) if single_attempt else False,
        "returncode": single_attempt.get("execution", {}).get("returncode") if single_attempt else None,
        "close_failure_tolerated_by_report": bool(
            single_attempt
            and single_attempt.get("decision") == "weekly_miniprogram_devtools_rendered_single_attempt_failed"
            and render_proof["status"] == "proven"
        ),
        "execution_summary_json": single_attempt.get("execution_summary_json", "") if single_attempt else "",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": DECISION_PASS if render_gate_ok else DECISION_BLOCKED,
        "source_execution_gate_decision": execution_gate.get("decision", ""),
        "source_execution_gate_release_id": execution_gate.get("release_id", ""),
        "upstream_public_proofs": str(DEFAULT_PUBLIC_PROOFS),
        "render_report": str(render_report_path),
        "rendered_audit": str(DEFAULT_RENDERED_AUDIT),
        "single_attempt": single_attempt_summary,
        "proofs": [render_proof],
        "audit_summary": audit_summary,
        "summary": {
            "remote_effective_total_required_proofs": 5,
            "remote_effective_total_proven_count": total_proven,
            "remote_effective_total_remaining_count": 5 - total_proven,
            "public_proof_proven_count": public_proven_count,
            "devtools_render_proof_proven": render_gate_ok,
            "remaining_proofs": [
                "remote_effective:cloudbase_database_current",
                "remote_effective:miniprogram_uploaded_version",
            ]
            if render_gate_ok
            else [
                "remote_effective:miniprogram_render_after_storage_clear",
                "remote_effective:cloudbase_database_current",
                "remote_effective:miniprogram_uploaded_version",
            ],
            "miniprogram_upload_allowed_now": False,
            "review_release_allowed_now": False,
            "release_ready": False,
        },
        "boundary": {
            "devtools_report_consumed": True,
            "devtools_executed_by_this_collector": False,
            "cloudbase_sync_executed": False,
            "cloudbase_write_executed": False,
            "cloudrun_deployed": False,
            "database_mutations": False,
            "coordinate_writes": False,
            "package_rebuild_executed": False,
            "miniprogram_upload_executed": False,
            "review_submitted": False,
            "public_release_executed": False,
            "credential_or_secret_read": False,
            "browser_cookie_or_profile_read": False,
            "docker_or_worker_started": False,
            "provider_or_model_call": False,
        },
    }


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    proof = report["proofs"][0]
    summary = report["summary"]
    lines = [
        "# Weekly Upload Effective Data DevTools Render Proof",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Decision: `{report['decision']}`",
        "",
        "## Summary",
        "",
        f"- Remote-effective proofs proven: `{summary['remote_effective_total_proven_count']}/5`",
        f"- Remaining proofs: `{', '.join(summary['remaining_proofs'])}`",
        f"- DevTools render proof proven: `{str(summary['devtools_render_proof_proven']).lower()}`",
        f"- Release ready: `{str(summary['release_ready']).lower()}`",
        "",
        "## Render Contract",
        "",
        f"- Item count: `{proof['item_count']}`",
        f"- Total items: `{proof['total_items']}`",
        f"- Dates: `{', '.join(proof['dates'])}`",
        f"- Contains 2026-05-29: `{str(proof['contains_2026_05_29']).lower()}`",
        f"- Cache notice: `{proof['cache_notice'] or '<empty>'}`",
        f"- Poster covers: `{proof['poster_cover_count']}`",
        f"- Poster image loads: `{proof['poster_image_load_count']}`",
        f"- Poster image errors: `{proof['poster_image_error_count']}`",
        f"- Exception count: `{proof['exception_count']}`",
        "",
        "## Boundary",
        "",
        "This artifact consumes an existing DevTools report. It does not upload, deploy, sync CloudBase, mutate DB/coordinates, start Docker/worker, call providers/models, read credentials, submit review, or release.",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-gate", type=Path, default=DEFAULT_EXECUTION_GATE)
    parser.add_argument("--public-proofs", type=Path, default=DEFAULT_PUBLIC_PROOFS)
    parser.add_argument("--render-report", type=Path, default=None)
    parser.add_argument("--rendered-audit", type=Path, default=DEFAULT_RENDERED_AUDIT)
    parser.add_argument("--single-attempt", type=Path, default=DEFAULT_SINGLE_ATTEMPT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    render_report_path = args.render_report or latest_current_package_report()
    execution_gate = read_json(args.execution_gate)
    public_proofs = read_json(args.public_proofs)
    render_report = read_json(render_report_path)
    rendered_audit = read_json(args.rendered_audit)
    single_attempt = read_json(args.single_attempt) if args.single_attempt.exists() else None
    report = build_report(
        execution_gate=execution_gate,
        public_proofs=public_proofs,
        render_report=render_report,
        render_report_path=render_report_path,
        rendered_audit=rendered_audit,
        single_attempt=single_attempt,
    )
    json_path = args.out_dir / "weekly_upload_effective_data_devtools_render_proof.json"
    write_json(json_path, report)
    write_scorecard(args.scorecard, report)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "remote_effective_total_proven_count": report["summary"]["remote_effective_total_proven_count"],
                "remote_effective_total_remaining_count": report["summary"]["remote_effective_total_remaining_count"],
                "devtools_render_proof_proven": report["summary"]["devtools_render_proof_proven"],
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
