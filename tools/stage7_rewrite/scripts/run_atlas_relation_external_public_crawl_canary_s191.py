#!/usr/bin/env python3
"""Run the S191 relation external public-crawl canary.

This story bridges the S190 relation acquisition queue to the existing bounded
source-acquisition fetcher. It resolves private source URLs from the source-url
recovery sidecar, runs no-cookie public fetches, and writes report-local
evidence only. It does not mutate DB1/DB2/DB3 or publish any public pointer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
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
SCHEMA_VERSION = "atlas_relation_external_public_crawl_canary_s191.v1"
CURRENT_STORY_ID = "S191"

DEFAULT_QUEUE = (
    REPORTS_ROOT
    / "atlas_relation_external_acquisition_queue_s190_20260602"
    / "s191_bounded_no_cookie_public_crawl_canary_queue.jsonl"
)
DEFAULT_ATLAS_DB = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_SOURCE_URL_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_source_url_recovery_139123_candidate"
    / "atlas_source_url_recovery.sqlite"
)
DEFAULT_OUT_DIR = REPORTS_ROOT / "atlas_relation_external_public_crawl_canary_s191_20260602"
DEFAULT_REPORT = REPO_ROOT / "reports" / "WEEKLY_ATLAS_RELATION_EXTERNAL_PUBLIC_CRAWL_CANARY_S191_20260602.md"
DEFAULT_DB2CTL_WORKTREE = Path(r"C:\code\.worktrees\wechathtmldownload\20260601-db2-weapons-containers")

SECRET_LINE_RE = re.compile(
    r"(?im)^.*\b(cookie|token|secret|authorization|bearer|password|passwd|api[_-]?key|set-cookie)\b.*$"
)
RAW_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.I)
D_DRIVE_RE = re.compile(r"(?i)(?:\bD:\\[^\s\"'<>]+|/mnt/d(?:/[^\s\"'<>]*)?)")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", compact(value, 2000).casefold())


def stable_hash(value: Any, length: int = 24) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:length]


def full_hash(value: Any) -> str:
    return hashlib.sha256(compact(value, 8000).encode("utf-8", errors="ignore")).hexdigest()


def rel_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except (OSError, ValueError):
        return str(path)


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for S191 live artifacts: {path}")


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


def collect_seed_refs(queue_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for queue_index, queue_row in enumerate(queue_rows):
        for seed_index, seed in enumerate(queue_row.get("seed_events") or []):
            source_ref_id = compact(seed.get("source_ref_id"), 160)
            if not source_ref_id or source_ref_id in seen:
                continue
            seen.add(source_ref_id)
            refs.append(
                {
                    "source_ref_id": source_ref_id,
                    "queue_task_id": compact(queue_row.get("task_id"), 240),
                    "group_id": compact(queue_row.get("group_id"), 160),
                    "dj_ids": queue_row.get("dj_ids") or [],
                    "display_names": queue_row.get("display_names") or [],
                    "route": compact(queue_row.get("route"), 120),
                    "queue_index": queue_index,
                    "seed_index": seed_index,
                    "seed_event": {
                        "source_account": compact(seed.get("source_account"), 240),
                        "source_title": compact(seed.get("source_title"), 500),
                        "event_title": compact(seed.get("event_title"), 500),
                        "starts_at": compact(seed.get("starts_at"), 80),
                        "post_date": compact(seed.get("post_date"), 80),
                        "venue_name": compact(seed.get("venue_name"), 240),
                        "city": compact(seed.get("city"), 80),
                    },
                }
            )
    return refs


def find_unique_article(
    source_conn: sqlite3.Connection,
    *,
    source_account: str,
    source_title: str,
    post_date: str,
) -> tuple[dict[str, Any] | None, str, int]:
    if not source_account or not source_title:
        return None, "missing_account_or_title", 0
    params: tuple[Any, ...]
    if post_date:
        sql = """
            SELECT * FROM article_source_url
            WHERE source_account = ? AND title = ? AND post_date = ?
            ORDER BY confidence DESC, article_uid
        """
        params = (source_account, source_title, post_date)
        method = "account_title_post_date_unique"
    else:
        sql = """
            SELECT * FROM article_source_url
            WHERE source_account = ? AND title = ?
            ORDER BY confidence DESC, article_uid
        """
        params = (source_account, source_title)
        method = "account_title_unique_without_post_date"
    rows = [row_dict(row) for row in source_conn.execute(sql, params).fetchall()]
    rows = [row for row in rows if row]
    if len(rows) == 1:
        return rows[0], method, 1
    if not rows:
        return None, "no_account_title_match", 0
    return None, f"ambiguous_{method}", len(rows)


def resolve_source_ref(
    seed_ref: dict[str, Any],
    atlas_conn: sqlite3.Connection,
    source_conn: sqlite3.Connection,
) -> dict[str, Any]:
    source_ref_id = seed_ref["source_ref_id"]
    atlas_row = row_dict(
        atlas_conn.execute(
            """
            SELECT source_ref_id, source_hash, source_account, source_title, post_date, source_kind
            FROM source_ref
            WHERE source_ref_id = ?
            LIMIT 1
            """,
            (source_ref_id,),
        ).fetchone()
    )
    base = {
        **seed_ref,
        "atlas_source_ref": atlas_row,
        "resolved": False,
        "resolution_method": "",
        "resolution_confidence": 0.0,
        "resolution_candidate_count": 0,
        "article_source_url_row": None,
        "blocked_reason": "",
    }
    if not atlas_row:
        base["blocked_reason"] = "source_ref_missing_in_db3"
        return base

    direct = row_dict(
        source_conn.execute(
            "SELECT * FROM article_source_url WHERE source_ref_id = ? LIMIT 1",
            (source_ref_id,),
        ).fetchone()
    )
    if direct:
        base.update(
            {
                "resolved": True,
                "resolution_method": "direct_source_ref_id",
                "resolution_confidence": 1.0,
                "resolution_candidate_count": 1,
                "article_source_url_row": direct,
            }
        )
        return base

    matched, method, candidate_count = find_unique_article(
        source_conn,
        source_account=compact(atlas_row.get("source_account"), 240),
        source_title=compact(atlas_row.get("source_title"), 500),
        post_date=compact(atlas_row.get("post_date"), 80),
    )
    if matched:
        base.update(
            {
                "resolved": True,
                "resolution_method": method,
                "resolution_confidence": 0.97 if "post_date" in method else 0.9,
                "resolution_candidate_count": candidate_count,
                "article_source_url_row": matched,
            }
        )
        return base
    base["blocked_reason"] = method
    base["resolution_candidate_count"] = candidate_count
    return base


def build_work_order(resolved: dict[str, Any]) -> dict[str, Any]:
    article = resolved["article_source_url_row"] or {}
    source_url = compact(article.get("source_url"), 5000)
    article_uid = compact(article.get("article_uid") or article.get("article_id") or article.get("source_ref_id"), 300)
    ticket_basis = {
        "story": CURRENT_STORY_ID,
        "source_ref_id": resolved["source_ref_id"],
        "article_uid": article_uid,
        "group_id": resolved.get("group_id"),
    }
    ticket_id = f"s191:{stable_hash(ticket_basis, 24)}"
    return {
        "fetch_preflight_ready": True,
        "article_uid": article_uid,
        "work_item_id": f"work:{ticket_id}",
        "source_account": compact(article.get("source_account") or (resolved.get("atlas_source_ref") or {}).get("source_account"), 240),
        "title": compact(article.get("title") or (resolved.get("atlas_source_ref") or {}).get("source_title"), 500),
        "source_ref_id": resolved["source_ref_id"],
        "acquisition_ticket_id": ticket_id,
        "report_local_artifact_scope": {
            "artifact_bundle_ref_id": f"report_local_artifact_bundle:{ticket_id}",
            "manifest_ref_id": f"s191_manifest:{ticket_id}",
        },
        "source_url_evidence": {
            "candidate_source_url_sha256": full_hash(source_url),
            "raw_source_url_emitted": False,
        },
        "s191_relation_context": {
            "group_id": resolved.get("group_id"),
            "dj_ids": resolved.get("dj_ids") or [],
            "display_names": resolved.get("display_names") or [],
            "route": resolved.get("route"),
            "seed_event": resolved.get("seed_event") or {},
            "resolved_article_uid": article_uid,
            "resolved_source_ref_id": compact(article.get("source_ref_id"), 160),
            "resolution_method": resolved.get("resolution_method"),
            "resolution_confidence": resolved.get("resolution_confidence"),
        },
    }


def build_source_url_sidecar_row(resolved: dict[str, Any]) -> dict[str, Any]:
    article = resolved["article_source_url_row"] or {}
    return {
        "article_uid": compact(article.get("article_uid") or article.get("article_id") or article.get("source_ref_id"), 300),
        "article_id": compact(article.get("article_id"), 160),
        "source_url": compact(article.get("source_url"), 5000),
        "source_ref_id": resolved["source_ref_id"],
        "resolved_article_source_ref_id": compact(article.get("source_ref_id"), 160),
        "source_account": compact(article.get("source_account"), 240),
        "title": compact(article.get("title"), 500),
        "post_date": compact(article.get("post_date"), 80),
        "resolution_method": resolved.get("resolution_method"),
        "resolution_confidence": resolved.get("resolution_confidence"),
        "private_internal_only": 1,
        "public_graph_visible": 0,
    }


def unresolved_task(resolved: dict[str, Any]) -> dict[str, Any]:
    atlas_row = resolved.get("atlas_source_ref") or {}
    return {
        "schema_version": SCHEMA_VERSION + ".unresolved",
        "current_story_id": CURRENT_STORY_ID,
        "source_ref_id": resolved["source_ref_id"],
        "group_id": resolved.get("group_id"),
        "dj_ids": resolved.get("dj_ids") or [],
        "display_names": resolved.get("display_names") or [],
        "route": resolved.get("route"),
        "blocked_reason": resolved.get("blocked_reason") or "unresolved",
        "resolution_candidate_count": resolved.get("resolution_candidate_count", 0),
        "source_account": compact(atlas_row.get("source_account"), 240),
        "source_title": compact(atlas_row.get("source_title"), 500),
        "post_date": compact(atlas_row.get("post_date"), 80),
        "source_kind": compact(atlas_row.get("source_kind"), 120),
        "source_hash": compact(atlas_row.get("source_hash"), 120),
        "seed_event": resolved.get("seed_event") or {},
        "next_action": "recover_source_url_from_mptext_export_or_provider_search_before_public_fetch",
        "write_authorization": {
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection": False,
            "deploy_upload_review_release": False,
        },
    }


def redact_runtime_log(text: str) -> str:
    redacted = SECRET_LINE_RE.sub("[REDACTED_CREDENTIAL_LINE]", text)
    redacted = RAW_URL_RE.sub("[REDACTED_URL]", redacted)
    redacted = D_DRIVE_RE.sub("[REDACTED_D_DRIVE_PATH]", redacted)
    return redacted[-6000:]


def collect_db2_control_plane(*, probe: bool, timeout_sec: int = 45) -> dict[str, Any]:
    if not probe:
        return {"probe_executed": False, "reason": "disabled_by_caller"}
    worktree = Path(os.environ.get("ATLAS_DB2CTL_WORKTREE") or DEFAULT_DB2CTL_WORKTREE)
    script = worktree / "tools" / "stage7_rewrite" / "scripts" / "db2ctl.py"
    if not script.exists():
        return {"probe_executed": False, "reason": "db2ctl_not_found", "worktree": str(worktree)}
    linux_worktree = "/mnt/c/" + str(worktree).replace("\\", "/").replace("C:/", "")
    commands = {
        "status": f"cd {linux_worktree!r} && python3 tools/stage7_rewrite/scripts/db2ctl.py status",
        "health_lock_holders": f"cd {linux_worktree!r} && python3 tools/stage7_rewrite/scripts/db2ctl.py health --lock-holders",
    }
    results: dict[str, Any] = {}
    for name, command in commands.items():
        try:
            completed = subprocess.run(
                ["wsl.exe", "-d", "Ubuntu", "--", "bash", "-lc", command],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
            results[name] = {
                "returncode": completed.returncode,
                "stdout_tail": redact_runtime_log(completed.stdout or ""),
                "stderr_tail": redact_runtime_log(completed.stderr or ""),
            }
        except FileNotFoundError as exc:
            results[name] = {"returncode": 127, "error": f"missing executable: {exc.filename}"}
        except subprocess.TimeoutExpired:
            results[name] = {"returncode": 124, "error": "timeout"}
    healthy = all(item.get("returncode") == 0 for item in results.values())
    return {
        "probe_executed": True,
        "worktree": str(worktree),
        "healthy": healthy,
        "commands": results,
        "would_write": False,
    }


def normalized_evidence_rows(
    *,
    resolved_rows: list[dict[str, Any]],
    fetch_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_source_ref = {row["source_ref_id"]: row for row in resolved_rows if row.get("resolved")}
    out: list[dict[str, Any]] = []
    for fetch in fetch_rows:
        resolved = by_source_ref.get(fetch.get("source_ref_id"))
        if not resolved:
            continue
        article = resolved.get("article_source_url_row") or {}
        seed = resolved.get("seed_event") or {}
        out.append(
            {
                "schema_version": SCHEMA_VERSION + ".normalized_evidence",
                "current_story_id": CURRENT_STORY_ID,
                "group_id": resolved.get("group_id"),
                "dj_ids": resolved.get("dj_ids") or [],
                "display_names": resolved.get("display_names") or [],
                "route": resolved.get("route"),
                "source_ref_id": resolved["source_ref_id"],
                "resolved_article_source_ref_id": compact(article.get("source_ref_id"), 160),
                "article_uid": compact(article.get("article_uid"), 300),
                "evidence_url_sha256": fetch.get("source_url_sha256", ""),
                "raw_source_url_emitted": False,
                "http_status": fetch.get("status_code", 0),
                "network_fetch_executed": bool(fetch.get("network_fetch_executed")),
                "fetch_decision": fetch.get("decision"),
                "decision_reasons": fetch.get("decision_reasons") or [],
                "content_hash": fetch.get("html_sha256", ""),
                "artifact_written": bool(fetch.get("artifact_written")),
                "article_artifact_ready": bool(fetch.get("article_artifact_ready")),
                "raw_cache_path": fetch.get("artifact_bundle_relpath", ""),
                "matched_source_account": compact(article.get("source_account"), 240),
                "matched_event_title": compact(seed.get("event_title") or seed.get("source_title"), 500),
                "matched_date": compact(seed.get("starts_at") or seed.get("post_date") or article.get("post_date"), 80),
                "matched_venue": compact(seed.get("venue_name"), 240),
                "matched_city": compact(seed.get("city"), 80),
                "platform": "wechat_mp_article",
                "confidence": resolved.get("resolution_confidence", 0.0),
                "accepted_for_db3_write": False,
                "accepted_for_db2_projection": False,
                "accepted_for_public_release": False,
            }
        )
    return out


def public_text_for_leak_scan(paths: list[Path]) -> str:
    parts: list[str] = []
    for path in paths:
        if path.exists():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def render_scorecard(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    fetch_counts = summary["fetch_summary"].get("counts", {})
    lines = [
        "# S191 Relation External Public Crawl Canary",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Decision: `{summary['decision']}`",
        f"- Queue rows: `{counts['queue_rows']}`",
        f"- Unique source refs: `{counts['unique_source_ref_ids']}`",
        f"- Resolved source refs: `{counts['resolved_source_ref_ids']}`",
        f"- Unresolved source refs: `{counts['unresolved_source_ref_ids']}`",
        f"- Network fetch rows: `{fetch_counts.get('network_fetch_executed_rows', 0)}`",
        f"- Article-ready artifacts: `{fetch_counts.get('article_artifact_ready_rows', 0)}`",
        f"- Artifact-written rows: `{fetch_counts.get('artifact_written_rows', 0)}`",
        f"- DB2 control plane healthy: `{summary['db2_control_plane'].get('healthy', False)}`",
        "",
        "## Resolution Counts",
        "",
    ]
    for key, value in summary["resolution_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Summary: `{summary['outputs']['summary_json']}`",
            f"- Work orders: `{summary['outputs']['work_orders_jsonl']}`",
            f"- Private source URL sidecar: `{summary['outputs']['private_source_url_jsonl']}`",
            f"- Unresolved source-ref tasks: `{summary['outputs']['unresolved_tasks_jsonl']}`",
            f"- Normalized evidence: `{summary['outputs']['normalized_evidence_jsonl']}`",
            f"- Bounded fetch summary: `{summary['fetch_summary']['outputs']['summary_json']}`",
            "",
            "## Boundary",
            "",
            "- Raw URLs are kept only in the private source URL sidecar used as fetch input; they are not printed in this report or normalized evidence.",
            "- Fetches use the existing no-cookie bounded source-acquisition runner and verified source URL SHA256 before network access.",
            "- DB1/DB2/DB3 mutation, DB2 projection, serving rebuild, deploy, upload, review, public release, OCR generation, LLM calls, browser profile use, cookie/API key reads, and memory writes did not run.",
            "- Unresolved source refs are not skipped; they are emitted as a next acquisition queue.",
            "",
            "## Next Gate",
            "",
            summary["execution_cursor"]["next_action"],
            "",
        ]
    )
    return "\n".join(lines)


def run_s191(
    *,
    queue_path: Path,
    atlas_db_path: Path,
    source_url_db_path: Path,
    out_dir: Path,
    report_path: Path,
    limit: int,
    timeout_sec: float,
    max_bytes: int,
    probe_db2ctl: bool = True,
    fetcher: fetch_runner.Fetcher = fetch_runner.fetch_html,
) -> dict[str, Any]:
    for label, path in (
        ("queue_path", queue_path),
        ("atlas_db_path", atlas_db_path),
        ("source_url_db_path", source_url_db_path),
        ("out_dir", out_dir),
        ("report_path", report_path),
    ):
        reject_d_path(path, label)
    generated_at = now_iso()
    queue_rows = read_jsonl(queue_path)
    seed_refs = collect_seed_refs(queue_rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    private_dir = out_dir / "private_inputs"
    fetch_dir = out_dir / "bounded_fetch"
    fetch_report = out_dir / "bounded_fetch_report.md"

    atlas_conn = sqlite_connect_ro(atlas_db_path)
    source_conn = sqlite_connect_ro(source_url_db_path)
    try:
        resolved_rows = [resolve_source_ref(seed, atlas_conn, source_conn) for seed in seed_refs]
    finally:
        atlas_conn.close()
        source_conn.close()

    resolved = [row for row in resolved_rows if row.get("resolved")]
    unresolved = [unresolved_task(row) for row in resolved_rows if not row.get("resolved")]
    if limit > 0:
        resolved_for_fetch = resolved[:limit]
    else:
        resolved_for_fetch = resolved
    work_orders = [build_work_order(row) for row in resolved_for_fetch]
    source_url_rows = [build_source_url_sidecar_row(row) for row in resolved_for_fetch]

    work_orders_path = out_dir / "s191_fetch_work_orders.jsonl"
    private_source_url_path = private_dir / "s191_private_source_url_sidecar.jsonl"
    unresolved_path = out_dir / "s191_unresolved_source_ref_tasks.jsonl"
    write_jsonl(work_orders_path, work_orders)
    write_jsonl(private_source_url_path, source_url_rows)
    write_jsonl(unresolved_path, unresolved)

    db2_control = collect_db2_control_plane(probe=probe_db2ctl)
    fetch_summary = fetch_runner.run_bounded_fetch(
        work_orders_path=work_orders_path,
        source_url_jsonl=private_source_url_path,
        out_dir=fetch_dir,
        report_path=fetch_report,
        limit=limit,
        timeout_sec=timeout_sec,
        max_bytes=max_bytes,
        fetcher=fetcher,
    )
    fetch_rows = read_jsonl(fetch_dir / "fetch_succeeded_rows.jsonl") + read_jsonl(fetch_dir / "fetch_blocked_rows.jsonl")
    evidence_rows = normalized_evidence_rows(resolved_rows=resolved_for_fetch, fetch_rows=fetch_rows)
    evidence_path = out_dir / "s191_normalized_public_evidence.jsonl"
    write_jsonl(evidence_path, evidence_rows)

    resolution_counts = Counter(
        row.get("resolution_method") if row.get("resolved") else row.get("blocked_reason")
        for row in resolved_rows
    )
    failed_checks: list[str] = []
    if not work_orders:
        failed_checks.append("no_resolved_source_urls_for_fetch")
    if fetch_summary.get("failed_checks"):
        failed_checks.extend([f"bounded_fetch:{item}" for item in fetch_summary["failed_checks"]])
    scan_text = public_text_for_leak_scan([evidence_path, report_path])
    if RAW_URL_RE.search(scan_text):
        failed_checks.append("public_s191_outputs_contain_raw_url")
    article_ready = int(fetch_summary.get("counts", {}).get("article_artifact_ready_rows") or 0)
    decision = (
        "s191_public_crawl_article_artifacts_ready_report_only"
        if article_ready and not failed_checks
        else "s191_public_crawl_completed_with_blocked_or_unresolved_rows_report_only"
        if work_orders and not failed_checks
        else "s191_public_crawl_failed_safety_or_resolution_gate"
    )
    outputs = {
        "summary_json": rel_path(out_dir / "atlas_relation_external_public_crawl_canary_s191.json"),
        "scorecard_markdown": rel_path(report_path),
        "work_orders_jsonl": rel_path(work_orders_path),
        "private_source_url_jsonl": rel_path(private_source_url_path),
        "unresolved_tasks_jsonl": rel_path(unresolved_path),
        "normalized_evidence_jsonl": rel_path(evidence_path),
        "bounded_fetch_dir": rel_path(fetch_dir),
    }
    next_action = (
        "S192: review article-ready report-local artifacts, then build a relation evidence review/write-gate that preserves fields and requires source-ref coverage before any DB3 relation mutation."
        if article_ready
        else "S192: use unresolved source-ref tasks and bounded browser-safe acquisition to recover missing original URLs before any relation write or DB2 projection."
    )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "current_story_id": CURRENT_STORY_ID,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "queue_path": rel_path(queue_path),
            "atlas_db_path": rel_path(atlas_db_path),
            "source_url_db_path": rel_path(source_url_db_path),
            "limit": limit,
            "timeout_sec": timeout_sec,
            "max_bytes": max_bytes,
        },
        "outputs": outputs,
        "counts": {
            "queue_rows": len(queue_rows),
            "seed_source_ref_rows": len(seed_refs),
            "unique_source_ref_ids": len(seed_refs),
            "resolved_source_ref_ids": len(resolved),
            "unresolved_source_ref_ids": len(unresolved),
            "fetch_work_orders": len(work_orders),
            "normalized_evidence_rows": len(evidence_rows),
        },
        "resolution_counts": dict(sorted(resolution_counts.items())),
        "fetch_summary": fetch_summary,
        "db2_control_plane": db2_control,
        "execution_cursor": {
            "next_story_id": "S192",
            "next_input": outputs["normalized_evidence_jsonl"] if article_ready else outputs["unresolved_tasks_jsonl"],
            "next_action": next_action,
            "db3_write_allowed_now": False,
            "db2_projection_allowed_now": False,
            "deploy_upload_review_release_allowed_now": False,
        },
        "safety": {
            "report_local_only": True,
            "raw_source_url_publicly_emitted": False,
            "private_source_url_sidecar_written": bool(source_url_rows),
            "cookie_or_token_read": False,
            "auth_material_used": False,
            "browser_profile_used": False,
            "llm_call_executed": False,
            "db1_mutation": False,
            "db2_mutation": False,
            "db3_mutation": False,
            "db2_projection": False,
            "deploy_upload_review_release": False,
            "d_root_scan": False,
        },
    }
    write_json(out_dir / "atlas_relation_external_public_crawl_canary_s191.json", summary)
    atomic_write_text(report_path, render_scorecard(summary))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--atlas-db", type=Path, default=DEFAULT_ATLAS_DB)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URL_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--limit", type=int, default=70)
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--max-bytes", type=int, default=524288)
    parser.add_argument("--skip-db2ctl-probe", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = run_s191(
        queue_path=args.queue,
        atlas_db_path=args.atlas_db,
        source_url_db_path=args.source_url_db,
        out_dir=args.out_dir,
        report_path=args.report,
        limit=args.limit,
        timeout_sec=args.timeout_sec,
        max_bytes=args.max_bytes,
        probe_db2ctl=not args.skip_db2ctl_probe,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "failed_checks": summary["failed_checks"],
                "resolved_source_ref_ids": summary["counts"]["resolved_source_ref_ids"],
                "unresolved_source_ref_ids": summary["counts"]["unresolved_source_ref_ids"],
                "network_fetch_executed_rows": summary["fetch_summary"]["counts"]["network_fetch_executed_rows"],
                "article_artifact_ready_rows": summary["fetch_summary"]["counts"]["article_artifact_ready_rows"],
                "summary": summary["outputs"]["summary_json"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
