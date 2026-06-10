#!/usr/bin/env python3
"""Audit whole wechathtmldownload Markdown docs for atlas/graph truth drift.

This is a documentation-only scan. It covers the project root, not only
tools/stage7_rewrite, while skipping dependency/runtime noise and secret-like
paths. It does not call models, scan D: roots, use paid APIs, or write graph /
vector databases.
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


STAGE7_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUT_DIR = PROJECT_ROOT / "reports" / "wechat_graph_pipeline_doc_truth_sync_20260518"
SCHEMA_VERSION = "wechat_graph_pipeline_doc_truth_sync.v2"

CURRENT_AUTHORITY = {
    "docs/ELECTRONIC_MUSIC_GRAPH_CURRENT_AUTHORITY_20260518.md",
    "docs/ELECTRONIC_MUSIC_GRAPH_PIPELINE_STAGE_MAP_20260518.md",
    "AGENTS.md",
    "docs/current-runtime.md",
    "docs/DOCUMENTATION_INDEX.md",
    "tools/stage7_rewrite/STAGE7_GRAPH_CURRENT_AUTHORITY_20260518.md",
    "tools/stage7_rewrite/STAGE7_SSOT_20260514.md",
    "tools/stage7_rewrite/SSOT.md",
    "tools/stage7_rewrite/LONGRUN_STATE.md",
    "tools/stage7_rewrite/NETWORK_ENTITY_SEARCH_METHOD_AUDIT_20260517.md",
    "tools/stage7_rewrite/OPENCLI_EXTERNAL_EVIDENCE_PLAN_20260516.md",
}

ACTIVE_EVIDENCE_PREFIXES = (
    "reports/",
    "tools/stage7_rewrite/reports/",
    "tools/stage7_rewrite/prds/",
)

STALE_PATTERNS = {
    "qwen3_only_plan": re.compile(r"(Qwen3[^.\n]{0,120}(?:only|唯一|当前向量执行口径|默认|主线)|local RTX 4090 Qwen3 vectors)", re.I),
    "weekly_as_graph_goal": re.compile(r"(weekly mini-program|小程序|weekly-api|CloudRun|published items)[^.\n]{0,120}(?:current truth|当前|目标|完成)", re.I),
    "old_graph_marker": re.compile(r"(45,568|45568|46,965|46965)[^.\n]{0,120}(?:current|当前|latest|最新|graph|图谱)", re.I),
    "old_max_dim": re.compile(r"(?<!\d)(2560(?:-d|d|维|\b)|最大维度|native 2560)", re.I),
    "ocr_after_llm": re.compile(r"(DeepSeek|LLM)[^.\n]{0,120}(?:before|先于|之后).*?(OCR|poster_ocr)|OCR[^.\n]{0,80}(?:after|LLM之后)", re.I),
}

STALE_SUPPRESSIONS = {
    "qwen3_only_plan": re.compile(
        r"compatibility/current-control|current-control evidence|old current-control|old Qwen3|do not use|not the next|not current|not .*full-vector plan|equivalent hit|text_sha1|conservative equivalent-hit|不再|仅保留|仅作|历史|降级|旧文档|evidence, not|对照",
        re.I,
    ),
    "weekly_as_graph_goal": re.compile(
        r"downstream|historical|consumer|history|not .*goal|not .*target|not .*completion|不是.*目标|不是.*完成|历史|下游|消费端|explicitly routed|unless explicitly routed",
        re.I,
    ),
    "old_graph_marker": re.compile(
        r"historical/current-control|historical|current-control|unless a current authority|valid .*evidence only|not .*latest|not the final atlas|consumer lane|不代表|历史|旧|对照",
        re.I,
    ),
    "old_max_dim": re.compile(
        r"canary|test|smoke|benchmark|no 2560-d advantage|native 2560-d vector canary|历史|old|reference|参考|验证|测试",
        re.I,
    ),
    "ocr_after_llm": re.compile(
        r"must .*OCR|OCR.*must|必须先.*OCR|OCR.*之前|order is|contract|顺序|当前口径|fixes|after WSL path fix|OCR text rows|llm_input\.md",
        re.I,
    ),
}

SKIP_PARTS = {
    ".git",
    "node_modules",
    ".venv",
    "__pycache__",
    ".pytest_cache",
}

SECRETISH_PART_RE = re.compile(r"(?i)(\.env|cookie|token|secret|password|credential|oauth|key)")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def rel_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def should_skip(path: Path) -> bool:
    parts = set(path.parts)
    if parts.intersection(SKIP_PARTS):
        return True
    return any(SECRETISH_PART_RE.search(part) for part in path.parts)


def iter_markdown(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.md"):
        if should_skip(path):
            continue
        files.append(path)
    return sorted(files, key=lambda item: rel_path(item).lower())


def classify(path: Path) -> str:
    rel = rel_path(path)
    name = path.name
    if rel in CURRENT_AUTHORITY:
        return "CURRENT_AUTHORITY"
    if rel.startswith(ACTIVE_EVIDENCE_PREFIXES):
        return "ACTIVE_EVIDENCE"
    if "/docs_archive/" in f"/{rel}/":
        return "HISTORICAL_EVIDENCE"
    if re.search(r"(HANDOFF|PLAN|REPORT|WATCHER|TICK|RUNBOOK)", name, re.I):
        return "HISTORICAL_EVIDENCE"
    if rel.startswith("docs/"):
        return "REFERENCE"
    return "VERIFY_BEFORE_USE"


def scan_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = rel_path(path)
    total_lines = text.count("\n") + 1
    stale_hits: list[dict[str, Any]] = []
    for hit_type, pattern in STALE_PATTERNS.items():
        for match in pattern.finditer(text):
            line_start = text.rfind("\n", 0, match.start()) + 1
            line_end = text.find("\n", match.start())
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end]
            context = text[max(0, match.start() - 180) : min(len(text), match.end() + 180)]
            if re.match(r"\s*-?\s*>?\s*2026-\d{2}-\d{2}", line):
                continue
            suppressor = STALE_SUPPRESSIONS.get(hit_type)
            if suppressor and suppressor.search(f"{line} {context}"):
                continue
            line_no = text.count("\n", 0, match.start()) + 1
            if rel.endswith("LONGRUN_STATE.md") and 300 < line_no < max(301, total_lines - 140):
                continue
            snippet = text[match.start() : min(len(text), match.end() + 160)]
            stale_hits.append(
                {
                    "type": hit_type,
                    "line": line_no,
                    "snippet": " ".join(snippet.split())[:260],
                }
            )
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
    rows = [scan_file(path) for path in iter_markdown(PROJECT_ROOT)]
    lifecycle_counts = Counter(row["lifecycle"] for row in rows)
    stale_counts = Counter()
    current_authority_stale_docs: list[dict[str, Any]] = []
    stale_docs: list[dict[str, Any]] = []
    for row in rows:
        if not row["stale_hits"]:
            continue
        stale_docs.append(row)
        for hit in row["stale_hits"]:
            stale_counts[hit["type"]] += 1
        if row["lifecycle"] == "CURRENT_AUTHORITY":
            current_authority_stale_docs.append(row)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "wechat_graph_pipeline_docs_scanned_current_authority_written",
        "project_root": str(PROJECT_ROOT),
        "stage7_root": str(STAGE7_ROOT),
        "markdown_files_scanned": len(rows),
        "lifecycle_counts": dict(sorted(lifecycle_counts.items())),
        "stale_pattern_counts": dict(sorted(stale_counts.items())),
        "current_authority_stale_docs": current_authority_stale_docs,
        "stale_docs_sample": stale_docs[:120],
        "current_truth": {
            "thread_scope": "China underground/electronic music graph",
            "stage7_scope": "one large production stage inside the whole pipeline",
            "weekly_miniprogram_status": "downstream/historical consumer evidence unless explicitly requested",
            "latest_graph_articles": 47340,
            "latest_graph_entities": 316245,
            "latest_graph_events": 59640,
            "vector_dim": 1024,
            "vector_roles": {
                "multilingual_baseline": "BAAI/bge-m3",
                "ocr_baseline": "BAAI/bge-m3",
                "snowflake_canary": "Snowflake/snowflake-arctic-embed-l-v2.0",
                "english_sidecar": "BAAI/bge-large-en-v1.5",
            },
            "qwen3_status": "current-control/compatibility evidence only; old Qwen3-only docs are not the next full-vector plan",
            "deepseek_status": "text-only; OCR/Markdown must precede Flash/Pro extraction for image/GIF evidence",
            "network_evidence": "HTTP fast evidence -> OpenCLI -> Maigret -> Lightpanda/Camofox -> Scrapling adapters -> normalized evidence -> review queue",
        },
        "safety": {
            "docs_only": True,
            "d_root_scan_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "secret_like_paths_skipped": True,
        },
    }
    write_json(out_dir / "wechat_graph_pipeline_doc_truth_sync.json", report)
    write_markdown(out_dir / "wechat_graph_pipeline_doc_truth_sync.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# WeChat Graph Pipeline Document Truth Sync",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- markdown_files_scanned: `{report['markdown_files_scanned']}`",
        f"- project_root: `{report['project_root']}`",
        "",
        "## Current Authority",
        "",
        "- Thread scope: China underground/electronic music graph.",
        "- Weekly/miniprogram docs are downstream or historical consumer evidence unless explicitly routed.",
        "- Latest graph marker: 47,340 articles, 316,245 graph entities, 59,640 graph events.",
        "- Vector route: 1024-d model-space isolation with BGE-M3 multilingual/OCR, Snowflake canary, and BGE-large-en English sidecar.",
        "- Qwen3 1024 remains old current-control/compatibility evidence, not the next default full-vector plan.",
        "- DeepSeek is text-only; image/GIF evidence must be OCRed into Markdown before Flash/Pro.",
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
            "- Documentation scan only. No model call, paid API, D: root scan, Qdrant/Neo4j write, or secret-like path read.",
        ]
    )
    write_text(path, "\n".join(lines) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.out_dir if args.out_dir.is_absolute() else PROJECT_ROOT / args.out_dir
    report = build_report(out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "markdown_files_scanned": report["markdown_files_scanned"],
                "current_authority_stale_docs": len(report["current_authority_stale_docs"]),
                "report": str(out_dir / "wechat_graph_pipeline_doc_truth_sync.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
