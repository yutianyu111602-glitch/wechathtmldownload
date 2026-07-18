#!/usr/bin/env python
"""Preflight local source material for aggregate-child poster OCR.

This report-only gate sits after the runtime release preflight. It answers one
operational question before any real OCR worker is allowed: can the selected
aggregate-child poster tasks be resolved to local article material, without
network/download/OCR/vision/API/CloudBase/package writes?

The output deliberately stores only source keys, hashes, counts, and bounded
queue labels. It never emits raw URLs, absolute/private paths, cookies, tokens,
or API keys.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PUBLISH_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "openclaw_weekly_daily_20260606_060904"
DEFAULT_RUNTIME_PREFLIGHT = DEFAULT_PUBLISH_DIR / "aggregate_child_poster_ocr_runtime_release_preflight.json"
DEFAULT_TASKS = DEFAULT_PUBLISH_DIR / "aggregate_child_poster_ocr_recovery_tasks.json"
RUNTIME_REPORT_ROOT = Path(os.environ.get("HUAIDJ_REPORT_ROOT", r"F:\DevData\HuaidjRuntime\state\reports"))
DEFAULT_REPORT = RUNTIME_REPORT_ROOT / "poster_recovery" / "aggregate_child_poster_ocr_source_material_preflight.json"
DEFAULT_SCORECARD = RUNTIME_REPORT_ROOT / "poster_recovery" / "WEEKLY_AGGREGATE_CHILD_POSTER_OCR_SOURCE_MATERIAL_PREFLIGHT.md"
SCHEMA_VERSION = "weekly_aggregate_child_poster_ocr_source_material_preflight.v1"
READY_DECISION = "weekly_aggregate_child_poster_ocr_source_material_preflight_ready_report_only_local_material_found"
BLOCKED_DECISION = "weekly_aggregate_child_poster_ocr_source_material_preflight_blocked_report_only_source_material_missing"
RUNTIME_SCHEMA = "weekly_aggregate_child_poster_ocr_runtime_release_preflight.v1"
RUNTIME_READY = "weekly_aggregate_child_poster_ocr_runtime_release_preflight_ready_report_only_requires_controller_release"
TASKS_SCHEMA = "weekly_aggregate_child_poster_ocr_recovery_tasks.v1"
PUBLIC_IMAGE_RE = re.compile(r"https?://[^\\s\"'<>]*(?:mmbiz\\.qpic\\.cn|mmecoa\\.qpic\\.cn|qpic\\.cn)[^\\s\"'<>]*", re.I)
RAW_URL_RE = re.compile(r"https?://|mp\\.weixin\\.qq\\.com|mmbiz\\.qpic\\.cn|mmecoa\\.qpic\\.cn|qpic\\.cn|wxfile://", re.I)
PRIVATE_PATH_RE = re.compile(r"(?i)([A-Z]:\\\\|/mnt/[a-z]/|/home/pc/|\\\\\\\\wsl\\.localhost\\\\|D:\\\\DDownload\\\\)")
SECRET_RE = re.compile(r"(?i)(bearer\\s+[a-z0-9._-]+|authorization\\s*[:=]|api[_-]?key\\s*[:=]|cookie\\s*[:=]|password\\s*[:=]|secret\\s*[:=]|sk-[a-z0-9_-]{12,})")
FALSE_EXECUTION_FLAGS = (
    "actual_runtime_worker_allowed_now",
    "actual_worker_started",
    "network_fetch_executed",
    "download_executed",
    "ocr_executed",
    "vision_api_executed",
    "cloudbase_storage_write_executed",
    "package_patch_executed",
    "child_source_action_reenabled",
    "cloudbase_db_write_executed",
    "db_write_executed",
    "db2_projection_executed",
    "db3_write_executed",
    "cloudrun_deploy_executed",
    "cloudbase_sync_executed",
    "miniprogram_upload_executed",
    "wechat_review_submitted",
    "public_release_executed",
    "credential_value_read",
    "secret_file_read",
    "browser_profile_read",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def sha16(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def safe_repo_path(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(REPO_ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def queue_label(path: Path) -> str:
    parent = path.parent.name
    if parent:
        return f"{parent}/{path.name}"
    return path.name


def safe_summary_for_queue(queue_file: Path) -> dict[str, Any]:
    summary_path = queue_file.parent / "summary.json"
    if not summary_path.exists():
        return {}
    try:
        summary = read_json(summary_path)
    except (OSError, json.JSONDecodeError):
        return {}
    allowed = (
        "generated_at",
        "since_date",
        "until_date",
        "history_max_post_date",
        "prefetch_max_post_date",
        "new_count",
        "rows_written",
        "account_count",
        "accounts_requested",
        "exporter_accounts_ok",
        "exporter_accounts_failed",
        "exporter_article_rows",
        "account_dirs_missing",
    )
    return {key: summary.get(key) for key in allowed if key in summary}


def leak_count(payload: Any) -> int:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return len(RAW_URL_RE.findall(text)) + len(PRIVATE_PATH_RE.findall(text)) + len(SECRET_RE.findall(text))


def check(check_id: str, passed: bool, evidence: str) -> dict[str, str]:
    return {
        "check_id": check_id,
        "required": "true",
        "status": "passed" if passed else "failed",
        "evidence": evidence,
    }


def selected_task_ids(runtime: dict[str, Any], max_tasks: int) -> list[str]:
    nested = as_dict(runtime.get("runtime_release_preflight"))
    ids = [str(row.get("id") or "").strip() for row in as_list(nested.get("selected_tasks")) if isinstance(row, dict)]
    return [task_id for task_id in ids if task_id][:max_tasks]


def task_by_id(tasks_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in as_list(tasks_report.get("tasks")):
        if not isinstance(row, dict):
            continue
        task_id = str(row.get("id") or "").strip()
        if task_id:
            out[task_id] = row
    return out


def source_map_sources(source_map: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = as_dict(source_map.get("sources"))
    return {str(key): value for key, value in sources.items() if isinstance(value, dict)}


def default_source_map_path(tasks_report: dict[str, Any], tasks_path: Path) -> Path | None:
    raw = str(tasks_report.get("source_url_map") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    candidates = [path] if path.is_absolute() else [tasks_path.parent / path, REPO_ROOT / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def queue_files_from_inputs(inputs: list[Path]) -> list[Path]:
    files: list[Path] = []
    seen: set[str] = set()
    for raw in inputs:
        path = raw
        if path.is_dir():
            candidates = [path / "weekly_activity_queue.jsonl", path / "latest_queue.jsonl"]
            candidates.extend(sorted(path.glob("*.jsonl")))
        else:
            candidates = [path]
        for candidate in candidates:
            if not candidate.exists() or not candidate.is_file():
                continue
            key = str(candidate.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            files.append(candidate)
    return files


def queue_material_index(
    queue_files: list[Path],
    source_urls_by_key: dict[str, str],
    candidate_meta_by_key: dict[str, dict[str, str]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any], dict[str, dict[str, Any]]]:
    url_to_key = {url: key for key, url in source_urls_by_key.items() if url}
    found: dict[str, list[dict[str, Any]]] = {key: [] for key in source_urls_by_key}
    account_rows: dict[str, dict[str, Any]] = {}
    account_date_rows: dict[tuple[str, str], list[dict[str, Any]]] = {}
    scanned_rows = 0
    scanned_files = []
    for queue_file in queue_files:
        file_rows = 0
        try:
            handle = queue_file.open("r", encoding="utf-8-sig")
        except OSError:
            continue
        with handle:
            for line in handle:
                if not line.strip():
                    continue
                file_rows += 1
                scanned_rows += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(row, dict):
                    continue
                account = normalize_text(row.get("account_nickname"))
                post_date = str(row.get("post_date") or "")[:10]
                digest = str(row.get("digest") or "")
                cover_url = str(row.get("cover_url") or "")
                body_chars = int_value(row.get("body_text_chars"))
                image_count = len(PUBLIC_IMAGE_RE.findall(digest)) + (1 if cover_url else 0)
                row_summary = {
                    "queue": queue_label(queue_file),
                    "title_hash": sha16(str(row.get("title") or "")),
                    "body_text_chars": body_chars,
                    "body_text_source_present": bool(str(row.get("body_text_source") or "").strip()),
                    "article_dir_declared": bool(str(row.get("article_dir") or "").strip()),
                    "image_candidate_count": image_count,
                }
                if account:
                    stats = account_rows.setdefault(
                        account,
                        {
                            "queue_row_count": 0,
                            "min_post_date": "",
                            "max_post_date": "",
                            "latest_title_hash": "",
                        },
                    )
                    stats["queue_row_count"] += 1
                    if post_date:
                        if not stats["min_post_date"] or post_date < stats["min_post_date"]:
                            stats["min_post_date"] = post_date
                        if not stats["max_post_date"] or post_date > stats["max_post_date"]:
                            stats["max_post_date"] = post_date
                            stats["latest_title_hash"] = row_summary["title_hash"]
                    account_date_rows.setdefault((account, post_date), []).append(row_summary)
                source_url = str(row.get("source_url") or "").strip()
                source_key = url_to_key.get(source_url)
                if not source_key:
                    continue
                found[source_key].append(row_summary)
        scanned_files.append(
            {
                "queue": queue_label(queue_file),
                "row_count": file_rows,
                "summary": safe_summary_for_queue(queue_file),
            }
        )
    candidate_account_diagnostics: dict[str, dict[str, Any]] = {}
    for source_key, meta in candidate_meta_by_key.items():
        account = normalize_text(meta.get("account_name"))
        published_at = str(meta.get("published_at") or "")[:10]
        account_stats = account_rows.get(account) or {}
        account_date_matches = account_date_rows.get((account, published_at), [])
        candidate_account_diagnostics[source_key] = {
            "account_present_in_queue": bool(account_stats),
            "account_queue_row_count": int_value(account_stats.get("queue_row_count")),
            "account_queue_min_post_date": str(account_stats.get("min_post_date") or ""),
            "account_queue_max_post_date": str(account_stats.get("max_post_date") or ""),
            "account_latest_title_hash": str(account_stats.get("latest_title_hash") or ""),
            "candidate_published_at": published_at,
            "account_date_queue_match_count": len(account_date_matches),
            "account_date_image_candidate_count": sum(int_value(row.get("image_candidate_count")) for row in account_date_matches),
            "account_date_body_text_candidate_count": sum(1 for row in account_date_matches if int_value(row.get("body_text_chars")) > 0),
        }
    return found, {
        "queue_file_count": len(queue_files),
        "queue_files": scanned_files,
        "scanned_row_count": scanned_rows,
    }, candidate_account_diagnostics


def build_source_material_preflight(
    runtime_preflight_path: Path,
    tasks_path: Path,
    source_map_path: Path | None,
    queue_paths: list[Path],
    max_tasks: int,
) -> dict[str, Any]:
    runtime = read_json(runtime_preflight_path)
    tasks_report = read_json(tasks_path)
    resolved_source_map_path = source_map_path or default_source_map_path(tasks_report, tasks_path)
    source_map = read_json(resolved_source_map_path) if resolved_source_map_path and resolved_source_map_path.exists() else {}
    sources = source_map_sources(source_map)
    selected_ids = selected_task_ids(runtime, max_tasks)
    tasks = task_by_id(tasks_report)
    selected_tasks = [tasks[task_id] for task_id in selected_ids if task_id in tasks]

    source_keys: list[str] = []
    candidate_meta_by_key: dict[str, dict[str, str]] = {}
    for task in selected_tasks:
        for article in as_list(task.get("candidate_articles")):
            if not isinstance(article, dict):
                continue
            source_key = str(article.get("source_key") or "").strip()
            if source_key and source_key not in source_keys:
                source_keys.append(source_key)
            if source_key:
                source = as_dict(sources.get(source_key))
                candidate_meta_by_key[source_key] = {
                    "account_name": str(source.get("account_name") or article.get("account_name") or "").strip(),
                    "published_at": str(source.get("published_at") or article.get("published_at") or "").strip(),
                }

    source_urls_by_key = {key: str(as_dict(sources.get(key)).get("url") or "").strip() for key in source_keys}
    queue_files = queue_files_from_inputs(queue_paths)
    local_material, queue_scan, candidate_account_diagnostics = queue_material_index(
        queue_files,
        source_urls_by_key,
        candidate_meta_by_key,
    )

    task_rows: list[dict[str, Any]] = []
    offline_ready_count = 0
    source_map_missing_total = 0
    queue_match_total = 0
    image_candidate_total = 0
    candidate_account_present_total = 0
    candidate_account_date_match_total = 0
    candidate_account_latest_before_candidate_total = 0
    for task in selected_tasks:
        candidates: list[dict[str, Any]] = []
        source_map_resolved = 0
        queue_match_count = 0
        image_candidate_count = 0
        body_text_candidate_count = 0
        article_dir_declared_count = 0
        account_present_count = 0
        account_date_match_count = 0
        account_latest_before_candidate_count = 0
        for article in as_list(task.get("candidate_articles")):
            if not isinstance(article, dict):
                continue
            source_key = str(article.get("source_key") or "").strip()
            if not source_key:
                continue
            map_present = bool(source_urls_by_key.get(source_key))
            matches = local_material.get(source_key) or []
            account_diag = candidate_account_diagnostics.get(source_key) or {}
            account_present = bool(account_diag.get("account_present_in_queue"))
            account_date_matches = int_value(account_diag.get("account_date_queue_match_count"))
            candidate_published_at = str(account_diag.get("candidate_published_at") or "")
            account_latest = str(account_diag.get("account_queue_max_post_date") or "")
            latest_before_candidate = bool(candidate_published_at and account_latest and account_latest < candidate_published_at)
            source_map_resolved += int(map_present)
            queue_match_count += len(matches)
            account_present_count += int(account_present)
            account_date_match_count += account_date_matches
            account_latest_before_candidate_count += int(latest_before_candidate)
            image_count = sum(int_value(match.get("image_candidate_count")) for match in matches)
            body_count = sum(1 for match in matches if int_value(match.get("body_text_chars")) > 0)
            article_dir_count = sum(1 for match in matches if match.get("article_dir_declared"))
            image_candidate_count += image_count
            body_text_candidate_count += body_count
            article_dir_declared_count += article_dir_count
            candidates.append(
                {
                    "source_key": source_key,
                    "source_url_sha256": str(article.get("source_url_sha256") or source_key),
                    "source_map_entry_present": map_present,
                    "local_queue_match_count": len(matches),
                    "local_image_candidate_count": image_count,
                    "local_body_text_candidate_count": body_count,
                    "article_dir_declared_count": article_dir_count,
                    "account_present_in_queue": account_present,
                    "account_queue_row_count": int_value(account_diag.get("account_queue_row_count")),
                    "account_queue_min_post_date": str(account_diag.get("account_queue_min_post_date") or ""),
                    "account_queue_max_post_date": account_latest,
                    "candidate_published_at": candidate_published_at,
                    "account_date_queue_match_count": account_date_matches,
                    "account_date_image_candidate_count": int_value(account_diag.get("account_date_image_candidate_count")),
                    "account_date_body_text_candidate_count": int_value(account_diag.get("account_date_body_text_candidate_count")),
                    "account_latest_before_candidate": latest_before_candidate,
                }
            )
        candidate_count = len(candidates)
        source_map_missing = max(0, candidate_count - source_map_resolved)
        source_map_missing_total += source_map_missing
        queue_match_total += queue_match_count
        image_candidate_total += image_candidate_count
        candidate_account_present_total += account_present_count
        candidate_account_date_match_total += account_date_match_count
        candidate_account_latest_before_candidate_total += account_latest_before_candidate_count
        offline_ready = queue_match_count > 0 and (image_candidate_count > 0 or article_dir_declared_count > 0)
        offline_ready_count += int(offline_ready)
        if offline_ready:
            material_gap_reason = ""
        elif account_present_count and not account_date_match_count:
            material_gap_reason = "candidate_account_present_but_candidate_date_missing_from_bounded_queues"
        elif account_present_count:
            material_gap_reason = "candidate_account_date_present_but_source_url_or_image_material_missing"
        else:
            material_gap_reason = "candidate_account_missing_from_bounded_queues"
        task_rows.append(
            {
                "id": str(task.get("id") or ""),
                "title_hash": sha16(str(task.get("title") or "")),
                "event_date_start": str(task.get("event_date_start") or ""),
                "event_date_end": str(task.get("event_date_end") or ""),
                "candidate_source_count": candidate_count,
                "source_map_resolved_count": source_map_resolved,
                "source_map_missing_count": source_map_missing,
                "local_queue_match_count": queue_match_count,
                "local_image_candidate_count": image_candidate_count,
                "local_body_text_candidate_count": body_text_candidate_count,
                "article_dir_declared_count": article_dir_declared_count,
                "candidate_account_present_count": account_present_count,
                "candidate_account_date_match_count": account_date_match_count,
                "candidate_account_latest_before_candidate_count": account_latest_before_candidate_count,
                "offline_ocr_material_ready": offline_ready,
                "material_gap_reason": material_gap_reason,
                "candidates": candidates,
            }
        )

    checks = [
        check("runtime_preflight_schema", runtime.get("schema_version") == RUNTIME_SCHEMA, str(runtime.get("schema_version"))),
        check("runtime_preflight_ready", runtime.get("decision") == RUNTIME_READY, str(runtime.get("decision"))),
        check("runtime_preflight_failed_checks_empty", not as_list(runtime.get("failed_required_check_ids")), json.dumps(runtime.get("failed_required_check_ids") or [])),
        check("runtime_preflight_report_only", runtime.get("report_only") is True, str(runtime.get("report_only"))),
        check("tasks_schema", tasks_report.get("schema_version") == TASKS_SCHEMA, str(tasks_report.get("schema_version"))),
        check("tasks_report_only", tasks_report.get("report_only") is True, str(tasks_report.get("report_only"))),
        check("tasks_leak_free", int_value(tasks_report.get("raw_public_url_leak_count")) == 0, str(tasks_report.get("raw_public_url_leak_count"))),
        check("selected_tasks_found", len(selected_tasks) == len(selected_ids) and len(selected_ids) > 0, f"{len(selected_tasks)}/{len(selected_ids)}"),
        check("source_map_available", bool(sources), str(len(sources))),
        check("selected_candidate_sources_resolve_to_source_map", source_map_missing_total == 0, str(source_map_missing_total)),
        check("bounded_queue_files_scanned", len(queue_files) > 0, str(len(queue_files))),
        check("offline_ocr_material_found_for_selected_tasks", offline_ready_count == len(selected_tasks) and len(selected_tasks) > 0, f"{offline_ready_count}/{len(selected_tasks)}"),
    ]
    for key in FALSE_EXECUTION_FLAGS:
        checks.append(check(f"{key}_false", runtime.get(key) is False, str(runtime.get(key))))

    failed = [row["check_id"] for row in checks if row["status"] != "passed"]
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": READY_DECISION if not failed else BLOCKED_DECISION,
        "report_only": True,
        "source_runtime_preflight_report": safe_repo_path(runtime_preflight_path),
        "source_tasks_report": safe_repo_path(tasks_path),
        "source_url_map_report": safe_repo_path(resolved_source_map_path) if resolved_source_map_path else "",
        "queue_scan": queue_scan,
        "selected_task_count": len(selected_tasks),
        "selected_task_ids": selected_ids,
        "candidate_source_count": len(source_keys),
        "source_map_resolved_source_count": sum(1 for key in source_keys if source_urls_by_key.get(key)),
        "source_map_missing_total": source_map_missing_total,
        "local_queue_match_total": queue_match_total,
        "local_image_candidate_total": image_candidate_total,
        "candidate_account_present_total": candidate_account_present_total,
        "candidate_account_date_match_total": candidate_account_date_match_total,
        "candidate_account_latest_before_candidate_total": candidate_account_latest_before_candidate_total,
        "offline_ocr_material_ready_task_count": offline_ready_count,
        "network_or_exporter_required_task_count": max(0, len(selected_tasks) - offline_ready_count),
        "tasks": task_rows,
        "checks": checks,
        "failed_required_check_ids": failed,
        "actual_ocr_worker_allowed_now": False,
        "network_fetch_executed": False,
        "download_executed": False,
        "ocr_executed": False,
        "vision_api_executed": False,
        "stepfun_api_executed": False,
        "mimo_api_executed": False,
        "cloudbase_storage_write_executed": False,
        "package_patch_executed": False,
        "cloudbase_db_write_executed": False,
        "db2_write_executed": False,
        "db3_write_executed": False,
        "cloudrun_deploy_executed": False,
        "cloudbase_sync_executed": False,
        "miniprogram_upload_executed": False,
        "wechat_review_submitted": False,
        "public_release_executed": False,
        "next_gate": "controller_authorized_source_material_fetch_or_exporter_refresh_then_ocr_worker",
    }
    report["raw_url_private_path_secret_leak_count"] = leak_count(report)
    if report["raw_url_private_path_secret_leak_count"]:
        report["decision"] = BLOCKED_DECISION
        if "output_raw_url_private_path_secret_leak_free" not in report["failed_required_check_ids"]:
            report["failed_required_check_ids"].append("output_raw_url_private_path_secret_leak_free")
    return report


def scorecard_text(report: dict[str, Any]) -> str:
    failed = report.get("failed_required_check_ids") or []
    return "\n".join(
        [
            "# Weekly Aggregate-Child Poster OCR Source Material Preflight",
            "",
            f"- decision: `{report.get('decision')}`",
            f"- selected_task_count: `{report.get('selected_task_count')}`",
            f"- candidate_source_count: `{report.get('candidate_source_count')}`",
            f"- source_map_missing_total: `{report.get('source_map_missing_total')}`",
            f"- local_queue_match_total: `{report.get('local_queue_match_total')}`",
            f"- local_image_candidate_total: `{report.get('local_image_candidate_total')}`",
            f"- candidate_account_present_total: `{report.get('candidate_account_present_total')}`",
            f"- candidate_account_date_match_total: `{report.get('candidate_account_date_match_total')}`",
            f"- candidate_account_latest_before_candidate_total: `{report.get('candidate_account_latest_before_candidate_total')}`",
            f"- offline_ocr_material_ready_task_count: `{report.get('offline_ocr_material_ready_task_count')}`",
            f"- network_or_exporter_required_task_count: `{report.get('network_or_exporter_required_task_count')}`",
            f"- leak_count: `{report.get('raw_url_private_path_secret_leak_count')}`",
            f"- failed_required_check_ids: `{', '.join(failed) if failed else '[]'}`",
            "",
            "Safety boundary: no network, download, OCR, vision API, StepFun/MiMo API, CloudBase write, package patch, deploy, sync, upload, review, or release was executed.",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-preflight", type=Path, default=DEFAULT_RUNTIME_PREFLIGHT)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--source-url-map", type=Path, default=None)
    parser.add_argument("--queue", type=Path, action="append", default=[])
    parser.add_argument("--max-tasks", type=int, default=5)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--scorecard", type=Path, default=DEFAULT_SCORECARD)
    args = parser.parse_args(argv)

    report = build_source_material_preflight(
        args.runtime_preflight,
        args.tasks,
        args.source_url_map,
        args.queue,
        max_tasks=args.max_tasks,
    )
    write_json(args.report, report)
    write_text(args.scorecard, scorecard_text(report))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not report["failed_required_check_ids"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
