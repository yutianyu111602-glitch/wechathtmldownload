"""Run the overnight Stage8 vector algorithm loop.

This is an experiment runner for the 93k underground electronic music map. It
materializes bounded Stage7 artifact roots into Stage8-style extracts, runs
large semantic-eval matrices with an embedding cache, and writes status,
results, and strategy markdown on every step.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import stage8_ocr_vector_canary as ocr_canary

semantic_eval = ocr_canary.semantic_eval

MIN_OBJECT_PRECISION_FOR_BROAD_MAP = 0.98


def now_cst() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S CST")


def parse_csv_ints(value: str) -> list[int]:
    return [int(part.strip()) for part in value.split(",") if part.strip()]


def parse_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def status_update(run_dir: Path, payload: dict[str, Any]) -> None:
    payload = dict(payload)
    payload["updated_at"] = now_cst()
    write_json(run_dir / "status.json", payload)


def materialize_sample(
    artifact_root: Path,
    run_dir: Path,
    sample: int,
    scan_limit: int,
    require_ocr: bool,
    derived_cards: bool,
) -> tuple[Path, list[Path], dict[str, Any]]:
    materialized_root = run_dir / f"materialized_sample{sample}_{'ocr' if require_ocr else 'broad'}_{'derived' if derived_cards else 'minimal'}"
    if materialized_root.exists():
        extract_files = sorted(materialized_root.rglob("extract.article.v1.json"))
        manifest = {
            "materialized_root": str(materialized_root),
            "files_selected": len(extract_files),
            "reused": True,
        }
        return materialized_root, extract_files, manifest
    artifact_dirs, scanned = ocr_canary.collect_real_ocr_artifact_dirs(
        artifact_root,
        sample=sample,
        scan_limit=scan_limit,
        require_ocr=require_ocr,
    )
    materialized_root.mkdir(parents=True, exist_ok=False)
    extract_files = ocr_canary.materialize_artifact_extracts(
        artifact_dirs,
        artifact_root,
        materialized_root,
        derive_cards=derived_cards,
    )
    manifest = {
        "artifact_root": str(artifact_root),
        "materialized_root": str(materialized_root),
        "sample": sample,
        "scan_limit": scan_limit,
        "scanned": scanned,
        "files_selected": len(extract_files),
        "require_ocr": require_ocr,
        "derived_cards": derived_cards,
        "artifact_dirs": [str(path.relative_to(artifact_root)) for path in artifact_dirs],
        "reused": False,
    }
    write_json(run_dir / f"materialized_sample{sample}_manifest.json", manifest)
    return materialized_root, extract_files, manifest


def summarize_variant(result: dict[str, Any], jobs: list[Any]) -> dict[str, Any]:
    summary = ocr_canary.summarize_result(result)
    summary["job_count"] = len(jobs)
    summary["object_kinds"] = sorted({job.object_kind for job in jobs})
    return summary


def write_strategy_markdown(run_dir: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage8 Vector Algorithm Loop Report",
        "",
        f"- updated_at: `{now_cst()}`",
        f"- run_dir: `{run_dir}`",
        f"- artifact_root: `{report.get('artifact_root', '')}`",
        f"- writes: `semantic eval only in this runner; write canary is a separate stage`",
        "",
        "## Results",
        "",
        "| sample | derived | require_ocr | variant | profile | cap | jobs | queries | Recall@5 | Rank1 | MRR@10 | City@10 | Object@10 | Source@10 | review_top3 | low_source_top3 | hard_neg_pass | source_gate_pass | OCR Recall@5 | OCR Top1 |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("results", []):
        ocr_intent = row.get("by_intent", {}).get("ocr_evidence_lookup", {})
        top1 = ""
        if row.get("ocr_query_top3"):
            top = row["ocr_query_top3"][0].get("top3", [])
            if top:
                top1 = top[0].get("kind", "")
        lines.append(
            f"| {row.get('sample')} | {row.get('derived_cards')} | {row.get('require_ocr')} | "
            f"{row.get('variant')} | {row.get('score_profile')} | {row.get('candidate_cap')} | "
            f"{row.get('job_count')} | {row.get('query_count')} | {row.get('recall_at_5')} | "
            f"{row.get('rank1')} | {row.get('mrr_at_10')} | {row.get('city_precision_at_10')} | "
            f"{row.get('object_kind_precision_at_10')} | {row.get('source_quality_at_10')} | "
            f"{row.get('review_lane_top3_rate')} | {row.get('low_source_top3_rate')} | "
            f"{row.get('hard_negative_pass_rate')} | {row.get('source_gate_pass_rate')} | "
            f"{ocr_intent.get('recall_at_5', '')} | {top1} |"
        )
    best = choose_current_best(report.get("results", []))
    lines.extend([
        "",
        "## Current Strategy",
        "",
        f"- best_candidate: `{best.get('variant', '')} + cap{best.get('candidate_cap', '')} + {best.get('score_profile', '')}`",
        f"- reason: `{best.get('reason', '')}`",
        "",
        "## Next Loop",
        "",
        "- Increase sample size or run write canary for the current best candidate.",
        "- Keep data-tier routing; do not force one parameter set across all tiers.",
        "",
    ])
    (run_dir / "STRATEGY_REPORT.md").write_text("\n".join(lines), encoding="utf-8")


def choose_current_best(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {"reason": "no results yet"}
    qualified = [
        row
        for row in results
        if float(row.get("object_kind_precision_at_10") or 0) >= MIN_OBJECT_PRECISION_FOR_BROAD_MAP
    ]
    ranking_pool = qualified or results
    ranked = sorted(
        ranking_pool,
        key=lambda row: (
            float(row.get("recall_at_5") or 0),
            float(row.get("rank1") or 0),
            float(row.get("mrr_at_10") or 0),
            float(row.get("city_precision_at_10") or 0),
            float(row.get("object_kind_precision_at_10") or 0),
            -int(row.get("candidate_cap") or 0),
        ),
        reverse=True,
    )
    best = dict(ranked[0])
    if qualified:
        best["reason"] = (
            f"highest recall/rank/mrr among rows with Object@10 >= "
            f"{MIN_OBJECT_PRECISION_FOR_BROAD_MAP}; object floor protects map intent routing"
        )
    else:
        best["reason"] = "highest recall/rank/mrr; no row met broad-map Object@10 floor"
    return best


def run_matrix(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    artifact_root = ocr_canary.validate_artifact_root(Path(args.artifact_root))
    report: dict[str, Any] = {
        "schema_version": "stage8_vector_algorithm_loop.v1",
        "artifact_root": str(artifact_root),
        "run_dir": str(run_dir),
        "started_at": now_cst(),
        "results": [],
    }
    status_update(run_dir, {"status": "running", "step": "start", "run_dir": str(run_dir)})
    samples = parse_csv_ints(args.samples)
    variants = parse_csv(args.variants)
    profiles = parse_csv(args.score_profiles)
    caps = parse_csv_ints(args.candidate_caps)
    for sample in samples:
        status_update(run_dir, {"status": "running", "step": f"materialize_sample{sample}"})
        materialized_root, extract_files, manifest = materialize_sample(
            artifact_root,
            run_dir,
            sample=sample,
            scan_limit=args.artifact_scan_limit,
            require_ocr=args.artifact_require_ocr,
            derived_cards=args.artifact_derived_cards,
        )
        eval_queries = semantic_eval.build_eval_queries(
            materialized_root,
            extract_files,
            query_mode=args.query_mode,
            auto_query_limit=args.auto_query_limit,
            auto_query_per_article=args.auto_query_per_article,
            hard_negative_limit=args.hard_negative_limit,
            hard_negative_per_article=args.hard_negative_per_article,
        )
        report.setdefault("samples", {})[str(sample)] = {
            **manifest,
            "query_count": len(eval_queries),
        }
        cache = semantic_eval.EmbeddingCache(run_dir / f"embedding_cache_sample{sample}.json")
        variant_jobs: dict[str, list[Any]] = {}
        for variant in variants:
            status_update(run_dir, {"status": "running", "step": f"build_jobs_sample{sample}_{variant}"})
            variant_jobs[variant] = semantic_eval.build_variant_jobs_from_files(
                ROOT,
                materialized_root,
                variant,
                extract_files,
                max_jobs=args.max_jobs,
                endpoint_override=args.endpoint_url,
                model_override=args.endpoint_model,
                dim_override=args.endpoint_dim,
            )
        for variant in variants:
            jobs = variant_jobs[variant]
            for profile in profiles:
                for cap in caps:
                    status_update(
                        run_dir,
                        {
                            "status": "running",
                            "step": "evaluate",
                            "sample": sample,
                            "variant": variant,
                            "profile": profile,
                            "cap": cap,
                        },
                    )
                    result = semantic_eval.evaluate_variant(
                        jobs,
                        queries=eval_queries,
                        score_profile=profile,
                        cache=cache,
                        candidate_policy=args.candidate_policy,
                        candidate_cap=cap,
                    )
                    cache.save()
                    row = summarize_variant(result, jobs)
                    row.update({
                        "sample": sample,
                        "variant": variant,
                        "score_profile": profile,
                        "candidate_cap": cap,
                        "derived_cards": bool(args.artifact_derived_cards),
                        "require_ocr": bool(args.artifact_require_ocr),
                    })
                    report["results"].append(row)
                    write_json(run_dir / "algorithm_results.json", report)
                    write_strategy_markdown(run_dir, report)
    best = choose_current_best(report["results"])
    report["completed_at"] = now_cst()
    report["best_candidate"] = best
    write_json(run_dir / "algorithm_results.json", report)
    write_strategy_markdown(run_dir, report)
    status_update(run_dir, {"status": "completed", "step": "done", "best_candidate": best})
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--samples", default="200")
    parser.add_argument("--artifact-scan-limit", type=int, default=5000)
    parser.add_argument("--artifact-require-ocr", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--artifact-derived-cards", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--variants", default="multi_card,research_v1")
    parser.add_argument("--score-profiles", default="adaptive_v3_source_guard")
    parser.add_argument("--candidate-policy", default="prefilter_v1")
    parser.add_argument("--candidate-caps", default="20")
    parser.add_argument("--query-mode", default="auto")
    parser.add_argument("--auto-query-limit", type=int, default=2000)
    parser.add_argument("--auto-query-per-article", type=int, default=12)
    parser.add_argument("--hard-negative-limit", type=int, default=0)
    parser.add_argument("--hard-negative-per-article", type=int, default=0)
    parser.add_argument("--endpoint-url", default="http://192.168.8.234:11437")
    parser.add_argument("--endpoint-model", default=None, help="Override embedding request model for candidate-model eval lanes")
    parser.add_argument("--endpoint-dim", type=int, default=None, help="Override expected embedding dimension for candidate-model eval lanes")
    parser.add_argument("--max-jobs", type=int, default=0)
    args = parser.parse_args(argv)
    report = run_matrix(args)
    print(json.dumps({
        "run_dir": report["run_dir"],
        "result_count": len(report["results"]),
        "best_candidate": report.get("best_candidate", {}),
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
