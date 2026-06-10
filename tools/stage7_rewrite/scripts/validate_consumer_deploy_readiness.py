#!/usr/bin/env python3
"""Validate PRD-08 consumer deploy readiness without deploying.

This report-only gate combines release pointer, unknown-time compatibility,
Qdrant aliases, local CloudRun smoke, graph promotion readiness, and publish
gate evidence. It never uploads, publishes, writes production SQLite, switches
consumer config, or mutates graph/vector state.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_OUT_DIR = Path("reports/consumer_deploy_readiness_20260515")
DEFAULT_POINTER_SMOKE = Path("reports/consumer_release_pointer_smoke_20260514/consumer_release_pointer_smoke.json")
DEFAULT_UNKNOWN_TIME = Path("reports/consumer_unknown_time_compat_20260514/consumer_unknown_time_compat.json")
DEFAULT_PUBLISH_GATE = Path("reports/consumer_publish_gate_review_20260515/consumer_publish_gate_review.json")
DEFAULT_E2E = Path("reports/e2e_integration_20260515/e2e_integration_report.json")
DEFAULT_WEEKLY_PATH = Path("reports/weekly_publish_path_decision_20260515/weekly_publish_path_decision.json")
DEFAULT_GRAPH_PROMOTION = Path("reports/graph_promotion_readiness_refresh_20260516/graph_promotion_readiness.json")
DEFAULT_QDRANT_URI = "http://127.0.0.1:6333"
DEFAULT_CLOUDRUN_BASE = "http://127.0.0.1:8787"
REQUIRED_QDRANT_ALIASES = [
    "wechat_stage7_article_qwen3_embedding_4b_1024_current",
    "wechat_stage7_entity_qwen3_embedding_4b_1024_current",
    "wechat_stage7_event_qwen3_embedding_4b_1024_current",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def require_local_uri(uri: str, label: str) -> None:
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"{label} URI must be local for report-only readiness: {uri}")


def qdrant_alias_check(qdrant_uri: str) -> dict[str, Any]:
    require_local_uri(qdrant_uri, "Qdrant")
    response = requests.get(f"{qdrant_uri.rstrip('/')}/aliases", timeout=15)
    response.raise_for_status()
    payload = response.json()
    aliases = payload.get("result", {}).get("aliases") or []
    alias_map = {item.get("alias_name"): item.get("collection_name") for item in aliases if isinstance(item, dict)}
    missing = [alias for alias in REQUIRED_QDRANT_ALIASES if alias not in alias_map]
    return {
        "ok": not missing,
        "required_aliases": REQUIRED_QDRANT_ALIASES,
        "missing_aliases": missing,
        "alias_targets": {alias: alias_map.get(alias) for alias in REQUIRED_QDRANT_ALIASES},
    }


def local_cloudrun_smoke(base_url: str) -> dict[str, Any]:
    require_local_uri(base_url, "CloudRun")
    paths = [
        "/healthz",
        "/api/v1/weekly/manifest",
        "/api/v1/weekly/current?limit=1",
    ]
    results = []
    for path in paths:
        url = f"{base_url.rstrip('/')}{path}"
        try:
            response = requests.get(url, timeout=15)
            body = response.text[:240]
            json_like = False
            try:
                response.json()
                json_like = True
            except ValueError:
                json_like = False
            results.append(
                {
                    "url": url,
                    "status_code": response.status_code,
                    "ok": 200 <= response.status_code < 300,
                    "json_like": json_like,
                    "body_preview": body,
                }
            )
        except requests.RequestException as exc:
            results.append({"url": url, "status_code": None, "ok": False, "error": str(exc)[:240]})
    return {"ok": all(item["ok"] and item.get("json_like", False) for item in results), "results": results}


def build_decision(
    *,
    pointer_smoke: dict[str, Any],
    unknown_time: dict[str, Any],
    publish_gate: dict[str, Any],
    e2e: dict[str, Any],
    weekly_path: dict[str, Any],
    graph_promotion: dict[str, Any],
    qdrant_aliases: dict[str, Any],
    cloudrun_smoke: dict[str, Any],
) -> dict[str, Any]:
    release_pointer_ok = bool(pointer_smoke.get("ok"))
    unknown_time_ok = bool(unknown_time.get("ok"))
    publish_allowed = bool(publish_gate.get("publish_allowed"))
    local_e2e_ready = bool(e2e.get("ok"))
    weekly_route_ready = bool(weekly_path.get("ok")) and weekly_path.get("recommended_path") == "weekly_recommendation_pipeline_for_weekly_publish"
    weekly_production_ready = bool(weekly_path.get("production_ready"))
    graph_promotion_allowed = bool(graph_promotion.get("promotion_allowed"))
    qdrant_aliases_present = bool(qdrant_aliases.get("ok"))
    cloudrun_local_ready = bool(cloudrun_smoke.get("ok"))
    publish_target = publish_gate.get("publish_target") or {}
    production_endpoint_configured = bool(
        publish_target.get("cloudbase_env") or publish_target.get("cloudrun_service") or publish_target.get("production_endpoint")
    )
    production_publish_policy_allows = bool(
        publish_gate.get("production_publish_allowed") or publish_gate.get("publish_allowed")
    )
    production_sqlite_write_allowed = bool(publish_gate.get("production_sqlite_write_allowed"))

    blockers = []
    if not production_publish_policy_allows:
        blockers.append("PRODUCTION_PUBLISH is globally forbidden")
    if not production_sqlite_write_allowed:
        blockers.append("PRODUCTION_SQLITE_WRITE is globally forbidden")
    if not publish_allowed:
        blockers.extend(publish_gate.get("blocking_reasons") or ["consumer publish gate is blocked"])
    if not graph_promotion_allowed:
        blockers.append("PRD-07 graph production promotion is blocked")
    if not weekly_production_ready:
        blockers.append("weekly publish path is report-only and production_ready=false")
    if not production_endpoint_configured:
        blockers.append("production CloudRun/CloudBase endpoint is not configured in this report-only run")
    if not release_pointer_ok:
        blockers.append("release pointer smoke failed")
    if not unknown_time_ok:
        blockers.append("unknown-time compatibility failed")
    if not qdrant_aliases_present:
        blockers.append("required Qwen3 Qdrant aliases are missing")
    if not cloudrun_local_ready:
        blockers.append("local CloudRun smoke failed")

    deploy_allowed = (
        release_pointer_ok
        and unknown_time_ok
        and local_e2e_ready
        and weekly_route_ready
        and qdrant_aliases_present
        and cloudrun_local_ready
        and publish_allowed
        and graph_promotion_allowed
        and weekly_production_ready
        and production_endpoint_configured
        and production_publish_policy_allows
        and production_sqlite_write_allowed
    )
    return {
        "schema_version": "stage7_consumer_deploy_readiness.v1",
        "generated_at": now_iso(),
        "ok": True,
        "decision": "consumer_deploy_ready" if deploy_allowed else "consumer_deploy_blocked_report_ready",
        "deploy_allowed": deploy_allowed,
        "report_only": True,
        "gates": {
            "release_pointer_ok": release_pointer_ok,
            "unknown_time_ok": unknown_time_ok,
            "local_e2e_ready": local_e2e_ready,
            "weekly_route_ready": weekly_route_ready,
            "weekly_production_ready": weekly_production_ready,
            "qdrant_aliases_present": qdrant_aliases_present,
            "cloudrun_local_ready": cloudrun_local_ready,
            "publish_allowed": publish_allowed,
            "graph_promotion_allowed": graph_promotion_allowed,
            "production_endpoint_configured": production_endpoint_configured,
            "production_publish_policy_allows": production_publish_policy_allows,
            "production_sqlite_write_allowed": production_sqlite_write_allowed,
        },
        "blockers": blockers,
        "qdrant_aliases": qdrant_aliases,
        "cloudrun_smoke": cloudrun_smoke,
        "evidence": {
            "pointer_smoke_decision": pointer_smoke.get("decision"),
            "unknown_time_decision": unknown_time.get("decision"),
            "publish_gate_decision": publish_gate.get("decision"),
            "e2e_decision": e2e.get("decision"),
            "weekly_path_decision": weekly_path.get("decision"),
            "graph_promotion_decision": graph_promotion.get("decision"),
        },
        "required_before_real_deploy": [
            "Lift production publish and production SQLite write bans in the current authority layer.",
            "Pass PRD-03 publish gate with explicit unknown-time business acceptance and rollback owner.",
            "Pass PRD-07 graph promotion or explicitly configure consumer to remain staging/read-only.",
            "Configure a production CloudRun/CloudBase endpoint and post-deploy smoke target.",
            "Keep old stella aliases and rollback pointer available.",
            "Run deploy and post-deploy smoke in a separately authorized production deploy gate.",
        ],
        "safety": {
            "production_publish_executed": False,
            "production_sqlite_write_executed": False,
            "cloud_deploy_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
        "writes": "reports_only",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Consumer Deploy Readiness",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- deploy_allowed: `{report['deploy_allowed']}`",
        "",
        "## Gates",
        "",
    ]
    for key, value in report["gates"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Blockers", ""])
    if report["blockers"]:
        for blocker in report["blockers"]:
            lines.append(f"- {blocker}")
    else:
        lines.append("- none")
    lines.extend(["", "## Qdrant Aliases", ""])
    for alias, target in (report["qdrant_aliases"].get("alias_targets") or {}).items():
        lines.append(f"- `{alias}` -> `{target}`")
    lines.extend(["", "## CloudRun Local Smoke", ""])
    for item in report["cloudrun_smoke"].get("results") or []:
        lines.append(f"- `{item['url']}` status=`{item.get('status_code')}` ok=`{item.get('ok')}`")
    lines.extend(["", "## Required Before Real Deploy", ""])
    for item in report["required_before_real_deploy"]:
        lines.append(f"- {item}")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only.",
            "- Local Qdrant alias reads and local CloudRun HTTP smoke only.",
            "- No cloud deploy, publish, production SQLite write, graph/vector write, mem0 write, paid API, or D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    qdrant_aliases = {} if args.skip_live else qdrant_alias_check(args.qdrant_uri)
    cloudrun_smoke = {} if args.skip_live else local_cloudrun_smoke(args.cloudrun_base_url)
    report = build_decision(
        pointer_smoke=read_json(args.pointer_smoke),
        unknown_time=read_json(args.unknown_time_report),
        publish_gate=read_json(args.publish_gate_report),
        e2e=read_json(args.e2e_report),
        weekly_path=read_json(args.weekly_path_report),
        graph_promotion=read_json(args.graph_promotion_report),
        qdrant_aliases=qdrant_aliases,
        cloudrun_smoke=cloudrun_smoke,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "consumer_deploy_readiness.json", report)
    write_markdown(args.out_dir / "consumer_deploy_readiness.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "deploy_allowed": report["deploy_allowed"],
                "blockers": report["blockers"],
                "report": str(args.out_dir / "consumer_deploy_readiness.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] or args.report_only_exit_zero else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--pointer-smoke", type=Path, default=DEFAULT_POINTER_SMOKE)
    parser.add_argument("--unknown-time-report", type=Path, default=DEFAULT_UNKNOWN_TIME)
    parser.add_argument("--publish-gate-report", type=Path, default=DEFAULT_PUBLISH_GATE)
    parser.add_argument("--e2e-report", type=Path, default=DEFAULT_E2E)
    parser.add_argument("--weekly-path-report", type=Path, default=DEFAULT_WEEKLY_PATH)
    parser.add_argument("--graph-promotion-report", type=Path, default=DEFAULT_GRAPH_PROMOTION)
    parser.add_argument("--qdrant-uri", default=DEFAULT_QDRANT_URI)
    parser.add_argument("--cloudrun-base-url", default=DEFAULT_CLOUDRUN_BASE)
    parser.add_argument("--skip-live", action="store_true")
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
