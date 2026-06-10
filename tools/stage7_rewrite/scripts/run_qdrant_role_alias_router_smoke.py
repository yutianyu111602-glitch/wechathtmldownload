#!/usr/bin/env python3
"""Read-only router smoke through promoted Qdrant role aliases.

This consumes apply_qdrant_role_alias_gate.py output and probes the promoted
`*_current` aliases directly. It never writes Qdrant points or aliases, calls
models, touches Neo4j/SQLite/mem0, publishes, uses paid APIs, or scans D:.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_vector_collection_router_smoke import (  # noqa: E402
    build_router_cases,
    probe_collection,
    reject_d_root,
    require_local_url,
    write_json,
)


SCHEMA_VERSION = "stage7_qdrant_role_alias_router_smoke.v1"
DEFAULT_APPLY_REPORT = Path("reports/qdrant_role_alias_apply_47k_delta375_20260519/qdrant_role_alias_apply_report.json")
DEFAULT_OUT_DIR = Path("reports/qdrant_role_alias_router_smoke_47k_delta375_20260519")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_root(path, "json")
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def qdrant_aliases(qdrant_url: str) -> dict[str, str]:
    response = requests.get(f"{qdrant_url.rstrip('/')}/aliases", timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(f"GET aliases failed {response.status_code}: {response.text[:500]}")
    data = response.json()
    rows = ((data.get("result") or {}).get("aliases") or [])
    return {str(row["alias_name"]): str(row["collection_name"]) for row in rows}


def groups_from_apply_report(report: dict[str, Any]) -> dict[str, dict[str, str]]:
    targets = report.get("targets") or []
    if not isinstance(targets, list) or not targets:
        raise ValueError("apply report has no targets")
    groups: dict[str, dict[str, str]] = defaultdict(dict)
    for target in targets:
        role = str(target.get("role") or "")
        kind = str(target.get("kind") or "")
        alias = str(target.get("alias") or "")
        if not role or not kind or not alias:
            raise ValueError(f"apply target missing role/kind/alias: {target}")
        groups[role][kind] = alias
    return dict(groups)


def verify_alias_targets(report: dict[str, Any], current_aliases: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for target in report.get("targets") or []:
        alias = str(target.get("alias") or "")
        expected = str(target.get("collection") or "")
        actual = current_aliases.get(alias)
        if actual != expected:
            errors.append(f"alias_target_mismatch:{alias}:{actual}!={expected}")
    return errors


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Qdrant Role Alias Router Smoke",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        f"- apply_report: `{report['apply_report']}`",
        f"- sample_size_per_alias: `{report['sample_size_per_alias']}`",
        f"- top_k: `{report['top_k']}`",
        "",
        "## Alias Probes",
        "",
    ]
    for channel, probes in report["channel_probes"].items():
        for probe in probes:
            lines.append(
                f"- `{channel}` `{probe['kind']}` alias `{probe['collection']}` "
                f"{probe['matched']}/{probe['checked']} match_rate `{probe['match_rate']}`"
            )
    lines.extend(["", "## Router Cases", ""])
    for case in report["router_cases"]:
        lines.append(f"- `{case['id']}` lang `{case['lang']}` channels `{case['routed_channels']}` fused `{len(case['fused'])}`")
    lines.extend(["", "## Alias Target Verification", ""])
    if report["alias_target_errors"]:
        for error in report["alias_target_errors"]:
            lines.append(f"- `{error}`")
    else:
        lines.append("- all current aliases point to expected staging collections")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_url(args.qdrant_url, "qdrant_url")
    reject_d_root(args.apply_report, "apply_report")
    reject_d_root(args.out_dir, "out_dir")
    apply_report = read_json(args.apply_report)
    groups = groups_from_apply_report(apply_report)
    current_aliases = qdrant_aliases(args.qdrant_url)
    alias_target_errors = verify_alias_targets(apply_report, current_aliases)

    channel_probes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for channel, aliases in groups.items():
        for kind, alias in aliases.items():
            channel_probes[channel].append(
                probe_collection(
                    args.qdrant_url,
                    channel,
                    kind,
                    alias,
                    args.sample_size_per_alias,
                    args.top_k,
                    timeout_sec=args.qdrant_timeout_sec,
                )
            )
    router_cases = build_router_cases(channel_probes, args.top_k, route_mode="role_isolated")
    all_probes = [probe for probes in channel_probes.values() for probe in probes]
    ok = not alias_target_errors and all(probe["checked"] > 0 and probe["match_rate"] == 1.0 for probe in all_probes) and all(
        case["fused"] for case in router_cases
    )
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": ok,
        "decision": "qdrant_role_alias_router_smoke_ready" if ok else "qdrant_role_alias_router_smoke_needs_review",
        "qdrant_url": args.qdrant_url,
        "apply_report": str(args.apply_report),
        "sample_size_per_alias": args.sample_size_per_alias,
        "top_k": args.top_k,
        "qdrant_timeout_sec": args.qdrant_timeout_sec,
        "collection_groups": groups,
        "alias_targets_current": current_aliases,
        "alias_target_errors": alias_target_errors,
        "channel_probes": dict(channel_probes),
        "router_cases": router_cases,
        "safety": {
            "model_loaded": False,
            "embedding_call_executed": False,
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "qdrant_point_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "production_publish_executed": False,
            "d_scan_executed": False,
            "secret_read_executed": False,
            "router_9_used": False,
        },
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.out_dir / "qdrant_role_alias_router_smoke.json"
    md_path = args.out_dir / "qdrant_role_alias_router_smoke.md"
    write_json(report_path, report)
    write_markdown(md_path, report)
    print(
        json.dumps(
            {"ok": report["ok"], "decision": report["decision"], "report": str(report_path)},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if ok else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--apply-report", type=Path, default=DEFAULT_APPLY_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--sample-size-per-alias", type=int, default=3)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--qdrant-timeout-sec", type=int, default=60)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
