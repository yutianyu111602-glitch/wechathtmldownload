#!/usr/bin/env python3
"""Audit blocker-as-skip risk across the Atlas longrun.

Report-only. This scans the longrun manifest and next-phase PRD for places
where a loop/story reports ready/pass while also carrying blocker language.
The goal is to count and classify possible "blocker treated as skipped"
surfaces before any production write or promotion.
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
LONGRUN_DIR = REPO_ROOT / "docs" / "longrun" / "atlas-route-external-db-20260531"
SCHEMA_VERSION = "blocker_as_skip_audit_s130.v1"
DEFAULT_MANIFEST = LONGRUN_DIR / "manifest.md"
DEFAULT_NEXT_PHASE_PRD = LONGRUN_DIR / "05-next-phase-prd.json"
DEFAULT_CURRENT_RUNTIME = REPO_ROOT / "docs" / "current-runtime.md"
DEFAULT_OUT_DIR = Path(__file__).resolve().parents[1] / "reports" / "blocker_as_skip_audit_s130_20260601"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_BLOCKER_AS_SKIP_AUDIT_S130_20260601.md"

READY_RE = re.compile(
    r"(?i)(\b(passed|pass|completed|complete|verified|uploaded|deployed)\b|\bready\b|ready_[a-z0-9_]*|[a-z0-9_]*_ready(?:_[a-z0-9_]*)?)"
)
BLOCKER_RE = re.compile(
    r"(?i)\b(blocked|blocker|not complete|incomplete|required_failed|failed|pending|unresolved|cannot be claimed|not ready|needs_[a-z0-9_]+|missing|still constrained|remains unresolved)\b"
)
EXPLICIT_CARRY_RE = re.compile(
    r"(?i)\b(next gate|next story|next safe action|current_blocker|current blocker chain|carried forward|before promotion|do not|does not authorize|not authorize|not count|cannot be claimed|report-only|report collection|repair|nonzero by default|report-mode)\b"
)
PRODUCTION_WRITE_PERMISSION_RE = re.compile(r"(?i)(production write|生产写入|写门|rollback|readback|回滚|读回)")
DB_LOCK_RE = re.compile(r"(?i)(db lock|db锁|database lock|busy_timeout|busy timeout|sqlite_busy|BEGIN IMMEDIATE|wal|write lock|文件锁)")
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


def is_neutral_blocker_metric_line(line: str) -> bool:
    lower = line.casefold()
    strong_blocker = any(
        phrase in lower
        for phrase in (
            "remains blocked",
            "remain blocked",
            "still blocked",
            "blocker remains",
            "not complete",
            "session_invalid",
            "invalid session",
            "status `111`",
            "source context still missing",
            "must be resolved",
        )
    )
    if strong_blocker:
        return False
    neutral_patterns = [
        r"failed\s*[`:= ]+0\b",
        r"0\s+failed\b",
        r"required[_ ]failed\s*[`:= ]+0\b",
        r"missing[^.;\n]*[`:= ]+0\b",
        r"pending[^.;\n]*[`:= ]+0(?:/0/0)?\b",
        r"blocked(?: rows| count)?\s*[`:= ]+0\b",
        r"blockers\s*[`:= ]+\[\]",
        r"finding(?:s| count)?\s*[`:= ]+0\b",
        r"leak hits\s*[`:= ]+0/0/0\b",
        r"skipped_no_actionable_problem",
        r"failed gate or pending queue rows ->",
        r"no failed gates",
    ]
    return any(re.search(pattern, lower) for pattern in neutral_patterns)


def is_neutral_ready_metric_line(line: str) -> bool:
    lower = line.casefold()
    neutral_patterns = [
        r"completion proven\s*[`:= ]+false\b",
        r"weekly_goal_completion_audit_not_complete",
        r"goal-completion audit not complete",
        r"\bnot[-_ ]complete\b",
        r"completed requirements\s*[`:= ]+\d+",
        r"incomplete requirements\s*[`:= ]+\d+",
        r"current pass artifacts\s*[`:= ]+0/",
    ]
    return any(re.search(pattern, lower) for pattern in neutral_patterns)


def matching_lines(
    text: str,
    pattern: re.Pattern[str],
    *,
    limit: int = 8,
    blocker_context: bool = False,
    ready_context: bool = False,
) -> list[str]:
    out = []
    for raw_line in text.splitlines():
        line = compact(raw_line)
        if not line:
            continue
        if pattern.search(line):
            if blocker_context and is_neutral_blocker_metric_line(line):
                continue
            if ready_context and is_neutral_ready_metric_line(line):
                continue
            out.append(line)
        if len(out) >= limit:
            break
    return out


def parse_manifest_loops(text: str) -> list[dict[str, str]]:
    matches = list(re.finditer(r"(?m)^## Loop\s+(.+?)\s*$", text))
    loops: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        loop_id = compact(match.group(1), 80)
        if loop_id.casefold() == "rule":
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        loops.append({"loop_id": loop_id, "body": text[start:end].strip()})
    return loops


def classify_manifest_loop(loop: dict[str, str]) -> dict[str, Any]:
    body = loop["body"]
    ready_lines = matching_lines(body, READY_RE, ready_context=True)
    blocker_lines = matching_lines(body, BLOCKER_RE, blocker_context=True)
    carry_lines = matching_lines(body, EXPLICIT_CARRY_RE)
    has_ready_claim = bool(ready_lines)
    has_blocker_language = bool(blocker_lines)
    has_explicit_carry = bool(carry_lines)

    if has_ready_claim and has_blocker_language and not has_explicit_carry:
        classification = "suspected_blocker_as_skip"
        severity = "high"
    elif has_ready_claim and has_blocker_language and has_explicit_carry:
        classification = "ready_with_explicit_blocker_carry"
        severity = "medium"
    elif has_blocker_language:
        classification = "blocker_recorded_without_ready_claim"
        severity = "low"
    else:
        classification = "no_blocker_language_detected"
        severity = "info"

    return {
        "row_id": stable_id({"source": "manifest", "loop_id": loop["loop_id"]}),
        "source": "manifest",
        "story_id": loop["loop_id"],
        "classification": classification,
        "severity": severity,
        "has_ready_claim": has_ready_claim,
        "has_blocker_language": has_blocker_language,
        "has_explicit_carry_forward": has_explicit_carry,
        "ready_lines": ready_lines,
        "blocker_lines": blocker_lines,
        "carry_forward_lines": carry_lines,
        "recommended_action": recommendation_for(classification),
    }


def story_text(story: dict[str, Any]) -> str:
    return json.dumps(story, ensure_ascii=False, sort_keys=True)


def classify_prd_story(story: dict[str, Any]) -> dict[str, Any]:
    text = story_text(story)
    passes = story.get("passes")
    blocker_lines = matching_lines(text, BLOCKER_RE, blocker_context=True)
    has_blocker_language = bool(blocker_lines) or bool(story.get("current_blocker"))
    has_explicit_carry = bool(story.get("current_blocker")) or bool(EXPLICIT_CARRY_RE.search(text))
    if passes is True and has_blocker_language and not has_explicit_carry:
        classification = "prd_pass_true_with_unaccounted_blocker"
        severity = "high"
    elif passes is True and has_blocker_language and has_explicit_carry:
        classification = "prd_pass_true_with_explicit_remaining_blocker"
        severity = "medium"
    elif passes is False and has_blocker_language:
        classification = "prd_open_story_blocker_recorded"
        severity = "low"
    else:
        classification = "prd_no_blocker_language_detected"
        severity = "info"
    return {
        "row_id": stable_id({"source": "05-next-phase-prd", "story_id": story.get("id")}),
        "source": "05-next-phase-prd",
        "story_id": compact(story.get("id"), 80),
        "classification": classification,
        "severity": severity,
        "passes": passes,
        "has_ready_claim": passes is True,
        "has_blocker_language": has_blocker_language,
        "has_explicit_carry_forward": has_explicit_carry,
        "ready_lines": [f"passes={passes}"],
        "blocker_lines": blocker_lines,
        "carry_forward_lines": matching_lines(text, EXPLICIT_CARRY_RE),
        "recommended_action": recommendation_for(classification),
    }


def recommendation_for(classification: str) -> str:
    if classification in {"suspected_blocker_as_skip", "prd_pass_true_with_unaccounted_blocker"}:
        return "open repair story before any production write or public promotion"
    if classification in {"ready_with_explicit_blocker_carry", "prd_pass_true_with_explicit_remaining_blocker"}:
        return "keep story pass scoped to artifact only; ensure next repair story exists and remains active"
    if "blocker_recorded" in classification:
        return "continue repair lane; do not mark goal complete"
    return "no action from blocker-as-skip audit"


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
        "# Weekly Blocker-As-Skip Audit S130",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Manifest loops audited: `{summary['manifest_loop_count']}`",
        f"- PRD stories audited: `{summary['prd_story_count']}`",
        f"- Ready/pass with blocker language: `{summary['ready_with_blocker_language_count']}`",
        f"- Explicitly carried forward: `{summary['explicit_carry_forward_count']}`",
        f"- Suspected blocker-as-skip rows: `{summary['suspected_blocker_as_skip_count']}`",
        f"- Production-write permission recorded: `{summary['production_write_permission_recorded']}`",
        f"- DB lock rule recorded: `{summary['db_lock_rule_recorded']}`",
        f"- Finding count: `{report['finding_count']}`",
        "",
        "## Classifications",
        "",
    ]
    for key, value in sorted(summary["by_classification"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Audit-only. No DB1/DB2/DB3 mutation, no deploy/upload/review, no external crawl, no model call, no cookie/token value read.",
            "- User granted production write/autonomy, but each write must still have source evidence, rollback contract, readback proof, and explicit blocker closure.",
            "- DB writes must define lock acquisition, busy timeout or bounded retry, backup/rollback, single-writer scope, and postwrite readback.",
            "- Blockers must be repaired, closed without promotion, or remain blocking; they must not be skipped.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_audit(
    *,
    manifest_path: Path,
    next_phase_prd_path: Path,
    current_runtime_path: Path,
    out_dir: Path,
    scorecard_path: Path,
) -> dict[str, Any]:
    manifest_text = manifest_path.read_text(encoding="utf-8")
    prd = json.loads(next_phase_prd_path.read_text(encoding="utf-8"))
    current_runtime_text = current_runtime_path.read_text(encoding="utf-8") if current_runtime_path.exists() else ""
    manifest_rows = [classify_manifest_loop(loop) for loop in parse_manifest_loops(manifest_text)]
    prd_rows = [classify_prd_story(story) for story in prd.get("stories", []) if isinstance(story, dict)]
    rows = manifest_rows + prd_rows
    by_classification = Counter(row["classification"] for row in rows)
    ready_with_blocker = [row for row in rows if row["has_ready_claim"] and row["has_blocker_language"]]
    suspected = [
        row
        for row in rows
        if row["classification"] in {"suspected_blocker_as_skip", "prd_pass_true_with_unaccounted_blocker"}
    ]
    explicit_carry = [row for row in ready_with_blocker if row["has_explicit_carry_forward"]]
    combined_runtime_text = manifest_text + "\n" + current_runtime_text
    production_write_permission_recorded = bool(PRODUCTION_WRITE_PERMISSION_RE.search(combined_runtime_text))
    db_lock_rule_recorded = bool(DB_LOCK_RE.search(combined_runtime_text))

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "blocker_as_skip_audit_ready_report_only",
        "inputs": {
            "manifest": rel_path(manifest_path),
            "next_phase_prd": rel_path(next_phase_prd_path),
            "current_runtime": rel_path(current_runtime_path),
        },
        "outputs": {
            "report": rel_path(out_dir / "blocker_as_skip_audit.json"),
            "rows": rel_path(out_dir / "blocker_as_skip_rows.jsonl"),
            "scorecard": rel_path(scorecard_path),
        },
        "summary": {
            "manifest_loop_count": len(manifest_rows),
            "prd_story_count": len(prd_rows),
            "audit_row_count": len(rows),
            "ready_with_blocker_language_count": len(ready_with_blocker),
            "explicit_carry_forward_count": len(explicit_carry),
            "suspected_blocker_as_skip_count": len(suspected),
            "production_write_permission_recorded": production_write_permission_recorded,
            "db_lock_rule_recorded": db_lock_rule_recorded,
            "by_classification": dict(by_classification),
        },
        "policy": {
            "blocker_handling_rule": "Every blocker must be repaired, closed without promotion, or remain blocking with an active repair story. A blocker may not be treated as skipped.",
            "production_write_rule": "Production writes are allowed by user instruction only after source evidence, rollback contract, readback proof, and explicit blocker closure are present.",
            "db_lock_rule": "Any DB write gate must declare lock acquisition, busy timeout or bounded retry, backup/rollback, single-writer scope, and postwrite readback before execution.",
            "goal_completion_rule": "Goal completion remains false while unresolved blockers exist, even if report-only artifacts pass.",
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
        "rows": rows,
        "secret_like_findings": [],
        "finding_count": 0,
        "next_story": "S131",
    }
    findings = secret_findings({"report": report, "rows": rows})
    report["secret_like_findings"] = findings
    report["finding_count"] = len(findings)
    if findings:
        report["decision"] = "blocker_as_skip_audit_blocked_report_only"
    atomic_write_json(out_dir / "blocker_as_skip_audit.json", report)
    atomic_write_jsonl(out_dir / "blocker_as_skip_rows.jsonl", rows)
    atomic_write_text(scorecard_path, render_scorecard(report))
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--next-phase-prd", type=Path, default=DEFAULT_NEXT_PHASE_PRD)
    parser.add_argument("--current-runtime", type=Path, default=DEFAULT_CURRENT_RUNTIME)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_audit(
        manifest_path=args.manifest,
        next_phase_prd_path=args.next_phase_prd,
        current_runtime_path=args.current_runtime,
        out_dir=args.out_dir,
        scorecard_path=args.scorecard,
    )
    print(json.dumps({"decision": report["decision"], "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["finding_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
