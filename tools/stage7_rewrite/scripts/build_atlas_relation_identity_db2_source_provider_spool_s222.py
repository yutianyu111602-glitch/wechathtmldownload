#!/usr/bin/env python3
"""Build S222 DB2 writer-compatible source-provider identity spool.

S222 is the report-only bridge after S221. It converts S213/S221 unresolved
source-provider acquisition rows into DB2 writer daemon `insert_identity_candidate`
events, but does not deliver them to the live DB2 spool and does not mutate DB2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import run_atlas_relation_identity_unicode_source_anchor_batch_s167 as s167


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S222"
REPORT_STEM = "atlas_relation_identity_db2_source_provider_spool_s222"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_INPUT = (
    REPORTS_ROOT
    / "atlas_relation_identity_p1_p2_recovery_workbench_s221_after_s219_20260602"
    / "s213_db2_source_provider_spool_queue.jsonl"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_identity_db2_source_provider_spool_s222_after_s221_20260602"
DEFAULT_SCORECARD = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_IDENTITY_DB2_SOURCE_PROVIDER_SPOOL_S222_AFTER_S221_20260602.md"

EXPECTED_INPUT_ROUTE = "S213D_db2_source_provider_acquisition_spool"
EVENT_OP = "insert_identity_candidate"
EVENT_SOURCE = "atlas_relation_identity_db2_source_provider_spool_s222"
EVENT_COLUMNS = {
    "accepted_for_graph",
    "alias_used",
    "avatar_url",
    "bio_snippet",
    "confidence",
    "display_name",
    "eid",
    "evidence_source_title",
    "evidence_source_url",
    "evidence_text",
    "fetched_at",
    "handle",
    "identity_proof",
    "match_type",
    "normalized_name",
    "platform",
    "review_status",
    "risk_flags",
    "source",
    "source_profile_id",
    "sidecar_id",
    "subject_id",
    "url_normalized",
}
INTERNAL_EVENT_KEYS = {"op", "mode"}
FORBIDDEN_KEY_RE = re.compile(r"(cookie|token|secret|password|authorization)", re.I)
RAW_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
RAW_PATH_RE = re.compile(r"(?i)(?:\b[A-Z]:\\[^\"'\n\r]+|/mnt/[a-z](?:/[^\"'\n\r]*)?)")
SECRET_RE = re.compile(r"(?i)(api[_-]?key|secret|authorization|cookie|bearer\s+[a-z0-9._-]{8,})")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel_path(path: Path) -> str:
    return s167.rel_path(path)


def stable_hash(value: Any, length: int = 24) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:length]


def stable_int_id(value: Any) -> int:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return int(hashlib.sha256(data).hexdigest()[:15], 16)


def compact(value: Any, limit: int = 400) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def scrub_text(value: Any, limit: int = 400) -> str:
    text = compact(value, limit)
    text = RAW_URL_RE.sub("redacted-url", text)
    text = RAW_PATH_RE.sub("redacted-local-path", text)
    text = SECRET_RE.sub("redacted-secret-word", text)
    return text


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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected JSON object")
            rows.append(value)
    return rows


def has_forbidden_key(value: Any) -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if FORBIDDEN_KEY_RE.search(str(key)):
                return str(key)
            found = has_forbidden_key(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = has_forbidden_key(child)
            if found:
                return found
    return None


def public_scan(paths: list[Path]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        for name, pattern in [("raw_url", RAW_URL_RE), ("raw_path", RAW_PATH_RE), ("secret_like", SECRET_RE)]:
            if pattern.search(text):
                findings.append({"artifact": rel_path(path), "finding": name})
    return findings


def join_values(values: Any, *, limit: int = 240) -> str:
    if not isinstance(values, list):
        return ""
    return " | ".join(scrub_text(value, limit) for value in values if compact(value))[:limit]


def source_seed_text(seed: dict[str, Any]) -> str:
    payload = {
        "common_source_accounts": seed.get("common_source_accounts") or [],
        "common_titles": seed.get("common_titles") or [],
        "common_venues": seed.get("common_venues") or [],
        "has_provider_anchor": bool(seed.get("has_provider_anchor")),
        "has_source_account_or_title_seed": bool(seed.get("has_source_account_or_title_seed")),
    }
    return scrub_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), 900)


def build_event(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    display_names = [scrub_text(value, 120) for value in row.get("display_names") or [] if compact(value)]
    display_name = " / ".join(display_names[:3])[:240] or scrub_text(row.get("group_id"), 240)
    normalized_values = [scrub_text(value, 120) for value in row.get("unicode_compact_values") or [] if compact(value)]
    normalized_name = normalized_values[0] if normalized_values else scrub_text(row.get("group_id"), 160)
    task_id = scrub_text(row.get("task_id") or stable_hash(row), 180)
    group_id = scrub_text(row.get("group_id"), 180)
    dj_ids = [scrub_text(value, 120) for value in row.get("dj_ids") or [] if compact(value)]
    seed = row.get("source_seed") if isinstance(row.get("source_seed"), dict) else {}
    evidence_summary = {
        "s222_task_id": task_id,
        "s213_group_id": group_id,
        "dj_ids": dj_ids,
        "source_seed": {
            "common_source_accounts": seed.get("common_source_accounts") or [],
            "common_titles": seed.get("common_titles") or [],
            "common_venues": seed.get("common_venues") or [],
            "has_provider_anchor": bool(seed.get("has_provider_anchor")),
            "has_source_account_or_title_seed": bool(seed.get("has_source_account_or_title_seed")),
        },
        "route": scrub_text(row.get("route"), 120),
        "db3_write_allowed_now": False,
        "db2_projection_allowed_now": False,
    }
    event = {
        "op": EVENT_OP,
        "mode": "ignore",
        "sidecar_id": stable_int_id(["S222", task_id, group_id, dj_ids]),
        "subject_id": f"relation_identity:{stable_hash([group_id, dj_ids], 20)}",
        "display_name": display_name,
        "normalized_name": normalized_name,
        "alias_used": join_values(display_names, limit=240),
        "platform": "source_provider_acquisition",
        "handle": task_id,
        "url_normalized": "",
        "avatar_url": "",
        "bio_snippet": source_seed_text(seed),
        "evidence_source_url": "",
        "evidence_source_title": join_values((seed.get("common_source_accounts") or []) + (seed.get("common_titles") or []) + (seed.get("common_venues") or []), limit=500),
        "evidence_text": scrub_text(json.dumps(evidence_summary, ensure_ascii=False, sort_keys=True), 1800),
        "match_type": "relation_identity_source_provider_seed",
        "confidence": 0.0,
        "identity_proof": 0,
        "accepted_for_graph": 0,
        "review_status": "source_provider_acquisition_pending",
        "risk_flags": "db3_write_disallowed;db2_projection_disallowed;requires_source_provider_acquisition",
        "fetched_at": generated_at,
        "source_profile_id": task_id,
        "eid": group_id,
        "source": EVENT_SOURCE,
    }
    forbidden = has_forbidden_key(event)
    if forbidden:
        raise ValueError(f"generated event contains forbidden key: {forbidden}")
    extra = sorted(set(event) - INTERNAL_EVENT_KEYS - EVENT_COLUMNS)
    if extra:
        raise ValueError(f"generated event contains unsupported keys: {extra}")
    return event


def build_spool(*, input_path: Path, out_dir: Path, scorecard_path: Path) -> dict[str, Any]:
    generated_at = now_iso()
    rows = read_jsonl(input_path)
    accepted_rows = [row for row in rows if row.get("route") == EXPECTED_INPUT_ROUTE]
    skipped_rows = [row for row in rows if row.get("route") != EXPECTED_INPUT_ROUTE]
    events = [build_event(row, generated_at) for row in accepted_rows]
    event_path = out_dir / "s222_db2_writer_identity_candidate_events.jsonl"
    dryrun_incoming_path = out_dir / "db2_writer_dryrun_spool" / "incoming" / "s222_identity_candidates.jsonl"
    write_jsonl(event_path, events)
    write_jsonl(dryrun_incoming_path, events)
    output_paths = [event_path, dryrun_incoming_path]
    safety_findings = public_scan(output_paths)
    decision = (
        "atlas_relation_identity_db2_source_provider_spool_s222_failed_safety_scan"
        if safety_findings
        else "atlas_relation_identity_db2_source_provider_spool_s222_ready_report_only"
    )
    counts = {
        "input_row_count": len(rows),
        "accepted_input_row_count": len(accepted_rows),
        "skipped_input_row_count": len(skipped_rows),
        "db2_writer_event_count": len(events),
        "events_by_op": dict(sorted(Counter(event["op"] for event in events).items())),
        "events_by_review_status": dict(sorted(Counter(event["review_status"] for event in events).items())),
    }
    report = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": generated_at,
        "decision": decision,
        "inputs": {
            "source_provider_queue": rel_path(input_path),
            "expected_input_route": EXPECTED_INPUT_ROUTE,
        },
        "counts": counts,
        "artifacts": {
            "report_json": rel_path(out_dir / f"{REPORT_STEM}.json"),
            "scorecard": rel_path(scorecard_path),
            "db2_writer_events_jsonl": rel_path(event_path),
            "db2_writer_dryrun_spool_dir": rel_path(out_dir / "db2_writer_dryrun_spool"),
            "db2_writer_dryrun_incoming_jsonl": rel_path(dryrun_incoming_path),
        },
        "execution_cursor": {
            "next_story_id": "S223",
            "next_action": "Validate this report-local spool with db2_writer_daemon dry-run, then only deliver to live DB2 writer spool after duplicate policy and live-writer status are explicitly green.",
            "next_input": rel_path(dryrun_incoming_path),
            "live_db2_spool_delivery_allowed_now": False,
            "db2_mutation_allowed_now": False,
            "db3_write_allowed_now": False,
            "deploy_upload_review_release_allowed_now": False,
        },
        "safety": {
            "report_only": True,
            "network_fetch": False,
            "live_db2_spool_delivery": False,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection": False,
            "deploy_upload_review_release": False,
            "cookie_token_secret_read": False,
            "secret_values_printed": False,
            "raw_source_url_emitted": False,
            "raw_archive_path_emitted": False,
            "safety_findings": safety_findings,
        },
    }
    write_json(out_dir / f"{REPORT_STEM}.json", report)
    write_scorecard(scorecard_path, report)
    return report


def write_scorecard(path: Path, report: dict[str, Any]) -> None:
    counts = report["counts"]
    lines = [
        "# Weekly Atlas Relation Identity DB2 Source Provider Spool S222",
        "",
        f"- Decision: `{report['decision']}`",
        f"- Input rows: `{counts['input_row_count']}`",
        f"- Accepted S213D rows: `{counts['accepted_input_row_count']}`",
        f"- DB2 writer events: `{counts['db2_writer_event_count']}`",
        "- Live DB2 spool delivery: `false`",
        "- DB2 mutation: `false`",
        "- DB3 mutation: `false`",
        "",
        "## Artifacts",
    ]
    for key, value in report["artifacts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Next Gate",
            "",
            "Run DB2 writer dry-run validation over the report-local `db2_writer_dryrun_spool` directory. Do not copy these events into the live DB2 spool until duplicate policy and live writer status are green.",
            "",
        ]
    )
    atomic_write_text(path, "\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_spool(input_path=args.input, out_dir=args.out_dir, scorecard_path=args.scorecard)
    print(json.dumps({"decision": report["decision"], "counts": report["counts"], "summary": report["artifacts"]["report_json"]}, ensure_ascii=False, sort_keys=True))
    return 0 if not report["safety"]["safety_findings"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
