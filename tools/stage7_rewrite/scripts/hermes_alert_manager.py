"""Evaluate Hermes alert rules against a local metrics snapshot."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from hermes_monitor_common import now_iso, read_json_if_exists, reject_d_path, write_json, write_text


DEFAULT_RULES = Path("hermes_alert_rules.yaml")
DEFAULT_METRICS = Path("reports/hermes_metrics_20260515/metrics_snapshot.json")
DEFAULT_OUT_DIR = Path("reports/hermes_alerts_20260515")
SCHEMA_VERSION = "stage7_hermes_alerts.v1"


def load_rules(path: Path) -> dict[str, Any]:
    reject_d_path(path, "rules")
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def add_alert(alerts: list[dict[str, Any]], severity: str, code: str, message: str) -> None:
    alerts.append({"severity": severity, "code": code, "message": message})


def evaluate_alerts(metrics: dict[str, Any], rules: dict[str, Any] | None = None) -> dict[str, Any]:
    rules = rules or {}
    thresholds = rules.get("thresholds") or {}
    alerts: list[dict[str, Any]] = []

    publish_gate = metrics.get("publish_gate") or {}
    if publish_gate.get("blocking_count", 0):
        add_alert(alerts, "amber", "consumer_publish_gate_blocked", f"publish gate has {publish_gate.get('blocking_count')} blocker(s)")
    if publish_gate.get("missing_publish_time_articles", 0):
        limit = int(thresholds.get("max_missing_publish_time_articles_for_production", 0))
        if int(publish_gate.get("missing_publish_time_articles") or 0) > limit:
            add_alert(alerts, "amber", "publish_time_unknown", f"{publish_gate.get('missing_publish_time_articles')} articles still lack publish_time")

    p1_social = metrics.get("p1_social") or {}
    if not p1_social.get("verify_ok"):
        add_alert(alerts, "red", "p1_social_verify_not_ok", "P1 social staging verification is not OK")
    if int(p1_social.get("non_staging_only_edges") or 0) > int(thresholds.get("max_non_staging_social_edges", 0)):
        add_alert(alerts, "red", "p1_social_non_staging_edges", "P1 social run contains non-staging edges")

    ocr_recovery = metrics.get("ocr_recovery") or {}
    if int(ocr_recovery.get("missing_count") or 0) > 0 and not ocr_recovery.get("has_non_dajiala_image_evidence"):
        add_alert(alerts, "amber", "ocr_recovery_blocked_by_missing_assets", "remaining OCR lane has no non-Dajiala image evidence")

    for service, status in (metrics.get("services") or {}).items():
        if status and not status.get("ok"):
            add_alert(alerts, "red", f"service_unreachable:{service}", f"{service} probe failed")

    counts = Counter(alert["severity"] for alert in alerts)
    decision = "red" if counts.get("red") else "amber" if counts.get("amber") else "green"
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "alerts": alerts,
        "counts": dict(counts),
        "writes": "reports_only",
    }


def write_alerts(out_dir: Path, report: dict[str, Any]) -> None:
    reject_d_path(out_dir, "out_dir")
    write_json(out_dir / "alerts.json", report)
    lines = ["# Hermes Alerts", "", f"- generated_at: `{report['generated_at']}`", f"- decision: `{report['decision']}`", ""]
    if report["alerts"]:
        for alert in report["alerts"]:
            lines.append(f"- `{alert['severity']}` `{alert['code']}`: {alert['message']}")
    else:
        lines.append("- none")
    lines.append("")
    write_text(out_dir / "alerts.md", "\n".join(lines))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", type=Path, default=DEFAULT_RULES)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--mode", choices=["canary", "snapshot"], default="canary")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    metrics = read_json_if_exists(args.metrics)
    rules = load_rules(args.rules)
    report = evaluate_alerts(metrics, rules)
    write_alerts(args.out_dir, report)
    print(json.dumps({"ok": True, "decision": report["decision"], "alerts": len(report["alerts"]), "report": str(args.out_dir / "alerts.json")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
