"""Autoresearch-style read-only experiment loop for Stage8 vector quality.

Run this on the Mac eval host by default. It wraps stage8_vector_semantic_eval.py
with repeatable experiment presets and writes a manifest, but never writes
Qdrant, Neo4j, or PC production DB.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT = r"D:\downstream_results\stage7_rewrite"
DEFAULT_ENDPOINT = "http://127.0.0.1:11437"


@dataclass(frozen=True)
class Experiment:
    name: str
    sample: int
    max_jobs: int
    variants: str
    score_profiles: str
    query_mode: str
    auto_query_limit: int
    hard_negative_limit: int
    candidate_policy: str = "prefilter_v1"
    candidate_cap: int = 50
    extract_scope: str = "all"
    project_articles: int = 93000
    auto_query_per_article: int = 8
    hard_negative_per_article: int = 4


def build_experiments(preset: str) -> list[Experiment]:
    canary = [
        Experiment(
            name="baseline_control",
            sample=40,
            max_jobs=240,
            variants="baseline,labeled_v2,multi_card",
            score_profiles="soft_payload,adaptive_v3_source_guard",
            query_mode="combined_hard",
            auto_query_limit=160,
            hard_negative_limit=80,
        ),
        Experiment(
            name="research_v1_canary",
            sample=80,
            max_jobs=720,
            variants="multi_card,research_v1",
            score_profiles="adaptive_v3_source_guard,adaptive_v4_source_gate",
            query_mode="combined_hard",
            auto_query_limit=320,
            hard_negative_limit=160,
        ),
    ]
    scale = [
        Experiment(
            name="research_v1_scale_projection",
            sample=160,
            max_jobs=1800,
            variants="multi_card,research_v1",
            score_profiles="adaptive_v3_source_guard,adaptive_v4_source_gate",
            query_mode="combined_hard",
            auto_query_limit=1200,
            hard_negative_limit=480,
        ),
        Experiment(
            name="research_v1_cap_sweep_cap25",
            sample=160,
            max_jobs=1800,
            variants="research_v1",
            score_profiles="adaptive_v4_source_gate",
            query_mode="combined_hard",
            auto_query_limit=1200,
            hard_negative_limit=480,
            candidate_cap=25,
        ),
        Experiment(
            name="research_v1_cap_sweep_cap100",
            sample=160,
            max_jobs=1800,
            variants="research_v1",
            score_profiles="adaptive_v4_source_gate",
            query_mode="combined_hard",
            auto_query_limit=1200,
            hard_negative_limit=480,
            candidate_cap=100,
        ),
    ]
    strict_sweep = [
        Experiment(
            name=f"research_v1_strict_cap{cap}",
            sample=160,
            max_jobs=1800,
            variants="research_v1",
            score_profiles="adaptive_v4_source_gate",
            query_mode="combined_hard",
            auto_query_limit=1200,
            hard_negative_limit=480,
            candidate_cap=cap,
        )
        for cap in (10, 15, 20, 25, 35, 50)
    ]
    if preset == "canary":
        return canary
    if preset == "scale":
        return scale
    if preset == "strict_sweep":
        return strict_sweep
    if preset == "full":
        return canary + scale + strict_sweep
    raise ValueError(f"unknown preset={preset}")


def build_command(eval_script: Path, args: argparse.Namespace, experiment: Experiment, report_dir: Path) -> list[str]:
    return [
        sys.executable,
        str(eval_script),
        "--output",
        str(args.output),
        "--extract-scope",
        experiment.extract_scope,
        "--sample",
        str(experiment.sample),
        "--max-jobs",
        str(experiment.max_jobs),
        "--variants",
        experiment.variants,
        "--score-profiles",
        experiment.score_profiles,
        "--query-mode",
        experiment.query_mode,
        "--auto-query-limit",
        str(experiment.auto_query_limit),
        "--auto-query-per-article",
        str(experiment.auto_query_per_article),
        "--hard-negative-limit",
        str(experiment.hard_negative_limit),
        "--hard-negative-per-article",
        str(experiment.hard_negative_per_article),
        "--candidate-policy",
        experiment.candidate_policy,
        "--candidate-cap",
        str(experiment.candidate_cap),
        "--project-articles",
        str(experiment.project_articles),
        "--endpoint-url",
        args.endpoint_url,
        "--report-dir",
        str(report_dir),
    ]


def run_experiment(command: list[str], dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"status": "planned", "returncode": None, "command": command}
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "command": command,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-4000:],
    }


def write_markdown(path: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# Stage8 Vector Research Loop",
        "",
        f"- run_id: `{manifest['run_id']}`",
        f"- preset: `{manifest['preset']}`",
        f"- dry_run: `{manifest['dry_run']}`",
        f"- endpoint_url: `{manifest['endpoint_url']}`",
        f"- production_writes: `{manifest['safety']['production_writes']}`",
        "",
        "## Experiments",
        "",
    ]
    for item in manifest["experiments"]:
        experiment = item["experiment"]
        result = item["result"]
        lines.append(f"- `{experiment['name']}`: {result['status']} cap={experiment['candidate_cap']} variants=`{experiment['variants']}` profiles=`{experiment['score_profiles']}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage8 vector autoresearch-style loop")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Stage7 output root. Bounded to this directory.")
    parser.add_argument("--endpoint-url", default=DEFAULT_ENDPOINT, help="Mac-local embedding endpoint. Use http://127.0.0.1:11437 on Mac.")
    parser.add_argument("--preset", default="canary", choices=["canary", "scale", "strict_sweep", "full"], help="Experiment matrix")
    parser.add_argument("--report-root", default=None, help="Directory for loop manifest and per-experiment reports")
    parser.add_argument("--run-id", default=None, help="Stable run id for reproducible report paths")
    parser.add_argument("--dry-run", action="store_true", help="Plan commands only; no embeddings called")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parent.parent
    eval_script = root / "scripts" / "stage8_vector_semantic_eval.py"
    run_id = args.run_id or datetime.now(timezone.utc).strftime("vector_research_%Y%m%d_%H%M%S")
    report_root = Path(args.report_root) if args.report_root else Path(args.output) / "stage8" / "vector_research_loop" / run_id
    report_root.mkdir(parents=True, exist_ok=True)

    results = []
    for experiment in build_experiments(args.preset):
        exp_report_dir = report_root / experiment.name
        exp_report_dir.mkdir(parents=True, exist_ok=True)
        command = build_command(eval_script, args, experiment, exp_report_dir)
        results.append(
            {
                "experiment": asdict(experiment),
                "report_dir": str(exp_report_dir),
                "result": run_experiment(command, args.dry_run),
            }
        )

    manifest = {
        "schema_version": "stage8_vector_research_loop.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "preset": args.preset,
        "dry_run": args.dry_run,
        "output": str(args.output),
        "endpoint_url": args.endpoint_url,
        "safety": {
            "production_writes": False,
            "qdrant_writes": False,
            "neo4j_writes": False,
            "pc_db_writes": False,
            "cloud_mem0_calls": False,
        },
        "experiments": results,
    }
    json_path = report_root / "stage8_vector_research_loop_manifest.json"
    md_path = report_root / "stage8_vector_research_loop_manifest.md"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(md_path, manifest)
    print(json.dumps({"ok": True, "json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2))
    return 0 if all(item["result"]["status"] in {"planned", "passed"} for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
