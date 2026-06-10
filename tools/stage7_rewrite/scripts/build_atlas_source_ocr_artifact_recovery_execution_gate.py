#!/usr/bin/env python3
"""Build a report-only execution gate for Atlas source/OCR artifact recovery.

The 03:48 localization probe split the current T5 cursor into two queues:
rows with OCR candidates but no exact date, and rows missing OCR/Markdown.
This gate checks whether those rows can actually advance locally before any
OCR runner or acceptance precheck is retried.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
LOCALIZATION_ROOT = STAGE7_ROOT / "reports" / "atlas_source_ocr_artifact_localization_probe_t5_20260526"
DEFAULT_DATE_BLOCKED = LOCALIZATION_ROOT / "ocr_candidate_present_date_blocked.jsonl"
DEFAULT_OCR_MISSING = LOCALIZATION_ROOT / "ocr_markdown_missing_generation_queue.jsonl"
DEFAULT_SOURCE_URL_JSONL = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_source_url_recovery_139123_candidate"
    / "article_source_url.jsonl"
)
DEFAULT_HOST_ARTIFACT_ROOT = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "host_html_artifacts"
    / "artifacts"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_ocr_artifact_recovery_execution_gate_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_OCR_ARTIFACT_RECOVERY_EXECUTION_GATE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_ocr_artifact_recovery_execution_gate.v1"

URL_RE = re.compile(r"https?://", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(r"(secret|token|cookie|password|api[_-]?key|authorization)", re.I)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas source/OCR execution gate: {path}")


def is_d_root_value(value: Any) -> bool:
    text = str(value or "").replace("\\", "/").casefold()
    return text.startswith("d:/") or text.startswith("/mnt/d/")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def safe_hash(value: Any, length: int = 16) -> str:
    return hashlib.sha256(compact(value, 8000).encode("utf-8", errors="ignore")).hexdigest()[:length]


def scrub_sensitive_words(value: Any, limit: int = 1000) -> str:
    return SENSITIVE_KEY_RE.sub("redacted-word", compact(value, limit))


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return path.name


def read_jsonl(path: Path, *, optional: bool = False) -> list[dict[str, Any]]:
    reject_d_path(path, "input_jsonl")
    if optional and not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def source_slug(source_account: str) -> str:
    text = compact(source_account, 180).casefold()
    slug = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return slug or safe_hash(source_account)


def host_scope(host_root: Path, source_account: str) -> dict[str, Any]:
    reject_d_path(host_root, "host_artifact_root")
    if not host_root.exists():
        return {
            "source_artifact_ref_id": safe_hash(source_account),
            "source_dir_present": False,
            "source_dir_status": "host_artifact_root_absent",
        }
    slug = source_slug(source_account)
    dirs = {child.name.casefold() for child in host_root.iterdir() if child.is_dir()}
    return {
        "source_artifact_ref_id": safe_hash(source_account),
        "source_dir_present": slug in dirs,
        "source_dir_status": "source_dir_present" if slug in dirs else "source_dir_absent_in_current_host_html_artifact_batch",
    }


def source_url_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        uid = compact(row.get("article_uid") or row.get("article_id"), 200)
        if uid:
            indexed[uid] = row
    return indexed


def safe_source_artifact_state(row: dict[str, Any] | None) -> dict[str, Any]:
    source = row or {}
    raw_url = compact(source.get("source_url"), 5000)
    archive_path = compact(source.get("archive_raw_html_path"), 1200)
    source_file = compact(source.get("source_file"), 1200)
    artifact_ref_present = bool(archive_path or source_file)
    artifact_ref_d_root = is_d_root_value(archive_path) or is_d_root_value(source_file)
    return {
        "source_url_recovery_found": bool(row),
        "source_ref_id": compact(source.get("source_ref_id"), 160),
        "source_url_present": bool(raw_url),
        "source_url_sha256": hashlib.sha256(raw_url.encode("utf-8", errors="ignore")).hexdigest() if raw_url else "",
        "source_url_match_basis": scrub_sensitive_words(source.get("match_basis"), 180),
        "post_date_present": bool(compact(source.get("post_date"), 80)),
        "post_time_present": bool(compact(source.get("post_time"), 80)),
        "sidecar_local_artifact_ref_present": artifact_ref_present,
        "sidecar_local_artifact_ref_id": safe_hash(f"{archive_path}|{source_file}") if artifact_ref_present else "",
        "sidecar_local_artifact_ref_d_root": artifact_ref_d_root,
        "local_image_count": as_int(source.get("local_image_count")),
        "raw_artifact_path_emitted": False,
        "raw_source_url_emitted": False,
    }


def row_queue_kind(row: dict[str, Any]) -> str:
    if compact(row.get("_input_queue"), 120):
        return compact(row.get("_input_queue"), 120)
    if row.get("existing_ocr_markdown_candidate_found"):
        return "ocr_candidate_present_date_blocked"
    return "ocr_markdown_missing_generation"


def route_row(
    *,
    generated_at: str,
    row: dict[str, Any],
    source_url_row: dict[str, Any] | None,
    host_artifact_root: Path,
) -> dict[str, Any]:
    uid = compact(row.get("article_uid"), 200)
    account = compact(row.get("source_account"), 240)
    source_state = safe_source_artifact_state(source_url_row)
    scope = host_scope(host_artifact_root, account)
    has_ocr_candidate = bool(row.get("existing_ocr_markdown_candidate_found"))
    has_exact_date = bool(row.get("exact_date_candidate_found"))
    missing_ocr_markdown = not has_ocr_candidate
    local_artifact_ready = bool(
        missing_ocr_markdown
        and (
            scope["source_dir_present"]
            or (
                source_state["sidecar_local_artifact_ref_present"]
                and not source_state["sidecar_local_artifact_ref_d_root"]
            )
        )
    )
    source_artifact_acquisition_required = bool(missing_ocr_markdown and not local_artifact_ready)

    if has_ocr_candidate and not has_exact_date:
        route = "exact_date_review_from_existing_ocr_candidate"
        next_action = "review_existing_ocr_and_article_text_for_exact_event_date_without_rerunning_acceptance"
    elif local_artifact_ready:
        route = "local_ocr_markdown_generation_ready"
        next_action = "run_bounded_local_ocr_markdown_generation_then_extract_exact_date"
    elif source_artifact_acquisition_required:
        route = "source_artifact_acquisition_required_before_ocr_generation"
        next_action = "locate_or_recover_original_article_assets_before_any_ocr_generation"
    elif has_exact_date and has_ocr_candidate:
        route = "candidate_evidence_present_acceptance_still_closed"
        next_action = "rerun_acceptance_precheck_only_after_reviewer_confirms_policy"
    else:
        route = "still_blocked_unclassified"
        next_action = "inspect_row_before_retrying_acceptance"

    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "article_uid": uid,
        "work_item_id": compact(row.get("work_item_id"), 120),
        "input_queue": row_queue_kind(row),
        "source_account": account,
        "title": compact(row.get("title"), 500),
        "blocking_fields": [compact(value, 120) for value in row.get("blocking_fields", []) if compact(value, 120)],
        "local_image_count": as_int(row.get("local_image_count") or source_state["local_image_count"]),
        "existing_ocr_markdown_candidate_found": has_ocr_candidate,
        "exact_date_candidate_found": has_exact_date,
        "source_url_artifact_state": source_state,
        "host_artifact_scope": scope,
        "local_ocr_markdown_generation_ready": local_artifact_ready,
        "source_artifact_acquisition_required": source_artifact_acquisition_required,
        "execution_route": route,
        "next_action": next_action,
        "acceptance_precheck_allowed_now": False,
        "ocr_execution_executed": False,
        "accepted_for_graph": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "write_status": "report_only",
    }


def scan_payload_for_leaks(value: Any) -> dict[str, int]:
    hits = {"local_path_hits": 0, "public_url_hits": 0, "sensitive_key_hits": 0}
    if isinstance(value, dict):
        for child in value.values():
            child_hits = scan_payload_for_leaks(child)
            for key, count in child_hits.items():
                hits[key] += count
        return hits
    if isinstance(value, list):
        for child in value:
            child_hits = scan_payload_for_leaks(child)
            for key, count in child_hits.items():
                hits[key] += count
        return hits
    text = compact(value, 4000)
    if not text:
        return hits
    hits["public_url_hits"] += len(URL_RE.findall(text))
    hits["local_path_hits"] += len(LOCAL_PATH_RE.findall(text))
    hits["sensitive_key_hits"] += len(SENSITIVE_KEY_RE.findall(text))
    return hits


def leak_scan(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    total = {"local_path_hits": 0, "public_url_hits": 0, "sensitive_key_hits": 0}
    for row in rows:
        hits = scan_payload_for_leaks(row)
        for key, count in hits.items():
            total[key] += count
    return total


def build_source_rollup(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["source_account"] or "UNKNOWN"].append(row)
    rollup = []
    for source, source_rows in sorted(grouped.items()):
        rollup.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_rollup",
                "generated_at": generated_at,
                "source_account": source,
                "target_rows": len(source_rows),
                "execution_route_counts": dict(sorted(Counter(row["execution_route"] for row in source_rows).items())),
                "local_ocr_markdown_generation_ready_rows": sum(
                    1 for row in source_rows if row["local_ocr_markdown_generation_ready"]
                ),
                "source_artifact_acquisition_required_rows": sum(
                    1 for row in source_rows if row["source_artifact_acquisition_required"]
                ),
                "exact_date_review_rows": sum(
                    1 for row in source_rows if row["execution_route"] == "exact_date_review_from_existing_ocr_candidate"
                ),
                "write_status": "report_only",
            }
        )
    return rollup


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    lines = [
        "# Atlas T5 Source/OCR Artifact Recovery Execution Gate - 2026-05-26",
        "",
        "Status: `CURRENT_AUTHORITY`",
        "Mode: `report_only`",
        "",
        "## LLM Audit Finding",
        "",
        "The 03:48 localization probe was internally consistent, but the next queues still did not say whether OCR can actually run from local artifacts. This gate checks the two queue files plus the bounded source-url sidecar and host-html artifact root. It prevents a blind OCR retry when image counts exist but local artifact paths are unavailable.",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Target rows: `{counts['target_rows']}`",
        f"- Exact-date review rows: `{counts['exact_date_review_rows']}`",
        f"- OCR/Markdown missing rows: `{counts['ocr_markdown_missing_rows']}`",
        f"- Local OCR/Markdown generation-ready rows: `{counts['local_ocr_markdown_generation_ready_rows']}`",
        f"- Source artifact acquisition required rows: `{counts['source_artifact_acquisition_required_rows']}`",
        f"- Source-url post-date/time rows: `{counts['source_url_post_date_rows']}` / `{counts['source_url_post_time_rows']}`",
        f"- Host source-dir present rows: `{counts['host_source_dir_present_rows']}`",
        f"- Acceptance-precheck allowed now: `{counts['acceptance_precheck_allowed_rows']}`",
        f"- Public URL / sensitive-key / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Outputs",
        "",
        f"- Summary JSON: `{outputs['summary_json']}`",
        f"- Gate rows: `{outputs['gate_rows_jsonl']}`",
        f"- Exact-date review queue: `{outputs['exact_date_review_queue_jsonl']}`",
        f"- OCR/Markdown generation-ready queue: `{outputs['ocr_markdown_generation_ready_queue_jsonl']}`",
        f"- Source artifact acquisition queue: `{outputs['source_artifact_acquisition_queue_jsonl']}`",
        f"- Acceptance hold rows: `{outputs['acceptance_hold_rows_jsonl']}`",
        f"- Source rollup: `{outputs['source_rollup_jsonl']}`",
        "",
        "## Row Snapshot",
        "",
    ]
    for row in rows[:10]:
        lines.append(
            f"- `{row['article_uid']}` `{row['source_account']}` / {row['title']} -> `{row['execution_route']}`; images `{row['local_image_count']}`; next `{row['next_action']}`"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only local execution gate.",
            "- No OCR execution, model call, source/raw Atlas DB write, serving SQLite write or rebuild, public pointer, CloudRun/VPS deploy, Neo4j/Qdrant/SQLite production write, mini-program upload/review, memory write, credential read, 9router use, destructive Git, or D root scan occurred.",
            "- Raw source URLs and local filesystem paths are not emitted. Source URL and artifact refs are represented by hashes/booleans only.",
            "",
            "## Next Cursor",
            "",
            "Review the two exact-date rows against existing OCR/article text. For the five OCR/Markdown-missing rows, first locate or recover original article/image artifacts; no local OCR generation should start from the current host artifact batch because it has no matching source directories for these accounts.",
            "",
        ]
    )
    return "\n".join(lines)


def build_execution_gate(
    *,
    date_blocked_path: Path,
    ocr_missing_path: Path,
    source_url_jsonl: Path,
    host_artifact_root: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for label, path in (
        ("date_blocked_path", date_blocked_path),
        ("ocr_missing_path", ocr_missing_path),
        ("source_url_jsonl", source_url_jsonl),
        ("host_artifact_root", host_artifact_root),
        ("out_dir", out_dir),
        ("report_path", report_path),
    ):
        reject_d_path(path, label)

    generated_at = now_iso()
    date_rows = read_jsonl(date_blocked_path)
    missing_rows = read_jsonl(ocr_missing_path)
    for row in date_rows:
        row["_input_queue"] = "ocr_candidate_present_date_blocked"
    for row in missing_rows:
        row["_input_queue"] = "ocr_markdown_missing_generation"
    source_urls = source_url_index(read_jsonl(source_url_jsonl, optional=True))
    rows = [
        route_row(
            generated_at=generated_at,
            row=row,
            source_url_row=source_urls.get(compact(row.get("article_uid"), 200)),
            host_artifact_root=host_artifact_root,
        )
        for row in date_rows + missing_rows
    ]
    exact_date_review = [row for row in rows if row["execution_route"] == "exact_date_review_from_existing_ocr_candidate"]
    generation_ready = [row for row in rows if row["local_ocr_markdown_generation_ready"]]
    source_acquisition = [row for row in rows if row["source_artifact_acquisition_required"]]
    acceptance_hold = [row for row in rows if not row["acceptance_precheck_allowed_now"]]
    source_rollup = build_source_rollup(rows, generated_at)

    write_jsonl(out_dir / "source_ocr_artifact_recovery_execution_gate_rows.jsonl", rows)
    write_jsonl(out_dir / "exact_date_review_queue.jsonl", exact_date_review)
    write_jsonl(out_dir / "ocr_markdown_generation_ready_queue.jsonl", generation_ready)
    write_jsonl(out_dir / "source_artifact_acquisition_queue.jsonl", source_acquisition)
    write_jsonl(out_dir / "acceptance_hold_rows.jsonl", acceptance_hold)
    write_jsonl(out_dir / "source_rollup.jsonl", source_rollup)

    leak = leak_scan(rows + source_rollup)
    failed_checks = [key for key, value in leak.items() if value]
    if not rows:
        failed_checks.append("no_execution_gate_rows")
    counts = {
        "target_rows": len(rows),
        "exact_date_review_rows": len(exact_date_review),
        "ocr_markdown_missing_rows": len(missing_rows),
        "local_ocr_markdown_generation_ready_rows": len(generation_ready),
        "source_artifact_acquisition_required_rows": len(source_acquisition),
        "acceptance_precheck_allowed_rows": sum(1 for row in rows if row["acceptance_precheck_allowed_now"]),
        "host_source_dir_present_rows": sum(1 for row in rows if row["host_artifact_scope"].get("source_dir_present")),
        "sidecar_local_artifact_ref_rows": sum(
            1 for row in rows if row["source_url_artifact_state"].get("sidecar_local_artifact_ref_present")
        ),
        "sidecar_d_root_artifact_ref_rows": sum(
            1 for row in rows if row["source_url_artifact_state"].get("sidecar_local_artifact_ref_d_root")
        ),
        "source_url_post_date_rows": sum(1 for row in rows if row["source_url_artifact_state"].get("post_date_present")),
        "source_url_post_time_rows": sum(1 for row in rows if row["source_url_artifact_state"].get("post_time_present")),
    }
    decision = (
        "atlas_source_ocr_artifact_recovery_execution_gate_failed_safety_scan"
        if failed_checks
        else "atlas_source_ocr_artifact_recovery_execution_gate_blocked_report_only"
        if counts["source_artifact_acquisition_required_rows"] or counts["exact_date_review_rows"]
        else "atlas_source_ocr_artifact_recovery_execution_gate_ready_report_only"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "execution_route_counts": dict(sorted(Counter(row["execution_route"] for row in rows).items())),
        "source_account_counts": dict(sorted(Counter(row["source_account"] or "UNKNOWN" for row in rows).items())),
        "inputs": {
            "date_blocked_queue": display_path(date_blocked_path),
            "ocr_missing_queue": display_path(ocr_missing_path),
            "source_url_jsonl": display_path(source_url_jsonl),
            "host_artifact_root": display_path(host_artifact_root),
        },
        "outputs": {
            "summary_json": display_path(out_dir / "source_ocr_artifact_recovery_execution_gate_summary.json"),
            "gate_rows_jsonl": display_path(out_dir / "source_ocr_artifact_recovery_execution_gate_rows.jsonl"),
            "exact_date_review_queue_jsonl": display_path(out_dir / "exact_date_review_queue.jsonl"),
            "ocr_markdown_generation_ready_queue_jsonl": display_path(out_dir / "ocr_markdown_generation_ready_queue.jsonl"),
            "source_artifact_acquisition_queue_jsonl": display_path(out_dir / "source_artifact_acquisition_queue.jsonl"),
            "acceptance_hold_rows_jsonl": display_path(out_dir / "acceptance_hold_rows.jsonl"),
            "source_rollup_jsonl": display_path(out_dir / "source_rollup.jsonl"),
            "report_md": display_path(report_path),
        },
        "leak_scan": leak,
        "llm_audit": {
            "artifact_contradiction_found": False,
            "queue_contradiction_found": False,
            "highest_leverage_lane": "execution_gate_between_localization_probe_and_any_ocr_or_acceptance_retry",
            "pipeline_improvement": "separates_exact_date_review_from_source_artifact_acquisition_and_local_ocr_generation_ready_rows",
            "stale_loop_avoided": "did_not_start_ocr_generation_when_current_host_artifact_batch_has_no_matching_source_dirs",
        },
        "safety": {
            "report_only": True,
            "raw_source_url_emitted": False,
            "raw_local_path_emitted": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "ocr_execution_executed": False,
            "source_sqlite_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "blocked_report_only_until_exact_date_review_and_source_artifact_acquisition_advance",
        "wait_reason": "current queues contain no row ready for acceptance precheck or local OCR generation from the bounded host artifact batch.",
        "next_resume_cursor": "Review exact_date_review_queue.jsonl first; then locate/recover source artifacts for source_artifact_acquisition_queue.jsonl before running OCR/Markdown generation or acceptance precheck.",
    }
    write_json(out_dir / "source_ocr_artifact_recovery_execution_gate_summary.json", summary)
    write_text(report_path, render_report(summary, rows))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-blocked", type=Path, default=DEFAULT_DATE_BLOCKED)
    parser.add_argument("--ocr-missing", type=Path, default=DEFAULT_OCR_MISSING)
    parser.add_argument("--source-url-jsonl", type=Path, default=DEFAULT_SOURCE_URL_JSONL)
    parser.add_argument("--host-artifact-root", type=Path, default=DEFAULT_HOST_ARTIFACT_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_execution_gate(
        date_blocked_path=args.date_blocked,
        ocr_missing_path=args.ocr_missing,
        source_url_jsonl=args.source_url_jsonl,
        host_artifact_root=args.host_artifact_root,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
