#!/usr/bin/env python3
"""Roll up the time-overlay local API smoke and package context preflight.

This gate binds the cumulative report-local serving time overlay candidate to
the local HTTP/browser smoke, search-date refresh evidence, and a prepared
CloudRun context. It does not deploy or upload public state.
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

DEFAULT_API_SMOKE = REPO_ROOT / "reports" / "atlas_serving_time_overlay_year_span_search_date_refresh_local_smoke_20260527_1804" / "api_smoke.json"
DEFAULT_BROWSER_SMOKE = REPO_ROOT / "reports" / "atlas_serving_time_overlay_year_span_search_date_refresh_local_smoke_20260527_1804" / "browser_smoke.json"
DEFAULT_REFRESH_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t5_serving_time_overlay_year_span_search_date_refresh_gate_20260527"
    / "serving_time_overlay_search_date_refresh_summary.json"
)
DEFAULT_CONTEXT_REPORT = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_time_year_span_overlay_cloudrun_context_20260527_1815"
    / "atlas_serving_sqlite_cloudrun_context.json"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t5_serving_time_overlay_year_span_local_api_package_preflight_20260527"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "ATLAS_T5_SERVING_TIME_OVERLAY_YEAR_SPAN_LOCAL_API_PACKAGE_PREFLIGHT_20260527.md"

PUBLIC_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|wx\.qq\.com", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\wsl|/mnt/|/home/)", re.IGNORECASE)
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|password|access[_-]?token|refresh[_-]?token|cookie|openid|unionid|fakeid)\s*[:=]",
    re.IGNORECASE,
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
    value = json.loads(path.read_text(encoding="utf-8-sig"))
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


def leak_scan_text(text: str) -> dict[str, int]:
    return {
        "public_url_hits": len(PUBLIC_URL_RE.findall(text)),
        "sensitive_key_hits": len(SENSITIVE_KEY_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def merge_leak_scans(*payloads: Any) -> dict[str, int]:
    text = "\n".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) for payload in payloads)
    return leak_scan_text(text)


def count_checks(payload: dict[str, Any]) -> tuple[int, int, list[str]]:
    checks = payload.get("checks") if isinstance(payload.get("checks"), dict) else {}
    failed = [str(name) for name, ok in checks.items() if not ok]
    return len(checks), len(checks) - len(failed), failed


def build_preflight(
    *,
    api_smoke_path: Path,
    browser_smoke_path: Path,
    refresh_summary_path: Path,
    context_report_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    api_smoke = read_json(api_smoke_path)
    browser_smoke = read_json(browser_smoke_path)
    refresh_summary = read_json(refresh_summary_path)
    context_report = read_json(context_report_path)

    api_total, api_passed, failed_api_checks = count_checks(api_smoke)
    browser_total, browser_passed, failed_browser_checks = count_checks(browser_smoke)
    refresh_counts = refresh_summary.get("counts") if isinstance(refresh_summary.get("counts"), dict) else {}
    context_ok = bool(context_report.get("ok")) and context_report.get("decision") == "atlas_serving_sqlite_cloudrun_context_ready"
    refresh_ok = (
        refresh_summary.get("decision") == "atlas_t5_serving_time_overlay_search_date_refresh_candidate_ready_report_local"
        and not refresh_summary.get("failed_checks")
        and int(refresh_counts.get("search_document_update_rows") or 0) > 0
        and int(refresh_counts.get("postwrite_search_text_date_match_rows") or 0)
        == int(refresh_counts.get("search_document_update_rows") or 0)
        and int(refresh_counts.get("postwrite_fts_date_match_rows") or 0)
        == int(refresh_counts.get("search_document_update_rows") or 0)
        and int(refresh_counts.get("table_count_drift_rows") or 0) == 0
    )

    candidate_db = normalize_rel(str(api_smoke.get("candidate_db") or ""))
    refresh_outputs = refresh_summary.get("outputs") if isinstance(refresh_summary.get("outputs"), dict) else {}
    refresh_candidate_db = normalize_rel(str(refresh_outputs.get("candidate_db") or ""))
    staged_candidate = context_report.get("candidate") if isinstance(context_report.get("candidate"), dict) else {}
    context_candidate_source = normalize_rel(str(staged_candidate.get("source") or ""))
    context_dir = normalize_rel(str(context_report.get("context_dir") or ""))
    sidecars = context_report.get("sidecars") if isinstance(context_report.get("sidecars"), dict) else {}
    sidecar_copied = sum(1 for row in sidecars.values() if isinstance(row, dict) and row.get("copied"))
    candidate_alignment = candidate_db == refresh_candidate_db == context_candidate_source

    failed_checks: list[str] = []
    if failed_api_checks or not api_smoke.get("ok"):
        failed_checks.append("local_api_smoke_failed")
    if failed_browser_checks or not browser_smoke.get("ok"):
        failed_checks.append("browser_smoke_failed")
    if not refresh_ok:
        failed_checks.append("search_date_refresh_gate_not_ready")
    if not context_ok:
        failed_checks.append("cloudrun_context_not_ready")
    if not candidate_alignment:
        failed_checks.append("candidate_db_alignment_failed")

    counts = {
        "api_checks_total": api_total,
        "api_checks_passed": api_passed,
        "browser_checks_total": browser_total,
        "browser_checks_passed": browser_passed,
        "search_document_update_rows": int(refresh_counts.get("search_document_update_rows") or 0),
        "postwrite_search_text_date_match_rows": int(refresh_counts.get("postwrite_search_text_date_match_rows") or 0),
        "postwrite_fts_date_match_rows": int(refresh_counts.get("postwrite_fts_date_match_rows") or 0),
        "table_count_drift_rows": int(refresh_counts.get("table_count_drift_rows") or 0),
        "input_changed_rows": int(refresh_counts.get("input_changed_rows") or 0),
        "candidate_db_alignment_rows": 1 if candidate_alignment else 0,
        "package_context_ready_rows": 1 if context_ok else 0,
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
        "schema_version": "stage7_atlas_t5_serving_time_overlay_local_api_package_contract.v1",
        "candidate_db": candidate_db,
        "cloudrun_context_dir": context_dir,
        "staged_candidate_db": normalize_rel(str(staged_candidate.get("staged_path") or "")),
        "candidate_db_sha256": staged_candidate.get("sha256", ""),
        "required_runtime_behavior": {
            "serving_db_mode": "read_only_serving_sqlite",
            "time_overlay_search_date_refresh_required": "event search text and FTS must contain refreshed date tokens for changed performance_event rows",
            "post_deploy_smoke_required": [
                "GET /healthz",
                "GET /api/v1/stage7/manifest",
                "GET /api/v1/stage7/search?q=MaFoL",
                "GET /api/v1/stage7/search?q=深圳&kind=events",
                "GET /api/v1/stage7/graph/profile?q=DaRou",
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
            "api_smoke": rel(api_smoke_path),
            "browser_smoke": rel(browser_smoke_path),
            "refresh_summary": rel(refresh_summary_path),
            "context_report": rel(context_report_path),
            "contract": contract,
        }
    )
    if any(leak_scan.values()):
        failed_checks.append("report_leak_scan_hits_present")

    decision = (
        "atlas_t5_serving_time_overlay_year_span_local_api_package_preflight_ready_report_only"
        if not failed_checks
        else "atlas_t5_serving_time_overlay_year_span_local_api_package_preflight_blocked_report_only"
    )
    summary = {
        "schema_version": "stage7_atlas_t5_serving_time_overlay_local_api_package_preflight.v1.summary",
        "generated_at": now_stamp(),
        "decision": decision,
        "failed_checks": sorted(set(failed_checks)),
        "counts": counts,
        "inputs": {
            "api_smoke": rel(api_smoke_path),
            "browser_smoke": rel(browser_smoke_path),
            "search_date_refresh_summary": rel(refresh_summary_path),
            "cloudrun_context_report": rel(context_report_path),
        },
        "outputs": {
            "summary_json": rel(out_dir / "serving_time_overlay_local_api_package_preflight_summary.json"),
            "contract": rel(out_dir / "serving_time_overlay_local_api_package_contract.json"),
            "report": rel(report_path),
        },
        "boundary_truth": boundary,
        "leak_scan": leak_scan,
        "next_resume_pointer": (
            rel(out_dir / "serving_time_overlay_local_api_package_preflight_summary.json")
            + ". Next: keep huaidj.club upload closed; continue remaining T6 span/source-context/source-OCR recovery or build another local Atlas data-quality lane."
        ),
    }

    write_json(out_dir / "serving_time_overlay_local_api_package_preflight_summary.json", summary)
    write_json(out_dir / "serving_time_overlay_local_api_package_contract.json", contract)
    report_lines = [
        "# ATLAS T5 Serving Time Overlay Year/Span Local API Package Preflight 20260527",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{decision}`",
        f"- failed_checks: `{summary['failed_checks']}`",
        f"- candidate_db: `{candidate_db}`",
        f"- cloudrun_context_dir: `{context_dir}`",
        f"- API checks passed/total: `{api_passed}/{api_total}`",
        f"- Browser checks passed/total: `{browser_passed}/{browser_total}`",
        f"- Search-date refresh rows: `{counts['search_document_update_rows']}`; search text/FTS date matches: `{counts['postwrite_search_text_date_match_rows']}/{counts['postwrite_fts_date_match_rows']}`",
        f"- Candidate alignment rows: `{counts['candidate_db_alignment_rows']}`; package context ready rows: `{counts['package_context_ready_rows']}`; sidecars copied: `{sidecar_copied}`",
        f"- Leak hits public_url/sensitive_key/local_path: `{leak_scan['public_url_hits']}/{leak_scan['sensitive_key_hits']}/{leak_scan['local_path_hits']}`",
        "",
        "## LLM Audit",
        "",
        "The refreshed cumulative time overlay candidate is now bound to the local HTTP API, browser page, search-date refresh evidence, and a prepared local CloudRun context. This is the right next gate after the source/raw time write because SQL row matches alone do not prove consumer behavior or package readiness. Public upload remains closed by user instruction, so this is a package-ready contract rather than a deployment.",
        "",
        "## Boundary",
        "",
        "- Local API/browser smoke executed against the report-local time overlay candidate only.",
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
    parser.add_argument("--api-smoke", type=Path, default=DEFAULT_API_SMOKE)
    parser.add_argument("--browser-smoke", type=Path, default=DEFAULT_BROWSER_SMOKE)
    parser.add_argument("--search-date-refresh-summary", type=Path, default=DEFAULT_REFRESH_SUMMARY)
    parser.add_argument("--context-report", type=Path, default=DEFAULT_CONTEXT_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_preflight(
        api_smoke_path=args.api_smoke,
        browser_smoke_path=args.browser_smoke,
        refresh_summary_path=args.search_date_refresh_summary,
        context_report_path=args.context_report,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps({"decision": summary["decision"], "failed_checks": summary["failed_checks"]}, ensure_ascii=False, indent=2))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
