#!/usr/bin/env python3
"""Multi-profile comparison runner for DeepSeek Stage7 extraction.

Runs N profiles on the same sample set, compares quality/cost metrics,
and writes results to mem0 for persistent cross-session memory.

Usage:
  python scripts/run_profile_compare.py \
    --manifest-jsonl reports/flash_ready_manifest_20260509.jsonl \
    --limit 100 --concurrency 2 \
    --out-dir reports --run-label canary_compare_v1
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
STAGE7_ROOT = SCRIPT_DIR.parent
PILOT_SCRIPT = SCRIPT_DIR / "stage7_deepseek_flash_pilot.py"
V4_PROMPT = STAGE7_ROOT / "config" / "prompt.extract.v4.zh.txt"
MICRO_PROMPT = STAGE7_ROOT / "config" / "prompt.extract.micro.zh.txt"

PROFILES = {
    "flash_v4": {
        "model": "deepseek-v4-pro",
        "prompt_path": str(V4_PROMPT),
        "thinking": "disabled",
        "max_tokens": 1024,
        "label": "Pro + V4 prompt",
        "cost_in": 1,
        "cost_out": 2,
    },
    "pro_v4": {
        "model": "deepseek-v4-pro",
        "prompt_path": str(V4_PROMPT),
        "thinking": "disabled",
        "max_tokens": 1024,
        "label": "Pro + V4 prompt (no thinking)",
        "cost_in": 3,
        "cost_out": 6,
    },
    "flash_micro": {
        "model": "deepseek-v4-pro",
        "prompt_path": str(MICRO_PROMPT),
        "thinking": "disabled",
        "max_tokens": 384,
        "label": "Pro + micro prompt (baseline)",
        "cost_in": 1,
        "cost_out": 2,
    },
    "pro_v4_think": {
        "model": "deepseek-v4-pro",
        "prompt_path": str(V4_PROMPT),
        "thinking": "disabled",
        "max_tokens": 2048,
        "label": "Pro + V4 prompt + extended output",
        "cost_in": 3,
        "cost_out": 6,
    },
}


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def run_profile(
    profile_key: str,
    profile: dict,
    manifest_jsonl: str,
    limit: int,
    concurrency: int,
    out_dir: Path,
    api_key: str,
    endpoint: str,
    seed: int,
) -> dict[str, Any]:
    """Run a single profile and return summary metrics."""
    label = profile["label"]
    print(f"\n{'='*60}")
    print(f"RUNNING: {label} ({profile_key})")
    print(f"{'='*60}")

    output_root = f"profile_{profile_key}_{now_stamp()}"
    cmd = [
        sys.executable,
        str(PILOT_SCRIPT),
        "--manifest-jsonl", manifest_jsonl,
        "--mode", "run",
        "--limit", str(limit),
        "--seed", str(seed),
        "--concurrency", str(concurrency),
        "--model", profile["model"],
        "--prompt-path", profile["prompt_path"],
        "--thinking", profile["thinking"],
        "--max-tokens", str(profile["max_tokens"]),
        "--endpoint", endpoint,
        "--out-dir", str(out_dir),
        "--output-root-name", output_root,
    ]

    env = os.environ.copy()
    env["DEEPSEEK_API_KEY"] = api_key

    started = time.perf_counter()
    result = subprocess.run(
        cmd,
        cwd=str(STAGE7_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=3600,
    )
    elapsed = time.perf_counter() - started

    summary_path = out_dir / output_root / "flash_summary.json"
    if not summary_path.exists():
        # Pro mode uses different summary name
        summary_path = out_dir / output_root / "pro_summary.json"
    if not summary_path.exists():
        # Check running summary
        running_path = out_dir / output_root / "flash_running_summary.json"
        if running_path.exists():
            summary_path = running_path

    summary: dict[str, Any] = {"profile_key": profile_key, "label": label, "exit_code": result.returncode, "elapsed_sec": round(elapsed, 1)}

    if summary_path.exists():
        try:
            data = json.loads(summary_path.read_text(encoding="utf-8"))
            summary.update({
                "processed_samples": data.get("processed_samples", 0),
                "selected_samples": data.get("selected_samples", 0),
                "api_ok_rate": data.get("api_ok_rate", 0),
                "parse_ok_rate": data.get("parse_ok_rate", 0),
                "schema_ok_rate": data.get("schema_ok_rate", 0),
                "estimated_cny": data.get("estimated_cny", 0),
                "chunk_count": data.get("chunk_count", 0),
                "prompt_tokens": data.get("prompt_tokens", 0),
                "completion_tokens": data.get("completion_tokens", 0),
            })
        except Exception:
            pass

    if result.returncode != 0:
        summary["stderr_tail"] = result.stderr[-500:] if result.stderr else ""

    print(f"  elapsed={elapsed:.0f}s exit={result.returncode} cost=¥{summary.get('estimated_cny', 0):.3f}")
    print(f"  api={summary.get('api_ok_rate', 0):.3f} parse={summary.get('parse_ok_rate', 0):.3f} schema={summary.get('schema_ok_rate', 0):.3f}")
    return summary


def compute_comparison(results: list[dict]) -> dict[str, Any]:
    """Compute comparison metrics across profiles."""
    comparison = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "profiles": [],
    }
    for r in results:
        entry = {
            "key": r["profile_key"],
            "label": r["label"],
            "elapsed_sec": r.get("elapsed_sec", 0),
            "exit_code": r.get("exit_code", -1),
            "processed": r.get("processed_samples", 0),
            "api_ok_rate": r.get("api_ok_rate", 0),
            "parse_ok_rate": r.get("parse_ok_rate", 0),
            "schema_ok_rate": r.get("schema_ok_rate", 0),
            "estimated_cny": r.get("estimated_cny", 0),
            "cost_per_sample": round(r.get("estimated_cny", 0) / max(r.get("processed_samples", 1), 1), 4),
        }
        comparison["profiles"].append(entry)

    # Rank by composite score: parse_ok * 0.4 + schema_ok * 0.4 + (1 - cost_per_sample/max_cost) * 0.2
    valid = [p for p in comparison["profiles"] if p["processed"] > 0]
    if valid:
        max_cost = max(p["cost_per_sample"] for p in valid) or 0.001
        for p in valid:
            cost_score = max(0, 1 - p["cost_per_sample"] / max_cost) if max_cost > 0 else 1
            p["composite_score"] = round(
                p["parse_ok_rate"] * 0.4 + p["schema_ok_rate"] * 0.4 + cost_score * 0.2, 4
            )
        valid.sort(key=lambda x: x["composite_score"], reverse=True)
        comparison["ranked"] = [p["key"] for p in valid]
        comparison["winner"] = valid[0]["key"] if valid else None

    return comparison


def write_local_memory(comparison: dict, run_label: str) -> None:
    """Write comparison results to local pipeline memory."""
    try:
        from pipeline_memory import add
        content = json.dumps({
            "run_label": run_label,
            "timestamp": comparison["generated_at"],
            "winner": comparison.get("winner"),
            "ranked": comparison.get("ranked", []),
            "profiles": comparison.get("profiles", []),
        }, ensure_ascii=False, indent=2)
        add(f"DeepSeek Stage7 profile comparison: {run_label}\n\n{content}",
            metadata={"type": "stage7_profile_compare", "run_label": run_label})
        print(f"\n  memory: wrote comparison for {run_label}")
    except Exception as e:
        print(f"\n  memory: write failed ({e})")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-jsonl", required=True, help="Path to manifest JSONL")
    parser.add_argument("--limit", type=int, default=100, help="Samples per profile (default: 100)")
    parser.add_argument("--seed", type=int, default=20260509)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--out-dir", default="reports")
    parser.add_argument("--run-label", default="canary_compare")
    parser.add_argument("--profiles", nargs="*", default=list(PROFILES.keys()),
                        help=f"Profiles to run (default: all). Available: {list(PROFILES.keys())}")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY")
    parser.add_argument("--endpoint", default="https://api.deepseek.com")
    parser.add_argument("--no-memory", action="store_true", help="Skip local memory write")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"ERROR: {args.api_key_env} not set", file=sys.stderr)
        return 1

    manifest_path = Path(args.manifest_jsonl)
    if not manifest_path.is_absolute():
        manifest_path = STAGE7_ROOT / manifest_path
    if not manifest_path.exists():
        print(f"ERROR: manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = STAGE7_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    profiles_to_run = {k: PROFILES[k] for k in args.profiles if k in PROFILES}
    if not profiles_to_run:
        print(f"ERROR: no valid profiles. Available: {list(PROFILES.keys())}", file=sys.stderr)
        return 1

    print(f"Profile Comparison: {args.run_label}")
    print(f"  manifest: {manifest_path}")
    print(f"  profiles: {list(profiles_to_run.keys())}")
    print(f"  limit: {args.limit}, concurrency: {args.concurrency}")
    print(f"  out_dir: {out_dir}")

    results: list[dict[str, Any]] = []
    for key, profile in profiles_to_run.items():
        result = run_profile(
            profile_key=key,
            profile=profile,
            manifest_jsonl=str(manifest_path),
            limit=args.limit,
            concurrency=args.concurrency,
            out_dir=out_dir,
            api_key=api_key,
            endpoint=args.endpoint,
            seed=args.seed,
        )
        results.append(result)

    comparison = compute_comparison(results)

    # Write comparison report
    report_path = out_dir / f"profile_compare_{args.run_label}_{now_stamp()}.json"
    report_path.write_text(json.dumps(comparison, ensure_ascii=False, indent=2))
    print(f"\nComparison report: {report_path}")

    if comparison.get("winner"):
        print(f"\nWINNER: {comparison['winner']} ({PROFILES[comparison['winner']]['label']})")
        for p in comparison["profiles"]:
            score = p.get("composite_score", "N/A")
            print(f"  {p['key']:20s} score={score:.4f} parse={p['parse_ok_rate']:.3f} schema={p['schema_ok_rate']:.3f} ¥={p['cost_per_sample']:.4f}/sample")

    if not args.no_memory:
        write_local_memory(comparison, args.run_label)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
