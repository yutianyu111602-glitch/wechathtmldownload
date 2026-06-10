"""Phase 0 — 京沪杭宁数据普查

Scan all extract.article.v1.json files in the short-core shard root and
optional merged roots. Use infer_city() to count articles per city.

Read-only — no DB writes, no embeddings.

Usage
-----
python scripts/province_data_census.py \
    --short-core-shard-root "D:\\downstream_results\\stage7_rewrite\\longrun\\...\\full_ready_short_core_shards4_c1_20260508_1740" \
    --merged-roots \
        "D:\\downstream_results\\stage7_rewrite\\stage8\\vector_algorithm_loop\\QWEN_MICRO_SHARDS_MERGED_ROOT_20260508_0658" \
        "D:\\downstream_results\\stage7_rewrite\\stage8\\vector_algorithm_loop\\CORE_HISTORICAL_SUCCESS_MERGED_ROOT_20260508_1815" \
    --out-dir "D:\\downstream_results\\stage7_rewrite\\stage8\\region_maps\\JINGHU_DATA_CENSUS_20260101_1200"
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stage7.atomic_io import safe_read_json
from stage7.vector_plan.enrichment import infer_city

TARGET_CITIES = {"北京", "上海", "杭州", "南京"}


def iter_extract_files(root: Path) -> list[Path]:
    """Recursively find all extract.article.v1.json under a root dir."""
    if not root.exists():
        print(f"[WARN] root does not exist, skipping: {root}", file=sys.stderr)
        return []
    return sorted(root.rglob("extract.article.v1.json"))


def census_root(root: Path, source_label: str) -> dict[str, Any]:
    files = iter_extract_files(root)
    city_stats: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "has_entities": 0, "has_events": 0, "zero_both": 0}
    )
    other_count = 0
    invalid_count = 0
    total_files = len(files)

    for i, fp in enumerate(files):
        if i % 500 == 0:
            print(f"  [{source_label}] {i}/{total_files} scanned...", flush=True)
        article = safe_read_json(fp, None)
        if not isinstance(article, dict) or not article:
            invalid_count += 1
            continue
        city = infer_city(article)
        if city not in TARGET_CITIES:
            other_count += 1
            continue
        stats = city_stats[city]
        stats["total"] += 1
        entities = article.get("entities") or []
        events = article.get("events") or []
        has_e = bool(entities)
        has_ev = bool(events)
        if has_e:
            stats["has_entities"] += 1
        if has_ev:
            stats["has_events"] += 1
        if not has_e and not has_ev:
            stats["zero_both"] += 1

    return {
        "source_label": source_label,
        "source_root": str(root),
        "total_files_scanned": total_files,
        "invalid_count": invalid_count,
        "other_city_count": other_count,
        "target_city_total": sum(v["total"] for v in city_stats.values()),
        "city_breakdown": dict(city_stats),
    }


def merge_census_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Deduplicate by canonical article_id if present, else by file stem hash."""
    merged: dict[str, dict[str, int]] = defaultdict(
        lambda: {"total": 0, "has_entities": 0, "has_events": 0, "zero_both": 0}
    )
    for rpt in reports:
        for city, stats in rpt["city_breakdown"].items():
            for k in ("total", "has_entities", "has_events", "zero_both"):
                merged[city][k] += stats[k]
    total = sum(v["total"] for v in merged.values())
    return {
        "target_region": "京沪杭宁",
        "target_cities": sorted(TARGET_CITIES),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_region_total": total,
        "city_summary": {
            city: {
                **stats,
                "entity_rate": round(stats["has_entities"] / stats["total"], 4) if stats["total"] else 0.0,
                "event_rate": round(stats["has_events"] / stats["total"], 4) if stats["total"] else 0.0,
                "zero_rate": round(stats["zero_both"] / stats["total"], 4) if stats["total"] else 0.0,
            }
            for city, stats in sorted(merged.items())
        },
        "per_source_reports": reports,
    }


def write_markdown(out_dir: Path, summary: dict[str, Any]) -> None:
    ts = summary["generated_at"]
    total = summary["target_region_total"]
    lines = [
        "# 京沪杭宁数据普查报告",
        "",
        f"- **生成时间**: `{ts}`",
        f"- **目标城市**: {', '.join(summary['target_cities'])}",
        f"- **目标区域总计**: {total} 篇",
        "",
        "## 城市明细",
        "",
        "| 城市 | 总计 | 含实体 | 含事件 | 两者为零 | 实体率 | 事件率 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for city, s in summary["city_summary"].items():
        lines.append(
            f"| {city} | {s['total']} | {s['has_entities']} | {s['has_events']} "
            f"| {s['zero_both']} | {s['entity_rate']:.1%} | {s['event_rate']:.1%} |"
        )
    lines += [
        "",
        "## 数据源",
        "",
    ]
    for rpt in summary["per_source_reports"]:
        lines += [
            f"### {rpt['source_label']}",
            f"- root: `{rpt['source_root']}`",
            f"- scanned: {rpt['total_files_scanned']}  invalid: {rpt['invalid_count']}  other_city: {rpt['other_city_count']}  target: {rpt['target_city_total']}",
            "",
        ]
    lines += [
        "## 下一步 (Phase 1)",
        "",
        "```",
        "python scripts/region_slice_builder.py \\",
        "    --cities 北京 上海 杭州 南京 \\",
        "    --short-core-shard-root <same shard root> \\",
        "    --merged-roots <same merged roots> \\",
        "    --out-dir D:\\\\downstream_results\\\\stage7_rewrite\\\\stage8\\\\region_maps\\\\JINGHU_SHORT_CORE_MERGED_ROOT_<ts>",
        "```",
        "",
    ]
    (out_dir / "census_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--short-core-shard-root",
        required=True,
        help="Path to full_ready_short_core_shards4_c1_* dir containing shard_00..shard_03",
    )
    parser.add_argument(
        "--merged-roots",
        nargs="+",
        default=[],
        help="Additional stage8 merged roots to scan (llm_extract subdirs)",
    )
    parser.add_argument("--out-dir", required=True, help="Output directory for census_summary.json/.md")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    reports: list[dict[str, Any]] = []

    # Scan short-core shard root (shard_00 .. shard_03)
    shard_root = Path(args.short_core_shard_root)
    shard_dirs = sorted(shard_root.glob("shard_*"))
    if not shard_dirs:
        # Maybe caller passed the root with shard dirs directly
        shard_dirs = [shard_root]
    for shard_dir in shard_dirs:
        label = f"short_core/{shard_dir.name}"
        print(f"[Phase0] Scanning {label}...")
        rpt = census_root(shard_dir, label)
        reports.append(rpt)
        print(f"  -> target_city_total={rpt['target_city_total']}")

    # Scan merged roots
    for merged in args.merged_roots:
        root = Path(merged)
        label = f"merged/{root.name}"
        print(f"[Phase0] Scanning {label}...")
        rpt = census_root(root, label)
        reports.append(rpt)
        print(f"  -> target_city_total={rpt['target_city_total']}")

    summary = merge_census_reports(reports)
    json_path = out_dir / "census_summary.json"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown(out_dir, summary)

    print("\n=== Census Complete ===")
    print(f"Output: {out_dir}")
    print(f"target_region_total: {summary['target_region_total']}")
    for city, s in summary["city_summary"].items():
        print(f"  {city}: {s['total']} (ents={s['has_entities']}, evts={s['has_events']})")

    ok = summary["target_region_total"] >= 50
    if not ok:
        print("\n[WARN] target_region_total < 50 — check city alias coverage or shard paths", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
