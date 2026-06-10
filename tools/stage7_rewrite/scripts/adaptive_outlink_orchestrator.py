#!/usr/bin/env python3
"""Adaptive Outlink Search Orchestrator — try multiple methods, compare, adapt.

After Post-Filter + cross-validation, this orchestrator:
1. Splits entities into method-specific queues
2. Runs multiple methods in parallel (where possible)
3. Tracks per-method and per-platform success rates
4. Re-routes failed entities to fallback methods
5. Produces a unified quality-scored review queue

Strategy matrix:
  instagram_maigret_priority → [HTTP outlink, Instagram search (OpenCLI)]
  maigret_first              → [Maigret, fixed-site search]
  fixed_site_search          → [fixed-site search, HTTP outlink]
  direct_outlink_expansion   → [HTTP outlink, Camofox verify]
"""

import json
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────────────────────
STAGE7_ROOT = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite"
)
CROSS_VALIDATED_QUEUE = (
    STAGE7_ROOT / "reports" / "atlas_cross_validation_20260521" / "atlas_cross_validated_queue.jsonl"
)
CROSS_VALIDATION_SUMMARY = (
    STAGE7_ROOT / "reports" / "atlas_cross_validation_20260521" / "atlas_cross_validation_summary.json"
)
REVIEW_QUEUE = (
    STAGE7_ROOT / "reports" / "atlas_entity_public_search_post_filter_full_138102_20260521"
    / "entity_public_search_review_queue.jsonl"
)
OUT_DIR = STAGE7_ROOT / "reports" / "atlas_adaptive_outlink_20260521"
SCHEMA_VERSION = "stage7_atlas_adaptive_outlink.v1"

# ── Method Configs ────────────────────────────────────────────────────────

METHOD_CONFIGS = {
    "instagram_deep": {
        "description": "Instagram deep extraction — bio, following list, post captions (OpenCLI Windows)",
        "command": [
            "python3", "scripts/instagram_deep_extraction.py",
        ],
        "success_indicators": ["instagram_deep_extraction_plan.json"],
        "quality_metric": "instagram_quality_score",
        "max_retries": 0,
        "timeout_sec": 1800,
        "requires_opencli_bridge": True,
        "note": "Requires OpenCLI daemon + browser profile ejk3c3qe connected (run opencli doctor first)",
    },
    "http_outlink": {
        "description": "HTTP profile outlink expansion (Linktree→SC/BC/MC/RA/YT)",
        "command": [
            "python3", "scripts/expand_atlas_social_profile_outlinks.py",
            "--review-queue", str(REVIEW_QUEUE),
            "--out-dir", str(OUT_DIR / "http_outlink"),
            "--fetch-mode", "http",
            "--limit", "500",
            "--timeout-sec", "12",
            "--sleep-sec", "0.5",
            "--follow-aggregators",
            "--max-aggregator-pages", "80",
        ],
        "success_indicators": ["atlas_social_profile_outlinks.jsonl"],
        "quality_metric": "high_value_outlink_rate",  # outlinks found / rows processed
        "max_retries": 1,
        "timeout_sec": 600,
    },
    "maigret_discovery": {
        "description": "Maigret username discovery (600+ sites)",
        "command": [
            "python3", "scripts/run_maigret_http_canary.py",
            "--base-url", "http://127.0.0.1:15051",
            "--candidates", str(OUT_DIR / "maigret_candidates.jsonl"),
            "--out-dir", str(OUT_DIR / "maigret"),
            "--limit", "50",
            "--top-sites", "30",
        ],
        "success_indicators": ["maigret_results.jsonl"],
        "quality_metric": "username_discovery_rate",
        "max_retries": 1,
        "timeout_sec": 900,
        "requires_candidates": True,
    },
    "fixed_site_search": {
        "description": "Fixed-site direct search (RA/SC/BC/MC/YT)",
        "command": [
            "python3", "scripts/search_fixed_site_profiles.py",
            "--review-queue", str(REVIEW_QUEUE),
            "--out-dir", str(OUT_DIR / "fixed_site"),
            "--platforms", "ra,soundcloud,bandcamp,mixcloud,youtube",
            "--timeout-sec", "15",
            "--sleep-sec", "0.5",
        ],
        "success_indicators": ["fixed_site_profile_candidates.jsonl"],
        "quality_metric": "profile_url_discovery_rate",
        "max_retries": 1,
        "timeout_sec": 600,
    },
    "radio_search": {
        "description": "Chinese radio platforms (baihui/cdcr/byyb/shcr/bilibili) — artist pages + mixes",
        "command": [
            "python3", "scripts/scrape_radio_platforms.py",
        ],
        "success_indicators": ["radio_crawl_master_summary.json"],
        "quality_metric": "radio_host_discovery_rate",
        "max_retries": 1,
        "timeout_sec": 900,
        "requires_candidates": False,
    },
    "scrapling_content": {
        "description": "Scrapling content evidence (static difficult pages)",
        "command": [
            "python3", "scripts/fetch_atlas_entity_public_search_content_evidence.py",
            "--review-queue", str(REVIEW_QUEUE),
            "--out-dir", str(OUT_DIR / "scrapling"),
            "--fetch-mode", "scrapling-get",
            "--scrapling-bin", "cmd.exe /c C:\\Users\\pc\\bin\\scrapling.cmd",
            "--limit", "200",
            "--timeout-sec", "20",
            "--sleep-sec", "0.5",
        ],
        "success_indicators": ["content_evidence.jsonl"],
        "quality_metric": "content_extraction_rate",
        "max_retries": 1,
        "timeout_sec": 900,
    },
}

# ── Strategy Routing ──────────────────────────────────────────────────────

STRATEGY_METHOD_MAP = {
    "instagram_maigret_priority": {
        "primary": ["instagram_deep", "http_outlink"],
        "fallback": ["scrapling_content", "radio_search"],
        "description": "High Atlas mentions → Instagram deep + HTTP outlink first",
    },
    "maigret_first": {
        "primary": ["maigret_discovery", "radio_search"],
        "fallback": ["http_outlink"],
        "description": "No Atlas match → Maigret + radio platforms discovery first",
    },
    "fixed_site_search": {
        "primary": ["fixed_site_search", "radio_search"],
        "fallback": ["http_outlink", "maigret_discovery"],
        "description": "Low Atlas mentions → fixed-site + radio, then fallback",
    },
    "direct_outlink_expansion": {
        "primary": ["http_outlink", "radio_search"],
        "fallback": ["scrapling_content"],
        "description": "Has Atlas social URLs → direct outlink + radio verification",
    },
}


def now_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def load_cross_validated_queue() -> list[dict]:
    """Load and group entities by recommended strategy."""
    if not CROSS_VALIDATED_QUEUE.exists():
        print(f"ERROR: cross-validated queue not found at {CROSS_VALIDATED_QUEUE}", file=sys.stderr)
        return []

    entities = []
    with open(CROSS_VALIDATED_QUEUE) as f:
        for line in f:
            entities.append(json.loads(line))
    return entities


def group_by_strategy(entities: list[dict]) -> dict[str, list[dict]]:
    """Group entities by recommended_strategy."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in entities:
        strategy = e.get("recommended_strategy", "maigret_first")
        groups[strategy].append(e)
    return dict(groups)


def run_method(method_name: str, config: dict) -> dict[str, Any]:
    """Run one method and return result metrics."""
    if config.get("requires_opencli_bridge"):
        import os
        bridge = "/home/pc/bin/opencli-wsl"
        if not os.path.exists(bridge):
            return {
                "method": method_name,
                "status": "skipped",
                "reason": "opencli_wsl_bridge_missing — run /home/pc/bin/opencli-wsl",
                "entities_processed": 0, "results_found": 0, "errors": 0, "duration_sec": 0,
            }
        # Check daemon
        import subprocess as sp
        rc = sp.run([bridge, "doctor"], capture_output=True, text=True, timeout=15)
        if "[FAIL]" in rc.stdout or rc.returncode != 0:
            return {
                "method": method_name,
                "status": "skipped",
                "reason": f"opencli_daemon_not_ready — connect browser profile ejk3c3qe first. Doctor: {rc.stdout[:200]}",
                "entities_processed": 0, "results_found": 0, "errors": 0, "duration_sec": 0,
            }

    if config.get("script_missing"):
        return {
            "method": method_name,
            "status": "skipped",
            "reason": "script_not_implemented",
            "entities_processed": 0,
            "results_found": 0,
            "errors": 0,
            "duration_sec": 0,
        }

    if config.get("requires_candidates"):
        candidates_path = Path(config["command"][config["command"].index("--candidates") + 1])
        if not candidates_path.exists():
            return {
                "method": method_name,
                "status": "skipped",
                "reason": "candidates_file_missing",
                "entities_processed": 0,
                "results_found": 0,
                "errors": 0,
                "duration_sec": 0,
            }

    print(f"\n{'='*60}")
    print(f"  Running: {method_name} — {config['description']}")
    print(f"{'='*60}")

    start = time.time()
    try:
        result = subprocess.run(
            config["command"],
            cwd=str(STAGE7_ROOT),
            capture_output=True,
            text=True,
            timeout=config.get("timeout_sec", 600),
        )

        duration = time.time() - start

        # Try to read summary JSON for metrics
        out_dir = Path(config["command"][config["command"].index("--out-dir") + 1])
        summary_path = None
        for indicator in config["success_indicators"]:
            candidate = out_dir / indicator
            if candidate.exists():
                summary_path = candidate
                break

        # Parse summary if available
        metrics = {
            "method": method_name,
            "status": "completed" if result.returncode == 0 else "failed",
            "returncode": result.returncode,
            "duration_sec": round(duration, 1),
            "stdout_last_10": "\n".join(result.stdout.strip().split("\n")[-10:]),
            "stderr_last_5": "\n".join(result.stderr.strip().split("\n")[-5:]),
        }

        if summary_path:
            try:
                with open(summary_path) as f:
                    summary_data = json.load(f)
                metrics["entities_processed"] = summary_data.get("input_rows", summary_data.get("selected_profile_rows", 0))
                metrics["results_found"] = summary_data.get("outlink_rows", summary_data.get("result_count", 0))
                metrics["errors"] = summary_data.get("error_count", 0)
                metrics["high_value"] = summary_data.get("high_value_followup_rows", 0)
            except Exception:
                # Count lines in output file as rough metric
                lines = sum(1 for _ in open(summary_path))
                metrics["entities_processed"] = 0
                metrics["results_found"] = lines
                metrics["errors"] = 0
                metrics["high_value"] = 0
        else:
            metrics["entities_processed"] = 0
            metrics["results_found"] = 0
            metrics["errors"] = 0
            metrics["high_value"] = 0

        # Quality score: results per entity processed
        if metrics["entities_processed"] > 0:
            metrics["quality_score"] = round(
                (metrics["results_found"] + metrics["high_value"] * 3) / metrics["entities_processed"], 2
            )
        else:
            metrics["quality_score"] = 0.0

        return metrics

    except subprocess.TimeoutExpired:
        return {
            "method": method_name,
            "status": "timeout",
            "duration_sec": config.get("timeout_sec", 600),
            "entities_processed": 0,
            "results_found": 0,
            "errors": 1,
            "high_value": 0,
            "quality_score": 0.0,
        }
    except Exception as e:
        return {
            "method": method_name,
            "status": "error",
            "error": str(e),
            "duration_sec": time.time() - start,
            "entities_processed": 0,
            "results_found": 0,
            "errors": 1,
            "high_value": 0,
            "quality_score": 0.0,
        }


def compare_methods(method_results: dict[str, dict]) -> str:
    """Compare method results and recommend which to scale."""
    best_method = None
    best_score = -1

    for name, metrics in method_results.items():
        score = metrics.get("quality_score", 0)
        if score > best_score and metrics.get("status") == "completed":
            best_score = score
            best_method = name

    return best_method or "http_outlink"


def adaptive_report(
    groups: dict[str, list[dict]],
    method_results: dict[str, dict],
    recommended_scale: str,
) -> dict:
    """Generate adaptive report with strategy recommendations."""
    strategy_counts = {k: len(v) for k, v in groups.items()}

    # Per-method quality ranking
    method_ranking = sorted(
        method_results.items(),
        key=lambda x: x[1].get("quality_score", 0),
        reverse=True,
    )

    total_entities = sum(strategy_counts.values())
    total_results = sum(m.get("results_found", 0) for m in method_results.values())
    total_errors = sum(m.get("errors", 0) for m in method_results.values())

    return {
        "generated_at": now_cst(),
        "schema_version": SCHEMA_VERSION,
        "decision": "atlas_adaptive_orchestration_report",
        "input": {
            "total_entities": total_entities,
            "strategy_distribution": strategy_counts,
        },
        "methods": {
            name: {
                "status": m.get("status"),
                "quality_score": m.get("quality_score"),
                "entities_processed": m.get("entities_processed"),
                "results_found": m.get("results_found"),
                "high_value": m.get("high_value"),
                "errors": m.get("errors"),
                "duration_sec": m.get("duration_sec"),
            }
            for name, m in method_results.items()
        },
        "method_ranking": [
            {"rank": i + 1, "method": name, "quality_score": m.get("quality_score")}
            for i, (name, m) in enumerate(method_ranking)
        ],
        "recommended_scale_method": recommended_scale,
        "total_results": total_results,
        "total_errors": total_errors,
        "quality_summary": {
            "best_method": method_ranking[0][0] if method_ranking else "none",
            "best_score": method_ranking[0][1].get("quality_score", 0) if method_ranking else 0,
            "methods_with_results": sum(
                1 for m in method_results.values() if m.get("results_found", 0) > 0
            ),
            "methods_failed": sum(
                1 for m in method_results.values() if m.get("status") not in ("completed", "skipped")
            ),
        },
        "adaptive_recommendations": generate_recommendations(method_results, groups),
        "safety": {
            "accepted_for_graph": False,
            "graph_write_allowed": False,
            "report_only": True,
        },
    }


def generate_recommendations(
    method_results: dict[str, dict], groups: dict[str, list[dict]]
) -> list[str]:
    """Generate actionable recommendations based on results."""
    recs = []

    for method_name, metrics in method_results.items():
        if metrics.get("status") == "skipped":
            recs.append(f"[SKIP] {method_name}: {metrics.get('reason', 'unknown')} — implement or skip")
        elif metrics.get("status") == "failed":
            recs.append(f"[FALLBACK] {method_name} failed (rc={metrics.get('returncode')}) — use fallback methods for affected entities")
        elif metrics.get("quality_score", 0) > 0.5:
            recs.append(f"[SCALE] {method_name}: quality_score={metrics['quality_score']} — scale this method to more entities")
        elif metrics.get("quality_score", 0) > 0:
            recs.append(f"[KEEP] {method_name}: quality_score={metrics['quality_score']} — continue at current scale, try alternatives in parallel")
        else:
            recs.append(f"[DEPRIORITIZE] {method_name}: quality_score=0 — deprioritize, try other methods first")

    return recs


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load cross-validated entities
    print("Loading cross-validated queue...", file=sys.stderr)
    entities = load_cross_validated_queue()
    if not entities:
        print("ERROR: No entities to process. Run cross-validation first.", file=sys.stderr)
        # Fallback: try to process review queue directly if cross-validation isn't ready
        if REVIEW_QUEUE.exists():
            print("Falling back to raw review queue...", file=sys.stderr)
            with open(REVIEW_QUEUE) as f:
                entities = [json.loads(line) for line in f]
            # Assign default strategy
            for e in entities:
                e["recommended_strategy"] = "maigret_first"
        else:
            sys.exit(1)

    groups = group_by_strategy(entities)
    print(f"Entities: {len(entities)} in {len(groups)} strategy groups", file=sys.stderr)
    for strategy, ents in groups.items():
        print(f"  {strategy}: {len(ents)} entities", file=sys.stderr)

    # Determine which methods to run based on available strategies
    methods_to_run = set()
    for strategy in groups:
        config = STRATEGY_METHOD_MAP.get(strategy, {})
        for method in config.get("primary", []):
            methods_to_run.add(method)

    print(f"\nMethods to run: {methods_to_run}", file=sys.stderr)

    # Run each method
    method_results = {}
    for method_name in methods_to_run:
        config = METHOD_CONFIGS.get(method_name)
        if not config:
            print(f"WARNING: no config for method '{method_name}'", file=sys.stderr)
            continue
        result = run_method(method_name, config)
        method_results[method_name] = result

        # Brief pause between methods
        if len(methods_to_run) > 1:
            time.sleep(2)

    # Compare and recommend
    recommended_scale = compare_methods(method_results)
    print(f"\nRecommended scale method: {recommended_scale}", file=sys.stderr)

    # Generate report
    report = adaptive_report(groups, method_results, recommended_scale)

    report_path = OUT_DIR / "adaptive_orchestration_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\nReport: {report_path}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
