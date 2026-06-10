#!/usr/bin/env python3
"""Replay exact local source archives for S191 relation evidence.

S192 handles the expected WeChat no-cookie blocker from S191: public HTTP
returns verification shells, while earlier mptext archives already contain
exact raw.html files. This script reads only exact archive paths from the
source-url recovery SQLite, writes report-local evidence bundles, and does not
scan D:, mutate DB1/DB2/DB3, or publish raw URLs/paths.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.stage7_rewrite.scripts import run_atlas_source_acquisition_bounded_fetch as fetch_runner


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
SCHEMA_VERSION = "atlas_relation_source_archive_replay_s192.v1"
CURRENT_STORY_ID = "S192"
DEFAULT_S191_DIR = REPORTS_ROOT / "atlas_relation_external_public_crawl_canary_s191_20260602"
DEFAULT_SOURCE_URL_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_source_url_recovery_139123_candidate"
    / "atlas_source_url_recovery.sqlite"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_source_archive_replay_s192_20260602"
DEFAULT_REPORT = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_SOURCE_ARCHIVE_REPLAY_S192_20260602.md"
DEFAULT_ALLOWED_ARCHIVE_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun\WHERE_TO_RAVE_WECHAT_SYNC_20260508")
RAW_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
D_DRIVE_RE = re.compile(r"(?i)(?:\bD:\\[^\s\"'<>]+|/mnt/d(?:/[^\s\"'<>]*)?)")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def stable_hash(value: Any, length: int = 24) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def rel_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        return str(path)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
        handle.write(payload)
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
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def sqlite_connect_ro(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def archive_path_allowed(path: Path, allowed_root: Path) -> bool:
    try:
        path_resolved = path.resolve()
        root_resolved = allowed_root.resolve()
        path_resolved.relative_to(root_resolved)
        return True
    except (OSError, ValueError):
        return False


def source_rows_by_article_uid(source_url_db: Path, article_uids: set[str]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not article_uids:
        return rows
    conn = sqlite_connect_ro(source_url_db)
    try:
        for uid in sorted(article_uids):
            row = row_dict(
                conn.execute(
                    """
                    SELECT source_ref_id, article_uid, article_id, source_account, title, post_date,
                           archive_raw_html_path, match_basis, confidence, entity_count, event_count,
                           local_image_count
                    FROM article_source_url
                    WHERE article_uid = ?
                    LIMIT 1
                    """,
                    (uid,),
                ).fetchone()
            )
            if row:
                rows[uid] = row
    finally:
        conn.close()
    return rows


def artifact_dir(out_dir: Path, row: dict[str, Any]) -> Path:
    return out_dir / "artifact_bundles" / stable_hash(
        {
            "source_ref_id": row.get("source_ref_id"),
            "article_uid": row.get("article_uid"),
            "story": CURRENT_STORY_ID,
        },
        24,
    )


def replay_row(
    *,
    generated_at: str,
    private_row: dict[str, Any],
    evidence_context: dict[str, Any] | None,
    source_row: dict[str, Any] | None,
    out_dir: Path,
    allowed_archive_root: Path,
    max_bytes: int,
) -> dict[str, Any]:
    base = {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "source_ref_id": compact(private_row.get("source_ref_id"), 160),
        "resolved_article_source_ref_id": compact(private_row.get("resolved_article_source_ref_id"), 160),
        "article_uid": compact(private_row.get("article_uid"), 300),
        "group_id": (evidence_context or {}).get("group_id", ""),
        "dj_ids": (evidence_context or {}).get("dj_ids") or [],
        "display_names": (evidence_context or {}).get("display_names") or [],
        "route": (evidence_context or {}).get("route", ""),
        "source_account": compact(private_row.get("source_account"), 240),
        "title": compact(private_row.get("title"), 500),
        "post_date": compact(private_row.get("post_date"), 80),
        "archive_path_sha256": "",
        "archive_path_emitted": False,
        "raw_source_url_emitted": False,
        "exact_archive_file_read": False,
        "artifact_written": False,
        "article_artifact_ready": False,
        "artifact_bundle_relpath": "",
        "html_artifact_ref_id": "",
        "html_sha256": "",
        "html_bytes": 0,
        "content_flags": {},
        "decision": "",
        "decision_reasons": [],
        "accepted_for_db3_write": False,
        "accepted_for_db2_projection": False,
        "accepted_for_public_release": False,
    }
    if not source_row:
        base["decision"] = "blocked_source_url_row_missing_report_only"
        base["decision_reasons"] = ["source_url_row_missing"]
        return base
    raw_archive_path = compact(source_row.get("archive_raw_html_path"), 5000)
    if not raw_archive_path:
        base["decision"] = "blocked_archive_path_missing_report_only"
        base["decision_reasons"] = ["archive_raw_html_path_missing"]
        return base
    archive_path = Path(raw_archive_path)
    base["archive_path_sha256"] = hashlib.sha256(raw_archive_path.encode("utf-8", errors="ignore")).hexdigest()
    if not archive_path_allowed(archive_path, allowed_archive_root):
        base["decision"] = "blocked_archive_path_outside_allowed_root_report_only"
        base["decision_reasons"] = ["archive_path_outside_allowed_root"]
        return base
    if not archive_path.is_file():
        base["decision"] = "blocked_archive_path_missing_on_disk_report_only"
        base["decision_reasons"] = ["archive_path_missing_on_disk"]
        return base
    data = archive_path.read_bytes()[:max_bytes]
    flags = fetch_runner.html_content_flags(data, "text/html; charset=utf-8", base["title"])
    has_article = bool(flags.get("wechat_article_marker_seen") or flags.get("js_content_text_len", 0) >= 20 or flags.get("title_prefix_seen"))
    bundle_dir = artifact_dir(out_dir, base)
    html_path = bundle_dir / "article.html"
    atomic_write_bytes(html_path, data)
    html_sha = bytes_hash(data)
    base.update(
        {
            "exact_archive_file_read": True,
            "artifact_written": True,
            "article_artifact_ready": bool(has_article),
            "artifact_bundle_relpath": rel_path(bundle_dir),
            "html_artifact_ref_id": f"report_local_html_artifact:{html_sha[:24]}",
            "html_sha256": html_sha,
            "html_bytes": len(data),
            "content_flags": flags,
            "decision": "archive_html_article_content_review_ready" if has_article else "archive_html_weak_review_only",
            "decision_reasons": ["article_content_marker_seen"] if has_article else ["article_content_marker_absent"],
        }
    )
    return base


def public_output_text(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        if path.exists():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# S192 Relation Source Archive Replay",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Input S191 rows: `{counts['input_private_source_rows']}`",
        f"- Exact archive paths found: `{counts['archive_paths_found']}`",
        f"- Exact archive files read: `{counts['exact_archive_files_read']}`",
        f"- Artifact-written rows: `{counts['artifact_written_rows']}`",
        f"- Article-ready rows: `{counts['article_artifact_ready_rows']}`",
        "",
        "## Decision Counts",
        "",
    ]
    for key, value in summary["decision_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- D: was not scanned. Only exact archive_raw_html_path values from source-url recovery SQLite were opened after allowed-root validation.",
            "- Raw D: paths and raw source URLs are not emitted in this report, summary, or normalized evidence.",
            "- No DB1/DB2/DB3 mutation, DB2 projection, deploy/upload/review/release, browser profile use, cookie/API key reads, LLM calls, OCR execution, or memory write occurred.",
            "",
            "## Next Gate",
            "",
            summary["execution_cursor"]["next_action"],
            "",
        ]
    )
    return "\n".join(lines)


def run_s192(
    *,
    s191_dir: Path,
    source_url_db: Path,
    out_dir: Path,
    report_path: Path,
    allowed_archive_root: Path,
    max_bytes: int,
) -> dict[str, Any]:
    generated_at = now_iso()
    private_source_path = s191_dir / "private_inputs" / "s191_private_source_url_sidecar.jsonl"
    s191_evidence_path = s191_dir / "s191_normalized_public_evidence.jsonl"
    private_rows = read_jsonl(private_source_path)
    evidence_rows = read_jsonl(s191_evidence_path) if s191_evidence_path.exists() else []
    evidence_by_source_ref = {row.get("source_ref_id"): row for row in evidence_rows}
    source_rows = source_rows_by_article_uid(source_url_db, {compact(row.get("article_uid"), 300) for row in private_rows})
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = [
        replay_row(
            generated_at=generated_at,
            private_row=row,
            evidence_context=evidence_by_source_ref.get(row.get("source_ref_id")),
            source_row=source_rows.get(compact(row.get("article_uid"), 300)),
            out_dir=out_dir,
            allowed_archive_root=allowed_archive_root,
            max_bytes=max_bytes,
        )
        for row in private_rows
    ]
    ready = [row for row in rows if row["article_artifact_ready"]]
    blocked = [row for row in rows if not row["article_artifact_ready"]]
    manifest_path = out_dir / "s192_archive_replay_manifest.jsonl"
    ready_path = out_dir / "s192_archive_article_ready_rows.jsonl"
    blocked_path = out_dir / "s192_archive_blocked_rows.jsonl"
    evidence_path = out_dir / "s192_normalized_archive_evidence.jsonl"
    summary_path = out_dir / "atlas_relation_source_archive_replay_s192.json"
    write_jsonl(manifest_path, rows)
    write_jsonl(ready_path, ready)
    write_jsonl(blocked_path, blocked)
    write_jsonl(evidence_path, rows)

    failed_checks: list[str] = []
    scan_text = public_output_text([manifest_path, ready_path, blocked_path, evidence_path])
    if RAW_URL_RE.search(scan_text):
        failed_checks.append("s192_public_outputs_contain_raw_url")
    if D_DRIVE_RE.search(scan_text):
        failed_checks.append("s192_public_outputs_contain_raw_d_path")
    decision = (
        "s192_archive_replay_article_artifacts_ready_report_only"
        if ready and not failed_checks
        else "s192_archive_replay_completed_with_blocked_rows_report_only"
        if rows and not failed_checks
        else "s192_archive_replay_failed_safety_gate"
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "current_story_id": CURRENT_STORY_ID,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "s191_dir": rel_path(s191_dir),
            "source_url_db": rel_path(source_url_db),
            "allowed_archive_root_sha256": hashlib.sha256(str(allowed_archive_root).encode("utf-8")).hexdigest(),
            "max_bytes": max_bytes,
        },
        "outputs": {
            "summary_json": rel_path(summary_path),
            "scorecard_markdown": rel_path(report_path),
            "manifest_jsonl": rel_path(manifest_path),
            "article_ready_jsonl": rel_path(ready_path),
            "blocked_jsonl": rel_path(blocked_path),
            "normalized_evidence_jsonl": rel_path(evidence_path),
            "artifact_bundles": rel_path(out_dir / "artifact_bundles"),
        },
        "counts": {
            "input_private_source_rows": len(private_rows),
            "source_url_rows_found": len(source_rows),
            "archive_paths_found": sum(1 for row in source_rows.values() if compact(row.get("archive_raw_html_path"), 5000)),
            "exact_archive_files_read": sum(1 for row in rows if row["exact_archive_file_read"]),
            "artifact_written_rows": sum(1 for row in rows if row["artifact_written"]),
            "article_artifact_ready_rows": len(ready),
            "blocked_or_not_ready_rows": len(blocked),
            "html_bytes_total": sum(int(row.get("html_bytes") or 0) for row in rows),
        },
        "decision_counts": dict(sorted(Counter(row["decision"] for row in rows).items())),
        "execution_cursor": {
            "next_story_id": "S193",
            "next_input": rel_path(ready_path) if ready else rel_path(blocked_path),
            "next_action": "S193: run source-ref coverage and relation evidence review on archive-ready rows, then open a no-empty-overwrite DB3 relation write gate only for rows that preserve existing fields and pass postwrite readback.",
            "db3_write_allowed_now": False,
            "db2_projection_allowed_now": False,
            "deploy_upload_review_release_allowed_now": False,
        },
        "safety": {
            "exact_archive_path_reads_only": True,
            "d_root_scan": False,
            "raw_archive_path_emitted": False,
            "raw_source_url_emitted": False,
            "cookie_or_token_read": False,
            "llm_call_executed": False,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection": False,
            "deploy_upload_review_release": False,
        },
    }
    write_json(summary_path, summary)
    atomic_write_text(report_path, render_report(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s191-dir", type=Path, default=DEFAULT_S191_DIR)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URL_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--allowed-archive-root", type=Path, default=DEFAULT_ALLOWED_ARCHIVE_ROOT)
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_s192(
        s191_dir=args.s191_dir,
        source_url_db=args.source_url_db,
        out_dir=args.out_dir,
        report_path=args.report,
        allowed_archive_root=args.allowed_archive_root,
        max_bytes=args.max_bytes,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "failed_checks": summary["failed_checks"],
                "exact_archive_files_read": summary["counts"]["exact_archive_files_read"],
                "article_artifact_ready_rows": summary["counts"]["article_artifact_ready_rows"],
                "summary": summary["outputs"]["summary_json"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
