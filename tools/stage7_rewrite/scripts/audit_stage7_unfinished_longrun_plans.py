#!/usr/bin/env python3
"""Audit Stage7 docs for unfinished plans and the current final-goal lane.

The script is report-only. It scans Markdown outside reports, reads current
status artifacts, and writes a compact JSON/Markdown audit. It does not touch
paid APIs, graph/vector stores, mem0, production deploys, or D: roots.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT_DIR = Path("reports/full_unfinished_plan_audit_20260517")
SCHEMA_VERSION = "stage7_unfinished_plan_audit.v1"

DOC_EXCLUDE_PARTS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "artifacts",
    "logs",
    "reports",
    "node_modules",
}
UNFINISHED_PATTERNS = [
    "未完成",
    "待执行",
    "待",
    "阻塞",
    "blocked",
    "pending",
    "todo",
    "下一步",
    "next",
    "remaining",
    "not done",
    "requires",
    "仍",
]
FINAL_GOAL_PATTERNS = [
    "终极目标",
    "最终目标",
    "final goal",
    "final vision",
    "地下电子音乐",
    "knowledge graph",
    "知识图谱",
    "100k",
    "100K",
    "93k",
    "93K",
    "图鉴",
]
WEEKLY_BOUNDARY_PATTERNS = [
    "小程序",
    "weekly",
    "CloudBase",
    "badDJ-weekly",
    "不要启动 full93k",
    "consumer",
]

AUTHORITY_FILES = [
    "LONGRUN_STATE.md",
    "MASTER_PLAN_20260513.md",
    "STAGE7_SSOT_20260514.md",
    "STAGE7_BIGSTEP_LONGRUN_PLAN_20260516.md",
    "prds/PROJECT_FINAL_VISION_20260515.md",
    "prds/PRD_MASTER_INDEX_20260515.md",
    "NEXT_STAGE_GATES_20260513.md",
    "STAGE7_CODEX_GOAL_LONGRUN_RUNBOOK_20260515.md",
    "NETWORK_ENTITY_SEARCH_METHOD_AUDIT_20260517.md",
    "COMPLETE_PIPELINE_PLAN_20260511.md",
    "PLAN_100K_V2_20260509.md",
    "docs_archive/WECHAT_MINIPROGRAM_CLOUDBASE_HANDOFF_2026-05-07.md",
    "docs_archive/DEEPSEEK_HYBRID_93K_TUI_HANDOFF_PLAN_2026-05-09.md",
    "docs_archive/FULL_EMPTY_LINK_RECOVERY_PLAN_2026-05-07.md",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def is_report_safe_path(path: Path) -> bool:
    rel_parts = set(path.relative_to(ROOT).parts)
    return not bool(rel_parts & DOC_EXCLUDE_PARTS)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def find_lines(text: str, patterns: list[str], limit: int = 12) -> list[dict[str, Any]]:
    hits: list[dict[str, Any]] = []
    lower_patterns = [item.lower() for item in patterns]
    for index, line in enumerate(text.splitlines(), start=1):
        low = line.lower()
        if any(pattern in low for pattern in lower_patterns):
            stripped = line.strip()
            if stripped:
                hits.append({"line": index, "text": stripped[:500]})
        if len(hits) >= limit:
            break
    return hits


def scan_docs() -> dict[str, Any]:
    docs: list[Path] = []
    for path in ROOT.rglob("*.md"):
        if is_report_safe_path(path):
            docs.append(path)
    docs.sort(key=lambda item: item.as_posix().lower())

    by_dir: Counter[str] = Counter()
    ranked: list[dict[str, Any]] = []
    final_goal_evidence: list[dict[str, Any]] = []
    weekly_boundary_evidence: list[dict[str, Any]] = []

    for path in docs:
        rel = path.relative_to(ROOT).as_posix()
        by_dir[rel.split("/")[0] if "/" in rel else "."] += 1
        text = read_text(path)
        low = text.lower()
        unfinished_score = sum(low.count(pattern.lower()) for pattern in UNFINISHED_PATTERNS)
        final_score = sum(low.count(pattern.lower()) for pattern in FINAL_GOAL_PATTERNS)
        weekly_score = sum(low.count(pattern.lower()) for pattern in WEEKLY_BOUNDARY_PATTERNS)
        if unfinished_score:
            ranked.append(
                {
                    "path": rel,
                    "unfinished_score": unfinished_score,
                    "final_goal_score": final_score,
                    "weekly_boundary_score": weekly_score,
                    "sample_unfinished_lines": find_lines(text, UNFINISHED_PATTERNS, limit=5),
                }
            )
        if rel in AUTHORITY_FILES:
            final_goal_evidence.append(
                {
                    "path": rel,
                    "score": final_score,
                    "lines": find_lines(text, FINAL_GOAL_PATTERNS, limit=8),
                }
            )
            weekly_boundary_evidence.append(
                {
                    "path": rel,
                    "score": weekly_score,
                    "lines": find_lines(text, WEEKLY_BOUNDARY_PATTERNS, limit=6),
                }
            )

    ranked.sort(
        key=lambda item: (item["unfinished_score"], item["final_goal_score"], item["weekly_boundary_score"]),
        reverse=True,
    )
    return {
        "markdown_count": len(docs),
        "markdown_by_dir": dict(sorted(by_dir.items())),
        "ranked_unfinished_docs": ranked[:60],
        "authority_final_goal_evidence": final_goal_evidence,
        "authority_weekly_boundary_evidence": weekly_boundary_evidence,
    }


def current_status() -> dict[str, Any]:
    prd_status = read_json(ROOT / "reports/prd_longrun_status_20260518/prd_longrun_status.json")
    final_readiness = read_json(ROOT / "reports/final_full_pipeline_readiness_20260518/final_full_pipeline_readiness.json")
    weekly_publish = read_json(ROOT / "reports/weekly_full_publish_20260517/weekly_full_publish_status.json")
    wave05 = read_json(ROOT / "reports/dajiala_paid_wave05_archive_20260517/dajiala-repair-status.json")
    wave06 = read_json(ROOT / "reports/dajiala_paid_wave06_archive_20260517/dajiala-repair-status.json")
    wave07 = read_json(ROOT / "reports/dajiala_paid_wave07_archive_20260517/dajiala-repair-status.json")
    combined_latest = read_json(
        ROOT / "reports/dajiala_paid_wave01_07_verified_combined_ocr_index_20260518/ocr_file_index_summary.json"
    )
    wave_queue = ROOT / "reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_prioritized_queue.jsonl"
    used_queue_paths = [
        ROOT / "reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_next100.jsonl",
        ROOT / "reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_next100_wave02.jsonl",
        ROOT / "reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_next100_wave03.jsonl",
        ROOT / "reports/dajiala_paid_prioritized_queue_20260516/dajiala_paid_next100_wave04.jsonl",
        ROOT / "reports/dajiala_paid_wave05_execution_packet_20260517/dajiala_paid_wave05.jsonl",
        ROOT / "reports/dajiala_paid_wave06_execution_packet_20260517/dajiala_paid_wave06.jsonl",
        ROOT / "reports/dajiala_paid_wave07_execution_packet_20260518/dajiala_paid_wave07.jsonl",
    ]
    queue_total = count_jsonl(wave_queue)
    used_counts = {path.relative_to(ROOT).as_posix(): count_jsonl(path) for path in used_queue_paths}
    used_total = sum(used_counts.values())
    prd_rows = prd_status.get("prds") or []
    status_counts: Counter[str] = Counter()
    not_product_complete: list[dict[str, Any]] = []
    blocked_prds: list[str] = []
    for row in prd_rows:
        status = str(row.get("status") or "")
        status_counts[status] += 1
        if "blocked" in status:
            blocked_prds.append(str(row.get("id") or ""))
        if status not in {"complete", "production_complete", "production_ready"}:
            not_product_complete.append(
                {
                    "id": row.get("id"),
                    "title": row.get("title"),
                    "status": status,
                    "production_ready": row.get("production_ready"),
                    "next_safe_action": row.get("next_safe_action"),
                    "blockers": row.get("blockers") or [],
                }
            )
    return {
        "prd_status": {
            "production_ready": prd_status.get("production_ready"),
            "blocked_prds": prd_status.get("blocked_prds")
            or final_readiness.get("blocked_prds")
            or [item for item in blocked_prds if item],
            "status_counts": dict(status_counts),
            "not_product_complete": not_product_complete,
            "known_limitations": prd_status.get("known_limitations") or [],
        },
        "final_readiness": {
            "decision": final_readiness.get("decision"),
            "full_pipeline_run_allowed": final_readiness.get("full_pipeline_run_allowed"),
            "release_ready_gates": final_readiness.get("release_ready_gates") or {},
            "known_limitations": final_readiness.get("known_limitations") or [],
            "non_production_ready_prds": final_readiness.get("non_production_ready_prds") or [],
        },
        "weekly_publish": weekly_publish,
        "dajiala": {
            "wave05_status": wave05.get("status"),
            "wave05_total": wave05.get("totalItems"),
            "wave05_succeeded": wave05.get("succeededCount"),
            "wave05_failed": wave05.get("failedCount"),
            "wave06_status": wave06.get("status"),
            "wave06_total": wave06.get("totalItems"),
            "wave06_succeeded": wave06.get("succeededCount"),
            "wave06_failed": wave06.get("failedCount"),
            "wave07_status": wave07.get("status"),
            "wave07_total": wave07.get("totalItems"),
            "wave07_succeeded": wave07.get("succeededCount"),
            "wave07_failed": wave07.get("failedCount"),
            "latest_consumed_wave": (
                "wave07"
                if wave07.get("status") == "completed"
                else "wave06"
                if wave06.get("status") == "completed"
                else "wave05"
            ),
            "verified_ocr_index_wave": "wave01_07",
            "verified_ocr_records": combined_latest.get("total_records")
            or combined_latest.get("total")
            or combined_latest.get("records")
            or combined_latest.get("record_count"),
            "prioritized_queue_total": queue_total,
            "known_used_queue_total": used_total,
            "known_unconsumed_queue_rows": max(queue_total - used_total, 0),
            "used_counts": used_counts,
        },
    }


def build_decisions(status: dict[str, Any]) -> list[dict[str, Any]]:
    dajiala = status["dajiala"]
    final_readiness = status["final_readiness"]
    weekly = status["weekly_publish"]
    prd_status = status["prd_status"]
    return [
        {
            "id": "FINAL_GOAL",
            "decision": "the final target is the 100k-level local-first China underground electronic music atlas, not only the weekly mini-program lane",
            "evidence": [
                "PROJECT_FINAL_VISION defines WeChat/OCR/radio/social/Dajiala -> Stage7 extracts -> Qdrant/Neo4j -> consumer/RAG/mem0/Hermes",
                "weekly publish status is a consumer artifact with item_count=%s"
                % ((weekly.get("current_release") or {}).get("item_count")),
            ],
        },
        {
            "id": "FULL_RUN_ALLOWED_BUT_NOT_DONE",
            "decision": "current gates allow starting the full pipeline, but many PRDs remain staging/report/canary level rather than product-complete",
            "evidence": [
                "final_readiness=%s full_pipeline_run_allowed=%s"
                % (final_readiness.get("decision"), final_readiness.get("full_pipeline_run_allowed")),
                "non_product_complete_prds=%s" % len(prd_status.get("not_product_complete") or []),
            ],
        },
        {
            "id": "PAID_WAVE_NEXT",
            "decision": "wave07 is consumed and low-ROI; do not rerun wave07, and any wave08 must first pass a fresh ROI/downstream-consumption packet",
            "evidence": [
                "wave05=%s total=%s succeeded=%s failed=%s"
                % (
                    dajiala.get("wave05_status"),
                    dajiala.get("wave05_total"),
                    dajiala.get("wave05_succeeded"),
                    dajiala.get("wave05_failed"),
                ),
                "wave06=%s total=%s succeeded=%s failed=%s"
                % (
                    dajiala.get("wave06_status"),
                    dajiala.get("wave06_total"),
                    dajiala.get("wave06_succeeded"),
                    dajiala.get("wave06_failed"),
                ),
                "wave07=%s total=%s succeeded=%s failed=%s"
                % (
                    dajiala.get("wave07_status"),
                    dajiala.get("wave07_total"),
                    dajiala.get("wave07_succeeded"),
                    dajiala.get("wave07_failed"),
                ),
                "verified_ocr_index=%s records=%s"
                % (dajiala.get("verified_ocr_index_wave"), dajiala.get("verified_ocr_records")),
                "known_unconsumed_queue_rows=%s" % dajiala.get("known_unconsumed_queue_rows"),
            ],
        },
        {
            "id": "WEEKLY_BOUNDARY",
            "decision": "weekly_activity_next_week_pipeline is a downstream consumer lane and must not be treated as the whole Stage7/100k pipeline",
            "evidence": [
                "weekly CloudRun/miniprogram publish can be green while OCR/social/RAG/full recovery remain incomplete",
            ],
        },
    ]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Unfinished Longrun Plan Audit",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- markdown_count: `{report['doc_scan']['markdown_count']}`",
        f"- final_readiness: `{report['current_status']['final_readiness']['decision']}`",
        f"- full_pipeline_run_allowed: `{report['current_status']['final_readiness']['full_pipeline_run_allowed']}`",
        "",
        "## Decisions",
        "",
    ]
    for item in report["decisions"]:
        lines.append(f"### {item['id']}")
        lines.append(f"- decision: {item['decision']}")
        for evidence in item["evidence"]:
            lines.append(f"- evidence: {evidence}")
        lines.append("")
    lines.extend(["## Current Dajiala", ""])
    for key, value in report["current_status"]["dajiala"].items():
        if key != "used_counts":
            lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Not Product-Complete PRDs", ""])
    for item in report["current_status"]["prd_status"]["not_product_complete"][:30]:
        lines.append(
            "- `{id}` {title}: status=`{status}`, production_ready=`{production_ready}`".format(**item)
        )
    lines.extend(["", "## Top Unfinished Docs", ""])
    for item in report["doc_scan"]["ranked_unfinished_docs"][:25]:
        lines.append(f"- `{item['path']}` score=`{item['unfinished_score']}`")
    lines.extend(["", "## Safety", ""])
    for key, value in report["safety"].items():
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report(out_dir: Path) -> dict[str, Any]:
    doc_scan = scan_docs()
    status = current_status()
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "doc_scan": doc_scan,
        "current_status": status,
        "decisions": build_decisions(status),
        "next_execution": {
            "lane": "dajiala_wave08_roi_gate_or_continue_non_paid_downstream",
            "first_wave_size": 100,
            "estimated_wave_cost": "requires_fresh_roi_packet",
            "stop_rules": [
                "stop if amount_not_enough/recharge appears",
                "stop if success rate after this wave is below 0.30",
                "stop if image-bearing assets among successes fall below 0.80",
                "resume only; do not retry failed rows blindly",
                "do not run wave08 only because old audit text says wave07 next",
            ],
        },
        "safety": {
            "paid_api_called": False,
            "d_scan": False,
            "secret_read_or_printed": False,
            "graph_vector_mem0_write": False,
            "publish": False,
            "reports_only": True,
        },
    }
    write_json(out_dir / "unfinished_plan_audit.json", report)
    write_markdown(out_dir / "unfinished_plan_audit.md", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.out_dir
    report = build_report(out_dir)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "markdown_count": report["doc_scan"]["markdown_count"],
                "decision_count": len(report["decisions"]),
                "known_unconsumed_queue_rows": report["current_status"]["dajiala"]["known_unconsumed_queue_rows"],
                "summary": str(out_dir / "unfinished_plan_audit.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
