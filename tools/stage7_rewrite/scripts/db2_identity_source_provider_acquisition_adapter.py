from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_DB = Path(os.environ.get("DB2_SWARM_DB", "/db2-data/atlas_swarm_data.sqlite"))
DEFAULT_REPORTS_DIR = Path(os.environ.get("DB2_REPORTS_DIR", "tools/stage7_rewrite/reports"))
DEFAULT_SOURCE = "atlas_relation_identity_db2_source_provider_spool_s222"
DEFAULT_REVIEW_STATUS = "source_provider_acquisition_pending"
DEFAULT_WORKBENCH_JSONL = os.environ.get("DB2_IDENTITY_WORKBENCH_JSONL", "")
WORKER_NAME = "identity_source_provider"
LEGACY_WORKER_NAME = "identity_source_provider_acquisition"

RAW_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
D_DRIVE_PATH_RE = re.compile(r"(?i)(?:\bD:\\[^\s\"'<>]+|/mnt/d(?:/[^\s\"'<>]*)?)")
SECRET_VALUE_RE = re.compile(
    r"(?i)(?:\b(?:cookie|token|secret|authorization|password|passwd|api[_-]?key|set-cookie)\b\s*[:=]|bearer\s+[a-z0-9._~+/=-]+)"
)


def is_secret_key(key: Any) -> bool:
    text = str(key).strip().lower().replace("-", "_")
    if text in {"cookie", "cookies", "token", "secret", "authorization", "bearer", "password", "passwd", "api_key", "apikey", "set_cookie"}:
        return True
    if text.endswith(("_token", "_secret", "_password", "_api_key")):
        return True
    return False

LANE_FALLBACK = "P3_external_manual_acquisition"
LANE_RANK = {
    "P1_recover_missing_profile_archive_or_provider": 1,
    "P2_provider_anchor_crosscheck": 2,
    "P2_resolved_source_url_public_or_archive_replay": 3,
    "P2_source_title_crosscheck": 4,
    "P3_external_manual_acquisition": 5,
}
ACTION_BY_LANE = {
    "P1_recover_missing_profile_archive_or_provider": "recover_missing_archive_for_uncovered_profile",
    "P2_provider_anchor_crosscheck": "provider_crosscheck_by_common_account_or_venue",
    "P2_resolved_source_url_public_or_archive_replay": "resolved_source_ref_replay_or_public_fetch",
    "P2_source_title_crosscheck": "source_title_or_event_title_provider_search",
    "P3_external_manual_acquisition": "external_provider_search_required",
}
WORKER_MODE_BY_LANE = {
    "P1_recover_missing_profile_archive_or_provider": "archive_or_provider_recovery_report_only",
    "P2_provider_anchor_crosscheck": "provider_anchor_crosscheck_report_only",
    "P2_resolved_source_url_public_or_archive_replay": "resolved_source_replay_or_no_cookie_public_fetch_report_only",
    "P2_source_title_crosscheck": "source_title_provider_crosscheck_report_only",
    "P3_external_manual_acquisition": "external_or_manual_acquisition_report_only",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def parse_json_object(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def sanitize_scalar(value: Any, *, max_chars: int = 500) -> Any:
    if not isinstance(value, str):
        return value
    redacted = RAW_URL_RE.sub("[REDACTED_URL]", value)
    redacted = D_DRIVE_PATH_RE.sub("[REDACTED_D_DRIVE_PATH]", redacted)
    if SECRET_VALUE_RE.search(redacted):
        return "[REDACTED_CREDENTIAL_VALUE]"
    if len(redacted) > max_chars:
        return f"{redacted[:max_chars]}...[truncated]"
    return redacted


def sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        output = {}
        for key, item in value.items():
            if is_secret_key(key) and isinstance(item, str) and item:
                output[str(key)] = "[REDACTED_CREDENTIAL_VALUE]"
            else:
                output[str(key)] = sanitize_value(item)
        return output
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    return sanitize_scalar(value)


def safe_list_count(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    if isinstance(value, tuple):
        return len(value)
    if isinstance(value, set):
        return len(value)
    if value in (None, "", {}):
        return 0
    return 1


def summarize_source_seed(seed: Any) -> dict[str, Any]:
    if not isinstance(seed, dict):
        return {
            "has_provider_anchor": False,
            "has_source_account_or_title_seed": False,
            "common_source_account_count": 0,
            "common_title_count": 0,
            "common_venue_count": 0,
            "source_seed_keys": [],
        }
    return {
        "has_provider_anchor": bool(seed.get("has_provider_anchor")),
        "has_source_account_or_title_seed": bool(seed.get("has_source_account_or_title_seed")),
        "common_source_account_count": safe_list_count(seed.get("common_source_accounts")),
        "common_title_count": safe_list_count(seed.get("common_titles")),
        "common_venue_count": safe_list_count(seed.get("common_venues")),
        "source_seed_keys": sorted(str(key) for key in seed.keys()),
    }


def infer_lane(seed_summary: dict[str, Any]) -> str:
    if seed_summary.get("has_provider_anchor") or int(seed_summary.get("common_venue_count") or 0) > 0:
        return "P2_provider_anchor_crosscheck"
    if int(seed_summary.get("common_source_account_count") or 0) > 0:
        return "P2_provider_anchor_crosscheck"
    if int(seed_summary.get("common_title_count") or 0) > 0 or seed_summary.get("has_source_account_or_title_seed"):
        return "P2_source_title_crosscheck"
    return LANE_FALLBACK


def load_workbench(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            payload = parse_json_object(text)
            task_id = str(payload.get("task_id") or "").strip()
            group_id = str(payload.get("group_id") or "").strip()
            if task_id:
                rows.setdefault(f"task:{task_id}", payload)
            if group_id:
                rows.setdefault(f"group:{group_id}", payload)
    return rows


def fetch_pending_candidates(
    conn: sqlite3.Connection,
    *,
    source: str,
    review_status: str,
    limit: int = 0,
) -> list[dict[str, Any]]:
    query = """
        SELECT
          sidecar_id,
          subject_id,
          display_name,
          normalized_name,
          alias_used,
          platform,
          handle,
          evidence_text,
          match_type,
          confidence,
          identity_proof,
          accepted_for_graph,
          review_status,
          risk_flags,
          source_profile_id,
          eid,
          source
        FROM dj_identity_candidates
        WHERE source = ?
          AND review_status = ?
          AND COALESCE(accepted_for_graph, 0) = 0
        ORDER BY sidecar_id
    """
    params: list[Any] = [source, review_status]
    if limit and limit > 0:
        query += " LIMIT ?"
        params.append(limit)
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def workbench_lookup(workbench: dict[str, dict[str, Any]], evidence: dict[str, Any]) -> dict[str, Any]:
    task_id = str(evidence.get("s222_task_id") or "").strip()
    group_id = str(evidence.get("s213_group_id") or "").strip()
    if task_id and f"task:{task_id}" in workbench:
        return workbench[f"task:{task_id}"]
    if group_id and f"group:{group_id}" in workbench:
        return workbench[f"group:{group_id}"]
    return {}


def build_plan_row(row: dict[str, Any], workbench: dict[str, dict[str, Any]]) -> dict[str, Any]:
    evidence = parse_json_object(str(row.get("evidence_text") or ""))
    wb = workbench_lookup(workbench, evidence)
    seed = evidence.get("source_seed") or wb.get("source_seed") or {}
    seed_summary = summarize_source_seed(seed)
    lane = str(wb.get("s228_lane") or infer_lane(seed_summary))
    next_action = str(wb.get("next_action") or ACTION_BY_LANE.get(lane) or ACTION_BY_LANE[LANE_FALLBACK])
    priority = str(wb.get("priority") or ("P1_missing_archive_recovery" if lane.startswith("P1_") else "P2_source_provider_acquisition"))
    dj_ids = evidence.get("dj_ids") if isinstance(evidence.get("dj_ids"), list) else wb.get("dj_ids")
    if not isinstance(dj_ids, list):
        dj_ids = []

    blocker_reasons = [
        "pending_source_provider_acquisition",
        "article_or_provider_evidence_missing",
        "db3_relation_integrity_still_red",
    ]
    if lane == "P3_external_manual_acquisition":
        blocker_reasons.append("external_or_manual_acquisition_required")
    if lane.startswith("P1_"):
        blocker_reasons.append("missing_profile_archive_or_provider_recovery_required")

    return sanitize_value(
        {
            "schema_version": "atlas_relation_identity_s231_source_provider_plan.v1",
            "adapter": "db2_identity_source_provider_acquisition_adapter",
            "worker_name": WORKER_NAME,
            "legacy_worker_name": LEGACY_WORKER_NAME,
            "sidecar_id": row.get("sidecar_id"),
            "source_profile_id": row.get("source_profile_id"),
            "eid": row.get("eid"),
            "subject_id": row.get("subject_id"),
            "display_name": row.get("display_name"),
            "normalized_name": row.get("normalized_name"),
            "alias_used": row.get("alias_used"),
            "platform": row.get("platform"),
            "handle": row.get("handle"),
            "task_id": evidence.get("s222_task_id") or wb.get("task_id"),
            "group_id": evidence.get("s213_group_id") or wb.get("group_id"),
            "dj_ids": dj_ids,
            "dj_id_count": len(dj_ids),
            "candidate_source": row.get("source"),
            "review_status": row.get("review_status"),
            "accepted_for_graph": int(row.get("accepted_for_graph") or 0),
            "s228_lane": lane,
            "lane_rank": LANE_RANK.get(lane, 99),
            "priority": priority,
            "next_action": next_action,
            "acquisition_strategy": wb.get("acquisition_strategy") or WORKER_MODE_BY_LANE.get(lane, WORKER_MODE_BY_LANE[LANE_FALLBACK]),
            "recommended_worker_mode": WORKER_MODE_BY_LANE.get(lane, WORKER_MODE_BY_LANE[LANE_FALLBACK]),
            "source_seed_summary": seed_summary,
            "workbench_joined": bool(wb),
            "db3_write_allowed_now": False,
            "db2_projection_allowed_now": False,
            "spool_write_allowed_now": False,
            "network_fetch_executed": False,
            "cookie_required": False,
            "blocker_reasons": blocker_reasons,
            "promotion_state": "report_only_acquisition_plan",
        }
    )


def sort_plan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (int(item.get("lane_rank") or 99), str(item.get("task_id") or ""), str(item.get("sidecar_id") or "")))


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def scan_text_findings(text: str) -> list[str]:
    findings: list[str] = []
    if RAW_URL_RE.search(text):
        findings.append("raw_url_present")
    if SECRET_VALUE_RE.search(text):
        findings.append("secret_like_text_present")
    if D_DRIVE_PATH_RE.search(text):
        findings.append("d_drive_path_present")
    return sorted(set(findings))


def scan_output_files(paths: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        file_findings = scan_text_findings(text)
        if file_findings:
            findings.append({"path": str(path), "findings": file_findings})
    return findings


def build_summary(
    *,
    db_path: Path,
    source: str,
    review_status: str,
    workbench_path: Path | None,
    workbench_count: int,
    plan_rows: list[dict[str, Any]],
    output_dir: Path,
    artifacts: dict[str, str],
    duration_sec: float,
    output_findings: list[dict[str, Any]],
) -> dict[str, Any]:
    lane_counts = Counter(str(row.get("s228_lane") or "") for row in plan_rows)
    action_counts = Counter(str(row.get("next_action") or "") for row in plan_rows)
    priority_counts = Counter(str(row.get("priority") or "") for row in plan_rows)
    joined_count = sum(1 for row in plan_rows if row.get("workbench_joined"))
    return sanitize_value(
        {
            "schema_version": "atlas_relation_identity_s231_source_provider_summary.v1",
            "current_story_id": "S231",
            "adapter": "db2_identity_source_provider_acquisition_adapter",
            "worker_name": WORKER_NAME,
            "legacy_worker_name": LEGACY_WORKER_NAME,
            "decision": "atlas_relation_identity_s231_identity_source_provider_ready_report_only",
            "generated_at": utc_now(),
            "duration_sec": round(duration_sec, 4),
            "db_path": str(db_path),
            "db_read_only": True,
            "input_source": source,
            "input_review_status": review_status,
            "input_candidate_count": len(plan_rows),
            "plan_row_count": len(plan_rows),
            "workbench_path": str(workbench_path) if workbench_path else "",
            "workbench_available": bool(workbench_count),
            "workbench_loaded_row_keys": workbench_count,
            "workbench_joined_count": joined_count,
            "workbench_unjoined_count": max(len(plan_rows) - joined_count, 0),
            "counts_by_lane": dict(sorted(lane_counts.items())),
            "counts_by_next_action": dict(sorted(action_counts.items())),
            "counts_by_priority": dict(sorted(priority_counts.items())),
            "db3_write_candidate_count": 0,
            "db2_projection_candidate_count": 0,
            "accepted_for_graph_candidate_count": 0,
            "network_fetch_executed": False,
            "spool_write_executed": False,
            "db_write_executed": False,
            "cookie_or_token_read": False,
            "raw_source_url_emitted": False,
            "raw_archive_path_emitted": False,
            "output_dir": str(output_dir),
            "artifacts": artifacts,
            "output_safety_findings": output_findings,
            "finding_count": len(output_findings),
            "next_gate": "run bounded provider/archive/no-cookie evidence collectors only after DB2 health/writer/schedule are green; keep DB3 writes blocked until article-ready or provider-crosschecked evidence exists",
            "production_state_difference": "report-only readback and acquisition planning; no DB1/DB2/DB3 mutation, no DB2 projection, no deploy, no upload, no review, no release",
        }
    )


def default_output_dir() -> Path:
    return DEFAULT_REPORTS_DIR / f"atlas_relation_identity_s231_identity_source_provider_{now_run_id()}"


def run(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    output_dir = args.output_dir or default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)

    workbench_path = Path(args.workbench_jsonl) if args.workbench_jsonl else None
    workbench = load_workbench(workbench_path)

    conn = connect_readonly(args.db)
    try:
        candidates = fetch_pending_candidates(
            conn,
            source=args.source,
            review_status=args.review_status,
            limit=args.limit,
        )
    finally:
        conn.close()

    plan_rows = sort_plan_rows([build_plan_row(row, workbench) for row in candidates])
    followup_rows = [
        {
            "schema_version": "atlas_relation_identity_s231_followup.v1",
            "sidecar_id": row.get("sidecar_id"),
            "task_id": row.get("task_id"),
            "group_id": row.get("group_id"),
            "s228_lane": row.get("s228_lane"),
            "next_action": row.get("next_action"),
            "blocker_reasons": row.get("blocker_reasons"),
            "db3_write_allowed_now": False,
            "db2_projection_allowed_now": False,
            "promotion_state": "blocked_pending_acquisition_not_skipped",
        }
        for row in plan_rows
    ]

    plan_path = output_dir / "s231_identity_source_provider_plan.jsonl"
    followup_path = output_dir / "s231_blocked_or_followup.jsonl"
    summary_path = output_dir / "summary.json"
    write_jsonl(plan_path, plan_rows)
    write_jsonl(followup_path, followup_rows)
    artifacts = {
        "plan_jsonl": str(plan_path),
        "blocked_or_followup_jsonl": str(followup_path),
        "summary_json": str(summary_path),
    }
    output_findings = scan_output_files([plan_path, followup_path])
    summary = build_summary(
        db_path=args.db,
        source=args.source,
        review_status=args.review_status,
        workbench_path=workbench_path,
        workbench_count=len(workbench),
        plan_rows=plan_rows,
        output_dir=output_dir,
        artifacts=artifacts,
        duration_sec=time.monotonic() - started,
        output_findings=output_findings,
    )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DB2 relation identity source/provider acquisition planner")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--review-status", default=DEFAULT_REVIEW_STATUS)
    parser.add_argument("--workbench-jsonl", default=DEFAULT_WORKBENCH_JSONL)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit < 0:
        raise SystemExit("--limit must be >= 0")
    summary = run(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if int(summary.get("finding_count") or 0) == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
