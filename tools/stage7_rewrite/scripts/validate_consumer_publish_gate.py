"""Validate the P5 consumer production publish gate without publishing.

This gate checks that the staging release pointer and unknown-time compatibility
are green, then verifies whether a separate production publish config explicitly
defines endpoint mapping, rollback, post-publish smoke, and business acceptance
for unknown publish_time. It writes reports only.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_POINTER_SMOKE = Path("reports/consumer_release_pointer_smoke_20260514/consumer_release_pointer_smoke.json")
DEFAULT_UNKNOWN_TIME_COMPAT = Path("reports/consumer_unknown_time_compat_20260514/consumer_unknown_time_compat.json")
DEFAULT_PUBLISH_CONFIG = Path("config/consumer_publish_gate.local.json")
DEFAULT_OUT_DIR = Path("reports/consumer_publish_gate_review_20260515")
SCHEMA_VERSION = "stage7_consumer_publish_gate_review.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for consumer publish gate: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def first_text(value: Any) -> str:
    return str(value or "").strip()


def present(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return value is not None


def load_optional_config(path: Path) -> tuple[dict[str, Any], list[str]]:
    reject_d_path(path, "publish_config")
    if not path.exists():
        return {}, ["publish config missing"]
    config = read_json(path)
    errors: list[str] = []
    if first_text(config.get("schema_version")) != "stage7_consumer_publish_gate_config.v1":
        errors.append("publish config schema_version invalid")
    target = config.get("publish_target") or {}
    if first_text(target.get("channel")) != "production":
        errors.append("publish_target.channel must be production")
    for key in ["artifact_source", "upload_strategy"]:
        if not present(target.get(key)):
            errors.append(f"publish_target.{key} missing")
    rollback = config.get("rollback") or {}
    for key in ["previous_pointer_path", "rollback_owner"]:
        if not present(rollback.get(key)):
            errors.append(f"rollback.{key} missing")
    smoke = config.get("post_publish_smoke") or {}
    if not present(smoke.get("required_checks")):
        errors.append("post_publish_smoke.required_checks missing")
    if int(smoke.get("sample_count") or 0) <= 0:
        errors.append("post_publish_smoke.sample_count must be positive")
    acceptance = config.get("unknown_time_business_acceptance") or {}
    if not bool(acceptance.get("accepted")):
        errors.append("unknown publish_time production policy not accepted")
    for key in ["accepted_by", "accepted_at", "user_visible_policy"]:
        if not present(acceptance.get(key)):
            errors.append(f"unknown_time_business_acceptance.{key} missing")
    return config, errors


def validate_gate(
    pointer_smoke_path: Path,
    unknown_time_compat_path: Path,
    publish_config_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    pointer_smoke = read_json(pointer_smoke_path)
    compat = read_json(unknown_time_compat_path)
    config, config_errors = load_optional_config(publish_config_path)
    blocking: list[str] = []
    warnings: list[str] = []

    if not bool(pointer_smoke.get("ok")):
        blocking.append("consumer release pointer smoke is not ok")
    if first_text(pointer_smoke.get("decision")) != "consumer_staging_pointer_verified":
        blocking.append("consumer release pointer smoke decision is not verified")
    if not bool(pointer_smoke.get("release_ready")):
        blocking.append("consumer release pointer is not release_ready")
    if not bool(pointer_smoke.get("full_count")):
        blocking.append("consumer release pointer smoke did not full-count files")
    for error in pointer_smoke.get("errors") or []:
        blocking.append(f"pointer smoke error: {error}")

    if not bool(compat.get("ok")):
        blocking.append("consumer unknown-time compatibility is not ok")
    if first_text(compat.get("decision")) != "consumer_unknown_time_staging_compatible":
        blocking.append("consumer unknown-time compatibility decision is not compatible")
    for error in compat.get("errors") or []:
        blocking.append(f"unknown-time compat error: {error}")

    pack = compat.get("pack") or {}
    counts = pack.get("counts") or {}
    missing_publish_time = int(counts.get("missing_publish_time_articles") or 0)
    if missing_publish_time:
        warnings.append(f"{missing_publish_time} articles still have unknown publish_time")
    if config_errors:
        blocking.extend(config_errors)

    dry_run_ready = not blocking
    production_authorization = config.get("production_authorization") or {}
    production_publish_allowed = dry_run_ready and bool(production_authorization.get("production_publish_allowed"))
    production_sqlite_write_allowed = dry_run_ready and bool(
        production_authorization.get("production_sqlite_write_allowed")
    )
    production_graph_labels_allowed = dry_run_ready and bool(
        production_authorization.get("production_graph_labels_allowed")
    )
    publish_allowed = production_publish_allowed
    decision = (
        "consumer_publish_gate_ready"
        if publish_allowed
        else "consumer_publish_gate_dry_run_ready"
        if dry_run_ready
        else "consumer_publish_gate_blocked"
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": True,
        "dry_run_ready": dry_run_ready,
        "publish_allowed": publish_allowed,
        "production_publish_allowed": production_publish_allowed,
        "production_sqlite_write_allowed": production_sqlite_write_allowed,
        "production_graph_labels_allowed": production_graph_labels_allowed,
        "production_authorization": production_authorization,
        "publish_target": config.get("publish_target") or {},
        "writes": "reports_only",
        "pointer_smoke_path": str(pointer_smoke_path),
        "unknown_time_compat_path": str(unknown_time_compat_path),
        "publish_config_path": str(publish_config_path),
        "blocking_reasons": blocking,
        "warnings": warnings,
        "counts": counts,
        "pointer_smoke_decision": pointer_smoke.get("decision"),
        "unknown_time_compat_decision": compat.get("decision"),
        "publish_config_loaded": bool(config),
        "required_publish_gate_fields": [
            "publish_target.channel",
            "publish_target.artifact_source",
            "publish_target.upload_strategy",
            "rollback.previous_pointer_path",
            "rollback.rollback_owner",
            "post_publish_smoke.required_checks",
            "post_publish_smoke.sample_count",
            "unknown_time_business_acceptance.accepted",
            "unknown_time_business_acceptance.accepted_by",
            "unknown_time_business_acceptance.accepted_at",
            "unknown_time_business_acceptance.user_visible_policy",
        ],
        "safety": [
            "reports_only",
            "no_cloud_publish",
            "no_production_sqlite_write",
            "no_graph_vector_db_write",
            "no_paid_api",
            "no_d_scan",
        ],
    }
    write_json(out_dir / "consumer_publish_gate_review.json", report)
    write_markdown(out_dir / "consumer_publish_gate_review.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Consumer Publish Gate Review",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- dry_run_ready: `{report['dry_run_ready']}`",
        f"- publish_allowed: `{report['publish_allowed']}`",
        f"- publish_config_loaded: `{report['publish_config_loaded']}`",
        "",
        "## Blocking Reasons",
        "",
    ]
    if report["blocking_reasons"]:
        for reason in report["blocking_reasons"]:
            lines.append(f"- {reason}")
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    if report["warnings"]:
        for warning in report["warnings"]:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")
    lines.extend(["", "## Required Gate Fields", ""])
    for field in report["required_publish_gate_fields"]:
        lines.append(f"- `{field}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Reports only.",
            "- This gate never publishes or writes production stores.",
            "- `publish_allowed` is true only when dry-run is ready and `production_authorization.production_publish_allowed=true`; this report still does not execute upload/write.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer-smoke", type=Path, default=DEFAULT_POINTER_SMOKE)
    parser.add_argument("--unknown-time-compat", type=Path, default=DEFAULT_UNKNOWN_TIME_COMPAT)
    parser.add_argument("--publish-config", type=Path, default=DEFAULT_PUBLISH_CONFIG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    report = validate_gate(args.pointer_smoke, args.unknown_time_compat, args.publish_config, args.out_dir)
    print(
        json.dumps(
            {
                "decision": report["decision"],
                "dry_run_ready": report["dry_run_ready"],
                "publish_allowed": report["publish_allowed"],
                "blocking_reasons": report["blocking_reasons"],
                "summary": str(args.out_dir / "consumer_publish_gate_review.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
