#!/usr/bin/env python3
"""Fetch and rank GitHub projects relevant to the Stage7 pipeline.

The output is a decision report, not an install script. It maps external
projects to concrete Stage7 lanes and labels each as use/borrow/quarantine/reject.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUT_DIR = Path("reports/open_source_project_research_20260514")

CANDIDATES = {
    "QwenLM/Qwen3-Embedding": {
        "lane": "vector/rerank",
        "decision": "use_now",
        "fit": "already selected for local RTX 4090 embedding and reranker lane",
    },
    "qdrant/qdrant": {
        "lane": "vector_db",
        "decision": "use_now",
        "fit": "current Stage7 promoted aliases already use Qdrant",
    },
    "getzep/graphiti": {
        "lane": "knowledge_graph",
        "decision": "borrow_ideas",
        "fit": "temporal/provenance graph patterns are useful for typed-edge promotion",
    },
    "neo4j-labs/llm-graph-builder": {
        "lane": "knowledge_graph",
        "decision": "borrow_ideas",
        "fit": "Neo4j import, validation, and graph-RAG UI patterns map to Stage7 staging QA",
    },
    "IBM/docling-graph": {
        "lane": "knowledge_graph",
        "decision": "borrow_ideas",
        "fit": "validated object-to-graph export pattern is relevant to typed-edge promotion",
    },
    "PaddlePaddle/PaddleOCR": {
        "lane": "ocr",
        "decision": "use_canary",
        "fit": "best default OCR candidate for poster/image lane on local GPU/CPU",
    },
    "Topdu/OpenOCR": {
        "lane": "ocr",
        "decision": "study_later",
        "fit": "research-grade OCR benchmark; useful if PaddleOCR quality is insufficient",
    },
    "soxoj/maigret": {
        "lane": "social_discovery",
        "decision": "use_now_with_guardrails",
        "fit": "username breadth discovery only; cannot prove identity",
    },
    "jo-inc/camofox-browser": {
        "lane": "social_validation",
        "decision": "use_now",
        "fit": "current local HTTP browser service for dynamic page snapshots and verification",
    },
    "daijro/camoufox": {
        "lane": "browser_engine",
        "decision": "upstream_reference",
        "fit": "engine upstream behind Camofox; do not integrate separately unless service breaks",
    },
    "unclecode/crawl4ai": {
        "lane": "crawler",
        "decision": "borrow_ideas",
        "fit": "LLM-friendly crawl output and markdown extraction patterns may help non-radio public pages",
    },
    "scrapy/scrapy": {
        "lane": "crawler",
        "decision": "study_later",
        "fit": "mature queueing/retry ideas, but JS-heavy radio pages still need Camofox",
    },
    "scdl-org/scdl": {
        "lane": "soundcloud",
        "decision": "quarantine_reference_only",
        "fit": "SoundCloud URL classification ideas only; GPL and downloader semantics are not suitable for direct dependency",
    },
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def fetch_repo(repo: str, timeout: float = 20.0) -> dict[str, Any]:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}",
        headers={"User-Agent": "codex-stage7-open-source-research"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return {
        "repo": repo,
        "html_url": payload.get("html_url"),
        "stars": payload.get("stargazers_count"),
        "forks": payload.get("forks_count"),
        "open_issues": payload.get("open_issues_count"),
        "pushed_at": payload.get("pushed_at"),
        "license": (payload.get("license") or {}).get("spdx_id"),
        "description": payload.get("description") or "",
    }


def collect_candidates() -> list[dict[str, Any]]:
    rows = []
    for repo, meta in CANDIDATES.items():
        try:
            row = fetch_repo(repo)
            row["fetch_ok"] = True
            row["fetch_error"] = ""
        except Exception as exc:  # pragma: no cover - network failure report path
            row = {"repo": repo, "fetch_ok": False, "fetch_error": f"{type(exc).__name__}: {exc}"}
        row.update(meta)
        rows.append(row)
    rows.sort(key=lambda item: (item.get("stars") or 0), reverse=True)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 GitHub Open Source Candidate Research",
        "",
        f"- generated_at: `{report['generated_at']}`",
        "- source: GitHub REST API + current Stage7 SSOT mapping",
        "- rule: high-star does not mean direct adoption; every project must map to a Stage7 lane and guardrail.",
        "",
        "## Decisions",
        "",
        "| repo | stars | lane | decision | license | pushed_at | fit |",
        "|---|---:|---|---|---|---|---|",
    ]
    for row in report["candidates"]:
        url = row.get("html_url") or f"https://github.com/{row['repo']}"
        lines.append(
            f"| [{row['repo']}]({url}) | {row.get('stars') or ''} | {row['lane']} | "
            f"{row['decision']} | {row.get('license') or ''} | {row.get('pushed_at') or ''} | {row['fit']} |"
        )

    lines.extend(
        [
            "",
            "## Stage7 Adoption Plan",
            "",
            "- Keep current stack: Qwen3-Embedding-4B/Reranker-4B, Qdrant aliases, Neo4j staging, Camofox, Maigret.",
            "- Borrow Graphiti temporal/provenance concepts when promoting generic `STAGE7_EDGE(predicate)` into typed edges.",
            "- Use Neo4j LLM Graph Builder and Docling-Graph as design references for graph validation and export UX, not as replacement runtimes.",
            "- Use PaddleOCR as the first OCR canary candidate; keep OpenOCR as a quality fallback if poster OCR underperforms.",
            "- Treat `scdl` as quarantined reference only because downloader semantics and GPL-2.0 are not a fit for the consumer graph pipeline.",
            "- Crawl4AI/Scrapy are study references; dynamic radio/social verification stays on Camofox for now.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(out_dir: Path) -> dict[str, Any]:
    report = {
        "schema_version": "stage7_open_source_research.v1",
        "generated_at": now_iso(),
        "candidates": collect_candidates(),
    }
    write_json(out_dir / "github_open_source_candidates.json", report)
    write_markdown(out_dir / "github_open_source_candidates.md", report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = run(Path(args.out_dir))
    print(json.dumps({"candidates": len(report["candidates"]), "out_dir": str(args.out_dir)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
