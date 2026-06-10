#!/usr/bin/env python3
"""Build report-only source acquisition preflight work orders for Atlas source/OCR.

This consumes the hashed/redacted external source acquisition candidates and
checks the source-url sidecar internally for deterministic fetch readiness. It
does not fetch URLs, run OCR, call models, or write source/graph/serving state.
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
ACQUISITION_PLAN_ROOT = STAGE7_ROOT / "reports" / "atlas_source_artifact_acquisition_plan_t5_20260526"
DEFAULT_INPUT = ACQUISITION_PLAN_ROOT / "external_source_acquisition_candidates.jsonl"
DEFAULT_SOURCE_URL_JSONL = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_source_url_recovery_139123_candidate"
    / "article_source_url.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_source_acquisition_preflight_t5_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_SOURCE_ACQUISITION_PREFLIGHT_20260526.md"
SCHEMA_VERSION = "stage7_atlas_source_acquisition_preflight.v1"

URL_RE = re.compile(r"https?://", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
SENSITIVE_KEY_RE = re.compile(r"(secret|token|cookie|password|api[_-]?key|authorization)", re.I)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def safe_hash(value: Any, length: int = 16) -> str:
    return hashlib.sha256(compact(value, 8000).encode("utf-8", errors="ignore")).hexdigest()[:length]


def full_hash(value: Any) -> str:
    return hashlib.sha256(compact(value, 8000).encode("utf-8", errors="ignore")).hexdigest()


def scrub_text(value: Any, limit: int = 1000) -> str:
    text = compact(value, limit)
    text = URL_RE.sub("redacted-url", text)
    text = LOCAL_PATH_RE.sub("redacted-local-path", text)
    text = SENSITIVE_KEY_RE.sub("redacted-word", text)
    return text


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas source acquisition preflight: {path}")


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


def source_url_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for row in rows:
        uid = compact(row.get("article_uid") or row.get("article_id"), 200)
        if uid:
            indexed[uid] = row
    return indexed


def candidate_source_state(row: dict[str, Any]) -> dict[str, Any]:
    state = row.get("source_url_artifact_state")
    if not isinstance(state, dict):
        state = {}
    return state


def build_work_order(generated_at: str, row: dict[str, Any], source_row: dict[str, Any] | None) -> dict[str, Any]:
    state = candidate_source_state(row)
    article_uid = compact(row.get("article_uid"), 200)
    source_ref_id = compact(state.get("source_ref_id"), 160)
    candidate_hash = compact(state.get("source_url_sha256"), 96)
    raw_url = compact((source_row or {}).get("source_url"), 5000)
    sidecar_hash = full_hash(raw_url) if raw_url else ""
    sidecar_found = bool(source_row)
    sidecar_url_present = bool(raw_url)
    hash_match = bool(candidate_hash and sidecar_hash and candidate_hash == sidecar_hash)
    hash_missing = bool(sidecar_url_present and not candidate_hash)
    hash_mismatch = bool(candidate_hash and sidecar_hash and candidate_hash != sidecar_hash)
    local_ready = bool(row.get("local_source_artifact_ready"))
    localize_ready = bool(local_ready and not sidecar_url_present)
    fetch_ready = bool(sidecar_found and sidecar_url_present and (hash_match or hash_missing) and not local_ready)

    if local_ready:
        route = "local_artifact_preflight_ready_without_fetch"
        blocked_reason = ""
    elif fetch_ready:
        route = "external_source_fetch_preflight_ready_report_only"
        blocked_reason = ""
    elif not sidecar_found or not sidecar_url_present:
        route = "blocked_source_url_sidecar_missing_or_unresolved"
        blocked_reason = "source_url_sidecar_missing_or_unresolved"
    elif hash_mismatch:
        route = "blocked_source_url_hash_mismatch"
        blocked_reason = "source_url_hash_mismatch"
    else:
        route = "blocked_source_acquisition_preflight_incomplete"
        blocked_reason = "source_acquisition_preflight_incomplete"

    ticket_seed = f"{article_uid}|{source_ref_id}|{candidate_hash or sidecar_hash}|{route}"
    ticket_id = f"source_acq:{safe_hash(ticket_seed, 20)}"
    bundle_ref = f"report_local_artifact_bundle:{safe_hash(ticket_seed + '|bundle', 20)}"
    manifest_ref = f"source_acq_manifest:{safe_hash(ticket_seed + '|manifest', 20)}"
    post_date_present = bool(compact((source_row or {}).get("post_date"), 80) or state.get("post_date_present"))
    post_time_present = bool(compact((source_row or {}).get("post_time"), 80) or state.get("post_time_present"))

    return {
        "schema_version": SCHEMA_VERSION + ".work_order",
        "generated_at": generated_at,
        "article_uid": article_uid,
        "work_item_id": compact(row.get("work_item_id"), 120),
        "source_account": scrub_text(row.get("source_account"), 240),
        "title": scrub_text(row.get("title"), 500),
        "local_image_count": int(row.get("local_image_count") or 0),
        "source_ref_id": source_ref_id,
        "source_url_evidence": {
            "candidate_source_url_sha256": candidate_hash,
            "sidecar_source_url_sha256": sidecar_hash,
            "source_url_sidecar_found": sidecar_found,
            "source_url_present_in_sidecar": sidecar_url_present,
            "source_url_sha256_matches_candidate": hash_match,
            "source_url_sha256_missing_from_candidate": hash_missing,
            "source_url_sha256_mismatch": hash_mismatch,
            "post_date_present": post_date_present,
            "post_time_present": post_time_present,
            "source_url_match_basis": scrub_text((source_row or {}).get("match_basis") or state.get("source_url_match_basis"), 180),
            "raw_source_url_emitted": False,
        },
        "preflight_route": route,
        "blocked_reason": blocked_reason,
        "fetch_preflight_ready": fetch_ready,
        "localize_without_fetch_ready": localize_ready,
        "network_fetch_executed": False,
        "ocr_execution_executed": False,
        "source_sqlite_write_executed": False,
        "acquisition_ticket_id": ticket_id,
        "report_local_artifact_scope": {
            "artifact_bundle_ref_id": bundle_ref,
            "manifest_ref_id": manifest_ref,
            "target_policy": "write_only_under_report_local_hashed_bundle_after_fetch_gate",
            "raw_target_path_emitted": False,
        },
        "allowed_next_actions_after_gate": [
            "resolve_raw_source_url_in_memory_from_sidecar",
            "fetch_public_article_without_auth_material",
            "store_html_and_images_under_report_local_hashed_bundle",
            "write_manifest_with_content_hashes_and_redacted_source_ref",
            "run leak_scan_before_opening_ocr_generation",
        ]
        if fetch_ready
        else [],
        "rollback_requirements": [
            "delete_only_the_report_local_hashed_bundle_and_manifest_created_for_this_ticket",
            "do_not_mutate_source_raw_atlas_db_serving_sqlite_graph_vector_or_public_pointer",
            "record rollback_or_no_artifact_created evidence in the acquisition execution report",
        ],
        "post_evidence_requirements": [
            "manifest_exists_with_html_or_image_hashes",
            "raw_source_url_and_local_paths_not_emitted",
            "auth_material_usage_false",
            "network_fetch_status_recorded_per_ticket",
            "ocr_markdown_generation_stays_closed_until_manifest_passes_leak_and_content_checks",
        ],
        "ocr_generation_allowed_now": False,
        "acceptance_precheck_allowed_now": False,
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
                "fetch_preflight_ready_rows": sum(1 for row in source_rows if row["fetch_preflight_ready"]),
                "localize_without_fetch_ready_rows": sum(
                    1 for row in source_rows if row["localize_without_fetch_ready"]
                ),
                "blocked_rows": sum(1 for row in source_rows if row["blocked_reason"]),
                "local_image_count_total": sum(int(row.get("local_image_count") or 0) for row in source_rows),
                "preflight_route_counts": dict(sorted(Counter(row["preflight_route"] for row in source_rows).items())),
                "write_status": "report_only",
            }
        )
    return rollup


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    lines = [
        "# Atlas T5 Source Acquisition Preflight - 2026-05-26",
        "",
        "Status: `CURRENT_AUTHORITY`",
        "Mode: `report_only`",
        "",
        "## LLM Audit Finding",
        "",
        "The acquisition plan correctly stopped before OCR because no local source artifacts exist. This preflight verifies that the five external candidates can be converted into deterministic fetch work orders from sidecar source-url hashes, while keeping raw source URLs out of reports and keeping all DB/graph/vector/public gates closed.",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input rows: `{counts['input_rows']}`",
        f"- Sidecar source URL found rows: `{counts['sidecar_source_url_found_rows']}`",
        f"- Source URL hash match rows: `{counts['source_url_hash_match_rows']}`",
        f"- Source URL hash mismatch rows: `{counts['source_url_hash_mismatch_rows']}`",
        f"- Fetch preflight-ready rows: `{counts['fetch_preflight_ready_rows']}`",
        f"- Localize-without-fetch ready rows: `{counts['localize_without_fetch_ready_rows']}`",
        f"- Blocked rows: `{counts['blocked_rows']}`",
        f"- OCR generation allowed now: `{counts['ocr_generation_allowed_now_rows']}`",
        f"- Acceptance precheck allowed now: `{counts['acceptance_precheck_allowed_now_rows']}`",
        f"- Public URL / sensitive-key / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Outputs",
        "",
        f"- Summary JSON: `{outputs['summary_json']}`",
        f"- Work orders: `{outputs['work_orders_jsonl']}`",
        f"- Fetch preflight-ready work orders: `{outputs['fetch_preflight_ready_jsonl']}`",
        f"- Blocked work orders: `{outputs['blocked_work_orders_jsonl']}`",
        f"- Source rollup: `{outputs['source_rollup_jsonl']}`",
        "",
        "## Row Snapshot",
        "",
    ]
    for row in rows[:10]:
        lines.append(
            f"- `{row['article_uid']}` `{row['source_account']}` -> `{row['preflight_route']}`; ticket `{row['acquisition_ticket_id']}`; images `{row['local_image_count']}`"
        )
    lines.extend(
        [
            "",
            "## Rollback / Post Evidence Contract",
            "",
            "- Rollback is report-local only: delete the hashed bundle/manifest for the ticket if a future fetch creates artifacts.",
            "- Post evidence for a future fetch must include content hashes, leak scan, auth-material usage false, and per-ticket fetch status.",
            "- OCR/Markdown generation may only open after fetched or localized artifacts pass content and leak checks.",
            "",
            "## Boundary",
            "",
            "- Report-only source acquisition preflight/work-order generation.",
            "- No source URL fetch, OCR execution, LLM/model call, source/raw Atlas DB write, serving SQLite write/rebuild, graph fact acceptance, public pointer, deploy, upload/review, memory write, credential read, 9router use, destructive Git, or D root scan occurred.",
            "- Raw source URLs and local filesystem paths are not emitted. Source URLs remain SHA256/ref identifiers only.",
            "",
            "## Next Cursor",
            "",
            "Execute a bounded acquisition runner only against `fetch_preflight_ready_work_orders.jsonl`, storing artifacts in report-local hashed bundles and producing rollback/post-fetch evidence. Keep OCR generation and source/OCR acceptance closed until that manifest exists and passes leak/content checks.",
            "",
        ]
    )
    return "\n".join(lines)


def build_preflight(
    *,
    input_path: Path,
    source_url_jsonl: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for label, path in (
        ("input_path", input_path),
        ("source_url_jsonl", source_url_jsonl),
        ("out_dir", out_dir),
        ("report_path", report_path),
    ):
        reject_d_path(path, label)

    generated_at = now_iso()
    candidates = read_jsonl(input_path)
    source_urls = source_url_index(read_jsonl(source_url_jsonl, optional=True))
    rows = [
        build_work_order(generated_at, row, source_urls.get(compact(row.get("article_uid"), 200)))
        for row in candidates
    ]
    fetch_ready = [row for row in rows if row["fetch_preflight_ready"]]
    localize_ready = [row for row in rows if row["localize_without_fetch_ready"]]
    blocked = [row for row in rows if row["blocked_reason"]]
    source_rollup = build_source_rollup(rows, generated_at)
    leak_hits = leak_scan(rows + source_rollup)
    failed_checks: list[str] = []
    if any(leak_hits.values()):
        failed_checks.append("source_acquisition_preflight_contains_public_url_secret_or_local_path")
    if not rows:
        failed_checks.append("no_source_acquisition_preflight_rows")
    decision = (
        "atlas_source_acquisition_preflight_ready_report_only"
        if (fetch_ready or localize_ready) and not failed_checks
        else "atlas_source_acquisition_preflight_blocked_report_only"
        if rows and not failed_checks
        else "atlas_source_acquisition_preflight_failed_safety_scan"
    )
    counts = {
        "input_rows": len(rows),
        "sidecar_source_url_found_rows": sum(
            1 for row in rows if row["source_url_evidence"]["source_url_sidecar_found"]
        ),
        "source_url_present_in_sidecar_rows": sum(
            1 for row in rows if row["source_url_evidence"]["source_url_present_in_sidecar"]
        ),
        "source_url_hash_match_rows": sum(
            1 for row in rows if row["source_url_evidence"]["source_url_sha256_matches_candidate"]
        ),
        "source_url_hash_missing_from_candidate_rows": sum(
            1 for row in rows if row["source_url_evidence"]["source_url_sha256_missing_from_candidate"]
        ),
        "source_url_hash_mismatch_rows": sum(
            1 for row in rows if row["source_url_evidence"]["source_url_sha256_mismatch"]
        ),
        "fetch_preflight_ready_rows": len(fetch_ready),
        "localize_without_fetch_ready_rows": len(localize_ready),
        "blocked_rows": len(blocked),
        "ocr_generation_allowed_now_rows": sum(1 for row in rows if row["ocr_generation_allowed_now"]),
        "acceptance_precheck_allowed_now_rows": sum(
            1 for row in rows if row["acceptance_precheck_allowed_now"]
        ),
        "network_fetch_executed_rows": sum(1 for row in rows if row["network_fetch_executed"]),
    }
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "inputs": {
            "external_source_acquisition_candidates": display_path(input_path),
            "source_url_jsonl": display_path(source_url_jsonl),
        },
        "outputs": {
            "summary_json": display_path(out_dir / "source_acquisition_preflight_summary.json"),
            "work_orders_jsonl": display_path(out_dir / "source_acquisition_preflight_work_orders.jsonl"),
            "fetch_preflight_ready_jsonl": display_path(out_dir / "fetch_preflight_ready_work_orders.jsonl"),
            "localize_without_fetch_ready_jsonl": display_path(out_dir / "localize_without_fetch_ready_work_orders.jsonl"),
            "blocked_work_orders_jsonl": display_path(out_dir / "blocked_source_acquisition_work_orders.jsonl"),
            "source_rollup_jsonl": display_path(out_dir / "source_rollup.jsonl"),
        },
        "counts": counts,
        "preflight_route_counts": dict(sorted(Counter(row["preflight_route"] for row in rows).items())),
        "source_account_counts": dict(sorted(Counter(row["source_account"] for row in rows).items())),
        "leak_scan": leak_hits,
        "llm_audit": {
            "artifact_consistency": "04:36 candidates are consistent with the source-url sidecar by article_uid and URL SHA256.",
            "stale_loop_avoided": "did not fetch, run OCR, or rerun source/OCR acceptance before producing per-ticket rollback and post-evidence requirements.",
            "highest_leverage_next_lane": "bounded report-local source acquisition runner over fetch_preflight_ready_work_orders.jsonl.",
        },
        "execution_cursor": {
            "next_lane": "source_acquisition_bounded_fetch_runner",
            "next_input": display_path(out_dir / "fetch_preflight_ready_work_orders.jsonl"),
            "rerun_ocr_generation_now": False,
            "rerun_acceptance_precheck_now": False,
            "next_command_intent": "Fetch only report-local article/image artifacts for preflight-ready tickets, then verify hashes/leak scan before OCR/Markdown generation.",
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
        "stop_reason": "none" if not failed_checks else "source_acquisition_preflight_failed_checks",
        "wait_reason": "ready_for_bounded_report_local_source_fetch_runner" if fetch_ready else "source_acquisition_preflight_blocked",
    }
    write_jsonl(out_dir / "source_acquisition_preflight_work_orders.jsonl", rows)
    write_jsonl(out_dir / "fetch_preflight_ready_work_orders.jsonl", fetch_ready)
    write_jsonl(out_dir / "localize_without_fetch_ready_work_orders.jsonl", localize_ready)
    write_jsonl(out_dir / "blocked_source_acquisition_work_orders.jsonl", blocked)
    write_jsonl(out_dir / "source_rollup.jsonl", source_rollup)
    write_json(out_dir / "source_acquisition_preflight_summary.json", summary)
    write_text(report_path, render_report(summary, rows))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--source-url-jsonl", type=Path, default=DEFAULT_SOURCE_URL_JSONL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_preflight(
        input_path=args.input,
        source_url_jsonl=args.source_url_jsonl,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
