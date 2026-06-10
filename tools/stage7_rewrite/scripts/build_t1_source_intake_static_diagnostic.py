#!/usr/bin/env python3
"""Build a no-secret T1 source-intake diagnostic from existing artifacts."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_REGISTRY = Path("tools/stage7_rewrite/registries/weekly_accounts_seed.json")
DEFAULT_PRE_REFRESH = Path(
    "tools/stage7_rewrite/reports/t1_exporter_queue_refresh_20260523_132824/pre_refresh_summary.json"
)
DEFAULT_VALIDATION = Path(
    "tools/stage7_rewrite/reports/t1_exporter_queue_refresh_20260523_132824/"
    "validate_weekly_daily_queue_refresh.json"
)
DEFAULT_OUT_DIR = Path("reports/t1_source_intake_static_diagnostic_20260525_2218")
DEFAULT_TOP_REPORT = Path("reports/ATLAS_T1_SOURCE_INTAKE_STATIC_DIAGNOSTIC_20260525.md")


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON: {path}")
    return data


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def account_summary(registry: dict[str, Any]) -> dict[str, Any]:
    accounts = registry.get("accounts") if isinstance(registry.get("accounts"), list) else []
    statuses: Counter[str] = Counter()
    missing_fakeid: list[str] = []
    export_incomplete = 0
    for account in accounts:
        if not isinstance(account, dict):
            continue
        status = str(account.get("status") or "unknown")
        statuses[status] += 1
        if not str(account.get("fakeid") or "").strip():
            missing_fakeid.append(str(account.get("account_id") or account.get("account_name") or "unknown"))
        if account.get("export_completed") is False:
            export_incomplete += 1
    active_like = sum(count for status, count in statuses.items() if status not in {"inactive", "closed"})
    return {
        "registry_schema_version": registry.get("schema_version"),
        "registry_updated_at": registry.get("updated_at"),
        "account_count": len(accounts),
        "active_like_count": active_like,
        "status_counts": dict(sorted(statuses.items())),
        "missing_fakeid_count": len(missing_fakeid),
        "missing_fakeid_account_ids": missing_fakeid,
        "export_completed_false_count": export_incomplete,
    }


def build_report(
    *,
    registry_path: Path,
    pre_refresh_path: Path,
    validation_path: Path,
    generated_at: datetime | None = None,
    stale_hours: int = 24,
) -> dict[str, Any]:
    now = generated_at or datetime.now()
    registry = load_json(registry_path)
    pre_refresh = load_json(pre_refresh_path)
    validation = load_json(validation_path)
    validation_at = parse_datetime(validation.get("generated_at"))
    validation_age_hours = None
    if validation_at is not None:
        validation_age_hours = round((now - validation_at).total_seconds() / 3600, 2)
    validation_ok = bool(validation.get("ok"))
    validation_stale = validation_age_hours is None or validation_age_hours > stale_hours
    pre_refresh_invalid_session = (
        str(pre_refresh.get("exporter_errors_sample") or "").lower().find("invalid session") >= 0
        or int(pre_refresh.get("exporter_accounts_failed") or 0) > 0
    )
    if validation_ok and not validation_stale:
        decision = "t1_source_intake_fresh_effective_report_only"
    elif validation_ok:
        decision = "t1_source_intake_stale_but_last_refresh_effective_report_only"
    else:
        decision = "t1_source_intake_blocked_report_only"

    return {
        "schema_version": "t1_source_intake_static_diagnostic.v1",
        "generated_at": now.isoformat(timespec="seconds"),
        "decision": decision,
        "no_secret_mode": True,
        "inputs": {
            "registry": str(registry_path),
            "pre_refresh_summary": str(pre_refresh_path),
            "queue_refresh_validation": str(validation_path),
        },
        "account_registry": account_summary(registry),
        "previous_queue_refresh": {
            "validation_ok": validation_ok,
            "validation_decision": validation.get("decision"),
            "validation_generated_at": validation.get("generated_at"),
            "validation_age_hours": validation_age_hours,
            "validation_stale_hours_threshold": stale_hours,
            "validation_stale": validation_stale,
            "rows_written": validation.get("rows_written"),
            "exporter_refresh_requested": validation.get("exporter_refresh_requested"),
            "exporter_accounts_ok": validation.get("exporter_accounts_ok"),
            "exporter_accounts_failed": validation.get("exporter_accounts_failed"),
            "exporter_article_rows": validation.get("exporter_article_rows"),
            "pre_refresh_invalid_session_seen": pre_refresh_invalid_session,
            "pre_refresh_accounts_requested": pre_refresh.get("accounts_requested"),
            "pre_refresh_account_dirs_missing": pre_refresh.get("account_dirs_missing"),
            "pre_refresh_missing_account_ids": pre_refresh.get("missing_account_ids") or [],
        },
        "handoff": {
            "t2_package_ready": validation_ok and not validation_stale,
            "t4_new_to_atlas_diff_ready": validation_ok and not validation_stale,
            "requires_fresh_exporter_probe_before_next_package": validation_stale or not validation_ok,
            "stop_reason": ""
            if validation_ok
            else "previous queue refresh validation is not effective; exporter/session diagnosis required",
            "wait_reason": ""
            if validation_ok and not validation_stale
            else "latest effective T1 queue evidence is stale for a new daily package; refresh requires no-secret session gate",
        },
        "boundaries": {
            "exporter_called": False,
            "cookie_or_env_secret_read": False,
            "d_drive_scanned": False,
            "production_mutation": False,
            "cloudrun_deploy": False,
            "mini_program_upload_or_review": False,
            "atlas_db_or_graph_write": False,
        },
    }


def write_markdown(path: Path, report: dict[str, Any], summary_path: Path) -> None:
    registry = report["account_registry"]
    refresh = report["previous_queue_refresh"]
    handoff = report["handoff"]
    boundary = report["boundaries"]
    lines = [
        "# ATLAS T1 Source Intake Static Diagnostic - 2026-05-25",
        "",
        "This is a report-only, no-secret T1 diagnostic. It does not call the exporter, read cookie/env secret values, scan D: roots, or mutate downstream state.",
        "",
        "## Decision",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Machine summary: `{summary_path}`",
        f"- Registry accounts: `{registry['account_count']}` total; `{registry['active_like_count']}` active-like",
        f"- Registry updated at: `{registry['registry_updated_at']}`",
        f"- Missing fakeid count: `{registry['missing_fakeid_count']}`",
        f"- Last queue validation: `{refresh['validation_decision']}` at `{refresh['validation_generated_at']}`",
        f"- Validation age hours: `{refresh['validation_age_hours']}`; stale threshold `{refresh['validation_stale_hours_threshold']}`",
        f"- Rows/account/article evidence: rows `{refresh['rows_written']}`, accounts ok `{refresh['exporter_accounts_ok']}`, accounts failed `{refresh['exporter_accounts_failed']}`, article rows `{refresh['exporter_article_rows']}`",
        f"- Pre-refresh invalid-session evidence seen: `{str(refresh['pre_refresh_invalid_session_seen']).lower()}`",
        "",
        "## T2/T4 Handoff",
        "",
        f"- T2 package-ready from this evidence: `{str(handoff['t2_package_ready']).lower()}`",
        f"- T4 new-to-Atlas diff-ready from this evidence: `{str(handoff['t4_new_to_atlas_diff_ready']).lower()}`",
        f"- Requires fresh exporter probe before next package: `{str(handoff['requires_fresh_exporter_probe_before_next_package']).lower()}`",
        f"- STOP_REASON: `{handoff['stop_reason'] or 'none'}`",
        f"- WAIT_REASON: `{handoff['wait_reason'] or 'none'}`",
        "",
        "## Boundaries",
        "",
    ]
    for key, value in boundary.items():
        lines.append(f"- `{key}`: `{str(value).lower()}`")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--pre-refresh-summary", type=Path, default=DEFAULT_PRE_REFRESH)
    parser.add_argument("--validation", type=Path, default=DEFAULT_VALIDATION)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--top-report", type=Path, default=DEFAULT_TOP_REPORT)
    parser.add_argument("--stale-hours", type=int, default=24)
    args = parser.parse_args()

    report = build_report(
        registry_path=args.registry,
        pre_refresh_path=args.pre_refresh_summary,
        validation_path=args.validation,
        stale_hours=args.stale_hours,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.out_dir / "summary.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(args.top_report, report, summary_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
