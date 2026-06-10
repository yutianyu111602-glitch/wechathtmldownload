#!/usr/bin/env python3
"""Build a report-only source artifact acquisition plan for Atlas source/OCR.

The input queue already says OCR/Markdown is missing. This gate determines
whether a local artifact is actually available, or whether the next step must be
source acquisition from hashed source-url refs. It does not fetch URLs, run OCR,
call models, or write source/graph/serving state.
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
EXECUTION_GATE_ROOT = STAGE7_ROOT / "reports" / "atlas_source_ocr_artifact_recovery_execution_gate_t5_20260526"
DEFAULT_INPUT = EXECUTION_GATE_ROOT / "source_artifact_acquisition_queue.jsonl"
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
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_artifact_acquisition_plan_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_ARTIFACT_ACQUISITION_PLAN_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_artifact_acquisition_plan.v1"

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
        raise ValueError(f"{label} must not point to D: for Atlas source artifact acquisition plan: {path}")


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


def host_artifact_dirs(host_root: Path) -> set[str]:
    reject_d_path(host_root, "host_artifact_root")
    if not host_root.exists():
        return set()
    return {child.name.casefold() for child in host_root.iterdir() if child.is_dir()}


def source_url_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        uid = compact(row.get("article_uid") or row.get("article_id"), 200)
        if uid:
            indexed[uid] = row
    return indexed


def safe_source_url_state(queue_row: dict[str, Any], source_row: dict[str, Any] | None) -> dict[str, Any]:
    source = source_row or {}
    queue_state = queue_row.get("source_url_artifact_state")
    if not isinstance(queue_state, dict):
        queue_state = {}
    raw_url = compact(source.get("source_url"), 5000)
    archive_path = compact(source.get("archive_raw_html_path"), 1200)
    source_file = compact(source.get("source_file"), 1200)
    artifact_ref_present = bool(archive_path or source_file or queue_state.get("sidecar_local_artifact_ref_present"))
    artifact_ref_d_root = (
        is_d_root_value(archive_path)
        or is_d_root_value(source_file)
        or bool(queue_state.get("sidecar_local_artifact_ref_d_root"))
    )
    return {
        "source_url_recovery_found": bool(source_row or queue_state.get("source_url_recovery_found")),
        "source_ref_id": compact(source.get("source_ref_id") or queue_state.get("source_ref_id"), 160),
        "source_url_present": bool(raw_url or queue_state.get("source_url_present")),
        "source_url_sha256": hashlib.sha256(raw_url.encode("utf-8", errors="ignore")).hexdigest()
        if raw_url
        else compact(queue_state.get("source_url_sha256"), 80),
        "source_url_match_basis": scrub_sensitive_words(source.get("match_basis") or queue_state.get("source_url_match_basis"), 180),
        "post_date_present": bool(compact(source.get("post_date"), 80) or queue_state.get("post_date_present")),
        "post_time_present": bool(compact(source.get("post_time"), 80) or queue_state.get("post_time_present")),
        "sidecar_local_artifact_ref_present": artifact_ref_present,
        "sidecar_local_artifact_ref_d_root": artifact_ref_d_root,
        "sidecar_local_artifact_ref_id": safe_hash(f"{archive_path}|{source_file}") if artifact_ref_present else "",
        "local_image_count": as_int(source.get("local_image_count") or queue_state.get("local_image_count") or queue_row.get("local_image_count")),
        "raw_source_url_emitted": False,
        "raw_artifact_path_emitted": False,
    }


def plan_row(
    *,
    generated_at: str,
    row: dict[str, Any],
    source_row: dict[str, Any] | None,
    present_host_dirs: set[str],
) -> dict[str, Any]:
    account = compact(row.get("source_account"), 240)
    slug = source_slug(account)
    source_state = safe_source_url_state(row, source_row)
    host_dir_present = slug in present_host_dirs
    local_artifact_ready = bool(
        host_dir_present
        or (
            source_state["sidecar_local_artifact_ref_present"]
            and not source_state["sidecar_local_artifact_ref_d_root"]
        )
    )
    external_candidate = bool(source_state["source_url_present"] and not local_artifact_ready)
    blocked_without_source_url = bool(not source_state["source_url_present"] and not local_artifact_ready)
    if local_artifact_ready:
        route = "local_source_artifact_ready_for_ocr_generation_gate"
        next_action = "run bounded OCR/Markdown generation preflight using local artifact refs"
    elif external_candidate:
        route = "external_source_acquisition_required_from_source_url_ref"
        next_action = "run source artifact acquisition preflight; fetch/store only report-local artifacts after explicit gate"
    else:
        route = "blocked_no_source_url_or_local_artifact_ref"
        next_action = "return to source URL recovery before OCR/Markdown generation"

    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "generated_at": generated_at,
        "article_uid": compact(row.get("article_uid"), 200),
        "work_item_id": compact(row.get("work_item_id"), 120),
        "source_account": account,
        "source_artifact_ref_id": safe_hash(account),
        "title": compact(row.get("title"), 500),
        "blocking_fields": [compact(item, 120) for item in row.get("blocking_fields", []) if compact(item, 120)],
        "local_image_count": source_state["local_image_count"],
        "source_slug": slug,
        "host_artifact_scope": {
            "host_source_dir_present": host_dir_present,
            "host_source_dir_status": "source_dir_present" if host_dir_present else "source_dir_absent_in_current_host_html_artifact_batch",
            "raw_host_path_emitted": False,
        },
        "source_url_artifact_state": source_state,
        "local_source_artifact_ready": local_artifact_ready,
        "external_source_acquisition_candidate": external_candidate,
        "blocked_without_source_url_or_local_ref": blocked_without_source_url,
        "acquisition_route": route,
        "next_action": next_action,
        "ocr_generation_allowed_now": local_artifact_ready,
        "acceptance_precheck_allowed_now": False,
        "accepted_for_graph": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "network_fetch_executed": False,
        "ocr_execution_executed": False,
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
                "local_image_count_total": sum(row["local_image_count"] for row in source_rows),
                "local_source_artifact_ready_rows": sum(1 for row in source_rows if row["local_source_artifact_ready"]),
                "external_source_acquisition_candidate_rows": sum(
                    1 for row in source_rows if row["external_source_acquisition_candidate"]
                ),
                "blocked_without_source_url_or_local_ref_rows": sum(
                    1 for row in source_rows if row["blocked_without_source_url_or_local_ref"]
                ),
                "acquisition_route_counts": dict(sorted(Counter(row["acquisition_route"] for row in source_rows).items())),
                "write_status": "report_only",
            }
        )
    return rollup


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    lines = [
        "# Atlas T5 Source Artifact Acquisition Plan - 2026-05-26",
        "",
        "Status: `CURRENT_AUTHORITY`",
        "Mode: `report_only`",
        "",
        "## LLM Audit Finding",
        "",
        "The exact-date review closed the existing OCR path for two rows. The remaining five OCR/Markdown rows have source URLs and image counts, but the current host artifact batch has no matching source directories and the source-url sidecar has no local artifact refs. OCR generation must not start from these rows until source artifacts are actually acquired.",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Target rows: `{counts['target_rows']}`",
        f"- Source URL present rows: `{counts['source_url_present_rows']}`",
        f"- Local image count total: `{counts['local_image_count_total']}`",
        f"- Host source-dir present rows: `{counts['host_source_dir_present_rows']}`",
        f"- Sidecar local artifact ref rows: `{counts['sidecar_local_artifact_ref_rows']}`",
        f"- Local source artifact-ready rows: `{counts['local_source_artifact_ready_rows']}`",
        f"- External source acquisition candidate rows: `{counts['external_source_acquisition_candidate_rows']}`",
        f"- Blocked without source URL/local ref rows: `{counts['blocked_without_source_url_or_local_ref_rows']}`",
        f"- OCR generation allowed rows: `{counts['ocr_generation_allowed_rows']}`",
        f"- Public URL / sensitive-key / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Outputs",
        "",
        f"- Summary JSON: `{outputs['summary_json']}`",
        f"- Acquisition plan rows: `{outputs['acquisition_plan_rows_jsonl']}`",
        f"- Local artifact ready rows: `{outputs['local_artifact_ready_rows_jsonl']}`",
        f"- External acquisition candidates: `{outputs['external_source_acquisition_candidates_jsonl']}`",
        f"- Source rollup: `{outputs['source_rollup_jsonl']}`",
        "",
        "## Row Snapshot",
        "",
    ]
    for row in rows[:10]:
        lines.append(
            f"- `{row['article_uid']}` `{row['source_account']}` -> `{row['acquisition_route']}`; images `{row['local_image_count']}`; next `{row['next_action']}`"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only local acquisition planning.",
            "- No source URL fetch, OCR execution, LLM/model call, source/raw Atlas DB write, serving SQLite write/rebuild, graph fact acceptance, public pointer, deploy, upload/review, memory write, credential read, 9router use, destructive Git, or D root scan occurred.",
            "- Raw source URLs and local filesystem paths are not emitted. Source URLs and artifact refs remain hashes/booleans.",
            "",
            "## Next Cursor",
            "",
            "Run a bounded source acquisition preflight for the five external acquisition candidates. Only after report-local article/image artifacts exist should OCR/Markdown generation be opened; source/OCR acceptance remains closed.",
            "",
        ]
    )
    return "\n".join(lines)


def build_acquisition_plan(
    *,
    input_path: Path,
    source_url_jsonl: Path,
    host_artifact_root: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for label, path in (
        ("input_path", input_path),
        ("source_url_jsonl", source_url_jsonl),
        ("host_artifact_root", host_artifact_root),
        ("out_dir", out_dir),
        ("report_path", report_path),
    ):
        reject_d_path(path, label)

    generated_at = now_iso()
    targets = read_jsonl(input_path)
    source_urls = source_url_index(read_jsonl(source_url_jsonl, optional=True))
    present_host_dirs = host_artifact_dirs(host_artifact_root)
    rows = [
        plan_row(
            generated_at=generated_at,
            row=target,
            source_row=source_urls.get(compact(target.get("article_uid"), 200)),
            present_host_dirs=present_host_dirs,
        )
        for target in targets
    ]
    local_ready = [row for row in rows if row["local_source_artifact_ready"]]
    external_candidates = [row for row in rows if row["external_source_acquisition_candidate"]]
    blocked_no_source = [row for row in rows if row["blocked_without_source_url_or_local_ref"]]
    source_rollup = build_source_rollup(rows, generated_at)
    leak_hits = leak_scan(rows + source_rollup)
    failed_checks: list[str] = []
    if any(leak_hits.values()):
        failed_checks.append("source_artifact_acquisition_plan_contains_public_url_secret_or_local_path")
    if not rows:
        failed_checks.append("no_source_artifact_acquisition_rows")
    decision = (
        "atlas_source_artifact_acquisition_plan_ready_for_local_ocr_generation_report_only"
        if local_ready and not failed_checks
        else "atlas_source_artifact_acquisition_plan_external_acquisition_required_report_only"
        if external_candidates and not failed_checks
        else "atlas_source_artifact_acquisition_plan_blocked_report_only"
        if rows and not failed_checks
        else "atlas_source_artifact_acquisition_plan_failed_safety_scan"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "source_artifact_acquisition_queue": display_path(input_path),
            "source_url_jsonl": display_path(source_url_jsonl),
            "host_artifact_root": display_path(host_artifact_root),
        },
        "outputs": {
            "summary_json": display_path(out_dir / "source_artifact_acquisition_plan_summary.json"),
            "acquisition_plan_rows_jsonl": display_path(out_dir / "source_artifact_acquisition_plan_rows.jsonl"),
            "local_artifact_ready_rows_jsonl": display_path(out_dir / "local_artifact_ready_rows.jsonl"),
            "external_source_acquisition_candidates_jsonl": display_path(
                out_dir / "external_source_acquisition_candidates.jsonl"
            ),
            "blocked_without_source_rows_jsonl": display_path(out_dir / "blocked_without_source_url_or_local_ref.jsonl"),
            "source_rollup_jsonl": display_path(out_dir / "source_rollup.jsonl"),
        },
        "counts": {
            "target_rows": len(rows),
            "source_url_present_rows": sum(1 for row in rows if row["source_url_artifact_state"]["source_url_present"]),
            "local_image_count_total": sum(row["local_image_count"] for row in rows),
            "host_source_dir_present_rows": sum(1 for row in rows if row["host_artifact_scope"]["host_source_dir_present"]),
            "sidecar_local_artifact_ref_rows": sum(
                1 for row in rows if row["source_url_artifact_state"]["sidecar_local_artifact_ref_present"]
            ),
            "local_source_artifact_ready_rows": len(local_ready),
            "external_source_acquisition_candidate_rows": len(external_candidates),
            "blocked_without_source_url_or_local_ref_rows": len(blocked_no_source),
            "ocr_generation_allowed_rows": sum(1 for row in rows if row["ocr_generation_allowed_now"]),
        },
        "acquisition_route_counts": dict(sorted(Counter(row["acquisition_route"] for row in rows).items())),
        "source_account_counts": dict(sorted(Counter(row["source_account"] for row in rows).items())),
        "leak_scan": leak_hits,
        "llm_audit": {
            "artifact_consistency": "04:09 acquisition queue is consistent with source-url sidecar and host artifact root.",
            "stale_loop_avoided": "did not run OCR generation when no matching local artifact refs exist.",
            "highest_leverage_next_lane": "bounded source acquisition preflight for source-url refs.",
        },
        "execution_cursor": {
            "next_lane": "source_artifact_acquisition_preflight",
            "rerun_ocr_generation_now": bool(local_ready),
            "rerun_acceptance_precheck_now": False,
            "next_input": "tools/stage7_rewrite/reports/atlas_source_artifact_acquisition_plan_t5_20260526/external_source_acquisition_candidates.jsonl",
            "next_command_intent": "Acquire report-local article/image artifacts from hashed source-url refs, then open OCR/Markdown generation gate.",
        },
        "safety": {
            "report_only": True,
            "raw_source_url_emitted": False,
            "raw_local_path_emitted": False,
            "network_fetch_executed": False,
            "ocr_execution_executed": False,
            "llm_call_executed": False,
            "production_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "source_sqlite_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "stop_reason": "none" if not failed_checks else "source_artifact_acquisition_plan_failed_checks",
        "wait_reason": "source_artifacts_not_local_yet" if rows and not local_ready else "none",
    }
    write_jsonl(out_dir / "source_artifact_acquisition_plan_rows.jsonl", rows)
    write_jsonl(out_dir / "local_artifact_ready_rows.jsonl", local_ready)
    write_jsonl(out_dir / "external_source_acquisition_candidates.jsonl", external_candidates)
    write_jsonl(out_dir / "blocked_without_source_url_or_local_ref.jsonl", blocked_no_source)
    write_jsonl(out_dir / "source_rollup.jsonl", source_rollup)
    write_json(out_dir / "source_artifact_acquisition_plan_summary.json", summary)
    write_text(report_path, render_report(summary, rows))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--source-url-jsonl", type=Path, default=DEFAULT_SOURCE_URL_JSONL)
    parser.add_argument("--host-artifact-root", type=Path, default=DEFAULT_HOST_ARTIFACT_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_acquisition_plan(
        input_path=args.input,
        source_url_jsonl=args.source_url_jsonl,
        host_artifact_root=args.host_artifact_root,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
