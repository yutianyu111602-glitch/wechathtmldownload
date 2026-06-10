#!/usr/bin/env python3
"""Build a report-only DB2 external-link projection quality gate.

This gate separates the prewrite candidates into a smaller clean set for the
next execution-gate attempt and blocked rows that need review or policy. It
does not mutate DB2 and does not deliver anything to the live writer spool.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"

SCHEMA_VERSION = "db2_external_link_projection_quality_gate.v1"
DEFAULT_PREWRITE_CANDIDATES = (
    REPORTS_ROOT
    / "db2_external_link_projection_prewrite_packet_20260604"
    / "db2_external_link_projection_prewrite_candidates.jsonl"
)
DEFAULT_ROLLBACK_CONTRACTS = (
    REPORTS_ROOT
    / "db2_external_link_projection_prewrite_packet_20260604"
    / "db2_external_link_projection_rollback_contracts.jsonl"
)
DEFAULT_READBACK_CONTRACTS = (
    REPORTS_ROOT
    / "db2_external_link_projection_prewrite_packet_20260604"
    / "db2_external_link_projection_postwrite_readback_contracts.jsonl"
)
DEFAULT_TARGET_AUDIT = (
    REPORTS_ROOT
    / "db2_external_link_projection_execution_gate_20260604"
    / "db2_live_target_conflict_audit.json"
)
DEFAULT_EXECUTION_GATE = (
    REPORTS_ROOT
    / "db2_external_link_projection_execution_gate_20260604"
    / "db2_external_link_projection_execution_gate.json"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "db2_external_link_projection_quality_gate_20260605"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "DB2_EXTERNAL_LINK_PROJECTION_QUALITY_GATE_20260605.md"

GENERIC_RA_PATH_PREFIXES = {
    "/exchange",
    "/features/",
    "/mix-of-the-day",
    "/music",
    "/oauth/",
    "/podcast",
    "/playlists",
    "/ra-guide",
    "/reviews",
    "/tickets/resale",
}
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|api[_-]?key[\"']?\s*[:=]|authorization[\"']?\s*[:=]|"
    r"bearer\s+[A-Za-z0-9._-]+|cookie[\"']?\s*[:=]|password[\"']?\s*[:=]|"
    r"secret[\"']?\s*[:=]|token[\"']?\s*[:=]|BEGIN [A-Z ]*PRIVATE KEY)"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path}: expected JSON object")
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError(f"{path}:{line_no}: expected JSON object")
        rows.append(payload)
    return rows


def text_value(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def is_generic_ra_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "ra.co" not in host and "residentadvisor" not in host:
        return False
    path = (parsed.path or "/").rstrip("/").lower() or "/"
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in GENERIC_RA_PATH_PREFIXES)


def target_audit_by_candidate(audit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = audit.get("candidate_audit_rows")
    if not isinstance(rows, list):
        rows = audit.get("sample_conflicts") if isinstance(audit.get("sample_conflicts"), list) else []
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("projection_candidate_id"):
            out[str(row["projection_candidate_id"])] = row
    return out


def conflict_count(audit_row: dict[str, Any] | None) -> int:
    if not audit_row:
        return 0
    total = 0
    for key in ("same_eid_url_existing_rows", "same_url_any_eid_existing_rows", "deterministic_outlink_id_existing_rows"):
        try:
            total += int(audit_row.get(key) or 0)
        except (TypeError, ValueError):
            pass
    return total


def classify_candidates(candidates: list[dict[str, Any]], target_audit: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    url_counts = Counter(text_value(row.get("source_url_hash"), 128) for row in candidates)
    audit_by_id = target_audit_by_candidate(target_audit)
    audit_has_full_rows = len(audit_by_id) >= len(candidates)
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for row in candidates:
        candidate = dict(row)
        candidate_id = text_value(candidate.get("projection_candidate_id"), 160)
        source_url_hash = text_value(candidate.get("source_url_hash"), 128)
        audit_row = audit_by_id.get(candidate_id)
        blockers: list[str] = []
        if text_value(candidate.get("confidence_band"), 40).lower() == "low":
            blockers.append("low_confidence")
        if url_counts[source_url_hash] > 1:
            blockers.append("duplicate_url_across_candidates")
        if is_generic_ra_url(text_value(candidate.get("safe_url"), 2000)):
            blockers.append("generic_or_low_value_ra_url")
        if audit_has_full_rows and conflict_count(audit_row) > 0:
            blockers.append("live_target_url_conflict")
        if not audit_has_full_rows:
            blockers.append("target_audit_detail_missing")
        candidate["schema_version"] = SCHEMA_VERSION + ".candidate_quality_row"
        candidate["quality_blockers"] = blockers
        candidate["quality_decision"] = "quality_ready_for_next_execution_gate" if not blockers else "blocked_by_quality_gate"
        candidate["quality_write_allowed_now"] = False
        if audit_row:
            candidate["target_audit"] = audit_row
        if blockers:
            blocked.append(candidate)
        else:
            ready.append(candidate)
    return ready, blocked


def iter_string_values(payload: Any) -> list[str]:
    if isinstance(payload, dict):
        values: list[str] = []
        for child in payload.values():
            values.extend(iter_string_values(child))
        return values
    if isinstance(payload, list):
        values = []
        for child in payload:
            values.extend(iter_string_values(child))
        return values
    if isinstance(payload, str):
        return [payload]
    return []


def leak_findings(payload: Any) -> list[dict[str, str]]:
    text = "\n".join(iter_string_values(payload))
    findings: list[dict[str, str]] = []
    for match in SECRET_RE.finditer(text):
        findings.append({"kind": "secret_like", "sample": match.group(0)[:48]})
        if len(findings) >= 20:
            break
    return findings


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# DB2 External Link Projection Quality Gate 20260605",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Generated: `{report['generated_at']}`",
        f"- Input candidates: `{summary['input_candidate_rows']}`",
        f"- Quality ready rows: `{summary['quality_ready_rows']}`",
        f"- Quality blocked rows: `{summary['quality_blocked_rows']}`",
        f"- Duplicate URL rows: `{summary['duplicate_url_rows']}`",
        f"- Low confidence rows: `{summary['low_confidence_rows']}`",
        f"- Live target conflict rows: `{summary['live_target_conflict_rows']}`",
        f"- Generic RA rows: `{summary['generic_ra_rows']}`",
        f"- Leak findings: `{summary['leak_finding_count']}`",
        "",
        "## Blockers",
        "",
    ]
    for key, value in summary["blockers_by_reason"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Artifacts", ""])
    for key, value in report["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Boundary", ""])
    for key, value in report["safety"].items():
        if key != "leak_findings":
            lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines) + "\n"


def build_quality_gate(
    *,
    candidates_path: Path,
    rollback_contracts_path: Path,
    readback_contracts_path: Path,
    target_audit_path: Path,
    execution_gate_path: Path,
    out_dir: Path,
    scorecard_path: Path,
) -> dict[str, Any]:
    generated_at = now_iso()
    candidates = read_jsonl(candidates_path)
    rollback_contracts = read_jsonl(rollback_contracts_path)
    readback_contracts = read_jsonl(readback_contracts_path)
    target_audit = read_json(target_audit_path)
    execution_gate = read_json(execution_gate_path)
    ready, blocked = classify_candidates(candidates, target_audit)
    findings = leak_findings({"ready": ready, "blocked": blocked})
    ready_ids = {row["projection_candidate_id"] for row in ready}
    ready_rollback_contracts = [row for row in rollback_contracts if row.get("projection_candidate_id") in ready_ids]
    ready_readback_contracts = [row for row in readback_contracts if row.get("projection_candidate_id") in ready_ids]

    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "db2_external_link_projection_quality_gate.json"
    ready_path = out_dir / "db2_external_link_projection_quality_ready_candidates.jsonl"
    blocked_path = out_dir / "db2_external_link_projection_quality_blocked_candidates.jsonl"
    ready_rollback_path = out_dir / "db2_external_link_projection_quality_ready_rollback_contracts.jsonl"
    ready_readback_path = out_dir / "db2_external_link_projection_quality_ready_postwrite_readback_contracts.jsonl"
    write_jsonl(ready_path, ready)
    write_jsonl(blocked_path, blocked)
    write_jsonl(ready_rollback_path, ready_rollback_contracts)
    write_jsonl(ready_readback_path, ready_readback_contracts)

    url_counts = Counter(text_value(row.get("source_url_hash"), 128) for row in candidates)
    blocker_counter: Counter[str] = Counter()
    for row in blocked:
        blocker_counter.update(row["quality_blockers"])
    summary = {
        "input_candidate_rows": len(candidates),
        "quality_ready_rows": len(ready),
        "quality_blocked_rows": len(blocked),
        "duplicate_url_groups": sum(1 for count in url_counts.values() if count > 1),
        "duplicate_url_rows": sum(count - 1 for count in url_counts.values() if count > 1),
        "low_confidence_rows": sum(1 for row in candidates if text_value(row.get("confidence_band"), 40).lower() == "low"),
        "live_target_conflict_rows": sum(1 for row in blocked if "live_target_url_conflict" in row["quality_blockers"]),
        "generic_ra_rows": sum(1 for row in blocked if "generic_or_low_value_ra_url" in row["quality_blockers"]),
        "ready_by_platform": dict(Counter(row.get("platform") or "" for row in ready).most_common()),
        "blocked_by_platform": dict(Counter(row.get("platform") or "" for row in blocked).most_common()),
        "blockers_by_reason": dict(blocker_counter.most_common()),
        "leak_finding_count": len(findings),
        "quality_ready_rollback_contract_rows": len(ready_rollback_contracts),
        "quality_ready_postwrite_readback_contract_rows": len(ready_readback_contracts),
    }
    decision = (
        "db2_external_link_projection_quality_gate_ready_subset_report_only"
        if ready and not findings
        else "db2_external_link_projection_quality_gate_blocked_report_only"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "inputs": {
            "prewrite_candidates": rel_path(candidates_path),
            "rollback_contracts": rel_path(rollback_contracts_path),
            "readback_contracts": rel_path(readback_contracts_path),
            "target_audit": rel_path(target_audit_path),
            "execution_gate": rel_path(execution_gate_path),
        },
        "artifacts": {
            "report_json": rel_path(report_path),
            "scorecard": rel_path(scorecard_path),
            "quality_ready_candidates_jsonl": rel_path(ready_path),
            "quality_blocked_candidates_jsonl": rel_path(blocked_path),
            "quality_ready_rollback_contracts_jsonl": rel_path(ready_rollback_path),
            "quality_ready_postwrite_readback_contracts_jsonl": rel_path(ready_readback_path),
        },
        "summary": summary,
        "upstream_execution_gate": {
            "decision": execution_gate.get("decision"),
            "execute_allowed_now": (execution_gate.get("execution_gate") or {}).get("execute_allowed_now"),
        },
        "safety": {
            "report_only": True,
            "db2_mutation": False,
            "live_db2_spool_delivery": False,
            "network_fetch": False,
            "cookie_token_secret_read": False,
            "secret_values_printed": False,
            "leak_findings": findings,
        },
        "next_gate": {
            "name": "rerun_projection_execution_gate_with_quality_ready_subset",
            "execute_allowed_now": False,
            "requires_live_worker_idle": True,
            "requires_conflict_policy_for_blocked_rows": True,
            "requires_exact_confirm_token": True,
        },
    }
    write_json(report_path, report)
    atomic_write_text(scorecard_path, render_scorecard(report))
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prewrite-candidates", type=Path, default=DEFAULT_PREWRITE_CANDIDATES)
    parser.add_argument("--rollback-contracts", type=Path, default=DEFAULT_ROLLBACK_CONTRACTS)
    parser.add_argument("--readback-contracts", type=Path, default=DEFAULT_READBACK_CONTRACTS)
    parser.add_argument("--target-audit", type=Path, default=DEFAULT_TARGET_AUDIT)
    parser.add_argument("--execution-gate", type=Path, default=DEFAULT_EXECUTION_GATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_quality_gate(
        candidates_path=args.prewrite_candidates,
        rollback_contracts_path=args.rollback_contracts,
        readback_contracts_path=args.readback_contracts,
        target_audit_path=args.target_audit,
        execution_gate_path=args.execution_gate,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
    )
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "summary": report["summary"],
                "artifacts": report["artifacts"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["decision"] == "db2_external_link_projection_quality_gate_ready_subset_report_only" else 1


if __name__ == "__main__":
    raise SystemExit(main())
