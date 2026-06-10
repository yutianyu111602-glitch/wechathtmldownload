#!/usr/bin/env python3
"""Build a no-deploy weekly release candidate dry-run report."""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


LEAK_RE = re.compile(r"https?://|www\.|mmbiz\.qpic\.cn|qpic\.cn|wx_fmt=|from=appmsg|#imgIndex=|openid", re.I)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"expected object JSON: {path}")
    return data


def count_observations(path: Path) -> tuple[int, int, int]:
    rows = 0
    source_hashes = 0
    leaks = 0
    with path.open("r", encoding="utf-8") as handle:
      for line in handle:
        if not line.strip():
            continue
        rows += 1
        row = json.loads(line)
        if row.get("source_url_hash"):
            source_hashes += 1
        if LEAK_RE.search(json.dumps(row, ensure_ascii=False)):
            leaks += 1
    return rows, source_hashes, leaks


def current_metrics(current: dict[str, Any]) -> dict[str, Any]:
    items = current.get("items") or []
    lineup = sum(bool(item.get("lineup_artists") or item.get("lineup")) for item in items)
    visible_leaks = 0
    for item in items:
        for key in ["description_original_lines", "dj_bio_lines"]:
            for line in item.get(key) or []:
                if LEAK_RE.search(str(line)):
                    visible_leaks += 1
    return {
        "items": len(items),
        "lineup_items": lineup,
        "missing_lineup": len(items) - lineup,
        "lineup_coverage": round(lineup / len(items), 4) if items else 0,
        "visible_text_leaks": visible_leaks,
    }


def snapshot_metrics(snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = snapshot.get("lineup_resolved") or []
    return {
        "lineup_rows": len(rows),
        "method_counts": dict(Counter(row.get("match_method") for row in rows)),
    }


def daily_queue_metrics(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"checked": False, "ok": True, "summary_path": "", "checks": {}}
    summary = load_json(path)

    def as_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    rows_written = as_int(summary.get("rows_written"))
    exporter_accounts_ok = as_int(summary.get("exporter_accounts_ok"))
    exporter_accounts_failed = as_int(summary.get("exporter_accounts_failed"))
    exporter_article_rows = as_int(summary.get("exporter_article_rows"))
    refresh_requested = bool(summary.get("exporter_refresh_requested"))
    refresh_effective = (
        refresh_requested
        and (
            (exporter_accounts_ok is not None and exporter_accounts_ok > 0)
            or (exporter_article_rows is not None and exporter_article_rows > 0)
        )
    )
    checks = {
        "daily_queue_summary_rows": rows_written is not None and rows_written > 0,
        "daily_queue_exporter_refresh_recorded": refresh_requested,
        "daily_queue_exporter_refresh_effective": refresh_effective,
    }
    return {
        "checked": True,
        "ok": all(checks.values()),
        "summary_path": str(path),
        "rows_written": rows_written,
        "exporter_refresh_requested": refresh_requested,
        "exporter_accounts_ok": exporter_accounts_ok,
        "exporter_accounts_failed": exporter_accounts_failed,
        "exporter_article_rows": exporter_article_rows,
        "checks": checks,
    }


def current_release_drift_metrics(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"checked": False, "ok": True, "summary_path": "", "checks": {}}
    summary = load_json(path)
    checks = {
        "current_release_no_default_deploy_drift": summary.get("ok") is True,
    }
    default_runtime = summary.get("default_runtime") if isinstance(summary.get("default_runtime"), dict) else {}
    deploy_context = summary.get("deploy_context") if isinstance(summary.get("deploy_context"), dict) else {}
    return {
        "checked": True,
        "ok": all(checks.values()),
        "summary_path": str(path),
        "decision": summary.get("decision"),
        "failed_checks": summary.get("failed_checks") or [],
        "preferred_current_authority": (summary.get("authority") or {}).get("preferred_current_authority")
        if isinstance(summary.get("authority"), dict)
        else None,
        "default_items": default_runtime.get("items_len"),
        "deploy_items": deploy_context.get("items_len"),
        "default_geo_coord_count": default_runtime.get("geo_coord_count"),
        "deploy_geo_coord_count": deploy_context.get("geo_coord_count"),
        "checks": checks,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    current = load_json(args.current)
    manifest = load_json(args.manifest)
    snapshot = load_json(args.snapshot)
    audit = load_json(args.audit)
    alias_summary = load_json(args.alias_summary)
    obs_rows, obs_hashes, obs_leaks = count_observations(args.observations)
    metrics = current_metrics(current)
    snap = snapshot_metrics(snapshot)
    daily_queue = daily_queue_metrics(args.daily_queue_summary)
    current_release_drift = current_release_drift_metrics(args.current_release_drift_summary)
    checks = {
        "items_meet_minimum": metrics["items"] >= args.expected_min_items,
        "visible_text_leaks_zero": metrics["visible_text_leaks"] == 0,
        "lineup_hard_fail_zero": audit.get("hard_fail_count") == 0,
        "observations_all_hashed": obs_rows > 0 and obs_rows == obs_hashes,
        "observations_leaks_zero": obs_leaks == 0,
        "alias_export_ready": alias_summary.get("ok") is True,
        "snapshot_has_lineup_rows": snap["lineup_rows"] > 0,
        "daily_queue_refresh_effective": daily_queue["ok"],
        "current_release_no_default_deploy_drift": current_release_drift["ok"],
    }
    ok = all(checks.values())
    return {
        "schema_version": "weekly_release_candidate_dry_run.v1",
        "decision": "release_candidate_local_gates_passed" if ok else "release_candidate_local_gates_blocked",
        "ok": ok,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "package": args.package,
        "manifest_generated_at": manifest.get("generated_at") or manifest.get("generatedAt"),
        "current": metrics,
        "snapshot": snap,
        "observations": {
            "rows": obs_rows,
            "source_url_hash": obs_hashes,
            "leak_hits": obs_leaks,
        },
        "audit": {
            "hard_fail_count": audit.get("hard_fail_count"),
            "summary": audit.get("summary") or {},
        },
        "alias_export": {
            "exported_entities": alias_summary.get("exported_entities"),
            "exported_alias_rows": alias_summary.get("exported_alias_rows"),
            "report_only": (alias_summary.get("safety") or {}).get("report_only"),
        },
        "daily_queue": daily_queue,
        "current_release_drift": current_release_drift,
        "checks": checks,
        "production_write_executed": False,
        "cloudrun_deploy_executed": False,
        "miniprogram_upload_executed": False,
        "wechat_review_submitted": False,
    }


def write_outputs(out_dir: Path, report: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "weekly_release_candidate_dry_run.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    notes = [
        "# Weekly Release Candidate Dry Run",
        "",
        f"- decision: `{report['decision']}`",
        f"- ok: `{str(report['ok']).lower()}`",
        f"- package: `{report['package']}`",
        f"- items: `{report['current']['items']}`",
        f"- lineup_coverage: `{report['current']['lineup_coverage']}`",
        f"- current_release_drift_ok: `{str(report['current_release_drift']['ok']).lower()}`",
        f"- backend writes/deploy/upload/review: `false`",
        "",
        "This is a local dry-run artifact only.",
        "",
    ]
    (out_dir / "weekly_release_candidate_dry_run.md").write_text("\n".join(notes), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--alias-summary", type=Path, required=True)
    parser.add_argument("--daily-queue-summary", type=Path)
    parser.add_argument("--current-release-drift-summary", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--package", default="WEEKLY_ACTIVITY_MINIPROGRAM_API_20260520")
    parser.add_argument("--expected-min-items", type=int, default=80)
    args = parser.parse_args()

    report = build_report(args)
    write_outputs(args.out_dir, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
