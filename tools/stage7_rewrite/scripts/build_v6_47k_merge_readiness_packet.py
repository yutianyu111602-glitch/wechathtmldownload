#!/usr/bin/env python3
"""Build a report-only readiness packet for the 47K baseline plus V6 P1 repairs.

This packet does not expand the full V6 81K lane. It only proves that the
current 47K stable baseline can be staged with the verified V6 P1 OCR repair
rows without duplicate add-on rows.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_MERGE_SUMMARY = Path("reports/stable_merge_47k_plus_v6_p1_repair_1397_20260518/stable_merge_summary.json")
DEFAULT_GAP_LEDGER = Path("reports/stage7_data_completeness_gap_ledger_20260518/gap_ledger.json")
DEFAULT_OUT_DIR = Path("reports/v6_47k_merge_readiness_packet_20260518")
SCHEMA_VERSION = "stage7_v6_47k_merge_readiness_packet.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def build_packet(merge: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    lane_counts = merge.get("lane_counts") if isinstance(merge.get("lane_counts"), dict) else {}
    source_counts = merge.get("source_counts") if isinstance(merge.get("source_counts"), dict) else {}
    summary = ledger.get("summary") if isinstance(ledger.get("summary"), dict) else {}
    base_47k_rows = int_value(lane_counts.get("unknown") or merge.get("base_rows"))
    p1_repair_rows = sum(int_value(count) for lane, count in lane_counts.items() if str(lane) != "unknown")
    total_articles = int_value(merge.get("articles"))
    residual_low_quality = int_value(summary.get("p1_low_quality_text_review_rows"))
    residual_ocr_empty = int_value(summary.get("p1_remaining_local_ocr_rerun_rows"))
    paid_recapture = int_value(summary.get("p1_paid_recapture_needed_rows"))
    blockers: list[str] = []
    if base_47k_rows != 45568:
        blockers.append(f"unexpected_base_47k_rows:{base_47k_rows}")
    if p1_repair_rows != int_value(summary.get("p1_ocr_markdown_repair_articles_promoted")):
        blockers.append("p1_repair_rows_do_not_match_gap_ledger")
    if total_articles != base_47k_rows + p1_repair_rows:
        blockers.append("merged_article_total_does_not_equal_base_plus_p1_repairs")
    if int_value(merge.get("missing_uid_rows")):
        blockers.append("missing_article_uid_rows_present")
    if paid_recapture:
        blockers.append("paid_recapture_still_required_for_p1")

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": not blockers,
        "decision": "v6_47k_p1_repair_merge_ready" if not blockers else "v6_47k_p1_repair_merge_blocked",
        "scope": "47k_baseline_plus_verified_v6_p1_ocr_repairs_only",
        "merge_summary": {
            "articles": total_articles,
            "base_47k_rows": base_47k_rows,
            "p1_repair_rows": p1_repair_rows,
            "lane_counts": lane_counts,
            "source_counts": source_counts,
            "duplicate_addon_rows_last_step": int_value(merge.get("duplicate_addon_rows")),
            "missing_uid_rows": int_value(merge.get("missing_uid_rows")),
            "totals": merge.get("totals") or {},
            "stable_articles": ((merge.get("outputs") or {}).get("stable_articles") if isinstance(merge.get("outputs"), dict) else ""),
            "manifest": ((merge.get("outputs") or {}).get("manifest") if isinstance(merge.get("outputs"), dict) else ""),
        },
        "p1_residual": {
            "low_quality_ocr_text_review_rows": residual_low_quality,
            "ocr_empty_rows": residual_ocr_empty,
            "paid_recapture_needed_rows": paid_recapture,
        },
        "blockers": blockers,
        "allowed_next_actions": [
            "use this merged stable JSONL as the next graph/vector staging candidate",
            "keep 99 low-quality OCR text rows out of Flash until reviewed",
            "keep 30 OCR-empty rows out of Flash unless a new local OCR strategy is justified",
        ],
        "forbidden_next_actions": [
            "do_not_treat_full_v6_81k_as_promoted_by_this_packet",
            "do_not_blind_pay_recapture_for_current_p1",
            "do_not_publish_or_alias_switch_from_this_report_only_packet",
        ],
        "safety": {
            "report_only": True,
            "deepseek_api_used": False,
            "paid_api_used": False,
            "ocr_execution": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_publish_executed": False,
            "d_broad_scan_executed": False,
        },
    }


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    merge = packet["merge_summary"]
    residual = packet["p1_residual"]
    lines = [
        "# V6 + 47K Merge Readiness Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- scope: `{packet['scope']}`",
        f"- merged_articles: `{merge['articles']}`",
        f"- base_47k_rows: `{merge['base_47k_rows']}`",
        f"- p1_repair_rows: `{merge['p1_repair_rows']}`",
        f"- p1_low_quality_review_rows: `{residual['low_quality_ocr_text_review_rows']}`",
        f"- p1_ocr_empty_rows: `{residual['ocr_empty_rows']}`",
        f"- p1_paid_recapture_needed_rows: `{residual['paid_recapture_needed_rows']}`",
        f"- stable_articles: `{merge['stable_articles']}`",
        "",
        "## Blockers",
        "",
    ]
    if packet["blockers"]:
        lines.extend(f"- {blocker}" for blocker in packet["blockers"])
    else:
        lines.append("- none")
    lines.extend(["", "## Allowed Next Actions", ""])
    lines.extend(f"- {item}" for item in packet["allowed_next_actions"])
    lines.extend(["", "## Forbidden Next Actions", ""])
    lines.extend(f"- {item}" for item in packet["forbidden_next_actions"])
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merge-summary", type=Path, default=DEFAULT_MERGE_SUMMARY)
    parser.add_argument("--gap-ledger", type=Path, default=DEFAULT_GAP_LEDGER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    packet = build_packet(read_json(args.merge_summary), read_json(args.gap_ledger))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "v6_47k_merge_readiness_packet.json", packet)
    write_markdown(args.out_dir / "v6_47k_merge_readiness_packet.md", packet)
    print(json.dumps({"ok": packet["ok"], "decision": packet["decision"], "out_dir": str(args.out_dir)}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if packet["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
