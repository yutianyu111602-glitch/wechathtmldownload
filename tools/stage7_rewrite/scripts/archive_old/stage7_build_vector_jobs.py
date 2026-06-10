#!/usr/bin/env python3
r"""CLI entry point: build vector embedding jobs from Stage 7 output.

Usage:
    python -m stage7.cli build-vector-jobs --output "D:\downstream_results\stage7_rewrite" --sample 20
    python scripts/stage7_build_vector_jobs.py --output "D:\downstream_results\stage7_rewrite" --sample 20
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime, timezone

import yaml

# Allow running as script or module
if __name__ == "__main__" and not __package__:
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root))
    __package__ = "stage7"

from stage7.vector_plan.schemas import VectorJob, VectorManifest
from stage7.vector_plan.build_embedding_jobs import build_jobs_from_article
from stage7.vector_plan.qdrant_prepare import build_collection_defs, write_collection_plan
from stage7.atomic_io import safe_read_json

logger = logging.getLogger(__name__)


def load_vector_config(config_path: Path) -> dict:
    """Load config/vector_endpoints.yaml."""
    if not config_path.exists():
        raise FileNotFoundError(f"vector_endpoints.yaml not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def find_extract_files(stage7_root: Path, sample: int | None = None) -> list[Path]:
    """Find extract.article.v1.json files under stage7 llm_extract/."""
    extract_dir = stage7_root / "llm_extract"
    if not extract_dir.exists():
        raise FileNotFoundError(f"llm_extract dir not found: {extract_dir}")

    files: list[Path] = []
    for account_dir in sorted(extract_dir.iterdir()):
        if not account_dir.is_dir():
            continue
        for article_dir in sorted(account_dir.iterdir()):
            if not article_dir.is_dir():
                continue
            extract_file = article_dir / "extract.article.v1.json"
            if extract_file.exists():
                files.append(extract_file)
                if sample and len(files) >= sample:
                    return files
    return files


def build_vector_jobs(
    stage7_root: Path,
    output_root: Path,
    config: dict,
    sample: int | None = None,
    card_template: str = "baseline",
) -> dict:
    """Build vector jobs from Stage 7 output.

    Returns stats dict.
    """
    endpoint_key = config.get("default_chinese_endpoint", "stella_large_zh_1024")
    ep_def = config.get("endpoints", {}).get(endpoint_key, {})
    model = ep_def.get("model", "infgrad/stella-large-zh-v2")
    endpoint_url = ep_def.get("url", "http://192.168.8.234:11437")
    dim = ep_def.get("dim", 1024)

    extract_files = find_extract_files(stage7_root, sample=sample)
    if not extract_files:
        logger.warning("No extract.article.v1.json files found")
        return {"job_count": 0, "files_scanned": 0}

    all_jobs: list[VectorJob] = []
    by_unit_type: dict[str, int] = {}
    files_scanned = 0

    for ef in extract_files:
        article_data = safe_read_json(ef, {})
        if not article_data:
            continue
        files_scanned += 1

        rel_path = str(ef.relative_to(stage7_root))
        jobs = build_jobs_from_article(
            article_data,
            source_path=rel_path,
            model=model,
            endpoint=endpoint_url,
            dim=dim,
            card_template=card_template,
        )
        for job in jobs:
            all_jobs.append(job)
            kind = job.object_kind
            by_unit_type[kind] = by_unit_type.get(kind, 0) + 1

    # Write jobs JSONL
    jobs_dir = output_root / "stage8" / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    if card_template == "baseline":
        suffix = f".sample{sample}" if sample else ""
    else:
        suffix = f".{card_template}.sample{sample}" if sample else f".{card_template}"
    jobs_path = jobs_dir / f"vector_jobs{suffix}.jsonl"

    with open(jobs_path, "w", encoding="utf-8") as f:
        for job in all_jobs:
            f.write(json.dumps(job.to_dict(), ensure_ascii=False, default=str) + "\n")

    # Write manifest
    manifest = VectorManifest(
        source_stage7_root=str(stage7_root),
        job_count=len(all_jobs),
        by_unit_type=by_unit_type,
        embedding_models=[model],
    )
    manifest_path = jobs_dir / f"vector_manifest{suffix}.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest.to_dict(), f, ensure_ascii=False, indent=2, default=str)

    # Write collection plan
    collection_defs = build_collection_defs(model=model, dim=dim)
    plan_path = write_collection_plan(jobs_dir, collection_defs)

    logger.info(
        f"Built {len(all_jobs)} jobs from {files_scanned} articles "
        f"(sample={sample})"
    )

    return {
        "job_count": len(all_jobs),
        "files_scanned": files_scanned,
        "by_unit_type": by_unit_type,
        "jobs_path": str(jobs_path),
        "manifest_path": str(manifest_path),
        "collection_plan_path": str(plan_path),
        "model": model,
        "endpoint": endpoint_url,
        "dim": dim,
        "card_template": card_template,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build vector embedding jobs from Stage 7 output")
    parser.add_argument("--output", default=r"D:\downstream_results\stage7_rewrite", help="Stage 7 output root")
    parser.add_argument("--sample", type=int, default=None, help="Limit to N articles")
    parser.add_argument("--config", default=None, help="Path to vector_endpoints.yaml")
    parser.add_argument("--card-template", default="baseline", choices=["baseline", "labeled_v2", "multi_card"], help="Canonical text/card template")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    output_root = Path(args.output)
    if not output_root.exists():
        logger.error(f"Output root not found: {output_root}")
        return 1

    config_path = Path(args.config) if args.config else Path(__file__).parent.parent / "config" / "vector_endpoints.yaml"
    config = load_vector_config(config_path)

    stats = build_vector_jobs(output_root, output_root, config, sample=args.sample, card_template=args.card_template)

    print(json.dumps(stats, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
