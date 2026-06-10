#!/usr/bin/env python3
"""Build the S131 historical blocker repair ledger.

Report-only. This consumes the S130 blocker-as-skip audit and assigns each
suspected historical row a current disposition, active repair story, production
impact, and DB-lock/write-gate requirement.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "historical_blocker_repair_ledger_s131.v1"
DEFAULT_S130_REPORT = STAGE7_ROOT / "reports" / "blocker_as_skip_audit_s130_20260601" / "blocker_as_skip_audit.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "historical_blocker_repair_ledger_s131_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_HISTORICAL_BLOCKER_REPAIR_LEDGER_S131_20260601.md"
SUSPECT_CLASSES = {"suspected_blocker_as_skip", "prd_pass_true_with_unaccounted_blocker"}
SECRET_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9_-]{12,}|token\s*[:=]\s*[^,\s]{8,}|cookie\s*[:=]\s*[^,\s]{8,}|password\s*[:=]\s*[^,\s]{8,}|BEGIN [A-Z ]*PRIVATE KEY)"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rel_path(path: Path, root: Path = REPO_ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_json(path: Path, payload: Any) -> None:
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def atomic_write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write_text(path, "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows))


def stable_id(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def compact(value: Any, limit: int = 420) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def joined_lines(row: dict[str, Any]) -> str:
    parts = []
    for key in ("ready_lines", "blocker_lines", "carry_forward_lines"):
        parts.extend(str(item) for item in row.get(key, []) if item)
    return "\n".join(parts).casefold()


def classify_repair(row: dict[str, Any]) -> dict[str, Any]:
    story_id = compact(row.get("story_id"), 80)
    text = joined_lines(row)
    if "devtools" in text or "websocket" in text or "9431" in text or "dirty devtools" in text:
        active_story = "S126"
        disposition = "keep_blocked_with_active_devtools_rendered_story"
        repair_action = "continue_s126_environment_protocol_rendered_artifact_gate"
        production_impact = "blocks mini-program rendered coverage, upload/review claims, and public UI validation"
        db_lock_required = False
    elif "geocode" in text or "coordinate" in text or "missing-geo" in text or "rust club" in text or "tencent" in text:
        active_story = "S131/S132 coordinate-write gate"
        disposition = "keep_blocked_with_active_coordinate_repair_story"
        repair_action = "build_coordinate_write_gate_with_provider_fix_source_evidence_and_db_lock_contract"
        production_impact = "blocks coordinate/address writes, deploy/upload preflight, and public map latest claims"
        db_lock_required = True
    else:
        active_story = "S131"
        disposition = "keep_blocked_with_manual_repair_story"
        repair_action = "manual_review_then_assign_owner_lane"
        production_impact = "blocks dependent production promotion until reviewed"
        db_lock_required = True

    if story_id == "031 Result":
        active_story = "S126 plus coordinate-write gate"
        disposition = "split_keep_blocked_devtools_and_coordinate"
        repair_action = "split_into_devtools_rendered_repair_and_coordinate_write_gate"
        production_impact = "blocks rendered UI claims and coordinate/address writes"
        db_lock_required = True

    return {
        "ledger_id": stable_id({"s131": row.get("row_id"), "story_id": story_id}),
        "source": row.get("source", ""),
        "story_id": story_id,
        "s130_classification": row.get("classification", ""),
        "s130_ready_lines": row.get("ready_lines", []),
        "s130_blocker_lines": row.get("blocker_lines", []),
        "disposition": disposition,
        "active_repair_story": active_story,
        "repair_action": repair_action,
        "production_impact": production_impact,
        "db_lock_required_before_write": db_lock_required,
        "production_write_allowed_now": False,
        "public_promotion_allowed_now": False,
        "closure_kind": "kept_blocking_with_active_repair_story",
        "required_write_gate_controls": [
            "lock acquisition",
            "busy_timeout or bounded retry",
            "backup/rollback contract",
            "single-writer scope",
            "postwrite readback",
        ]
        if db_lock_required
        else [],
        "report_only": True,
    }


def secret_findings(payload: Any) -> list[dict[str, str]]:
    text = json.dumps(payload, ensure_ascii=False)
    findings = []
    for match in SECRET_RE.finditer(text):
        findings.append({"pattern": "secret_like_text", "sample": match.group(0)[:16] + "..."})
        if len(findings) >= 10:
            break
    return findings


def render_scorecard(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Weekly Historical Blocker Repair Ledger S131",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Suspected input rows: `{summary['suspected_input_count']}`",
        f"- Ledger rows: `{summary['ledger_row_count']}`",
        f"- Kept blocking with active repair story: `{summary['kept_blocking_count']}`",
        f"- DB-lock required rows: `{summary['db_lock_required_count']}`",
        f"- Production write allowed now: `{summary['production_write_allowed_now_count']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Dispositions",
        "",
    ]
    for key, value in sorted(summary["by_disposition"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only ledger. No DB1/DB2/DB3 mutation, no deploy/upload/review, no external crawl, no model call, no cookie/token value read.",
            "- Historical blockers remain blocking unless the active repair story closes them with evidence.",
            "- DB-impacting rows require lock acquisition, busy timeout or bounded retry, backup/rollback, single-writer scope, and postwrite readback before any write.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_ledger(*, s130_report_path: Path, out_dir: Path, scorecard_path: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    s130 = json.loads(s130_report_path.read_text(encoding="utf-8"))
    suspected = [row for row in s130.get("rows", []) if row.get("classification") in SUSPECT_CLASSES]
    ledger_rows = [classify_repair(row) for row in suspected]
    by_disposition = Counter(row["disposition"] for row in ledger_rows)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "historical_blocker_repair_ledger_ready_report_only",
        "inputs": {
            "s130_report": rel_path(s130_report_path),
        },
        "outputs": {
            "report": rel_path(out_dir / "historical_blocker_repair_ledger.json"),
            "rows": rel_path(out_dir / "historical_blocker_repair_rows.jsonl"),
            "scorecard": rel_path(scorecard_path),
        },
        "summary": {
            "suspected_input_count": len(suspected),
            "ledger_row_count": len(ledger_rows),
            "kept_blocking_count": sum(1 for row in ledger_rows if row["closure_kind"] == "kept_blocking_with_active_repair_story"),
            "db_lock_required_count": sum(1 for row in ledger_rows if row["db_lock_required_before_write"]),
            "production_write_allowed_now_count": sum(1 for row in ledger_rows if row["production_write_allowed_now"]),
            "public_promotion_allowed_now_count": sum(1 for row in ledger_rows if row["public_promotion_allowed_now"]),
            "by_disposition": dict(by_disposition),
            "all_suspects_accounted": len(suspected) == len(ledger_rows) and all(row["active_repair_story"] for row in ledger_rows),
        },
        "boundary": {
            "report_only": True,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "deploy_or_upload": False,
            "network_fetch": False,
            "model_call_performed": False,
            "cookie_values_read": False,
            "token_values_read": False,
        },
        "rows": ledger_rows,
        "secret_like_findings": [],
        "finding_count": 0,
        "next_story": "S132",
    }
    findings = secret_findings({"report": report, "rows": ledger_rows})
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings or not report["summary"]["all_suspects_accounted"]:
        report["decision"] = "historical_blocker_repair_ledger_blocked_report_only"
    atomic_write_json(out_dir / "historical_blocker_repair_ledger.json", report)
    atomic_write_jsonl(out_dir / "historical_blocker_repair_rows.jsonl", ledger_rows)
    atomic_write_text(scorecard_path, render_scorecard(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s130-report", type=Path, default=DEFAULT_S130_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_ledger(s130_report_path=args.s130_report, out_dir=args.out_dir, scorecard_path=args.scorecard)
    print(json.dumps({"decision": report["decision"], "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["finding_count"] == 0 and report["summary"]["all_suspects_accounted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
