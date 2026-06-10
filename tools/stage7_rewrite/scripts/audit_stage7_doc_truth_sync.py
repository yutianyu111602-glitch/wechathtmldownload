#!/usr/bin/env python3
"""Audit Stage7 Markdown docs against the current atlas graph/vector truth.

This is a documentation-only audit. It reads Markdown files under this
Stage7 workspace, classifies lifecycle buckets, and records old vector wording
that must not steer future runs. It does not call models, touch DBs, write
Qdrant aliases, scan D:, or read secrets.
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
DEFAULT_OUT_DIR = ROOT / "reports" / "stage7_doc_truth_sync_20260518"
SCHEMA_VERSION = "stage7_doc_truth_sync.v2"

CURRENT_AUTHORITY = {
    "STAGE7_GRAPH_CURRENT_AUTHORITY_20260518.md",
    "STAGE7_SSOT_20260514.md",
    "SSOT.md",
    "MASTER_PLAN_20260513.md",
    "STAGE7_FULL_PIPELINE_INTEGRATION_PLAN_20260518.md",
    "STAGE7_KEY_FINDINGS_AND_FIXES_20260518.md",
    "STAGE7_ALL_PLANS_LANDED_20260518.md",
    "LONGRUN_STATE.md",
    "NETWORK_ENTITY_SEARCH_METHOD_AUDIT_20260517.md",
    "reports/embedding_model_matrix_eval_20260517/PIPELINE_INTEGRATION_REPLACEMENT_PLAN_2026-05-17.md",
    "reports/embedding_model_matrix_eval_20260517/EMBEDDING_MODEL_SELECTION_REPORT_2026-05-17.md",
    "reports/embedding_model_matrix_eval_20260517/FULL_AUDIT_TEST_REPORT_2026-05-17.md",
}

ACTIVE_EVIDENCE_PREFIXES = (
    "reports/stage7_doc_truth_sync_20260518/",
    "reports/stage7_graph_artifact_rounds_reconciliation_20260518/",
    "reports/stable_merge_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/",
    "reports/graph_production_promotion_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_",
    "reports/language_field_vector_jobs_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/",
    "reports/vector_role_artifacts_47k_plus_v6_p1_repair_1397_plus_paid_wave09_21_delta375_20260518/",
    "reports/embedding_model_matrix_eval_20260517/",
)

STALE_PATTERNS = {
    "qwen3_only_execution": re.compile(r"Qwen3[-/A-Za-z0-9_. ]*(?:vectors?|向量|Embedding).*?(?:当前|执行口径|use now|only|唯一|主)", re.I),
    "qwen3_as_default_main": re.compile(r"(?:当前向量执行口径|Use now).*Qwen3|local RTX 4090 only: Qwen3", re.I),
    "old_max_dim_or_2560": re.compile(r"(?<!\d)2560(?:-d|d|维|\b)|最大维度|native 2560", re.I),
    "old_weekly_as_goal": re.compile(
        r"(weekly mini-program|小程序|weekly-api|published items)[^.\n]{0,160}(?:current truth|当前|目标|完成|proof|ready|production|作为.*完成)",
        re.I,
    ),
}

STALE_SUPPRESSIONS = {
    "qwen3_only_execution": re.compile(
        r"compatibility/current-control|current-control evidence|not the next|not current|不再|仅保留|仅作|历史|降级|旧文档|old Qwen3|对照",
        re.I,
    ),
    "qwen3_as_default_main": re.compile(
        r"compatibility/current-control|current-control evidence|not the next|not current|不再|仅保留|仅作|历史|降级|旧文档|old Qwen3|对照",
        re.I,
    ),
    "old_max_dim_or_2560": re.compile(
        r"canary|test|smoke|benchmark|no 2560-d advantage|native 2560-d vector canary|历史|old|reference|参考|验证|测试",
        re.I,
    ),
    "old_weekly_as_goal": re.compile(
        r"downstream|historical|consumer|history|not .*goal|not .*target|not .*completion|不是.*目标|不是.*完成|历史|下游|消费端|explicitly routed|unless explicitly routed|served only|drift|repaired|source-grounded",
        re.I,
    ),
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def rel_path(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def iter_markdown(root: Path) -> list[Path]:
    ignored_parts = {".git", "node_modules", ".venv", "__pycache__"}
    files: list[Path] = []
    for path in root.rglob("*.md"):
        if any(part in ignored_parts for part in path.parts):
            continue
        files.append(path)
    return sorted(files, key=lambda item: rel_path(item).lower())


def classify(path: Path) -> str:
    rel = rel_path(path)
    name = path.name
    if rel in CURRENT_AUTHORITY or name in CURRENT_AUTHORITY:
        return "CURRENT_AUTHORITY"
    if rel.startswith(ACTIVE_EVIDENCE_PREFIXES):
        return "ACTIVE_EVIDENCE"
    if rel.startswith("docs_archive/"):
        return "HISTORICAL_EVIDENCE"
    if rel.startswith("reports/"):
        return "VERIFY_BEFORE_USE"
    if rel.startswith("prds/"):
        return "REFERENCE_PRD"
    if re.search(r"(HANDOFF|PLAN|REPORT|TICK|WATCHDOG)", name, re.I):
        return "HISTORICAL_EVIDENCE"
    return "REFERENCE"


def match_line(text: str, start: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end == -1:
        line_end = len(text)
    return text[line_start:line_end]


def should_ignore_stale_hit(hit_type: str, line: str, context: str) -> bool:
    if re.match(r"\s*-?\s*>?\s*2026-\d{2}-\d{2}", line):
        return True
    suppressor = STALE_SUPPRESSIONS.get(hit_type)
    return bool(suppressor and suppressor.search(f"{line} {context}"))


def scan_file(path: Path) -> dict[str, Any]:
    rel = rel_path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    stale_hits: list[dict[str, Any]] = []
    for hit_type, pattern in STALE_PATTERNS.items():
        for match in pattern.finditer(text):
            line = match_line(text, match.start())
            context = text[max(0, match.start() - 180) : min(len(text), match.end() + 180)].replace("\n", " ")
            if should_ignore_stale_hit(hit_type, line, context):
                continue
            line_no = text.count("\n", 0, match.start()) + 1
            snippet = text[match.start() : min(len(text), match.end() + 140)].replace("\n", " ")
            stale_hits.append({"type": hit_type, "line": line_no, "snippet": snippet[:240]})
            break
    return {
        "path": rel,
        "bytes": path.stat().st_size,
        "lifecycle": classify(path),
        "stale_hits": stale_hits,
    }


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


def build_report(out_dir: Path) -> dict[str, Any]:
    rows = [scan_file(path) for path in iter_markdown(ROOT)]
    lifecycle_counts = Counter(row["lifecycle"] for row in rows)
    stale_counts = Counter()
    stale_docs: list[dict[str, Any]] = []
    current_authority_stale_docs: list[dict[str, Any]] = []
    for row in rows:
        if row["stale_hits"]:
            stale_docs.append(row)
            for hit in row["stale_hits"]:
                stale_counts[hit["type"]] += 1
            if row["lifecycle"] == "CURRENT_AUTHORITY":
                current_authority_stale_docs.append(row)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "stage7_docs_scanned_and_current_graph_vector_truth_synced",
        "scope": "Stage7-stage docs only. Stage7 is one large production stage inside the whole electronic-music atlas pipeline; mini-program/weekly docs are downstream or historical unless explicitly routed.",
        "markdown_files_scanned": len(rows),
        "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
        "stale_pattern_counts": dict(sorted(stale_counts.items())),
        "current_authority_stale_docs": current_authority_stale_docs,
        "stale_docs_sample": stale_docs[:80],
        "latest_truth": {
            "graph_marker_articles": 47340,
            "graph_marker_entities": 316245,
            "graph_marker_events": 59640,
            "stable_merge_articles": 47340,
            "verified_wave01_21_paid_ocr_records": 807,
            "wave09_21_delta_records_consumed": 375,
            "language_vector_roles_1024d": {
                "multilingual_baseline": "BAAI/bge-m3",
                "snowflake_canary": "Snowflake/snowflake-arctic-embed-l-v2.0",
                "english_sidecar": "BAAI/bge-large-en-v1.5",
                "ocr_baseline": "BAAI/bge-m3",
            },
            "qwen3_status": "compatibility/current-control evidence only; do not use old Qwen3-only docs as the next full-vector plan",
            "whole_pipeline_map": "../../docs/ELECTRONIC_MUSIC_GRAPH_PIPELINE_STAGE_MAP_20260518.md",
        },
        "safety": {
            "markdown_read_only_scan": True,
            "d_scan_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "secret_paths_read": False,
        },
    }
    write_json(out_dir / "stage7_doc_truth_sync.json", report)
    write_markdown(out_dir / "stage7_doc_truth_sync.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Document Truth Sync",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- markdown_files_scanned: `{report['markdown_files_scanned']}`",
        f"- scope: {report['scope']}",
        "",
        "## Current Truth",
        "",
        "- Main thread target: China underground/electronic music graph, not weekly/miniprogram.",
        "- Stage7 is one large production stage inside the whole pipeline, not the whole pipeline itself.",
        "- DeepSeek is text-only: image/GIF evidence must be OCRed, merged into Markdown/MarkItDown, then sent to Flash/Pro text extraction.",
        "- Text embedding dimensions stay 1024.",
        "- Do not mix vector spaces even when dimensions match.",
        "- Latest vector route is language/field isolated: BGE-M3 multilingual/OCR, Snowflake canary, and BGE English sidecar.",
        "- Existing Qwen3-4B 1024 artifacts and aliases are compatibility/current-control evidence, not the next default full rebuild plan.",
        "",
        "## Counts",
        "",
        f"- Lifecycle counts: `{json.dumps(report['lifecycle_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- Stale pattern counts: `{json.dumps(report['stale_pattern_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Current Authority Stale Hits",
        "",
    ]
    if not report["current_authority_stale_docs"]:
        lines.append("- None detected.")
    else:
        for row in report["current_authority_stale_docs"]:
            hit_types = ", ".join(sorted({hit["type"] for hit in row["stale_hits"]}))
            lines.append(f"- `{row['path']}`: {hit_types}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Markdown/content scan only. No model call, paid API, graph/vector write, D: scan, or secret-path read.",
        ]
    )
    write_text(path, "\n".join(lines) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.out_dir if args.out_dir.is_absolute() else ROOT / args.out_dir
    report = build_report(out_dir)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "markdown_files_scanned": report["markdown_files_scanned"],
                "current_authority_stale_docs": len(report["current_authority_stale_docs"]),
                "report": str(out_dir / "stage7_doc_truth_sync.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
