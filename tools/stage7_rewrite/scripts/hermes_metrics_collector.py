"""Collect local Stage7 Hermes metrics into a report-only snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hermes_heartbeat import http_probe
from hermes_monitor_common import latest_markdown_heading, now_iso, read_json_if_exists, reject_d_path, write_json, write_text


DEFAULT_OUT_DIR = Path("reports/hermes_metrics_20260515")
SCHEMA_VERSION = "stage7_hermes_metrics.v1"


def collect_metrics(root: Path, *, check_services: bool = False) -> dict[str, Any]:
    reject_d_path(root, "root")
    publish_gate = read_json_if_exists(root / "reports/consumer_publish_gate_review_20260515/consumer_publish_gate_review.json")
    social_verify = read_json_if_exists(root / "reports/neo4j_p1_social_staging_20260515/canary_verification.json")
    ocr_audit = read_json_if_exists(root / "reports/ocr_root_cause_20260515/non_dajiala_recoverability_audit_v30_20260515/summary.json")
    coverage = read_json_if_exists(root / "reports/ocr_root_cause_20260515/corrected_full_stable_extract_v30_deepseek_recovered1217_20260515/coverage_vs_fixed_routes.json")

    services: dict[str, Any] = {}
    if check_services:
        services = {
            "qdrant": http_probe("http://127.0.0.1:6333/"),
            "neo4j": http_probe("http://127.0.0.1:7474/"),
            "camofox": http_probe("http://127.0.0.1:9377/health"),
        }

    metrics = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "root": str(root),
        "longrun": {"last_round": latest_markdown_heading(root / "LONGRUN_STATE.md")},
        "publish_gate": {
            "decision": publish_gate.get("decision"),
            "dry_run_ready": bool(publish_gate.get("dry_run_ready")),
            "publish_allowed": bool(publish_gate.get("publish_allowed")),
            "blocking_count": len(publish_gate.get("blocking_reasons") or []),
            "warning_count": len(publish_gate.get("warnings") or []),
            "missing_publish_time_articles": (publish_gate.get("counts") or {}).get("missing_publish_time_articles"),
        },
        "p1_social": {
            "verify_ok": bool(social_verify.get("ok")),
            "has_profile_edges": (social_verify.get("counts") or {}).get("has_profile_edges"),
            "staging_only_edges": (social_verify.get("counts") or {}).get("staging_only_edges"),
            "non_staging_only_edges": (social_verify.get("counts") or {}).get("non_staging_only_edges"),
        },
        "ocr_recovery": {
            "missing_count": ocr_audit.get("missing_count"),
            "has_non_dajiala_image_evidence": any(
                int(value or 0) > 0
                for key, value in (ocr_audit.get("field_positive_counts") or {}).items()
                if key != "has_processed_assets_true"
            ),
        },
        "stable_coverage": {
            "label": coverage.get("label"),
            "totals": coverage.get("totals") or coverage.get("summary") or {},
        },
        "services": services,
        "metric_classes": ["pipeline_health", "service_health", "quality_gates", "cost_inputs"],
        "writes": "reports_only",
    }
    return metrics


def write_metrics(out_dir: Path, metrics: dict[str, Any]) -> None:
    reject_d_path(out_dir, "out_dir")
    write_json(out_dir / "metrics_snapshot.json", metrics)
    lines = [
        "# Hermes Metrics Snapshot",
        "",
        f"- generated_at: `{metrics['generated_at']}`",
        f"- publish_gate_decision: `{metrics['publish_gate']['decision']}`",
        f"- publish_gate_blocking_count: `{metrics['publish_gate']['blocking_count']}`",
        f"- p1_social_edges: `{metrics['p1_social']['has_profile_edges']}`",
        f"- ocr_missing_count: `{metrics['ocr_recovery']['missing_count']}`",
        f"- metric_classes: `{', '.join(metrics['metric_classes'])}`",
        "",
    ]
    write_text(out_dir / "metrics_summary.md", "\n".join(lines))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--mode", choices=["canary", "snapshot"], default="canary")
    parser.add_argument("--check-services", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    metrics = collect_metrics(args.root, check_services=args.check_services)
    write_metrics(args.out_dir, metrics)
    print(json.dumps({"ok": True, "mode": args.mode, "metrics": str(args.out_dir / "metrics_snapshot.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
