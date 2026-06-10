#!/usr/bin/env python3
"""Report-only localization probe for Q6 manual participant source/OCR blockers."""
from __future__ import annotations

import argparse
import importlib.util
import json
from collections import Counter
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
HELPER_PATH = STAGE7_ROOT / "scripts" / "probe_atlas_source_ocr_artifact_localization.py"
DEFAULT_WORK_ORDERS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_blocker_recovery_q6_20260526"
    / "source_ocr_recovery_work_orders.jsonl"
)
DEFAULT_FIRST_BATCH_EVIDENCE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_source_ocr_first_batch_evidence_probe_t5_20260526"
    / "first_batch_evidence_probe_rows.jsonl"
)
DEFAULT_ATLAS_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_SOURCE_URL_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_source_url_recovery_139123_candidate"
    / "atlas_source_url_recovery.sqlite"
)
DEFAULT_HOST_ARTIFACT_ROOT = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "host_html_artifacts"
    / "artifacts"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_source_ocr_localization_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_OCR_LOCALIZATION_PROBE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_source_ocr_localization_probe.v1"


spec = importlib.util.spec_from_file_location("source_ocr_localization_helper", HELPER_PATH)
helper = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(helper)


def display_path(path: Path) -> str:
    return helper.display_path(path)


def q6_row(row: dict[str, Any]) -> dict[str, Any]:
    updated = dict(row)
    updated["schema_version"] = SCHEMA_VERSION + ".row"
    updated["q6_manual_participant_source_ocr_probe"] = True
    updated["acceptance_precheck_allowed_now"] = False
    updated["accepted_for_graph"] = False
    updated["serving_rebuild_allowed"] = False
    updated["graph_write_allowed"] = False
    updated["public_serving_field_allowed"] = False
    updated["memory_write_allowed"] = False
    updated["write_status"] = "report_only"
    return updated


def render_report(summary: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    lines = [
        "# Atlas T6 Manual Participant Source/OCR Localization Probe - 2026-05-26",
        "",
        "Status: `CURRENT_AUTHORITY`",
        "Mode: `report_only`",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Source/OCR work-order rows: `{counts['target_rows']}`",
        f"- Source DB article rows found: `{counts['source_db_article_rows_found']}`",
        f"- Source URL sidecar rows found: `{counts['source_url_rows_found']}`",
        f"- Existing OCR/Markdown candidate rows: `{counts['existing_ocr_markdown_candidate_rows']}`",
        f"- Exact date candidate rows: `{counts['exact_date_candidate_rows']}`",
        f"- Acceptance-ready rows: `{counts['acceptance_ready_rows']}`",
        f"- Still blocked rows: `{counts['still_blocked_rows']}`",
        f"- Public URL / sensitive-key / local path leak hits: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Outputs",
        "",
        f"- Summary JSON: `{outputs['summary_json']}`",
        f"- Probe rows: `{outputs['probe_rows_jsonl']}`",
        f"- OCR candidate present but date blocked: `{outputs['ocr_candidate_present_date_blocked_jsonl']}`",
        f"- OCR/Markdown missing queue: `{outputs['ocr_markdown_missing_generation_queue_jsonl']}`",
        f"- Date candidate present, acceptance closed: `{outputs['date_candidate_present_acceptance_closed_jsonl']}`",
        f"- Still blocked rows: `{outputs['still_blocked_rows_jsonl']}`",
        f"- Source rollup: `{outputs['source_rollup_jsonl']}`",
        "",
        "## Row Snapshot",
        "",
    ]
    for row in rows[:10]:
        lines.append(
            f"- `{row['article_uid']}` `{row['source_account']}` / {row['title']} -> `{row['localization_status']}`; date candidates `{row['exact_date_candidate_count']}`; OCR candidate `{row['existing_ocr_markdown_candidate_found']}`; next `{row['next_action']}`"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- Report-only local probe over existing Q6 recovery work orders.",
            "- No OCR execution, model call, network fetch, source/raw Atlas DB write, serving SQLite write or rebuild, public pointer, CloudRun/VPS deploy, Neo4j/Qdrant/SQLite production write, mini-program upload/review, memory write, credential read, 9router use, destructive Git, or D root scan occurred.",
            "- Raw source URLs and local filesystem paths are not emitted. Artifact scope is represented by hashes, counts, and booleans.",
            "",
            "## Next Cursor",
            "",
            "Use the still-blocked rows for manual artifact recovery. Rerun Q6 source-context review or acceptance precheck only after exact date and OCR/Markdown evidence is recovered.",
            "",
        ]
    )
    return "\n".join(lines)


def build_q6_source_ocr_localization_probe(
    *,
    work_orders_path: Path,
    first_batch_evidence_path: Path,
    atlas_db: Path,
    source_url_db: Path,
    host_artifact_root: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    for label, path in (
        ("work_orders_path", work_orders_path),
        ("first_batch_evidence_path", first_batch_evidence_path),
        ("atlas_db", atlas_db),
        ("source_url_db", source_url_db),
        ("host_artifact_root", host_artifact_root),
        ("out_dir", out_dir),
        ("report_path", report_path),
    ):
        helper.reject_d_path(path, label)

    generated_at = helper.now_iso()
    work_orders = [
        row
        for row in helper.read_jsonl(work_orders_path)
        if helper.compact(row.get("recovery_lane"), 160) == "source_ocr_recovery"
    ]
    evidence_rows = helper.evidence_by_uid(helper.read_jsonl(first_batch_evidence_path, optional=True))
    uids = [helper.compact(row.get("article_uid"), 200) for row in work_orders if helper.compact(row.get("article_uid"), 200)]
    articles = helper.load_articles(atlas_db, uids)
    entities = helper.load_entities(atlas_db, uids)
    events = helper.load_event_counts(atlas_db, uids)
    source_urls = helper.load_source_url_rows(source_url_db, uids)

    rows = [
        q6_row(
            helper.build_probe_row(
                generated_at=generated_at,
                target=row,
                evidence=evidence_rows.get(helper.compact(row.get("article_uid"), 200)),
                article=articles.get(helper.compact(row.get("article_uid"), 200)),
                entities=entities.get(helper.compact(row.get("article_uid"), 200), []),
                event_count=events.get(helper.compact(row.get("article_uid"), 200), 0),
                source_url=source_urls.get(helper.compact(row.get("article_uid"), 200)),
                host_root=host_artifact_root,
            )
        )
        for row in work_orders
    ]
    ocr_present_date_blocked = [
        row
        for row in rows
        if row["existing_ocr_markdown_candidate_found"]
        and row["localization_status"] in {"blocked_missing_exact_date", "candidate_evidence_present_acceptance_still_closed"}
    ]
    ocr_missing = [row for row in rows if not row["existing_ocr_markdown_candidate_found"]]
    date_present_acceptance_closed = [row for row in rows if row["exact_date_candidate_found"]]
    still_blocked = [row for row in rows if not row["acceptance_precheck_allowed_now"]]
    rollup = helper.build_source_rollup(rows, generated_at)
    for item in rollup:
        item["schema_version"] = SCHEMA_VERSION + ".source_rollup"

    helper.write_jsonl(out_dir / "source_ocr_localization_probe_rows.jsonl", rows)
    helper.write_jsonl(out_dir / "ocr_candidate_present_date_blocked.jsonl", ocr_present_date_blocked)
    helper.write_jsonl(out_dir / "ocr_markdown_missing_generation_queue.jsonl", ocr_missing)
    helper.write_jsonl(out_dir / "date_candidate_present_acceptance_closed.jsonl", date_present_acceptance_closed)
    helper.write_jsonl(out_dir / "still_blocked_rows.jsonl", still_blocked)
    helper.write_jsonl(out_dir / "source_rollup.jsonl", rollup)

    leak = helper.leak_scan(rows + rollup)
    failed_checks = [key for key, value in leak.items() if value]
    counts = {
        "target_rows": len(rows),
        "source_db_article_rows_found": sum(1 for row in rows if row["source_db_article_found"]),
        "source_url_rows_found": sum(1 for row in rows if row["source_url_evidence"].get("source_url_recovery_found")),
        "existing_ocr_markdown_candidate_rows": sum(1 for row in rows if row["existing_ocr_markdown_candidate_found"]),
        "missing_ocr_markdown_rows": len(ocr_missing),
        "exact_date_candidate_rows": sum(1 for row in rows if row["exact_date_candidate_found"]),
        "date_candidate_present_acceptance_closed_rows": len(date_present_acceptance_closed),
        "acceptance_ready_rows": sum(1 for row in rows if row["acceptance_precheck_allowed_now"]),
        "still_blocked_rows": len(still_blocked),
        "host_artifact_source_dir_present_rows": sum(1 for row in rows if row["host_artifact_scope"].get("source_dir_present")),
    }
    decision = (
        "atlas_social_manual_participant_source_ocr_localization_failed_safety_scan"
        if failed_checks
        else "atlas_social_manual_participant_source_ocr_localization_blocked_report_only"
        if still_blocked
        else "atlas_social_manual_participant_source_ocr_localization_ready_for_later_acceptance_report_only"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "localization_status_counts": dict(sorted(Counter(row["localization_status"] for row in rows).items())),
        "source_account_counts": dict(sorted(Counter(row["source_account"] or "UNKNOWN" for row in rows).items())),
        "inputs": {
            "work_orders": display_path(work_orders_path),
            "first_batch_evidence": display_path(first_batch_evidence_path),
            "atlas_db": display_path(atlas_db),
            "source_url_db": display_path(source_url_db),
            "host_artifact_root": display_path(host_artifact_root),
        },
        "outputs": {
            "summary_json": display_path(out_dir / "source_ocr_localization_probe_summary.json"),
            "probe_rows_jsonl": display_path(out_dir / "source_ocr_localization_probe_rows.jsonl"),
            "ocr_candidate_present_date_blocked_jsonl": display_path(out_dir / "ocr_candidate_present_date_blocked.jsonl"),
            "ocr_markdown_missing_generation_queue_jsonl": display_path(out_dir / "ocr_markdown_missing_generation_queue.jsonl"),
            "date_candidate_present_acceptance_closed_jsonl": display_path(out_dir / "date_candidate_present_acceptance_closed.jsonl"),
            "still_blocked_rows_jsonl": display_path(out_dir / "still_blocked_rows.jsonl"),
            "source_rollup_jsonl": display_path(out_dir / "source_rollup.jsonl"),
            "report_md": display_path(report_path),
        },
        "leak_scan": leak,
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
        "stop_reason": "blocked_report_only_until_exact_date_and_ocr_markdown_evidence_are_recovered",
        "wait_reason": "Q6 source/OCR blocker still lacks acceptance-ready exact-date plus OCR/Markdown evidence; all write and public gates remain closed.",
        "next_resume_cursor": display_path(out_dir / "still_blocked_rows.jsonl"),
    }
    helper.write_json(out_dir / "source_ocr_localization_probe_summary.json", summary)
    helper.write_text(report_path, render_report(summary, rows))
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-orders", type=Path, default=DEFAULT_WORK_ORDERS)
    parser.add_argument("--first-batch-evidence", type=Path, default=DEFAULT_FIRST_BATCH_EVIDENCE)
    parser.add_argument("--atlas-db", type=Path, default=DEFAULT_ATLAS_DB)
    parser.add_argument("--source-url-db", type=Path, default=DEFAULT_SOURCE_URL_DB)
    parser.add_argument("--host-artifact-root", type=Path, default=DEFAULT_HOST_ARTIFACT_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_q6_source_ocr_localization_probe(
        work_orders_path=args.work_orders,
        first_batch_evidence_path=args.first_batch_evidence,
        atlas_db=args.atlas_db,
        source_url_db=args.source_url_db,
        host_artifact_root=args.host_artifact_root,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
