#!/usr/bin/env python3
"""Build S232D-3A seed target-resolver contract.

S232D-3 proved that the first five canary rows can hydrate S228
common_source_accounts, but those seeds are names only. This report-only
contract defines the next safe resolver gate without fetching network resources,
reading credentials, writing DBs, projecting DB2, or releasing consumers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
REPORTS_ROOT = REPO_ROOT / "tools" / "stage7_rewrite" / "reports"
DEFAULT_S232D3 = REPORTS_ROOT / "atlas_relation_identity_s232d3_no_cookie_canary_20260602" / "atlas_relation_identity_s232d3_no_cookie_canary.json"
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_s232d3a_seed_target_resolver_contract_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_S232D3A_SEED_TARGET_RESOLVER_CONTRACT_20260602.md"

STORY_ID = "S232D-3A"
SCHEMA_VERSION = "atlas_relation_identity_s232d3a_seed_target_resolver_contract.v1"
QUEUE_SCHEMA_VERSION = "atlas_relation_identity_s232d3a_seed_target_resolver_queue.v1"

RAW_URL_RE = re.compile(r"https?://", re.IGNORECASE)
PRIVATE_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|/mnt/[a-z]/|/home/pc/|\\\\)", re.IGNORECASE)
SECRET_RE = re.compile(
    r"(?:bearer\s+[a-z0-9._~+/=-]+|sk-[a-z0-9]{12,}|x-auth-key\s*[:=]|"
    r"cookie_value|token_value|password\s*[:=]|authorization\s*[:=]|sessionid=|api[_-]?key\s*[:=])",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return f"external-fixture/{path.name}"


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ok"}
    return bool(value)


def as_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def leak_scan(payload: Any) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, f"{path}.{key}" if path else str(key))
            return
        if isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{path}[{index}]")
            return
        if value is None:
            return
        text = str(value)
        for kind, pattern in (("raw_url", RAW_URL_RE), ("private_path", PRIVATE_PATH_RE), ("secret_like", SECRET_RE)):
            if pattern.search(text):
                findings.append({"kind": kind, "path": path, "severity": "block"})

    walk(payload, "")
    return findings


def normalize_seed(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def seed_kind(seed: str) -> str:
    normalized = normalize_seed(seed)
    if any(word in normalized for word in ("bar", "club", "shanghai", "kw")):
        return "source_account_or_venue_name"
    return "source_account_name"


def build_queue_rows(evidence_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for evidence in evidence_rows:
        seed_accounts = evidence.get("seed_source_accounts")
        if not isinstance(seed_accounts, list):
            seed_accounts = []
        for seed in seed_accounts:
            if not isinstance(seed, str) or not seed.strip():
                continue
            rows.append(
                {
                    "schema_version": QUEUE_SCHEMA_VERSION,
                    "story_id": STORY_ID,
                    "work_order_id": evidence.get("work_order_id") or "",
                    "ordinal": as_int(evidence.get("ordinal")),
                    "display_name": evidence.get("display_name") or "",
                    "group_id": evidence.get("group_id") or "",
                    "seed_kind": seed_kind(seed),
                    "seed_value": seed,
                    "seed_value_hash": sha256_text(seed)[:24],
                    "target_resolution_status": "blocked_target_resolver_contract_required",
                    "target_material_present": False,
                    "network_fetch_ready": False,
                    "network_fetch_attempted": False,
                    "db_write_executed": False,
                    "db2_projection_executed": False,
                    "required_resolution_evidence": [
                        "exact_public_provider_or_source_target_with_provenance",
                        "same_seed_account_or_same_venue_anchor",
                        "no_cookie_accessible_or_local_source_ref",
                        "no_raw_url_output_policy_satisfied",
                        "work_order_id_stays_in_first5_or_new_release_allowlist",
                    ],
                    "next_gate": "s232d3b_target_resolution_canary_requires_controller_release",
                }
            )
    return rows


def validate_s232d3(report: dict[str, Any]) -> list[dict[str, Any]]:
    failed: list[dict[str, Any]] = []
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    if report.get("decision") != "atlas_relation_identity_s232d3_no_cookie_canary_blocked_seed_hydrated_without_public_fetch_target":
        failed.append({"check": "s232d3_blocked_seed_hydrated_decision"})
    if report.get("mode") != "in-container" or not as_bool(report.get("inside_container")):
        failed.append({"check": "s232d3_in_container_evidence_required"})
    if as_int(counts.get("selected_work_order_count")) != 5:
        failed.append({"check": "s232d3_selected_work_order_count_5"})
    if as_int(counts.get("s228_seed_hydrated_count")) != 5:
        failed.append({"check": "s232d3_s228_seed_hydrated_count_5"})
    if as_int(counts.get("network_fetch_attempt_count")) != 0:
        failed.append({"check": "s232d3_network_fetch_attempt_count_zero"})
    if as_int(counts.get("raw_url_private_path_secret_leak_count")) != 0:
        failed.append({"check": "s232d3_leak_count_zero"})
    for flag in ("db_write_executed", "db1_mutation", "db2_mutation", "db3_mutation", "db2_projection_allowed_now", "db3_write_allowed_now", "deploy_upload_release_allowed_now"):
        if as_bool(report.get(flag)):
            failed.append({"check": "s232d3_forbidden_flag_false", "flag": flag})
    return failed


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    s232d3 = read_json(args.s232d3)
    evidence_rows = s232d3.get("evidence_rows")
    if not isinstance(evidence_rows, list):
        evidence_rows = []
    failed_checks = validate_s232d3(s232d3)
    queue_rows = build_queue_rows(evidence_rows)
    distinct_seed_hashes = {row["seed_value_hash"] for row in queue_rows}
    seed_kind_counts = Counter(row["seed_kind"] for row in queue_rows)

    if len(queue_rows) != as_int((s232d3.get("counts") or {}).get("s228_seed_hydrated_count")):
        failed_checks.append(
            {
                "check": "resolver_queue_matches_hydrated_seed_count",
                "queue_count": len(queue_rows),
                "hydrated_count": as_int((s232d3.get("counts") or {}).get("s228_seed_hydrated_count")),
            }
        )

    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "story_id": STORY_ID,
        "generated_at": utc_now(),
        "decision": "",
        "inputs": {
            "s232d3_no_cookie_canary": rel(args.s232d3),
        },
        "counts": {
            "input_evidence_row_count": len(evidence_rows),
            "target_resolver_queue_count": len(queue_rows),
            "distinct_seed_account_count": len(distinct_seed_hashes),
            "network_fetch_ready_count": 0,
            "network_fetch_attempt_count": 0,
            "db_write_candidate_count": 0,
            "db2_projection_candidate_count": 0,
            "failed_check_count": len(failed_checks),
            "raw_url_private_path_secret_leak_count": 0,
            "seed_kind_counts": dict(seed_kind_counts),
        },
        "contract": {
            "status": "report_only_target_resolver_contract_required",
            "scope": "first5_s232d0_s232c_allowlist_from_s232d3_only",
            "s228_seed_hydration_read_only": True,
            "s228_seed_hydration_expands_work_orders": False,
            "seed_names_are_not_fetch_targets": True,
            "raw_url_output_allowed": False,
            "credential_read_allowed": False,
            "db1_db2_db3_write_allowed": False,
            "db2_projection_allowed": False,
            "deploy_sync_upload_review_release_allowed": False,
            "future_target_resolution_must_prove": [
                "exact public provider/source target provenance without credential requirement",
                "same seed account or same venue anchor for the same work_order_id",
                "hashed target/domain metadata only in JSON/markdown/logs",
                "no raw URL/private path/secret leak",
                "new controller release before network fetch or target resolver canary",
            ],
        },
        "queue_preview": queue_rows,
        "failed_checks": failed_checks,
        "collector_executed": False,
        "network_fetch_executed": False,
        "db_write_executed": False,
        "db1_mutation": False,
        "db2_mutation": False,
        "db3_mutation": False,
        "db2_projection_allowed_now": False,
        "db3_write_allowed_now": False,
        "deploy_upload_release_allowed_now": False,
        "cookie_or_token_read": False,
        "api_key_read": False,
        "browser_profile_read": False,
        "raw_source_url_emitted": False,
        "private_path_emitted": False,
        "next_gate": "S232D-3B target-resolution canary requires a new controller release and concrete target-resolution contract evidence.",
        "production_state_difference": "Report-only resolver contract; no network fetch, DB mutation, DB2 projection, deploy/sync/upload/review/release, credential read, or raw URL output.",
    }
    leak_payload = {key: value for key, value in report.items() if key != "queue_preview"}
    leak_payload["queue_preview"] = queue_rows
    leaks = leak_scan(leak_payload)
    report["leak_findings"] = leaks
    report["counts"]["raw_url_private_path_secret_leak_count"] = len(leaks)
    if leaks:
        failed_checks.extend(leaks)
        report["counts"]["failed_check_count"] = len(failed_checks)
        report["raw_source_url_emitted"] = any(row.get("kind") == "raw_url" for row in leaks)
        report["private_path_emitted"] = any(row.get("kind") == "private_path" for row in leaks)
    report["decision"] = (
        "atlas_relation_identity_s232d3a_seed_target_resolver_contract_ready_report_only"
        if not failed_checks
        else "atlas_relation_identity_s232d3a_seed_target_resolver_contract_blocked_input_not_green"
    )
    return report


def render_markdown(report: dict[str, Any]) -> str:
    counts = report["counts"]
    return "\n".join(
        [
            "# S232D-3A Seed Target Resolver Contract",
            "",
            f"- Decision: `{report['decision']}`",
            f"- Target resolver queue: `{counts['target_resolver_queue_count']}`",
            f"- Distinct seed accounts: `{counts['distinct_seed_account_count']}`",
            f"- Network fetch ready / attempted: `{counts['network_fetch_ready_count']}` / `{counts['network_fetch_attempt_count']}`",
            f"- DB write candidates / DB2 projection candidates: `{counts['db_write_candidate_count']}` / `{counts['db2_projection_candidate_count']}`",
            f"- Leak count: `{counts['raw_url_private_path_secret_leak_count']}`",
            f"- Failed checks: `{counts['failed_check_count']}`",
            "",
            "## Boundary",
            "",
            "- Report-only contract. No network fetch and no collector execution.",
            "- Seed account names are not fetch targets and must not be converted into search URLs by this gate.",
            "- No cookie/token/.env/browser profile/API key/credential read.",
            "- No DB1/DB2/DB3 write, no DB2 projection, no deploy/sync/upload/review/release.",
            "- S232D-4 / DB3 write remains unreleased.",
            "",
            "## Next Gate",
            "",
            "- `S232D-3B` may only run after a new controller release and concrete target-resolution evidence that can produce provider/source targets without raw URL leakage.",
            "",
            "## Artifacts",
            "",
            f"- `{report.get('artifacts', {}).get('summary_json', '')}`",
            f"- `{report.get('artifacts', {}).get('target_resolver_queue', '')}`",
            "",
        ]
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report = build_report(args)
    json_path = args.out_dir / "atlas_relation_identity_s232d3a_seed_target_resolver_contract.json"
    queue_path = args.out_dir / "s232d3a_seed_target_resolver_queue.jsonl"
    markdown_path = args.out_dir / "atlas_relation_identity_s232d3a_seed_target_resolver_contract.md"
    report["artifacts"] = {
        "summary_json": rel(json_path),
        "target_resolver_queue": rel(queue_path),
        "markdown": rel(markdown_path),
        "scorecard": rel(args.scorecard),
    }
    write_json(json_path, report)
    write_jsonl(queue_path, report["queue_preview"])
    markdown = render_markdown(report)
    markdown_path.write_text(markdown, encoding="utf-8")
    args.scorecard.parent.mkdir(parents=True, exist_ok=True)
    args.scorecard.write_text(markdown, encoding="utf-8")
    write_json(json_path, report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build S232D-3A seed target-resolver contract")
    parser.add_argument("--s232d3", type=Path, default=DEFAULT_S232D3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    report = run(parse_args(argv))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not report.get("failed_checks") else 1


if __name__ == "__main__":
    raise SystemExit(main())
