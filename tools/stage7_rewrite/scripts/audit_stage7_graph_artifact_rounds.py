#!/usr/bin/env python3
"""Reconcile Stage7 graph artifact rounds from reports, memory, and handoffs.

Read-only audit. This scans only the local Stage7 reports directory and records
which historical production/extraction/repair rounds are already consumed by
the current electronic-music graph lane, and which rounds still need downstream
processing. It does not call paid APIs, LLMs, OCR, Qdrant, Neo4j, mem0, or D:.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DEFAULT_OUT_DIR = REPORTS / "stage7_graph_artifact_rounds_reconciliation_20260518"
SCHEMA_VERSION = "stage7_graph_artifact_rounds_reconciliation.v1"
WAVE01_21_INDEX = REPORTS / "dajiala_paid_wave01_21_verified_combined_ocr_index_20260518" / "ocr_file_index_summary.json"
WAVE09_21_DELTA_SUMMARY = REPORTS / "ocr_markitdown_flash_reprocess_plan_wave09_21_delta_20260518" / "delta_manifest_summary.json"
WAVE09_21_STABLE_SUMMARY = (
    REPORTS / "ocr_markdown_flash_wave09_21_delta375_stable_extract_20260518" / "stable_materialize_summary.json"
)
WAVE09_21_PROMOTION_VERIFY = (
    REPORTS / "graph_production_promotion_ocr_markdown_flash_wave09_21_delta375_verify_20260518" / "promotion_report.json"
)
UNIFIED_STABLE_SUMMARY = (
    REPORTS / "stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518" / "stable_merge_summary.json"
)
UNIFIED_PROMOTION_APPLY = (
    REPORTS
    / "graph_production_promotion_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_apply_20260518"
    / "promotion_report.json"
)
UNIFIED_PROMOTION_VERIFY = (
    REPORTS
    / "graph_production_promotion_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_verify_20260518"
    / "promotion_report.json"
)

MEMORY_EVIDENCE = [
    {
        "source": "local_mem0",
        "id": "ee8a8e4c-e74c-4f4c-91a3-3ffebd3a1e3b",
        "claim": "93K truth entrypoints and release-pass-vs-intake warning.",
    },
    {
        "source": "local_mem0",
        "id": "ea4819d2-3487-44fe-9df9-74f8875aefca",
        "claim": "OCR must reach LLM before markdown/DeepSeek text extraction; mixed OCR routing.",
    },
    {
        "source": "local_mem0",
        "id": "e6ade9b4-960c-494b-9d28-d943ca793af6",
        "claim": "Electronic-music map embedding plan uses routed multi-channel vectors.",
    },
]

ROLLOUT_EVIDENCE = [
    {
        "thread_id": "019dffef-dbe1-7122-a198-acf124dddbb8",
        "path": "C:/Users/pc/.codex/memories/rollout_summaries/2026-05-07T00-56-42-RfaE-wechat_93k_full_empty_longrun_resume_and_backlog_recovery.md",
        "claim": "93K full-empty recovery waves and backlog-aware supervisor.",
    },
    {
        "thread_id": "019e0a17-a58f-7523-994a-5bf90b7caa4e",
        "path": "C:/Users/pc/.codex/memories/rollout_summaries/2026-05-09T00-16-22-2D82-93k_watchdog_quality_checkpoints_pause_deepseek_flash_x_arti.md",
        "claim": "93K full extraction watchdog and quality checkpoints.",
    },
    {
        "thread_id": "019e0a18-5feb-76b2-a4d2-530213f05dbd",
        "path": "C:/Users/pc/.codex/memories/rollout_summaries/2026-05-09T00-17-10-DBRH-wechat_93k_gpt_oss_batch800_soft_evidence_match_handoff.md",
        "claim": "GPT-OSS batch800 routing and soft-evidence fix.",
    },
    {
        "thread_id": "019e0a19-7d22-76a3-9bb4-42ace50eabe4",
        "path": "C:/Users/pc/.codex/memories/rollout_summaries/2026-05-09T00-18-23-4Bhi-where_to_rave_fullmap_secondpass_recovery_and_auth_fix.md",
        "claim": "SECOND_PASS/FULL_MAP recovery, auth repair, and Dajiala candidate policy.",
    },
    {
        "thread_id": "019e0a5b-ecac-7060-958c-8a8db234ba89",
        "path": "C:/Users/pc/.codex/memories/rollout_summaries/2026-05-09T01-30-57-kTzP-deepseek_hybrid_93k_tui_handoff_plan.md",
        "claim": "DeepSeek Flash+Pro hybrid plan and calibration.",
    },
    {
        "thread_id": "019e371c-1eb6-7c12-9d9c-00ee4b14ca84",
        "path": "C:/Users/pc/.codex/memories/rollout_summaries/2026-05-17T18-04-10-fnuc-gpu_process_identification_and_task_attribution.md",
        "claim": "Vector sidecar runtime attribution and Qdrant wave evidence.",
    },
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return sum(1 for line in handle if line.strip())


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def dir_exists(name: str) -> bool:
    return (REPORTS / name).exists()


def load_summary(path: str) -> dict[str, Any]:
    return read_json(ROOT / path)


def wave_number(value: str) -> int:
    if value == "next100":
        return 1
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else 0


def scan_dajiala_waves() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    archive_by_wave: dict[str, dict[str, Any]] = {}
    for folder in REPORTS.iterdir():
        if not folder.is_dir():
            continue
        match = re.match(r"dajiala_paid_(?:next100_)?(wave\d+|next100)(?:_balance_retry)?_archive_", folder.name)
        if not match:
            continue
        wave_id = match.group(1)
        status = read_json(folder / "dajiala-repair-status.json")
        items = status.get("items")
        item_counts = Counter()
        if isinstance(items, list):
            item_counts.update(str(item.get("status") or "unknown") for item in items if isinstance(item, dict))
        success_manifest = count_jsonl(folder / "dajiala_success_manifest.jsonl")
        image_manifest = count_jsonl(folder / "dajiala_success_with_images_manifest.jsonl")
        rejected_manifest = count_jsonl(folder / "dajiala_rejected_manifest.jsonl")
        total_items = int(status.get("totalItems") or len(items or []) or success_manifest + rejected_manifest)
        succeeded = int(status.get("succeededCount") or success_manifest or item_counts.get("success") or item_counts.get("succeeded") or 0)
        failed = int(status.get("failedCount") or rejected_manifest or item_counts.get("failed") or 0)
        queued = int(status.get("queuedCount") or item_counts.get("pending") or item_counts.get("queued") or 0)
        running = int(status.get("runningCount") or item_counts.get("running") or 0)
        record = {
            "wave_id": wave_id,
            "archive_dir": folder.name,
            "archive_status": status.get("status") or "missing_status",
            "total_items": total_items,
            "succeeded_count": succeeded,
            "failed_count": failed,
            "queued_count": queued,
            "running_count": running,
            "success_manifest_rows": success_manifest,
            "success_with_images_rows": image_manifest,
            "rejected_manifest_rows": rejected_manifest,
            "started_at": status.get("startedAt") or "",
            "ended_at": status.get("endedAt") or "",
        }
        key = wave_id
        if key in archive_by_wave:
            key = f"{wave_id}:{folder.name}"
        archive_by_wave[key] = record

    for folder in REPORTS.iterdir():
        if not folder.is_dir():
            continue
        match = re.match(r"dajiala_paid_(?:next100_)?(wave\d+|next100)(?:_balance_retry)?_ocr_manifest_", folder.name)
        if not match:
            continue
        wave_id = match.group(1)
        target_key = wave_id if wave_id in archive_by_wave else None
        if target_key is None:
            candidates = [key for key in archive_by_wave if key.startswith(f"{wave_id}:")]
            target_key = candidates[0] if candidates else wave_id
            archive_by_wave.setdefault(target_key, {"wave_id": wave_id})
        archive_by_wave[target_key]["ocr_manifest_dir"] = folder.name
        archive_by_wave[target_key]["ocr_manifest_rows"] = count_jsonl(folder / "recovered_manifest.jsonl")

    for folder in REPORTS.iterdir():
        if not folder.is_dir():
            continue
        match = re.match(r"dajiala_paid_(?:next100_)?(wave\d+|next100)(?:_balance_retry)?_ocr_index_", folder.name)
        if not match:
            continue
        wave_id = match.group(1)
        target_key = wave_id if wave_id in archive_by_wave else None
        if target_key is None:
            candidates = [key for key in archive_by_wave if key.startswith(f"{wave_id}:")]
            target_key = candidates[0] if candidates else wave_id
            archive_by_wave.setdefault(target_key, {"wave_id": wave_id})
        summary = read_json(folder / "ocr_file_index_summary.json")
        archive_by_wave[target_key]["ocr_index_dir"] = folder.name
        archive_by_wave[target_key]["ocr_index_records"] = int(summary.get("record_count") or 0)
        archive_by_wave[target_key]["ocr_index_status"] = summary.get("status") or ""

    waves = sorted(archive_by_wave.values(), key=lambda row: (wave_number(str(row.get("wave_id") or "")), str(row.get("archive_dir") or "")))
    totals = {
        "archive_round_records": len(waves),
        "archive_total_items": sum(int(row.get("total_items") or 0) for row in waves),
        "archive_succeeded_count": sum(int(row.get("succeeded_count") or 0) for row in waves),
        "archive_failed_count": sum(int(row.get("failed_count") or 0) for row in waves),
        "archive_queued_count": sum(int(row.get("queued_count") or 0) for row in waves),
        "archive_running_count": sum(int(row.get("running_count") or 0) for row in waves),
        "success_manifest_rows": sum(int(row.get("success_manifest_rows") or 0) for row in waves),
        "success_with_images_rows": sum(int(row.get("success_with_images_rows") or 0) for row in waves),
        "rejected_manifest_rows": sum(int(row.get("rejected_manifest_rows") or 0) for row in waves),
        "ocr_manifest_rows": sum(int(row.get("ocr_manifest_rows") or 0) for row in waves),
        "ocr_index_records": sum(int(row.get("ocr_index_records") or 0) for row in waves),
    }
    consumed_index = read_json(REPORTS / "dajiala_paid_latest_verified_combined_ocr_index_20260518" / "ocr_file_index_summary.json")
    base_index = read_json(REPORTS / "dajiala_paid_wave01_07_verified_combined_ocr_index_20260518" / "ocr_file_index_summary.json")
    wave01_21_index = read_json(WAVE01_21_INDEX)
    wave09_21_delta = read_json(WAVE09_21_DELTA_SUMMARY)
    wave09_21_stable = read_json(WAVE09_21_STABLE_SUMMARY)
    wave09_21_promotion = read_json(WAVE09_21_PROMOTION_VERIFY)
    unified_stable = read_json(UNIFIED_STABLE_SUMMARY)
    unified_promotion = read_json(UNIFIED_PROMOTION_VERIFY)
    wave09_21_records = sum(
        int(row.get("ocr_index_records") or 0)
        for row in waves
        if 9 <= wave_number(str(row.get("wave_id") or "")) <= 21
    )
    wave09_21_graph_promoted = (
        wave09_21_promotion.get("ok") is True
        and wave09_21_promotion.get("decision") == "graph_production_promotion_verified"
    )
    unified_graph_promoted = (
        unified_promotion.get("ok") is True
        and unified_promotion.get("decision") == "graph_production_promotion_verified"
    )
    totals.update(
        {
            "verified_latest_combined_records": int(consumed_index.get("record_count") or 0),
            "verified_wave01_07_records": int(base_index.get("record_count") or 0),
            "verified_wave01_21_records": int(wave01_21_index.get("record_count") or 0),
            "wave09_21_ocr_index_records": wave09_21_records,
            "wave09_21_probably_unconsumed_records": max(
                0,
                wave09_21_records
                - max(0, int(consumed_index.get("record_count") or 0) - int(base_index.get("record_count") or 0)),
            ),
            "wave09_21_delta_manifest_rows": int(wave09_21_delta.get("delta_rows") or 0),
            "wave09_21_stable_articles": int(wave09_21_stable.get("articles") or 0),
            "wave09_21_graph_promoted": wave09_21_graph_promoted,
            "wave09_21_remaining_after_delta_graph_records": 0 if wave09_21_graph_promoted else wave09_21_records,
            "unified_stable_articles": int(unified_stable.get("articles") or 0),
            "unified_graph_promoted": unified_graph_promoted,
        }
    )
    return waves, totals


def build_lanes() -> list[dict[str, Any]]:
    source = load_summary("reports/production_graph_source_lane_audit_20260518/source_lane_audit.json")
    gap = load_summary("reports/stage7_data_completeness_gap_ledger_20260518/gap_ledger.json")
    prod_state = load_summary(
        "reports/superlongrun_production_state_47k_plus_v6_p1_repair_1397_20260518/superlongrun_production_state.json"
    )
    lanes: list[dict[str, Any]] = []
    for lane in source.get("lanes") or []:
        if isinstance(lane, dict):
            lanes.append(
                {
                    "lane_id": lane.get("lane_id"),
                    "role": lane.get("role"),
                    "current_use": lane.get("current_use"),
                    "counts": lane.get("counts") or lane.get("counts_observed_at_close") or {},
                    "next_gate": lane.get("next_gate") or "",
                    "evidence": lane.get("evidence") or [],
                }
            )
    summary = gap.get("summary") or {}
    lanes.append(
        {
            "lane_id": "current_47k_plus_v6_p1_repair1397_production_marker",
            "role": "current electronic-music graph production marker",
            "current_use": "current graph/vector/consumer base; not full V6+47K+all-paid expansion",
            "counts": {
                "articles": summary.get("current_47k_plus_p1_graph_articles")
                or ((prod_state.get("stage7") or {}).get("articles")),
                "entities": summary.get("current_47k_plus_p1_graph_entities"),
                "events": summary.get("current_47k_plus_p1_graph_events"),
                "p1_repair_articles": summary.get("p1_ocr_markdown_repair_articles_promoted"),
            },
            "evidence": [
                "reports/stable_merge_47k_plus_v6_p1_repair_1397_20260518/stable_merge_summary.json",
                "reports/graph_production_promotion_47k_plus_v6_p1_repair_1397_verify_20260518/promotion_report.json",
            ],
        }
    )
    unified_stable = load_summary(
        "reports/stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/stable_merge_summary.json"
    )
    unified_apply = read_json(UNIFIED_PROMOTION_APPLY)
    unified_verify = read_json(UNIFIED_PROMOTION_VERIFY)
    if unified_stable or unified_verify:
        mutated_counts = unified_apply.get("mutated_counts") if isinstance(unified_apply.get("mutated_counts"), dict) else {}
        lanes.append(
            {
                "lane_id": "current_47340_plus_paid_wave09_21_production_marker",
                "role": "current electronic-music graph production marker after paid OCR wave09-21 delta consumption",
                "current_use": "current graph production marker; vector/consumer alias refresh still follows separately",
                "counts": {
                    "stable_articles": unified_stable.get("articles"),
                    "stable_entities_total": (unified_stable.get("totals") or {}).get("entities"),
                    "stable_events_total": (unified_stable.get("totals") or {}).get("events"),
                    "graph_marker_articles": mutated_counts.get("article"),
                    "graph_marker_entities": mutated_counts.get("entity"),
                    "graph_marker_events": mutated_counts.get("event"),
                    "promotion_verified": unified_verify.get("ok") is True,
                },
                "evidence": [
                    "reports/stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/stable_merge_summary.json",
                    "reports/graph_production_promotion_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_verify_20260518/promotion_report.json",
                ],
            }
        )
    return lanes


def build_decisions(dajiala_totals: dict[str, Any]) -> list[dict[str, Any]]:
    wave09_21_consumed = bool(dajiala_totals.get("wave09_21_graph_promoted"))
    unified_promoted = bool(dajiala_totals.get("unified_graph_promoted"))
    decisions = [
        {
            "id": "USER_MEMORY_CONFIRMED",
            "decision": "There are more than three artifact rounds; the graph lane must reconcile V6, Full-Map 47K, Dajiala/OCR repair waves, 93K recovery/QA, and vector sidecars separately.",
            "evidence": ["local mem0 search", "rollout summaries", "Stage7 reports directory"],
        },
        {
            "id": "UNFINISHED_AUDIT_STALE_FOR_DAJIALA_ROUNDS",
            "decision": "The latest unfinished audit that stops at wave07 is stale for Dajiala round inventory.",
            "evidence": [
                "reports/dajiala_paid_wave09_ocr_index_20260518 through reports/dajiala_paid_wave21_ocr_index_20260518 exist",
                f"wave09_21_ocr_index_records={dajiala_totals.get('wave09_21_ocr_index_records')}",
                f"wave09_21_probably_unconsumed_records={dajiala_totals.get('wave09_21_probably_unconsumed_records')}",
                f"wave09_21_remaining_after_delta_graph_records={dajiala_totals.get('wave09_21_remaining_after_delta_graph_records')}",
            ],
        },
        {
            "id": "NO_DUPLICATE_PAID_RETRY",
            "decision": "Do not start another paid Dajiala runner from this report; consume already verified local OCR indexes first.",
            "evidence": [
                "wave23, wave24, wave26 had zero successes",
                "wave25 status is stale/running with queued rows and no success manifests; classify before retry",
            ],
        },
        {
            "id": "NEXT_GRAPH_ACTION",
            "decision": "Next safe graph action is vector/consumer staging refresh for the 47,340-row marker; do not treat weekly/miniprogram as this thread's completion target.",
            "evidence": [
                f"wave09_21_graph_promoted={wave09_21_consumed}",
                f"unified_graph_promoted={unified_promoted}",
                f"unified_stable_articles={dajiala_totals.get('unified_stable_articles')}",
            ],
        },
    ]
    if wave09_21_consumed:
        decisions.append(
            {
                "id": "WAVE09_21_CONSUMED_IN_GRAPH",
                "decision": "The recovered wave09-21 paid OCR evidence has passed OCR->Markdown->Flash, stable materialization, and graph production verification.",
                "evidence": [
                    "reports/ocr_markdown_flash_wave09_21_delta375_stable_extract_20260518/stable_materialize_summary.json",
                    "reports/graph_production_promotion_ocr_markdown_flash_wave09_21_delta375_verify_20260518/promotion_report.json",
                ],
            }
        )
    return decisions


def build_report(out_dir: Path) -> dict[str, Any]:
    waves, dajiala_totals = scan_dajiala_waves()
    lanes = build_lanes()
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "graph_artifact_rounds_reconciled_more_than_three_rounds_confirmed",
        "scope": "China underground electronic music graph only; weekly/miniprogram is treated as downstream consumer and excluded from completion target.",
        "memory_evidence": MEMORY_EVIDENCE,
        "rollout_evidence": ROLLOUT_EVIDENCE,
        "lane_inventory": lanes,
        "dajiala_rounds": waves,
        "dajiala_totals": dajiala_totals,
        "decisions": build_decisions(dajiala_totals),
        "next_order": [
            "Refresh vector/consumer staging for the unified 47,340-row electronic-music graph marker if downstream semantic search must be current.",
            "Keep remaining V6 image-bucket P2/P3/P4 and external user roots as validation-only backlog until source evidence is verified.",
            "Do not run more Dajiala paid waves until wave25 stale status is classified and a fresh ROI/downstream-consumption packet exists.",
        ],
        "safety": {
            "reports_only": True,
            "paid_api_called": False,
            "llm_called": False,
            "ocr_execution": False,
            "qdrant_write": False,
            "neo4j_write": False,
            "mem0_write": False,
            "d_scan": False,
            "secrets_read_or_printed": False,
            "used_9router": False,
        },
    }
    write_json(out_dir / "graph_artifact_rounds_reconciliation.json", report)
    write_markdown(out_dir / "graph_artifact_rounds_reconciliation.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    totals = report["dajiala_totals"]
    lines = [
        "# Stage7 Graph Artifact Rounds Reconciliation",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- scope: {report['scope']}",
        "",
        "## Key Counts",
        "",
        f"- Dajiala archive round records: `{totals['archive_round_records']}`",
        f"- Dajiala success_manifest_rows: `{totals['success_manifest_rows']}`",
        f"- Dajiala success_with_images_rows: `{totals['success_with_images_rows']}`",
        f"- Dajiala OCR index records across discovered per-wave indexes: `{totals['ocr_index_records']}`",
        f"- Verified latest combined OCR records before reconciliation: `{totals['verified_latest_combined_records']}`",
        f"- Verified wave01-07 records: `{totals['verified_wave01_07_records']}`",
        f"- Verified wave01-21 records after reconciliation: `{totals['verified_wave01_21_records']}`",
        f"- Wave09-21 OCR index records not consumed by stale latest combined index: `{totals['wave09_21_probably_unconsumed_records']}`",
        f"- Wave09-21 records remaining after delta graph promotion: `{totals['wave09_21_remaining_after_delta_graph_records']}`",
        f"- Unified stable articles: `{totals['unified_stable_articles']}`",
        f"- Unified graph promotion verified: `{totals['unified_graph_promoted']}`",
        "",
        "## Decisions",
        "",
    ]
    for item in report["decisions"]:
        lines.append(f"- `{item['id']}`: {item['decision']}")
    lines.extend(["", "## Next Order", ""])
    for idx, item in enumerate(report["next_order"], start=1):
        lines.append(f"{idx}. {item}")
    lines.extend(["", "## Safety", "", "- Report-only; no paid API, LLM, OCR execution, graph/vector/mem0 write, D: scan, or 9router use."])
    write_text(path, "\n".join(lines) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_report(args.out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "archive_round_records": report["dajiala_totals"]["archive_round_records"],
                "wave09_21_probably_unconsumed_records": report["dajiala_totals"][
                    "wave09_21_probably_unconsumed_records"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
