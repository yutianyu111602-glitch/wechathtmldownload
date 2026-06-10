#!/usr/bin/env python3
"""Roll up the Atlas entity-merge second-pass local API/package preflight.

This gate binds the accepted DeepSeek Pro second-pass entity-merge sidecar to
the local Stage7 API/browser smoke and prepared CloudRun context. It does not
deploy or upload public state; it records the exact package contract required
for a later explicit publish gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = SCRIPT_DIR.parent

DEFAULT_VALIDATION = REPO_ROOT / "reports" / "atlas_entity_merge_validation_secondpass_current" / "entity_merge_validation_summary.json"
DEFAULT_API_SMOKE = REPO_ROOT / "reports" / "atlas_entity_merge_secondpass_local_smoke_current" / "api_smoke.json"
DEFAULT_BROWSER_SMOKE = REPO_ROOT / "reports" / "atlas_entity_merge_secondpass_local_smoke_current" / "browser_smoke.json"
DEFAULT_CONTEXT_REPORT = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_sqlite_cloudrun_context_entity_merge_secondpass_20260527_1625"
    / "atlas_serving_sqlite_cloudrun_context.json"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_entity_merge_secondpass_local_api_package_preflight_20260527"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "ATLAS_ENTITY_MERGE_SECONDPASS_LOCAL_API_PACKAGE_PREFLIGHT_20260527.md"

PUBLIC_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|wx\.qq\.com", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\wsl|/mnt/|/home/)", re.IGNORECASE)
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|password|access[_-]?token|refresh[_-]?token|cookie|openid|unionid|fakeid)\s*[:=]",
    re.IGNORECASE,
)

MOBILE_ENTITY_CHECKS = (
    "mobile_loopy_entity_merge",
    "mobile_oil_entity_merge_bounded",
    "mobile_all_query_to_venue",
    "mobile_all_id_to_venue",
    "mobile_all_sound_system",
    "public_payload_no_path_or_source_leak",
)


def now_stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT)).replace("/", "\\")
    except ValueError:
        digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
        return f"<external_path_hash:{digest}>"


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def normalize_rel(value: str) -> str:
    if not value:
        return ""
    path = Path(value)
    if path.is_absolute():
        return rel(path)
    return str(path).replace("/", "\\")


def count_checks(payload: dict[str, Any]) -> tuple[int, int, list[str]]:
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    failed = [str(name) for name, ok in checks.items() if not ok]
    return len(checks), len(checks) - len(failed), failed


def merge_leak_scans(*payloads: Any) -> dict[str, int]:
    text = "\n".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) for payload in payloads)
    return {
        "public_url_hits": len(PUBLIC_URL_RE.findall(text)),
        "sensitive_key_hits": len(SENSITIVE_KEY_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def known_cases_ok(validation: dict[str, Any]) -> tuple[int, int, list[str]]:
    cases = validation.get("known_cases") if isinstance(validation.get("known_cases"), list) else []
    failed: list[str] = []
    for row in cases:
        if not isinstance(row, dict):
            failed.append("malformed_known_case")
            continue
        if not row.get("ok"):
            failed.append(str(row.get("case") or "unknown_case"))
    return len(cases), len(cases) - len(failed), failed


def sidecar_status(context_report: dict[str, Any]) -> tuple[int, int, dict[str, str]]:
    sidecars = context_report.get("sidecars") if isinstance(context_report.get("sidecars"), dict) else {}
    sha_by_name: dict[str, str] = {}
    copied = 0
    for name, row in sidecars.items():
        if not isinstance(row, dict):
            continue
        if row.get("copied"):
            copied += 1
        sha_by_name[str(name)] = str(row.get("sha256") or "")
    return len(sidecars), copied, sha_by_name


def build_preflight(
    *,
    validation_path: Path,
    api_smoke_path: Path,
    browser_smoke_path: Path,
    context_report_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    validation = read_json(validation_path)
    api_smoke = read_json(api_smoke_path)
    browser_smoke = read_json(browser_smoke_path)
    context_report = read_json(context_report_path)

    api_total, api_passed, failed_api_checks = count_checks(api_smoke)
    browser_total, browser_passed, failed_browser_checks = count_checks(browser_smoke)
    known_total, known_passed, failed_known_cases = known_cases_ok(validation)
    sidecar_total, sidecar_copied, sidecar_sha = sidecar_status(context_report)

    validation_coverage = validation.get("coverage") if isinstance(validation.get("coverage"), dict) else {}
    validation_plan = validation.get("plan") if isinstance(validation.get("plan"), dict) else {}
    group_integrity = validation.get("group_integrity") if isinstance(validation.get("group_integrity"), dict) else {}
    context_candidate = context_report.get("candidate") if isinstance(context_report.get("candidate"), dict) else {}
    api_checks = api_smoke.get("checks") if isinstance(api_smoke.get("checks"), dict) else {}

    context_ok = bool(context_report.get("ok")) and context_report.get("decision") == "atlas_serving_sqlite_cloudrun_context_ready"
    validation_ok = (
        validation.get("decision") == "atlas_entity_merge_outputs_validated"
        and not validation.get("hard_blockers")
        and int(validation_coverage.get("missing_decisions") or 0) == 0
        and int(group_integrity.get("duplicate_subject_count") or 0) == 0
        and int(group_integrity.get("member_count_mismatch_count") or 0) == 0
        and int(group_integrity.get("forbidden_hit_count") or 0) == 0
        and failed_known_cases == []
    )
    mobile_failed = [name for name in MOBILE_ENTITY_CHECKS if not api_checks.get(name)]

    failed_checks: list[str] = []
    if not validation_ok:
        failed_checks.append("entity_merge_validation_not_ready")
    if failed_known_cases:
        failed_checks.append("known_case_failures_present")
    if failed_api_checks or not api_smoke.get("ok"):
        failed_checks.append("local_api_smoke_failed")
    if mobile_failed:
        failed_checks.append("mobile_entity_merge_checks_failed")
    if failed_browser_checks or not browser_smoke.get("ok"):
        failed_checks.append("browser_smoke_failed")
    if not context_ok:
        failed_checks.append("cloudrun_context_not_ready")
    if sidecar_copied < 2:
        failed_checks.append("required_sidecars_not_copied")

    candidate_db = normalize_rel(str(api_smoke.get("candidate_db") or context_candidate.get("source") or ""))
    context_dir = normalize_rel(str(context_report.get("context_dir") or ""))
    counts = {
        "api_checks_total": api_total,
        "api_checks_passed": api_passed,
        "browser_checks_total": browser_total,
        "browser_checks_passed": browser_passed,
        "mobile_entity_checks_total": len(MOBILE_ENTITY_CHECKS),
        "mobile_entity_checks_passed": len(MOBILE_ENTITY_CHECKS) - len(mobile_failed),
        "known_cases_total": known_total,
        "known_cases_passed": known_passed,
        "queue_rows": int(validation_coverage.get("queue_rows") or 0),
        "latest_execute_decisions": int(validation_coverage.get("latest_execute_decisions") or 0),
        "missing_decisions": int(validation_coverage.get("missing_decisions") or 0),
        "final_merge_groups": int(validation_plan.get("merge_groups") or 0),
        "merged_subjects": int(validation_plan.get("merged_subjects") or 0),
        "review_rows": int(validation_plan.get("review_rows") or 0),
        "split_rows": int(validation_plan.get("split_rows") or 0),
        "duplicate_subject_count": int(group_integrity.get("duplicate_subject_count") or 0),
        "member_count_mismatch_count": int(group_integrity.get("member_count_mismatch_count") or 0),
        "forbidden_hit_count": int(group_integrity.get("forbidden_hit_count") or 0),
        "package_context_ready_rows": 1 if context_ok else 0,
        "package_sidecars_total": sidecar_total,
        "package_sidecars_copied": sidecar_copied,
        "cloudrun_deploy_rows": 0,
        "huaidj_upload_rows": 0,
        "public_pointer_rows": 0,
        "graph_vector_write_rows": 0,
        "source_raw_write_rows": 0,
        "memory_write_rows": 0,
    }
    boundary = {
        "candidate_db_opened_by_local_service_read_only": True,
        "local_http_smoke_executed": True,
        "browser_smoke_executed": True,
        "cloudrun_context_prepared_local_only": context_ok,
        "cloudrun_or_vps_deploy_executed": False,
        "huaidj_club_upload_executed": False,
        "public_pointer_updated": False,
        "graph_vector_public_mutation_executed": False,
        "source_raw_db_write_executed": False,
        "selected_serving_db_mutated": False,
        "serving_rebuild_executed": False,
        "network_ocr_model_memory_executed": False,
    }
    contract = {
        "schema_version": "stage7_atlas_entity_merge_secondpass_local_api_package_contract.v1",
        "candidate_db": candidate_db,
        "cloudrun_context_dir": context_dir,
        "staged_candidate_db": normalize_rel(str(context_candidate.get("staged_path") or "")),
        "candidate_db_sha256": str(context_candidate.get("sha256") or ""),
        "sidecar_sha256": sidecar_sha,
        "required_runtime_behavior": {
            "entity_merge_sidecar": "read_only_sidecar_loaded_from_ATLAS_ENTITY_MERGE_GROUPS_PATH",
            "mobile_query_preference": "bare q labels such as ALL must prefer entity search before event-title noise",
            "bounded_profile_aggregation": "large venue/org merge groups must remain capped for mobile profile response latency",
            "public_payload": "no local path, sidecar filename, raw source URL, or source JSON leak",
            "post_deploy_smoke_required": [
                "GET /healthz",
                "GET /api/v1/stage7/manifest",
                "GET /api/v1/stage7/search?q=Loopy",
                "GET /api/v1/stage7/graph/profile?q=OIL",
                "GET /api/v1/stage7/graph/profile?q=ALL",
                "GET /atlas",
            ],
        },
        "rollback": {
            "preserve_previous_serving_context_required": True,
            "restore_previous_cloudrun_revision_required_before_public_pointer_change": True,
            "post_rollback_smoke_required": True,
        },
        "publication_boundary": {
            "package_ready_for_later_publish_gate": not failed_checks,
            "cloudrun_deploy_allowed_now": False,
            "huaidj_club_upload_allowed_now": False,
            "reason": "huaidj.club/public website upload remains disabled until explicit user re-enable",
        },
    }
    leak_scan = merge_leak_scans(
        {
            "candidate_db": candidate_db,
            "context_dir": context_dir,
            "validation": rel(validation_path),
            "api_smoke": rel(api_smoke_path),
            "browser_smoke": rel(browser_smoke_path),
            "context_report": rel(context_report_path),
            "contract": contract,
        }
    )
    if any(leak_scan.values()):
        failed_checks.append("report_leak_scan_hits_present")

    failed_checks = sorted(set(failed_checks))
    decision = (
        "atlas_entity_merge_secondpass_local_api_package_preflight_ready_report_only"
        if not failed_checks
        else "atlas_entity_merge_secondpass_local_api_package_preflight_blocked_report_only"
    )
    summary = {
        "schema_version": "stage7_atlas_entity_merge_secondpass_local_api_package_preflight.v1.summary",
        "generated_at": now_stamp(),
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "inputs": {
            "validation": rel(validation_path),
            "api_smoke": rel(api_smoke_path),
            "browser_smoke": rel(browser_smoke_path),
            "cloudrun_context_report": rel(context_report_path),
        },
        "outputs": {
            "summary_json": rel(out_dir / "entity_merge_secondpass_local_api_package_preflight_summary.json"),
            "contract": rel(out_dir / "entity_merge_secondpass_local_api_package_contract.json"),
            "report": rel(report_path),
        },
        "boundary_truth": boundary,
        "leak_scan": leak_scan,
        "next_resume_pointer": (
            rel(out_dir / "entity_merge_secondpass_local_api_package_preflight_summary.json")
            + ". Next: keep huaidj.club upload closed; continue T6 span/year/source-OCR recovery, avatar storage provenance, or another local data-quality lane until public upload is explicitly re-enabled."
        ),
    }

    write_json(out_dir / "entity_merge_secondpass_local_api_package_preflight_summary.json", summary)
    write_json(out_dir / "entity_merge_secondpass_local_api_package_contract.json", contract)
    report_lines = [
        "# ATLAS Entity Merge Second-Pass Local API Package Preflight 20260527",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{decision}`",
        f"- failed_checks: `{failed_checks}`",
        f"- candidate_db: `{candidate_db}`",
        f"- cloudrun_context_dir: `{context_dir}`",
        f"- API checks passed/total: `{api_passed}/{api_total}`",
        f"- Browser checks passed/total: `{browser_passed}/{browser_total}`",
        f"- Mobile entity checks passed/total: `{counts['mobile_entity_checks_passed']}/{counts['mobile_entity_checks_total']}`",
        f"- Known cases passed/total: `{known_passed}/{known_total}`",
        f"- Final merge groups / merged subjects: `{counts['final_merge_groups']}/{counts['merged_subjects']}`",
        f"- Review/split rows: `{counts['review_rows']}/{counts['split_rows']}`",
        f"- Missing decisions / hard blockers: `{counts['missing_decisions']}/{validation.get('hard_blockers') or []}`",
        f"- Package context ready rows: `{counts['package_context_ready_rows']}`; sidecars copied: `{sidecar_copied}/{sidecar_total}`",
        f"- Leak hits public_url/sensitive_key/local_path: `{leak_scan['public_url_hits']}/{leak_scan['sensitive_key_hits']}/{leak_scan['local_path_hits']}`",
        "",
        "## LLM Audit",
        "",
        "The second-pass Pro route is the safer accepted route because Flash was more aggressive on ambiguous mixed-type clusters. This packet verifies that the accepted sidecar is not just valid JSONL: it is bound to the local HTTP service, mobile query behavior, browser surface, and local package context. Public upload remains closed by user instruction, so this is a local package-ready contract rather than a deployment.",
        "",
        "## Boundary",
        "",
        "- Local API/browser smoke executed against the selected serving DB with report-local sidecars.",
        "- CloudRun context was prepared locally only; no CloudRun/VPS deploy, huaidj.club upload, public pointer mutation, graph/vector write, selected serving mutation, source/raw DB write, OCR/network/model call, memory write, credential read, 9router use, destructive Git, or D-root scan occurred.",
        "",
        f"Next resume pointer: `{summary['next_resume_pointer']}`",
        "",
    ]
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(report_lines), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation", type=Path, default=DEFAULT_VALIDATION)
    parser.add_argument("--api-smoke", type=Path, default=DEFAULT_API_SMOKE)
    parser.add_argument("--browser-smoke", type=Path, default=DEFAULT_BROWSER_SMOKE)
    parser.add_argument("--context-report", type=Path, default=DEFAULT_CONTEXT_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_preflight(
        validation_path=args.validation,
        api_smoke_path=args.api_smoke,
        browser_smoke_path=args.browser_smoke,
        context_report_path=args.context_report,
        out_dir=args.out_dir,
        report_path=args.report_path,
    )
    print(json.dumps({"decision": summary["decision"], "failed_checks": summary["failed_checks"]}, ensure_ascii=False))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
