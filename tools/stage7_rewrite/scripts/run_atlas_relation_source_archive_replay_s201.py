#!/usr/bin/env python3
"""Replay exact local archives from the S200 P0 queue.

S201 bypasses the low-yield public no-cookie route when S200 proves that exact
mptext archive files already exist for every profile in a relation group. It
reads only the source_ref IDs listed in the S200 queue and the exact
archive_raw_html_path values from the source-url recovery SQLite. It does not
scan D:, fetch the network, or mutate DB1/DB2/DB3.
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

from tools.stage7_rewrite.scripts import run_atlas_relation_source_archive_replay_s192 as s192


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPORTS_ROOT = STAGE7_ROOT / "reports"
CURRENT_STORY_ID = "S201"
REPORT_STEM = "atlas_relation_source_archive_replay_s201"
SCHEMA_VERSION = f"{REPORT_STEM}.v1"

DEFAULT_QUEUE = (
    REPORTS_ROOT
    / "atlas_relation_identity_residual_repair_superbatch_s200_20260602"
    / "s201_exact_local_archive_replay_queue.jsonl"
)
DEFAULT_SOURCE_URL_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_source_url_recovery_139123_candidate"
    / "atlas_source_url_recovery.sqlite"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_source_archive_replay_s201_20260602"
DEFAULT_REPORT = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_SOURCE_ARCHIVE_REPLAY_S201_20260602.md"
DEFAULT_ALLOWED_ARCHIVE_ROOT = Path(r"D:\downstream_results\stage7_rewrite\longrun\WHERE_TO_RAVE_WECHAT_SYNC_20260508")
RAW_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
RAW_PATH_RE = re.compile(r"(?i)(?:\b[A-Z]:\\[^\"'\n\r]+|/mnt/[a-z](?:/[^\"'\n\r]*)?)")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel_path(path: Path) -> str:
    return s192.rel_path(path)


def artifact_ref(path: Path, out_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        try:
            return str(path.resolve().relative_to(out_dir.resolve().parent)).replace("\\", "/")
        except (OSError, ValueError):
            return f"artifact_bundles/{path.name}"


def stable_hash(value: Any, length: int = 24) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def compact(value: Any, limit: int = 1000) -> str:
    return s192.compact(value, limit=limit)


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
    return s192.read_jsonl(path)


def sqlite_connect_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def source_rows_by_source_ref(source_url_db: Path, source_ref_ids: set[str]) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not source_ref_ids:
        return rows
    conn = sqlite_connect_ro(source_url_db)
    try:
        for source_ref_id in sorted(source_ref_ids):
            row = conn.execute(
                """
                SELECT source_ref_id, article_uid, article_id, source_account, title, post_date,
                       archive_raw_html_path, match_basis, confidence, entity_count, event_count,
                       local_image_count
                FROM article_source_url
                WHERE source_ref_id = ?
                LIMIT 1
                """,
                (source_ref_id,),
            ).fetchone()
            if row:
                rows[source_ref_id] = {key: row[key] for key in row.keys()}
    finally:
        conn.close()
    return rows


def artifact_dir(out_dir: Path, queue_row: dict[str, Any], source_ref_id: str) -> Path:
    return out_dir / "artifact_bundles" / stable_hash(
        {
            "story": CURRENT_STORY_ID,
            "group_id": queue_row.get("group_id"),
            "dj_ids": queue_row.get("dj_ids"),
            "source_ref_id": source_ref_id,
        },
        24,
    )


def replay_one(
    *,
    generated_at: str,
    queue_row: dict[str, Any],
    source_ref_id: str,
    source_row: dict[str, Any] | None,
    out_dir: Path,
    allowed_archive_root: Path,
    max_bytes: int,
) -> dict[str, Any]:
    base = {
        "schema_version": SCHEMA_VERSION + ".row",
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": generated_at,
        "group_id": compact(queue_row.get("group_id"), 200),
        "dj_ids": queue_row.get("dj_ids") or [],
        "display_names": queue_row.get("display_names") or [],
        "route": compact(queue_row.get("route") or "S201_exact_local_archive_replay", 120),
        "source_ref_id": compact(source_ref_id, 160),
        "resolved_article_source_ref_id": compact(source_ref_id, 160),
        "article_uid": "",
        "source_account": "",
        "title": "",
        "post_date": "",
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
    base.update(
        {
            "article_uid": compact(source_row.get("article_uid"), 300),
            "source_account": compact(source_row.get("source_account"), 240),
            "title": compact(source_row.get("title"), 500),
            "post_date": compact(source_row.get("post_date"), 80),
        }
    )
    raw_archive_path = compact(source_row.get("archive_raw_html_path"), 5000)
    if not raw_archive_path:
        base["decision"] = "blocked_archive_path_missing_report_only"
        base["decision_reasons"] = ["archive_raw_html_path_missing"]
        return base
    base["archive_path_sha256"] = hashlib.sha256(raw_archive_path.encode("utf-8", errors="ignore")).hexdigest()
    archive_path = Path(raw_archive_path)
    if not s192.archive_path_allowed(archive_path, allowed_archive_root):
        base["decision"] = "blocked_archive_path_outside_allowed_root_report_only"
        base["decision_reasons"] = ["archive_path_outside_allowed_root"]
        return base
    if not archive_path.is_file():
        base["decision"] = "blocked_archive_path_missing_on_disk_report_only"
        base["decision_reasons"] = ["archive_path_missing_on_disk"]
        return base
    data = archive_path.read_bytes()[:max_bytes]
    flags = s192.fetch_runner.html_content_flags(data, "text/html; charset=utf-8", base["title"])
    has_article = bool(flags.get("wechat_article_marker_seen") or flags.get("js_content_text_len", 0) >= 20 or flags.get("title_prefix_seen"))
    bundle_dir = artifact_dir(out_dir, queue_row, source_ref_id)
    html_path = bundle_dir / "article.html"
    atomic_write_bytes(html_path, data)
    html_sha = s192.bytes_hash(data)
    base.update(
        {
            "exact_archive_file_read": True,
            "artifact_written": True,
            "article_artifact_ready": bool(has_article),
            "artifact_bundle_relpath": artifact_ref(bundle_dir, out_dir),
            "html_artifact_ref_id": f"report_local_html_artifact:{html_sha[:24]}",
            "html_sha256": html_sha,
            "html_bytes": len(data),
            "content_flags": flags,
            "decision": "archive_html_article_content_review_ready" if has_article else "archive_html_weak_review_only",
            "decision_reasons": ["article_content_marker_seen"] if has_article else ["article_content_marker_absent"],
        }
    )
    return base


def scan_public_outputs(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if RAW_URL_RE.search(text):
            findings.append(f"raw_url_emitted:{rel_path(path)}")
        if RAW_PATH_RE.search(text):
            findings.append(f"raw_path_emitted:{rel_path(path)}")
    return findings


def run_s201(
    *,
    queue_path: Path,
    source_url_db: Path,
    out_dir: Path,
    report_path: Path,
    allowed_archive_root: Path,
    max_bytes: int,
) -> dict[str, Any]:
    generated_at = now_iso()
    queue_rows = read_jsonl(queue_path)
    source_ref_ids = {str(ref) for row in queue_rows for ref in (row.get("source_ref_ids") or []) if str(ref)}
    source_rows = source_rows_by_source_ref(source_url_db, source_ref_ids)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for queue_row in queue_rows:
        for source_ref_id in queue_row.get("source_ref_ids") or []:
            rows.append(
                replay_one(
                    generated_at=generated_at,
                    queue_row=queue_row,
                    source_ref_id=str(source_ref_id),
                    source_row=source_rows.get(str(source_ref_id)),
                    out_dir=out_dir,
                    allowed_archive_root=allowed_archive_root,
                    max_bytes=max_bytes,
                )
            )
    ready = [row for row in rows if row["article_artifact_ready"]]
    blocked = [row for row in rows if not row["article_artifact_ready"]]
    manifest_path = out_dir / "s201_archive_replay_manifest.jsonl"
    ready_path = out_dir / "s201_archive_article_ready_rows.jsonl"
    blocked_path = out_dir / "s201_archive_blocked_rows.jsonl"
    evidence_path = out_dir / "s201_normalized_archive_evidence.jsonl"
    summary_path = out_dir / f"{REPORT_STEM}.json"
    write_jsonl(manifest_path, rows)
    write_jsonl(ready_path, ready)
    write_jsonl(blocked_path, blocked)
    write_jsonl(evidence_path, rows)
    failed_checks = scan_public_outputs([manifest_path, ready_path, blocked_path, evidence_path])
    decision = (
        "atlas_relation_source_archive_replay_s201_article_artifacts_ready_report_only"
        if ready and not failed_checks
        else "atlas_relation_source_archive_replay_s201_completed_with_blocked_rows_report_only"
        if rows and not failed_checks
        else "atlas_relation_source_archive_replay_s201_failed_safety_gate"
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "current_story_id": CURRENT_STORY_ID,
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "queue_path": rel_path(queue_path),
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
            "input_queue_rows": len(queue_rows),
            "input_source_ref_ids": len(source_ref_ids),
            "source_url_rows_found": len(source_rows),
            "exact_archive_files_read": sum(1 for row in rows if row["exact_archive_file_read"]),
            "artifact_written_rows": sum(1 for row in rows if row["artifact_written"]),
            "article_artifact_ready_rows": len(ready),
            "blocked_or_not_ready_rows": len(blocked),
            "html_bytes_total": sum(int(row.get("html_bytes") or 0) for row in rows),
            "ready_group_count": len({row["group_id"] for row in ready}),
        },
        "decision_counts": dict(sorted(Counter(row["decision"] for row in rows).items())),
        "execution_cursor": {
            "next_story_id": "S202",
            "next_input": rel_path(ready_path) if ready else rel_path(blocked_path),
            "next_action": "Run S193/S194 dry-runs on S201 article-ready rows; execute only candidates that pass article alias coverage, lock, backup, transaction, redirect, and readback.",
            "db3_write_allowed_now": False,
            "db2_projection_allowed_now": False,
            "deploy_upload_review_release_allowed_now": False,
        },
        "safety": {
            "exact_archive_path_reads_only": True,
            "d_root_scan": False,
            "raw_archive_path_emitted": False,
            "raw_source_url_emitted": False,
            "network_fetch": False,
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
    atomic_write_text(report_path, render_scorecard(summary))
    return summary


def render_scorecard(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# Weekly Atlas Relation Source Archive Replay S201",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Input queue rows: `{counts['input_queue_rows']}`",
        f"- Input source refs: `{counts['input_source_ref_ids']}`",
        f"- Source-url rows found: `{counts['source_url_rows_found']}`",
        f"- Exact archive files read: `{counts['exact_archive_files_read']}`",
        f"- Article-ready rows: `{counts['article_artifact_ready_rows']}`",
        f"- Ready groups: `{counts['ready_group_count']}`",
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
            "- Reads only S200 P0 source_ref IDs and exact archive_raw_html_path values after allowed-root validation.",
            "- No D: scan, no network fetch, no DB1/DB2/DB3 write, no DB2 projection, no deploy/upload/review/release.",
            "- Raw source URLs and exact archive paths are not emitted.",
            "",
            "## Artifacts",
        ]
    )
    for key, value in summary["outputs"].items():
        lines.append(f"- `{key}`: `{value}`")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URL_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--allowed-archive-root", type=Path, default=DEFAULT_ALLOWED_ARCHIVE_ROOT)
    parser.add_argument("--max-bytes", type=int, default=2_000_000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_s201(
        queue_path=args.queue,
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
