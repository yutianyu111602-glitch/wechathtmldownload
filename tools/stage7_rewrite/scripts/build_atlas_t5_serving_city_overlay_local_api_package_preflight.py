#!/usr/bin/env python3
"""Roll up the city-overlay local API smoke and package context preflight.

This gate binds the report-local serving city overlay candidate to the actual
CloudRun service code path after the short-city fallback fix. It does not deploy
or upload public state; it records the exact local API/browser smoke and package
context contract needed for a later explicit publish gate.
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

DEFAULT_API_SMOKE = REPO_ROOT / "reports" / "atlas_serving_city_overlay_local_api_smoke_20260527_0813" / "api_smoke.json"
DEFAULT_BROWSER_SMOKE = REPO_ROOT / "reports" / "atlas_serving_city_overlay_local_api_smoke_20260527_0813" / "browser_smoke.json"
DEFAULT_SHORT_CITY_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t5_serving_city_overlay_short_city_search_gate_20260527"
    / "serving_city_overlay_short_city_search_gate_summary.json"
)
DEFAULT_CONTEXT_REPORT = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_city_overlay_cloudrun_context_20260527_0816"
    / "atlas_serving_sqlite_cloudrun_context.json"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t5_serving_city_overlay_local_api_package_preflight_20260527"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "ATLAS_T5_SERVING_CITY_OVERLAY_LOCAL_API_PACKAGE_PREFLIGHT_20260527.md"

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


def city_counts(api_smoke: dict[str, Any]) -> dict[str, int]:
    searches = api_smoke.get("city_event_searches")
    if not isinstance(searches, dict):
        return {
            "city_query_rows": 0,
            "city_event_result_rows": 0,
            "city_event_match_rows": 0,
            "city_event_failed_rows": 1,
        }
    result_rows = 0
    match_rows = 0
    failed = 0
    for row in searches.values():
        if not isinstance(row, dict):
            failed += 1
            continue
        result_count = int(row.get("result_count") or 0)
        match_count = int(row.get("event_city_match_rows") or 0)
        result_rows += result_count
        match_rows += match_count
        if result_count <= 0 or match_count <= 0:
            failed += 1
    return {
        "city_query_rows": len(searches),
        "city_event_result_rows": result_rows,
        "city_event_match_rows": match_rows,
        "city_event_failed_rows": failed,
    }


def build_preflight(
    *,
    api_smoke_path: Path,
    browser_smoke_path: Path,
    short_city_summary_path: Path,
    context_report_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    api_smoke = read_json(api_smoke_path)
    browser_smoke = read_json(browser_smoke_path)
    short_city_summary = read_json(short_city_summary_path)
    context_report = read_json(context_report_path)

    api_total, api_passed, failed_api_checks = count_checks(api_smoke)
    browser_total, browser_passed, failed_browser_checks = count_checks(browser_smoke)
    city = city_counts(api_smoke)
    short_counts = short_city_summary.get("counts") if isinstance(short_city_summary.get("counts"), dict) else {}
    context_ok = bool(context_report.get("ok")) and context_report.get("decision") == "atlas_serving_sqlite_cloudrun_context_ready"
    short_city_ok = (
        short_city_summary.get("decision") == "atlas_t5_serving_city_overlay_short_city_search_gate_ready_report_only"
        and not short_city_summary.get("failed_checks")
        and int(short_counts.get("direct_city_fallback_match_rows") or 0) > 0
    )

    failed_checks: list[str] = []
    if failed_api_checks or not api_smoke.get("ok"):
        failed_checks.append("local_api_smoke_failed")
    if failed_browser_checks or not browser_smoke.get("ok"):
        failed_checks.append("browser_smoke_failed")
    if city["city_event_failed_rows"]:
        failed_checks.append("city_event_search_failed")
    if not short_city_ok:
        failed_checks.append("short_city_fallback_gate_not_ready")
    if not context_ok:
        failed_checks.append("cloudrun_context_not_ready")

    candidate_db = normalize_rel(str(api_smoke.get("candidate_db") or ""))
    context_dir = normalize_rel(str(context_report.get("context_dir") or ""))
    staged_candidate = context_report.get("candidate") if isinstance(context_report.get("candidate"), dict) else {}
    sidecars = context_report.get("sidecars") if isinstance(context_report.get("sidecars"), dict) else {}
    sidecar_copied = sum(1 for row in sidecars.values() if isinstance(row, dict) and row.get("copied"))

    counts = {
        "api_checks_total": api_total,
        "api_checks_passed": api_passed,
        "browser_checks_total": browser_total,
        "browser_checks_passed": browser_passed,
        **city,
        "short_city_fallback_match_rows": int(short_counts.get("direct_city_fallback_match_rows") or 0),
        "short_city_unique_terms": int(short_counts.get("unique_city_terms") or 0),
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
        "schema_version": "stage7_atlas_t5_serving_city_overlay_local_api_package_contract.v1",
        "candidate_db": candidate_db,
        "cloudrun_context_dir": context_dir,
        "staged_candidate_db": normalize_rel(str(staged_candidate.get("staged_path") or "")),
        "candidate_db_sha256": staged_candidate.get("sha256", ""),
        "required_runtime_behavior": {
            "short_cjk_city_query": "HTTP search kind=events must return event rows with exact item.city",
            "serving_db_mode": "read_only_serving_sqlite",
            "post_deploy_smoke_required": [
                "GET /healthz",
                "GET /api/v1/stage7/manifest",
                "GET /api/v1/stage7/search?q=深圳&kind=events",
                "GET /api/v1/stage7/search?q=上海&kind=events",
                "GET /api/v1/stage7/graph/profile?q=MaFoL",
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
            "short_city_summary": rel(short_city_summary_path),
            "context_report": rel(context_report_path),
            "contract": contract,
        }
    )
    if any(leak_scan.values()):
        failed_checks.append("report_leak_scan_hits_present")

    decision = (
        "atlas_t5_serving_city_overlay_local_api_package_preflight_ready_report_only"
        if not failed_checks
        else "atlas_t5_serving_city_overlay_local_api_package_preflight_blocked_report_only"
    )
    summary = {
        "schema_version": "stage7_atlas_t5_serving_city_overlay_local_api_package_preflight.v1.summary",
        "generated_at": now_stamp(),
        "decision": decision,
        "failed_checks": sorted(set(failed_checks)),
        "counts": counts,
        "inputs": {
            "api_smoke": rel(api_smoke_path),
            "browser_smoke": rel(browser_smoke_path),
            "short_city_summary": rel(short_city_summary_path),
            "cloudrun_context_report": rel(context_report_path),
        },
        "outputs": {
            "summary_json": rel(out_dir / "serving_city_overlay_local_api_package_preflight_summary.json"),
            "contract": rel(out_dir / "serving_city_overlay_local_api_package_contract.json"),
            "report": rel(report_path),
        },
        "boundary_truth": boundary,
        "leak_scan": leak_scan,
        "next_resume_pointer": (
            rel(out_dir / "serving_city_overlay_local_api_package_preflight_summary.json")
            + ". Next: keep huaidj.club upload closed; continue T6 exact-date/source-OCR recovery or another gap closure lane until public upload is explicitly re-enabled."
        ),
    }

    write_json(out_dir / "serving_city_overlay_local_api_package_preflight_summary.json", summary)
    write_json(out_dir / "serving_city_overlay_local_api_package_contract.json", contract)
    report_lines = [
        "# ATLAS T5 Serving City Overlay Local API Package Preflight 20260527",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{decision}`",
        f"- failed_checks: `{summary['failed_checks']}`",
        f"- candidate_db: `{candidate_db}`",
        f"- cloudrun_context_dir: `{context_dir}`",
        f"- API checks passed/total: `{api_passed}/{api_total}`",
        f"- Browser checks passed/total: `{browser_passed}/{browser_total}`",
        f"- City event searches: `{city['city_event_match_rows']}/{city['city_event_result_rows']}` exact-city result rows across `{city['city_query_rows']}` queries",
        f"- Short-city fallback rows: `{counts['short_city_fallback_match_rows']}` across `{counts['short_city_unique_terms']}` city terms",
        f"- Package context ready rows: `{counts['package_context_ready_rows']}`; sidecars copied: `{sidecar_copied}`",
        f"- Leak hits public_url/sensitive_key/local_path: `{leak_scan['public_url_hits']}/{leak_scan['sensitive_key_hits']}/{leak_scan['local_path_hits']}`",
        "",
        "## LLM Audit",
        "",
        "The previous SQL-only gate was not enough for promotion because it proved the candidate table state but not the HTTP service path. This packet binds the same overlay candidate to the service API, browser page, short-city fallback behavior, and a prepared local CloudRun context. Public upload remains closed by user instruction, so this is a local package-ready contract rather than a deployment.",
        "",
        "## Boundary",
        "",
        "- Local API/browser smoke executed against the report-local overlay candidate only.",
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
    parser.add_argument("--short-city-summary", type=Path, default=DEFAULT_SHORT_CITY_SUMMARY)
    parser.add_argument("--context-report", type=Path, default=DEFAULT_CONTEXT_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_preflight(
        api_smoke_path=args.api_smoke,
        browser_smoke_path=args.browser_smoke,
        short_city_summary_path=args.short_city_summary,
        context_report_path=args.context_report,
        out_dir=args.out_dir,
        report_path=args.report_path,
    )
    print(json.dumps({"decision": summary["decision"], "failed_checks": summary["failed_checks"]}, ensure_ascii=False))
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
