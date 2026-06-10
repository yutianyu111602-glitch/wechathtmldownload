#!/usr/bin/env python3
r"""Atlas Outlink Quality Monitor — periodic quality check + strategy adjustment.

Runs after each outlink batch to:
1. Check output quality (high_value rate, error rate, platform yield)
2. Compare against previous batches (trend detection)
3. Recommend strategy adjustments if quality degrades
4. Write quality report for automated decision-making
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────────────────────
STAGE7_ROOT = Path(
    "/mnt/c/code/githubstar/wechathtmldownload/tools/stage7_rewrite"
)
REPORTS_DIR = STAGE7_ROOT / "reports"
QUALITY_DIR = REPORTS_DIR / "atlas_quality_monitor_20260521"
QUALITY_LOG = QUALITY_DIR / "quality_monitor_log.jsonl"
SCHEMA_VERSION = "stage7_atlas_quality_monitor.v1"

# Quality thresholds
MIN_HIGH_VALUE_RATE = 0.03  # 3% of outlinks should be high-value
MIN_FETCH_SUCCESS_RATE = 0.10  # 10% fetch success
MAX_ERROR_RATE = 0.50  # 50% max error rate
QUALITY_DEGRADE_THRESHOLD = 0.3  # 30% drop from previous batch triggers adjustment

# Known output directories to scan
OUTLINK_DIRS = sorted(
    [d for d in REPORTS_DIR.glob("atlas_social_profile_outlinks_*")]
    if REPORTS_DIR.exists() else [],
    key=lambda p: p.stat().st_mtime if p.exists() else 0,
    reverse=True,
)

MAIGRET_DIRS = sorted(
    [d for d in REPORTS_DIR.glob("atlas_maigret_*")]
    if REPORTS_DIR.exists() else [],
    key=lambda p: p.stat().st_mtime if p.exists() else 0,
    reverse=True,
)

CROSS_VALIDATION_DIR = REPORTS_DIR / "atlas_cross_validation_20260521"
ADAPTIVE_DIR = REPORTS_DIR / "atlas_adaptive_outlink_20260521"


def now_cst() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def scan_batch_quality(batch_dir: Path) -> dict | None:
    """Scan a batch output directory and compute quality metrics."""
    summary_path = batch_dir / "atlas_social_profile_outlinks_summary.json"
    if not summary_path.exists():
        return None

    with open(summary_path) as f:
        summary = json.load(f)

    outlinks_path = batch_dir / "atlas_social_profile_outlinks.jsonl"
    errors_path = batch_dir / "atlas_social_profile_outlink_errors.jsonl"
    followup_path = batch_dir / "atlas_social_outlink_followup_queue.jsonl"

    outlink_count = sum(1 for _ in open(outlinks_path)) if outlinks_path.exists() else 0
    error_count = sum(1 for _ in open(errors_path)) if errors_path.exists() else 0
    followup_count = sum(1 for _ in open(followup_path)) if followup_path.exists() else 0

    input_rows = summary.get("input_rows", summary.get("selected_profile_rows", 0))
    high_value = summary.get("high_value_followup_rows", followup_count)

    # Platform distribution
    platform_counts = summary.get("outlink_platform_counts", summary.get("platform_counts", {}))
    outlink_kinds = summary.get("outlink_kind_counts", {})

    # Fetch status
    fetch_status = summary.get("profile_fetch_status_counts", {})

    metrics = {
        "batch_dir": str(batch_dir),
        "input_rows": input_rows,
        "outlink_count": outlink_count,
        "error_count": error_count,
        "high_value_count": high_value,
        "followup_count": followup_count,
        "high_value_rate": round(high_value / max(input_rows, 1), 4),
        "fetch_success_rate": round(
            fetch_status.get("fetched", 0) / max(input_rows, 1), 4
        ),
        "error_rate": round(error_count / max(input_rows + error_count, 1), 4),
        "top_platforms": dict(
            sorted(platform_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        ) if platform_counts else {},
        "top_outlink_kinds": dict(
            sorted(outlink_kinds.items(), key=lambda x: x[1], reverse=True)[:5]
        ) if outlink_kinds else {},
        "decision": summary.get("decision", "unknown"),
        "accepted_for_graph": summary.get("accepted_for_graph", 0),
    }

    return metrics


def scan_maigret_quality(batch_dir: Path) -> dict | None:
    """Scan a Maigret batch directory."""
    results_path = batch_dir / "maigret_results.jsonl"
    if not results_path.exists():
        return None

    lines = sum(1 for _ in open(results_path))
    return {
        "batch_dir": str(batch_dir),
        "results_count": lines,
    }


def compare_with_previous(current: dict, previous: dict | None) -> dict:
    """Compare current batch quality with previous and detect trends."""
    if not previous:
        return {"trend": "first_batch", "changes": []}

    changes = []
    for key in ["high_value_rate", "fetch_success_rate", "error_rate"]:
        if key in current and key in previous:
            prev_val = previous[key]
            curr_val = current[key]
            if prev_val > 0:
                change_pct = (curr_val - prev_val) / prev_val
                if abs(change_pct) >= QUALITY_DEGRADE_THRESHOLD:
                    direction = "improved" if change_pct > 0 else "degraded"
                    changes.append({
                        "metric": key,
                        "previous": prev_val,
                        "current": curr_val,
                        "change_pct": round(change_pct * 100, 1),
                        "direction": direction,
                    })

    if not changes:
        return {"trend": "stable", "changes": []}

    degraded_count = sum(1 for c in changes if c["direction"] == "degraded")
    if degraded_count >= 2:
        trend = "degrading"
    elif degraded_count == 1:
        trend = "minor_degradation"
    elif all(c["direction"] == "improved" for c in changes):
        trend = "improving"
    else:
        trend = "mixed"

    return {"trend": trend, "changes": changes}


def recommend_adjustments(current: dict, trend: dict) -> list[str]:
    """Generate strategy adjustment recommendations."""
    recs = []

    # High-value rate checks
    hr = current.get("high_value_rate", 0)
    if hr < MIN_HIGH_VALUE_RATE:
        recs.append("[ADJUST] High-value rate too low ({:.1%}) — try broader query formulations (name_dj, name_electronic)".format(hr))
    elif hr > 0.10:
        recs.append("[KEEP] High-value rate excellent ({:.1%}) — continue current strategy".format(hr))

    # Error rate checks
    er = current.get("error_rate", 0)
    if er > MAX_ERROR_RATE:
        recs.append("[ADJUST] Error rate critical ({:.1%}) — increase sleep interval, reduce batch size, check network".format(er))
        recs.append("[FALLBACK] Switch to Scrapling or OpenCLI for blocked platforms")
    elif er > 0.30:
        recs.append("[WARN] Error rate elevated ({:.1%}) — monitor next batch".format(er))

    # Fetch success checks
    fs = current.get("fetch_success_rate", 0)
    if fs < MIN_FETCH_SUCCESS_RATE:
        recs.append("[ADJUST] Fetch rate too low ({:.1%}) — try alternative fetch modes (scrapling, opencli)".format(fs))

    # Platform yield analysis
    platforms = current.get("top_platforms", {})
    if platforms:
        best_platform = max(platforms.items(), key=lambda x: x[1]) if platforms else ("none", 0)
        recs.append(f"[ANALYSIS] Top platform: {best_platform[0]} ({best_platform[1]} hits) — prioritize this platform")
        
        # If only one platform dominates, try diversifying
        if len(platforms) == 1 and list(platforms.values())[0] > 10:
            recs.append("[DIVERSIFY] Single platform dominance — try adding social platforms (Instagram, Linktree)")

    # Outlink kind analysis
    kinds = current.get("top_outlink_kinds", {})
    if kinds:
        music_kinds = sum(
            v for k, v in kinds.items()
            if k in ("audio_profile", "audio_track_candidate", "audio_collection_or_mixtape")
        )
        if music_kinds == 0:
            recs.append("[ADJUST] No music outlinks found — try music-first platform priority (SC, BC, RA)")

    # Trend-based adjustments
    if trend.get("trend") == "degrading":
        recs.append("[URGENT] Quality degrading across multiple metrics — pause and investigate")
    elif trend.get("trend") == "improving":
        recs.append("[SCALE] Quality improving — safe to increase batch size or add parallel methods")

    # Strategy routing based on entity type yield
    per_type = current.get("per_type_performance", {})
    if not per_type:
        recs.append("[TEST] Run search_strategy_variations.py to determine optimal query per entity type")

    return recs


def main():
    QUALITY_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": now_cst(),
        "schema_version": SCHEMA_VERSION,
        "decision": "atlas_quality_monitor_report_only",
    }

    # Scan outlink batches
    outlink_metrics = []
    for batch_dir in OUTLINK_DIRS[:5]:
        metrics = scan_batch_quality(batch_dir)
        if metrics:
            outlink_metrics.append(metrics)

    # Scan Maigret batches
    maigret_metrics = []
    for batch_dir in MAIGRET_DIRS[:3]:
        metrics = scan_maigret_quality(batch_dir)
        if metrics:
            maigret_metrics.append(metrics)

    report["outlink_batches"] = outlink_metrics
    report["maigret_batches"] = maigret_metrics

    # Latest batch quality
    latest = outlink_metrics[0] if outlink_metrics else None
    previous = outlink_metrics[1] if len(outlink_metrics) > 1 else None

    if latest:
        report["latest_quality"] = {
            "high_value_rate": latest["high_value_rate"],
            "fetch_success_rate": latest["fetch_success_rate"],
            "error_rate": latest["error_rate"],
            "top_platform": max(latest.get("top_platforms", {}).items(), key=lambda x: x[1])[0]
            if latest.get("top_platforms") else "none",
        }

        trend = compare_with_previous(latest, previous)
        report["trend"] = trend

        recommendations = recommend_adjustments(latest, trend)
        report["recommendations"] = recommendations
    else:
        report["latest_quality"] = None
        report["trend"] = {"trend": "no_data"}
        report["recommendations"] = ["[WAIT] No outlink batches found yet — waiting for Post-Filter + orchestration"]

    # Cross-validation status
    cv_summary = CROSS_VALIDATION_DIR / "atlas_cross_validation_summary.json"
    if cv_summary.exists():
        with open(cv_summary) as f:
            cv = json.load(f)
        report["cross_validation"] = {
            "strategy_distribution": cv.get("strategy_distribution", {}),
            "identity_url_entities": cv.get("identity_url_entities", 0),
        }

    # Adaptive orchestration status
    adaptive_report_path = ADAPTIVE_DIR / "adaptive_orchestration_report.json"
    if adaptive_report_path.exists():
        with open(adaptive_report_path) as f:
            ar = json.load(f)
        report["adaptive_orchestration"] = {
            "recommended_scale_method": ar.get("recommended_scale_method"),
            "best_score": ar.get("quality_summary", {}).get("best_score", 0),
        }

    # Safety
    report["safety"] = {
        "accepted_for_graph": False,
        "graph_write_allowed": False,
        "report_only": True,
    }

    # Write report
    report_path = QUALITY_DIR / "quality_monitor_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Append to log
    log_entry = {
        "time": now_cst(),
        "has_batches": len(outlink_metrics) > 0,
        "latest_quality": report.get("latest_quality"),
        "trend": report.get("trend", {}).get("trend"),
        "recommendation_count": len(report.get("recommendations", [])),
    }
    with open(QUALITY_LOG, "a") as f:
        f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    print(f"Report: {report_path}", file=sys.stderr)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
