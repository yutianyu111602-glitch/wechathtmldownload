from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from collections.abc import Iterable


DEFAULT_REPORTS_ROOT = Path("C:/code/githubstar/wechathtmldownload/tools/stage7_rewrite/reports")
DEFAULT_OUTPUT = Path("tools/stage7_rewrite/reports/db2_openclaw_artifact_scan_latest.json")

RUNTIME_RELEASE_PATTERNS = (
    "*direct*deepseek*materialization*runtime*release*.json",
    "*openclaw*direct*deepseek*materialization*release*.json",
)
RUNTIME_REPORT_PATTERNS = (
    "*direct*deepseek*materialization*runtime*summary*.json",
    "*openclaw*direct*deepseek*materialization*runtime*.json",
)
RUNTIME_PLAN_PATTERNS = (
    "*direct*deepseek*runtime*execution*plan*.json",
    "*direct*deepseek*materialization*runtime*execution*plan*.json",
)
CONTROLLER_APPROVAL_PATTERNS = (
    "*direct*deepseek*runtime*controller*approval*.json",
    "*direct*deepseek*materialization*runtime*approval*.json",
)


def load_json_if_possible(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def classify_artifact(path: Path, payload: dict[str, Any] | None) -> dict[str, Any]:
    decision = str((payload or {}).get("decision") or "")
    release_id = str((payload or {}).get("release_id") or (payload or {}).get("release", {}).get("release_id") or "")
    lower_name = path.name.lower()
    is_consumption_status = lower_name.endswith("_consumption_status.json")
    runtime_allowed = bool((payload or {}).get("runtime_execution_allowed_now") or (payload or {}).get("materialization_runtime_allowed_now"))
    runtime_executed = bool((payload or {}).get("runtime_executed") or (payload or {}).get("materialization_runtime_executed"))
    is_execution_plan = not is_consumption_status and decision == "openclaw_direct_deepseek_materialization_runtime_execution_plan_ready_report_only"
    is_controller_approval = not is_consumption_status and decision == "openclaw_direct_deepseek_materialization_runtime_controller_approval_ready_no_execution"
    is_release_candidate = (
        not is_consumption_status
        and not is_execution_plan
        and not is_controller_approval
        and "direct" in decision
        and "deepseek" in decision
        and "materialization" in decision
        and "release" in decision
    )
    is_runtime_report = (
        not is_consumption_status
        and not is_execution_plan
        and not is_controller_approval
        and not is_release_candidate
        and "direct" in decision
        and "deepseek" in decision
        and "materialization" in decision
        and "runtime" in decision
    )

    return {
        "path": str(path),
        "decision": decision,
        "release_id": release_id,
        "json_parse_ok": payload is not None,
        "is_consumption_status": is_consumption_status,
        "is_direct_deepseek_materialization_release_candidate": is_release_candidate,
        "is_direct_deepseek_materialization_runtime_report": is_runtime_report,
        "is_direct_deepseek_materialization_runtime_execution_plan": is_execution_plan,
        "is_direct_deepseek_materialization_runtime_controller_approval": is_controller_approval,
        "runtime_allowed": runtime_allowed,
        "runtime_executed": runtime_executed,
    }


def normalize_report_roots(reports_root: Path | Iterable[Path]) -> list[Path]:
    if isinstance(reports_root, (str, Path)):
        return [Path(reports_root)]
    return [Path(root) for root in reports_root]


def scan_artifacts(reports_root: Path | Iterable[Path], *, max_files: int = 200) -> dict[str, Any]:
    report_roots = normalize_report_roots(reports_root)
    matches: dict[str, Path] = {}
    scanned_roots: list[str] = []
    missing_roots: list[str] = []
    invalid_roots: list[str] = []
    max_files_reached = False
    for root in report_roots:
        if not root.exists():
            missing_roots.append(str(root))
            continue
        if not root.is_dir():
            invalid_roots.append(str(root))
            continue
        scanned_roots.append(str(root))
        for pattern in RUNTIME_RELEASE_PATTERNS + RUNTIME_REPORT_PATTERNS + RUNTIME_PLAN_PATTERNS + CONTROLLER_APPROVAL_PATTERNS:
            for path in root.glob(f"**/{pattern}"):
                if path.is_file():
                    matches[str(path)] = path
                if len(matches) >= max_files:
                    max_files_reached = True
                    break
            if max_files_reached:
                break
        if max_files_reached:
            break

    artifacts = [
        classify_artifact(path, load_json_if_possible(path))
        for path in sorted(matches.values(), key=lambda item: str(item).lower())
    ]
    release_candidates = [item for item in artifacts if item["is_direct_deepseek_materialization_release_candidate"]]
    runtime_reports = [item for item in artifacts if item["is_direct_deepseek_materialization_runtime_report"]]
    runtime_plans = [item for item in artifacts if item["is_direct_deepseek_materialization_runtime_execution_plan"]]
    controller_approvals = [item for item in artifacts if item["is_direct_deepseek_materialization_runtime_controller_approval"]]
    executable_releases = [
        item for item in release_candidates
        if item["runtime_allowed"] is True and item["runtime_executed"] is False
    ]
    json_parse_failed_count = len([item for item in artifacts if item["json_parse_ok"] is False])
    skipped_consumption_status_count = len([item for item in artifacts if item["is_consumption_status"]])
    unclassified_artifact_count = len([
        item for item in artifacts
        if not item["is_consumption_status"]
        and not item["is_direct_deepseek_materialization_release_candidate"]
        and not item["is_direct_deepseek_materialization_runtime_report"]
        and not item["is_direct_deepseek_materialization_runtime_execution_plan"]
        and not item["is_direct_deepseek_materialization_runtime_controller_approval"]
    ])

    if runtime_reports:
        next_action = "consume_direct_deepseek_materialization_runtime_report_read_only"
    elif controller_approvals:
        next_action = "run_controller_approval_runtime_execution_gate_verifier"
    elif runtime_plans:
        next_action = "wait_for_explicit_controller_approval_for_runtime_execution"
    elif executable_releases:
        next_action = "run_direct_deepseek_materialization_runtime_release_gate_verifier"
    else:
        next_action = "wait_for_explicit_direct_deepseek_materialization_runtime_release"

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reports_root": str(report_roots[0]) if report_roots else "",
        "reports_roots": [str(root) for root in report_roots],
        "scanned_roots": scanned_roots,
        "scanned_root_count": len(scanned_roots),
        "missing_roots": missing_roots,
        "missing_root_count": len(missing_roots),
        "invalid_roots": invalid_roots,
        "invalid_root_count": len(invalid_roots),
        "max_files": max_files,
        "max_files_reached": max_files_reached,
        "scanned_file_count": len(artifacts),
        "json_parse_failed_count": json_parse_failed_count,
        "skipped_consumption_status_count": skipped_consumption_status_count,
        "unclassified_artifact_count": unclassified_artifact_count,
        "direct_deepseek_materialization_release_candidate_count": len(release_candidates),
        "direct_deepseek_materialization_runtime_report_count": len(runtime_reports),
        "direct_deepseek_materialization_runtime_execution_plan_count": len(runtime_plans),
        "direct_deepseek_materialization_runtime_controller_approval_count": len(controller_approvals),
        "executable_release_candidate_count": len(executable_releases),
        "next_action": next_action,
        "read_only": True,
        "would_execute": False,
        "would_start_docker": False,
        "would_call_network_or_deepseek": False,
        "would_call_deepseek": False,
        "would_write_live_db": False,
        "would_write": False,
        "would_rebuild_package": False,
        "would_upload_or_release": False,
        "would_read_credentials": False,
        "artifacts": artifacts,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scan bounded OpenClaw report artifacts without executing runtime work")
    parser.add_argument("--reports-root", type=Path, action="append", default=None)
    parser.add_argument("--max-files", type=int, default=200)
    parser.add_argument("--output", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = scan_artifacts(args.reports_root or [DEFAULT_REPORTS_ROOT], max_files=args.max_files)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
