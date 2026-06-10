#!/usr/bin/env python3
"""Inventory full LLM stable outputs and extract missing atlas delta rows.

This is a local artifact integration step for the China electronic music
atlas. It scans existing stable JSONL artifacts under the Stage7 reports tree,
compares the known full LLM runs against the current atlas stable base, and
materializes only the already-processed rows that are missing from the atlas.

It does not call LLMs, OCR, paid APIs, Qdrant, Neo4j, SQLite, mem0, CloudRun,
or WeChat. It also does not scan D: roots.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_PATH = Path(__file__).resolve()
STAGE7_ROOT = SCRIPT_PATH.parents[1]
PROJECT_ROOT = SCRIPT_PATH.parents[3]
REPORTS = STAGE7_ROOT / "reports"
DEFAULT_OUT_DIR = REPORTS / "atlas_full_llm_inventory_20260520"
SCHEMA_VERSION = "atlas_full_llm_inventory.v1"

CURRENT_STABLE = (
    REPORTS
    / "stable_merge_all_deepseek_127490_plus_oldroute_retry21_20260520"
    / "stable_articles.jsonl"
)
FULLMAP_47K_STABLE = REPORTS / "fullmap_47k_ready_text_authok_20260513_174006" / "stable_extract_v1" / "stable_articles.jsonl"
FULL_V6_STABLE = REPORTS / "full_v6_81417_stable_extract_20260519" / "stable_articles.jsonl"
LEGACY_V30_STABLE = (
    REPORTS
    / "ocr_root_cause_20260515"
    / "corrected_full_stable_extract_v30_deepseek_recovered1217_20260515"
    / "stable_articles.jsonl"
)

UID_RE = re.compile(r'"article_uid"\s*:\s*"([^"]+)"')
FACT_KEYS = ("entities", "events", "relations", "claims")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except Exception:
        return str(path)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
        tmp = Path(handle.name)
    tmp.replace(path)
    return count


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def uid_from_line(line: str) -> str:
    match = UID_RE.search(line)
    return match.group(1) if match else ""


def iter_jsonl_lines(path: Path):
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            if line.strip():
                yield line_no, line


def load_uids(path: Path) -> set[str]:
    uids: set[str] = set()
    for _line_no, line in iter_jsonl_lines(path):
        uid = uid_from_line(line)
        if uid:
            uids.add(uid)
    return uids


def route_of(row: dict[str, Any]) -> tuple[str, str]:
    route = row.get("corrected_route")
    if not isinstance(route, dict):
        return "unknown", "unknown"
    return str(route.get("lane") or "unknown"), str(route.get("coverage_source") or "unknown")


def list_len(row: dict[str, Any], key: str) -> int:
    value = row.get(key)
    return len(value) if isinstance(value, list) else 0


def discover_stable_paths() -> list[Path]:
    paths = sorted(REPORTS.rglob("stable_articles.jsonl"), key=lambda item: str(item).lower())
    return [path for path in paths if path.is_file()]


def load_summary_for_stable(path: Path) -> dict[str, Any]:
    candidates = [
        path.parent / "stable_merge_summary.json",
        path.parent / "stable_materialize_summary.json",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8-sig", errors="replace"))
        except Exception:
            continue
        return data if isinstance(data, dict) else {}
    return {}


def classify_stable(path: Path) -> str:
    text = rel(path).lower()
    if path.resolve() == CURRENT_STABLE.resolve():
        return "current_atlas_base"
    if path.resolve() == FULLMAP_47K_STABLE.resolve():
        return "full_llm_run_1_current_47k"
    if path.resolve() == FULL_V6_STABLE.resolve():
        return "full_llm_run_2_full_v6"
    if path.resolve() == LEGACY_V30_STABLE.resolve():
        return "full_llm_run_3_legacy_v30_missing_delta_source"
    if "corrected_full_stable_extract_v" in text and "ocr_root_cause_20260515" in text:
        return "legacy_v30_subset_or_intermediate"
    if "fullmap_old_route" in text or "dajiala" in text or "wave" in text:
        return "delta_or_repair_stable"
    return "stable_artifact"


def inventory_path(path: Path, current_uids: set[str]) -> tuple[dict[str, Any], set[str]]:
    summary = load_summary_for_stable(path)
    uids: set[str] = set()
    duplicate_uids = 0
    rows = 0
    missing_current = 0
    missing_lane_counts: Counter[str] = Counter()
    missing_source_counts: Counter[str] = Counter()
    missing_totals: Counter[str] = Counter()
    missing_samples: list[dict[str, Any]] = []

    for line_no, line in iter_jsonl_lines(path):
        rows += 1
        uid = uid_from_line(line)
        if not uid:
            continue
        if uid in uids:
            duplicate_uids += 1
            continue
        uids.add(uid)
        if uid in current_uids:
            continue
        missing_current += 1
        row = json.loads(line)
        lane, source = route_of(row)
        missing_lane_counts[lane] += 1
        missing_source_counts[source] += 1
        for key in FACT_KEYS:
            missing_totals[key] += list_len(row, key)
        if len(missing_samples) < 5:
            missing_samples.append(
                {
                    "article_uid": uid,
                    "line_no": line_no,
                    "source_account": row.get("source_account"),
                    "title": row.get("title"),
                    "lane": lane,
                    "coverage_source": source,
                    "entities": list_len(row, "entities"),
                    "events": list_len(row, "events"),
                }
            )

    return (
        {
            "schema_version": f"{SCHEMA_VERSION}.stable_source",
            "path": rel(path),
            "classification": classify_stable(path),
            "rows": rows,
            "unique_article_uids": len(uids),
            "duplicate_uids": duplicate_uids,
            "missing_from_current_atlas": missing_current,
            "missing_lane_counts": dict(sorted(missing_lane_counts.items())),
            "missing_source_counts": dict(sorted(missing_source_counts.items())),
            "missing_fact_totals": dict(sorted(missing_totals.items())),
            "missing_samples": missing_samples,
            "summary_articles": summary.get("articles"),
            "summary_generated_at": summary.get("generated_at"),
            "summary_schema_version": summary.get("schema_version"),
        },
        uids,
    )


def annotated_legacy_delta_rows(legacy_path: Path, current_uids: set[str]):
    for line_no, line in iter_jsonl_lines(legacy_path):
        uid = uid_from_line(line)
        if not uid or uid in current_uids:
            continue
        row = json.loads(line)
        route = row.get("corrected_route")
        route = dict(route) if isinstance(route, dict) else {}
        route.setdefault("source_jsonl", rel(legacy_path))
        route.setdefault("source_line", line_no)
        route["atlas_full_llm_delta"] = "legacy_v30_missing_from_127511"
        row["corrected_route"] = route
        quality = row.get("quality")
        quality = dict(quality) if isinstance(quality, dict) else {}
        quality["atlas_delta_materialized_at"] = now_iso()
        quality["atlas_delta_reason"] = "existing full LLM stable row missing from 127511 atlas base"
        quality["source_revalidated"] = quality.get("source_revalidated", False)
        row["quality"] = quality
        row["_atlas_delta_source"] = {
            "source_stable_articles": rel(legacy_path),
            "source_line": line_no,
            "integration": "full_llm_legacy_v30_missing_delta",
        }
        yield row


def materialize_legacy_delta(out_dir: Path, current_uids: set[str]) -> dict[str, Any]:
    delta_dir = out_dir / "legacy_v30_missing10591_stable_extract_20260520"
    stable_path = delta_dir / "stable_articles.jsonl"
    manifest_path = delta_dir / "stable_articles_manifest.jsonl"
    rows = list(annotated_legacy_delta_rows(LEGACY_V30_STABLE, current_uids))
    totals: Counter[str] = Counter()
    lane_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    manifest_rows: list[dict[str, Any]] = []
    for row in rows:
        lane, source = route_of(row)
        lane_counts[lane] += 1
        source_counts[source] += 1
        for key in FACT_KEYS:
            totals[key] += list_len(row, key)
        manifest_rows.append(
            {
                "article_uid": row.get("article_uid"),
                "source_account": row.get("source_account"),
                "title": row.get("title"),
                "lane": lane,
                "coverage_source": source,
                "entities": list_len(row, "entities"),
                "events": list_len(row, "events"),
                "relations": list_len(row, "relations"),
                "claims": list_len(row, "claims"),
            }
        )
    write_jsonl(stable_path, rows)
    write_jsonl(manifest_path, manifest_rows)
    summary = {
        "schema_version": f"{SCHEMA_VERSION}.legacy_v30_delta",
        "generated_at": now_iso(),
        "source_stable_articles": rel(LEGACY_V30_STABLE),
        "current_atlas_base": rel(CURRENT_STABLE),
        "articles": len(rows),
        "lane_counts": dict(sorted(lane_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "totals": dict(sorted(totals.items())),
        "outputs": {
            "stable_articles": rel(stable_path),
            "manifest": rel(manifest_path),
            "summary_json": rel(delta_dir / "stable_materialize_summary.json"),
            "summary_md": rel(delta_dir / "stable_materialize_summary.md"),
        },
        "writes": "delta stable JSONL artifacts only; no LLM/OCR/API/vector/DB writes",
    }
    write_json(delta_dir / "stable_materialize_summary.json", summary)
    write_text(
        delta_dir / "stable_materialize_summary.md",
        "\n".join(
            [
                "# Legacy V30 Missing Stable Delta",
                "",
                f"- generated_at: `{summary['generated_at']}`",
                f"- source: `{summary['source_stable_articles']}`",
                f"- current_base: `{summary['current_atlas_base']}`",
                f"- articles: `{summary['articles']}`",
                f"- lane_counts: `{summary['lane_counts']}`",
                f"- source_counts: `{summary['source_counts']}`",
                f"- totals: `{summary['totals']}`",
                f"- writes: `{summary['writes']}`",
                "",
            ]
        ),
    )
    return summary


def build_inventory(out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    current_uids = load_uids(CURRENT_STABLE)
    stable_rows: list[dict[str, Any]] = []
    uid_sets: dict[str, set[str]] = {}
    for path in discover_stable_paths():
        row, uids = inventory_path(path, current_uids)
        stable_rows.append(row)
        if path in {FULLMAP_47K_STABLE, FULL_V6_STABLE, LEGACY_V30_STABLE, CURRENT_STABLE}:
            uid_sets[rel(path)] = uids

    legacy_delta = materialize_legacy_delta(out_dir, current_uids)
    required = {
        "current": current_uids,
        "fullmap_47k": uid_sets.get(rel(FULLMAP_47K_STABLE), set()),
        "full_v6_81417": uid_sets.get(rel(FULL_V6_STABLE), set()),
        "legacy_v30": uid_sets.get(rel(LEGACY_V30_STABLE), set()),
    }
    comparisons = {
        "fullmap_47k_missing_from_current": len(required["fullmap_47k"] - current_uids),
        "full_v6_81417_missing_from_current": len(required["full_v6_81417"] - current_uids),
        "legacy_v30_missing_from_current": len(required["legacy_v30"] - current_uids),
        "legacy_v30_missing_from_full_v6": len(required["legacy_v30"] - required["full_v6_81417"]),
        "legacy_v30_missing_from_fullmap_47k": len(required["legacy_v30"] - required["fullmap_47k"]),
    }
    inventory_jsonl = out_dir / "stable_source_inventory.jsonl"
    write_jsonl(inventory_jsonl, stable_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "legacy_v30_missing_delta_ready_for_atlas_integration",
        "current_atlas_base": rel(CURRENT_STABLE),
        "current_atlas_articles": len(current_uids),
        "stable_sources_scanned": len(stable_rows),
        "full_llm_runs": [
            {
                "id": "fullmap_47k_ready_text_authok_20260513_174006",
                "stable_articles": rel(FULLMAP_47K_STABLE),
                "articles": len(required["fullmap_47k"]),
                "missing_from_current_atlas": comparisons["fullmap_47k_missing_from_current"],
                "decision": "already_in_current_atlas",
            },
            {
                "id": "overnight_v6_20260510_111419_full_v6_81417",
                "stable_articles": rel(FULL_V6_STABLE),
                "articles": len(required["full_v6_81417"]),
                "missing_from_current_atlas": comparisons["full_v6_81417_missing_from_current"],
                "decision": "already_in_current_atlas",
            },
            {
                "id": "corrected_full_stable_extract_v30_deepseek_recovered1217_20260515",
                "stable_articles": rel(LEGACY_V30_STABLE),
                "articles": len(required["legacy_v30"]),
                "missing_from_current_atlas": comparisons["legacy_v30_missing_from_current"],
                "decision": "promote_missing_delta_from_existing_llm_output",
            },
        ],
        "comparisons": comparisons,
        "legacy_v30_delta": legacy_delta,
        "outputs": {
            "json": rel(out_dir / "atlas_full_llm_inventory.json"),
            "markdown": rel(out_dir / "atlas_full_llm_inventory.md"),
            "stable_source_inventory": rel(inventory_jsonl),
            "legacy_v30_delta_stable": legacy_delta["outputs"]["stable_articles"],
        },
        "safety": {
            "report_only_except_local_delta_artifacts": True,
            "d_scan_executed": False,
            "llm_called": False,
            "ocr_executed": False,
            "paid_api_used": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "cloudrun_publish_executed": False,
            "used_9router": False,
            "secrets_read_or_printed": False,
        },
    }
    write_json(out_dir / "atlas_full_llm_inventory.json", summary)
    write_text(
        out_dir / "atlas_full_llm_inventory.md",
        "\n".join(
            [
                "# Atlas Full LLM Inventory",
                "",
                f"- generated_at: `{summary['generated_at']}`",
                f"- decision: `{summary['decision']}`",
                f"- current_atlas_articles: `{summary['current_atlas_articles']}`",
                f"- stable_sources_scanned: `{summary['stable_sources_scanned']}`",
                "",
                "## Full LLM Runs",
                "",
                "| Run | Articles | Missing From Current | Decision |",
                "| --- | ---: | ---: | --- |",
                *[
                    f"| `{row['id']}` | `{row['articles']}` | `{row['missing_from_current_atlas']}` | `{row['decision']}` |"
                    for row in summary["full_llm_runs"]
                ],
                "",
                "## Legacy V30 Delta",
                "",
                f"- articles: `{legacy_delta['articles']}`",
                f"- lane_counts: `{legacy_delta['lane_counts']}`",
                f"- source_counts: `{legacy_delta['source_counts']}`",
                f"- totals: `{legacy_delta['totals']}`",
                f"- stable: `{legacy_delta['outputs']['stable_articles']}`",
                "",
                "## Safety",
                "",
                "- Existing local LLM stable artifacts only.",
                "- No new LLM/OCR/API/vector/graph/database/network action in this inventory step.",
                "- No D: root scan.",
                "",
            ]
        ),
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args(argv)
    summary = build_inventory(args.out_dir)
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
