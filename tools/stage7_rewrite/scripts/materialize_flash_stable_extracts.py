#!/usr/bin/env python3
"""Materialize Stage7 Flash raw_content rows into a stable article JSONL.

Reads only Flash report JSONL files already under C: reports. It does not
read article source archives, call APIs, build vectors, or write databases.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import sys

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent
if str(STAGE7_ROOT) not in sys.path:
    sys.path.insert(0, str(STAGE7_ROOT))

from stage7.json_repair import parse_and_repair_json  # noqa: E402
from stage7.sanitize import sanitize_article_level, sanitize_extract_limits  # noqa: E402
from stage7.schema_normalize import normalize_extract_schema  # noqa: E402


FACT_KEYS = ("entities", "events", "relations", "claims")
LIST_KEYS = FACT_KEYS + ("topics", "keywords", "ocr_evidence")


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            yield line_no, json.loads(line)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_score_routes(path: Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    routes: dict[str, dict[str, Any]] = {}
    for _line_no, row in read_jsonl(path):
        uid = str(row.get("article_uid") or "")
        if uid:
            routes[uid] = {
                "routing": row.get("routing") or {},
                "metrics": row.get("metrics") or {},
            }
    return routes


def merge_lists(target: dict[str, Any], extract: dict[str, Any]) -> None:
    for key in LIST_KEYS:
        value = extract.get(key)
        if isinstance(value, list):
            target.setdefault(key, []).extend(item for item in value if isinstance(item, dict) or isinstance(item, str))


def materialize_row(row: dict[str, Any], *, route: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, int]]:
    article: dict[str, Any] = {
        "schema_version": "stage7_flash_stable_article.v1",
        "article_uid": str(row.get("article_uid") or ""),
        "article_id": str(row.get("article_id") or ""),
        "sample_id": str(row.get("sample_id") or ""),
        "source_account": str(row.get("source_account") or ""),
        "title": str(row.get("title") or ""),
        "quality_grade": str(row.get("quality_grade") or ""),
        "input_chars": int(row.get("input_chars") or 0),
        "local_image_count": int(row.get("local_image_count") or 0),
        "llm_input_path": str(row.get("llm_input_path") or ""),
        "meta_path": str(row.get("meta_path") or ""),
        "entities": [],
        "events": [],
        "relations": [],
        "claims": [],
        "topics": [],
        "keywords": [],
        "ocr_evidence": [],
    }
    stats = {
        "chunks_seen": 0,
        "chunks_api_ok": 0,
        "chunks_parse_ok": 0,
        "chunks_raw_parse_ok": 0,
        "chunks_raw_parse_failed": 0,
        "chunks_sanitized": 0,
        "raw_content_missing": 0,
    }
    sanitize_totals: dict[str, int] = {}
    for chunk in row.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        stats["chunks_seen"] += 1
        if chunk.get("api_ok"):
            stats["chunks_api_ok"] += 1
        if chunk.get("parse_ok"):
            stats["chunks_parse_ok"] += 1
        raw = str(chunk.get("raw_content") or "")
        if not raw:
            stats["raw_content_missing"] += 1
            continue
        parsed = parse_and_repair_json(raw)
        if not parsed.ok or not isinstance(parsed.value, dict):
            stats["chunks_raw_parse_failed"] += 1
            continue
        stats["chunks_raw_parse_ok"] += 1
        normalized, _norm_stats = normalize_extract_schema(parsed.value)
        if not isinstance(normalized, dict):
            stats["chunks_raw_parse_failed"] += 1
            continue
        sanitized, sanitize_stats = sanitize_extract_limits(normalized, source_text=None)
        if any(sanitize_stats.values()):
            stats["chunks_sanitized"] += 1
            for key, value in sanitize_stats.items():
                if value:
                    sanitize_totals[key] = sanitize_totals.get(key, 0) + int(value)
        merge_lists(article, sanitized)

    article_sanitized, article_stats = sanitize_article_level(article, source_text=None)
    article_sanitized["quality"] = {
        "source": "flash_raw_content_materialized_c_only",
        "materialized_at": datetime.now().isoformat(timespec="seconds"),
        "source_revalidated": False,
        "source_revalidation_reason": "C-only postprocess; did not read D:/mnt/d llm_input files",
        "flash_chunk_count": int(row.get("chunk_count") or stats["chunks_seen"]),
        "flash_ok_chunks": int(row.get("ok_chunks") or 0),
        "flash_parse_ok_chunks": int(row.get("parse_ok_chunks") or 0),
        "flash_schema_ok_chunks": int(row.get("schema_ok_chunks") or 0),
        "materialize_stats": stats,
        "sanitize_stats": sanitize_totals,
        "article_sanitize_stats": {k: v for k, v in article_stats.items() if v},
        "scorer_v2": route or {},
    }
    return article_sanitized, stats


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Stable Flash Materialization Summary",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- articles: `{summary['articles']}`",
        f"- chunks_seen: `{summary['chunks_seen']}`",
        f"- chunks_raw_parse_failed: `{summary['chunks_raw_parse_failed']}`",
        f"- entity0_pct: `{summary['entity0_pct']}`",
        f"- event0_pct: `{summary['event0_pct']}`",
        f"- avg_entities_per_article: `{summary['avg_entities_per_article']}`",
        f"- avg_events_per_article: `{summary['avg_events_per_article']}`",
        f"- writes: `{summary['writes']}`",
        "",
        "## Outputs",
    ]
    for key, value in summary["outputs"].items():
        lines.append(f"- {key}: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def materialize(flash_jsonl_paths: list[Path], out_dir: Path, score_jsonl: Path | None = None) -> dict[str, Any]:
    routes = load_score_routes(score_jsonl)
    out_dir.mkdir(parents=True, exist_ok=True)
    articles: list[dict[str, Any]] = []
    manifest: list[dict[str, Any]] = []
    totals = {
        "chunks_seen": 0,
        "chunks_api_ok": 0,
        "chunks_parse_ok": 0,
        "chunks_raw_parse_ok": 0,
        "chunks_raw_parse_failed": 0,
        "raw_content_missing": 0,
    }
    seen: set[str] = set()
    for path in flash_jsonl_paths:
        for line_no, row in read_jsonl(path):
            uid = str(row.get("article_uid") or "")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            article, stats = materialize_row(row, route=routes.get(uid))
            for key in totals:
                totals[key] += int(stats.get(key) or 0)
            article["_source"] = {"flash_jsonl": str(path), "line": line_no}
            articles.append(article)
            manifest.append(
                {
                    "article_uid": uid,
                    "source_account": article.get("source_account"),
                    "title": article.get("title"),
                    "entities": len(article.get("entities") or []),
                    "events": len(article.get("events") or []),
                    "relations": len(article.get("relations") or []),
                    "claims": len(article.get("claims") or []),
                    "routing": ((routes.get(uid) or {}).get("routing") or {}).get("decision", ""),
                }
            )

    articles_path = out_dir / "stable_articles.jsonl"
    manifest_path = out_dir / "stable_articles_manifest.jsonl"
    write_jsonl(articles_path, articles)
    write_jsonl(manifest_path, manifest)
    article_count = len(articles)
    entity0 = sum(1 for item in articles if not item.get("entities"))
    event0 = sum(1 for item in articles if not item.get("events"))
    entities_total = sum(len(item.get("entities") or []) for item in articles)
    events_total = sum(len(item.get("events") or []) for item in articles)
    summary = {
        "schema_version": "stage7_flash_stable_materialize.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_files": [str(path) for path in flash_jsonl_paths],
        "score_jsonl": str(score_jsonl or ""),
        "articles": article_count,
        **totals,
        "entity0_pct": round(entity0 / max(article_count, 1) * 100, 3),
        "event0_pct": round(event0 / max(article_count, 1) * 100, 3),
        "avg_entities_per_article": round(entities_total / max(article_count, 1), 3),
        "avg_events_per_article": round(events_total / max(article_count, 1), 3),
        "writes": "stable JSONL artifacts only; no API/vector/DB/graph/source archive reads",
        "outputs": {
            "stable_articles": str(articles_path),
            "manifest": str(manifest_path),
            "summary_json": str(out_dir / "stable_materialize_summary.json"),
            "summary_md": str(out_dir / "stable_materialize_summary.md"),
        },
    }
    write_json(out_dir / "stable_materialize_summary.json", summary)
    write_summary_md(out_dir / "stable_materialize_summary.md", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flash-jsonl", action="append", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--score-jsonl", default="")
    args = parser.parse_args(argv)
    summary = materialize(
        flash_jsonl_paths=[Path(value) for value in args.flash_jsonl],
        out_dir=Path(args.out_dir),
        score_jsonl=Path(args.score_jsonl) if args.score_jsonl else None,
    )
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
