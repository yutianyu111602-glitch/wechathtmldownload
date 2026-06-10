"""Phase 1 — 京沪杭宁 区域切片构建器

Filter extract.article.v1.json files to target cities and build a
gate-ready merged root for Phase 2 multi-model evaluation.

Read + copy only — no DB writes, no embeddings.

Usage
-----
python scripts/region_slice_builder.py \
    --cities 北京 上海 杭州 南京 \
    --short-core-shard-root "D:\\...\\full_ready_short_core_shards4_c1_20260508_1740" \
    --merged-roots "D:\\...\\CORE_HISTORICAL_SUCCESS_MERGED_ROOT_20260508_1815" \
    --out-dir "D:\\downstream_results\\stage7_rewrite\\stage8\\region_maps\\JINGHU_SHORT_CORE_MERGED_ROOT_<ts>"
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stage7.atomic_io import safe_read_json
from stage7.vector_plan.enrichment import infer_city


def iter_extract_files(root: Path) -> list[Path]:
    if not root.exists():
        print(f"[WARN] root does not exist, skipping: {root}", file=sys.stderr)
        return []
    return sorted(root.rglob("extract.article.v1.json"))


def build_slice(
    target_cities: set[str],
    sources: list[tuple[str, Path]],
    out_dir: Path,
) -> dict[str, Any]:
    """Copy matching articles into out_dir/llm_extract/<source_slug>/<...>/extract.article.v1.json."""
    out_extract = out_dir / "llm_extract"
    out_extract.mkdir(parents=True, exist_ok=True)

    seen_ids: set[str] = set()
    city_counts: dict[str, int] = {}
    total_copied = 0
    total_skipped_city = 0
    total_invalid = 0
    total_dup = 0
    manifest_rows: list[dict[str, Any]] = []

    for source_slug, source_root in sources:
        files = iter_extract_files(source_root)
        source_copied = 0
        print(f"[Phase1] {source_slug}: {len(files)} files to scan...", flush=True)

        for i, fp in enumerate(files):
            if i % 500 == 0 and i > 0:
                print(f"  [{source_slug}] {i}/{len(files)} ...", flush=True)

            article = safe_read_json(fp, None)
            if not isinstance(article, dict) or not article:
                total_invalid += 1
                continue

            city = infer_city(article)
            if city not in target_cities:
                total_skipped_city += 1
                continue

            # Deduplicate by article_id if available, else by source_path stem
            art_id = (
                article.get("article_id")
                or article.get("url")
                or str(fp.stem)
            )
            if art_id in seen_ids:
                total_dup += 1
                continue
            seen_ids.add(art_id)

            # Annotate with city_label for downstream scripts
            article["city_label"] = city
            article.setdefault("schema_version", "article_extract.v1")

            # Write to out_extract / source_slug / relative path from llm_extract
            # Try to strip llm_extract prefix; fallback to full relative path
            try:
                rel = fp.relative_to(source_root / "llm_extract")
            except ValueError:
                try:
                    rel = fp.relative_to(source_root)
                except ValueError:
                    rel = fp.name  # type: ignore[assignment]

            dst = out_extract / source_slug / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(
                json.dumps(article, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            total_copied += 1
            source_copied += 1
            city_counts[city] = city_counts.get(city, 0) + 1
            manifest_rows.append(
                {
                    "source_slug": source_slug,
                    "city_label": city,
                    "dst": str(dst.relative_to(out_dir)),
                    "article_id": art_id,
                }
            )

        print(f"  -> {source_slug}: copied {source_copied}")

    # Write manifest
    manifest_path = out_dir / "region_slice_manifest.jsonl"
    with manifest_path.open("w", encoding="utf-8") as mf:
        for row in manifest_rows:
            mf.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Emit a fake vector_endpoints.yaml so stage8_vector_semantic_eval.py can find it
    # (it just reads config/vector_endpoints.yaml from the root)
    _copy_vector_config(out_dir)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_cities": sorted(target_cities),
        "region_label": "京沪杭宁",
        "total_copied": total_copied,
        "total_invalid": total_invalid,
        "total_dup": total_dup,
        "total_skipped_city": total_skipped_city,
        "city_counts": city_counts,
        "out_dir": str(out_dir),
        "llm_extract_dir": str(out_extract),
        "manifest": str(manifest_path),
    }


def _copy_vector_config(out_dir: Path) -> None:
    """Copy config/vector_endpoints.yaml from stage7_rewrite root so evals can read it."""
    config_src = ROOT / "config" / "vector_endpoints.yaml"
    if not config_src.exists():
        return
    config_dst = out_dir / "config" / "vector_endpoints.yaml"
    config_dst.parent.mkdir(parents=True, exist_ok=True)
    config_dst.write_bytes(config_src.read_bytes())


def write_markdown(out_dir: Path, report: dict[str, Any]) -> None:
    ts = report["generated_at"]
    total = report["total_copied"]
    lines = [
        "# 京沪杭宁 区域切片报告 (Phase 1)",
        "",
        f"- **生成时间**: `{ts}`",
        f"- **目标城市**: {', '.join(report['target_cities'])}",
        f"- **复制总计**: {total}",
        f"- **去重丢弃**: {report['total_dup']}",
        f"- **城市过滤丢弃**: {report['total_skipped_city']}",
        "",
        "## 城市分布",
        "",
        "| 城市 | 文章数 |",
        "|---|---:|",
    ]
    for city, cnt in sorted(report["city_counts"].items()):
        lines.append(f"| {city} | {cnt} |")
    lines += [
        "",
        f"- **llm_extract**: `{report['llm_extract_dir']}`",
        f"- **manifest**: `{report['manifest']}`",
        "",
        "## 下一步 (Phase 2)",
        "",
        "运行四模型语义评估:",
        "```bash",
        "python scripts/stage8_vector_semantic_eval.py \\",
        f"  --output-root {out_dir} \\",
        "  --sample-articles 0 --max-jobs 0 \\",
        "  --candidate-cap 5 20 \\",
        "  --score-profiles adaptive_v3_source_guard adaptive_v4_source_gate \\",
        "  --endpoint-url http://192.168.8.234:11437 \\",
        "  --endpoint-model stella-large-zh-v2 --endpoint-dim 1024 \\",
        "  --out-dir JINGHU_EVAL_stella_large_<ts>",
        "```",
        "",
    ]
    (out_dir / "REGION_SLICE_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cities", nargs="+", default=["北京", "上海", "杭州", "南京"])
    parser.add_argument("--short-core-shard-root", required=True)
    parser.add_argument("--merged-roots", nargs="*", default=[])
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args(argv)

    target_cities = set(args.cities)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build source list: shards first, then merged roots
    sources: list[tuple[str, Path]] = []
    shard_root = Path(args.short_core_shard_root)
    shard_dirs = sorted(shard_root.glob("shard_*"))
    if shard_dirs:
        for sd in shard_dirs:
            sources.append((sd.name, sd))
    else:
        sources.append(("short_core", shard_root))

    for mroot in args.merged_roots:
        root = Path(mroot)
        sources.append((root.name, root))

    report = build_slice(target_cities, sources, out_dir)

    json_path = out_dir / "region_slice_report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(out_dir, report)

    print("\n=== Phase 1 Slice Complete ===")
    print(f"Output:  {out_dir}")
    print(f"Copied:  {report['total_copied']}")
    for city, cnt in sorted(report["city_counts"].items()):
        print(f"  {city}: {cnt}")

    ok = report["total_copied"] >= 50
    if not ok:
        print("\n[WARN] total_copied < 50 — check paths and city aliases", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
