#!/usr/bin/env python3
"""Build a report-only Qdrant role-alias promotion gate packet.

This script validates current role-isolated full-wave staging collections and
proposes stable aliases for the atlas vector route. It never applies alias
changes, writes points, calls models, touches Neo4j/SQLite/mem0, uses paid
APIs, publishes, or scans D:.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


SCHEMA_VERSION = "stage7_qdrant_role_alias_gate.v1"
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
DEFAULT_OUT_DIR = Path("reports/qdrant_role_alias_gate_47k_delta375_20260519")
CONFIRM_TOKEN = "ENABLE_QDRANT_ROLE_ALIAS_PROMOTE"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_root(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def require_local_qdrant(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Qdrant URL must be local for role alias gate: {url}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_root(path, "json")
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def slug(text: str) -> str:
    value = text.strip().lower().replace("/", "_").replace("-", "_").replace(".", "_")
    return "_".join(part for part in "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value).split("_") if part)


def alias_name(kind: str, role: str, dim: int) -> str:
    return f"wechat_stage7_{slug(kind)}_{slug(role)}_{dim}_current"


def parse_role_report_arg(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"--role-report must be role=path, got: {value}")
    role, path = value.split("=", 1)
    role = role.strip()
    if not role:
        raise ValueError(f"--role-report role is empty: {value}")
    return role, Path(path.strip())


def qdrant_request(method: str, url: str, **kwargs) -> dict[str, Any]:
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 60), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed {response.status_code}: {response.text[:500]}")
    return response.json() if response.text else {}


def qdrant_aliases(qdrant_url: str) -> dict[str, str]:
    data = qdrant_request("GET", f"{qdrant_url.rstrip('/')}/aliases", timeout=30)
    rows = ((data.get("result") or {}).get("aliases") or [])
    return {str(row["alias_name"]): str(row["collection_name"]) for row in rows}


def qdrant_collection_info(qdrant_url: str, collection: str) -> dict[str, Any] | None:
    response = requests.get(f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}", timeout=30)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise RuntimeError(f"GET collection {collection} failed {response.status_code}: {response.text[:500]}")
    return response.json().get("result") or {}


def collection_health(qdrant_url: str, collection: str) -> dict[str, Any]:
    info = qdrant_collection_info(qdrant_url, collection)
    if info is None:
        return {"exists": False, "healthy": False, "status": "missing", "points_count": 0}
    optimizer_status = info.get("optimizer_status")
    return {
        "exists": True,
        "healthy": info.get("status") == "green" and (optimizer_status == "ok" or optimizer_status is None),
        "status": info.get("status"),
        "optimizer_status": optimizer_status,
        "points_count": int(info.get("points_count") or 0),
        "indexed_vectors_count": info.get("indexed_vectors_count"),
        "segments_count": info.get("segments_count"),
    }


def target_rows_from_report(role: str, report_path: Path) -> list[dict[str, Any]]:
    report = read_json(report_path)
    state = report.get("state") or {}
    plan = report.get("plan") or {}
    collections = state.get("collections") or plan.get("collections") or {}
    written_counts = state.get("written_counts") or {}
    qdrant_health = report.get("qdrant_health") or {}
    dim = int(state.get("dim") or plan.get("dim") or 0)
    model = str(state.get("model") or plan.get("model") or "")
    model_role = str(state.get("model_role") or plan.get("model_role") or role)
    if not collections:
        raise ValueError(f"{report_path} has no collections")
    if dim <= 0:
        raise ValueError(f"{report_path} has no positive dim")
    rows = []
    for kind, collection in sorted(collections.items()):
        # Full-wave reports may represent either a fresh collection build or a
        # delta upsert into an existing alias target. For alias promotion, the
        # target invariant is the live collection total, not the number of cards
        # written by the latest delta run.
        expected_count = int((qdrant_health.get(kind) or {}).get("points_count") or written_counts.get(kind) or 0)
        rows.append(
            {
                "role": role,
                "model_role": model_role,
                "kind": str(kind),
                "model": model,
                "dim": dim,
                "collection": str(collection),
                "alias": alias_name(str(kind), role, dim),
                "expected_count": expected_count,
                "report_path": str(report_path),
            }
        )
    return rows


def targets_from_role_reports(values: list[str]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    for value in values:
        role, path = parse_role_report_arg(value)
        if role in seen_roles:
            raise ValueError(f"duplicate --role-report role: {role}")
        seen_roles.add(role)
        targets.extend(target_rows_from_report(role, path))
    if not targets:
        raise ValueError("at least one --role-report is required")
    return targets


def build_actions(targets: list[dict[str, Any]], aliases_before: dict[str, str]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for target in targets:
        alias = target["alias"]
        collection = target["collection"]
        existing = aliases_before.get(alias)
        if existing == collection:
            continue
        if existing and existing != collection:
            actions.append({"delete_alias": {"alias_name": alias}})
        actions.append({"create_alias": {"alias_name": alias, "collection_name": collection}})
    return actions


def build_rollback_actions(targets: list[dict[str, Any]], aliases_before: dict[str, str]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for target in targets:
        alias = target["alias"]
        current = aliases_before.get(alias)
        if current is None:
            actions.append({"delete_alias": {"alias_name": alias}})
        elif current != target["collection"]:
            actions.append({"delete_alias": {"alias_name": alias}})
            actions.append({"create_alias": {"alias_name": alias, "collection_name": current}})
    return actions


def validate_targets(qdrant_url: str, targets: list[dict[str, Any]], aliases_before: dict[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    validated: list[dict[str, Any]] = []
    hard_gates: list[str] = []
    seen_aliases: set[str] = set()
    for target in targets:
        alias = target["alias"]
        if alias in seen_aliases:
            hard_gates.append(f"duplicate_alias:{alias}")
        seen_aliases.add(alias)
        health = collection_health(qdrant_url, target["collection"])
        points_count = int(health.get("points_count") or 0)
        expected_count = int(target["expected_count"] or 0)
        if not health.get("exists"):
            hard_gates.append(f"missing_collection:{target['collection']}")
        if not health.get("healthy"):
            hard_gates.append(f"unhealthy_collection:{target['collection']}")
        if expected_count and points_count != expected_count:
            hard_gates.append(f"points_count_mismatch:{target['collection']}:{points_count}!={expected_count}")
        if int(target["dim"]) != 1024:
            hard_gates.append(f"unexpected_dim:{target['collection']}:{target['dim']}")
        validated.append(
            {
                **target,
                "current_alias_target": aliases_before.get(alias),
                "alias_conflict": bool(aliases_before.get(alias) and aliases_before.get(alias) != target["collection"]),
                "qdrant_health": health,
            }
        )
    return validated, sorted(set(hard_gates))


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Qdrant Role Alias Gate",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- ok: `{report['ok']}`",
        f"- hard_gates_remaining: `{len(report['hard_gates_remaining'])}`",
        f"- action_count_if_applied_later: `{len(report['planned_actions'])}`",
        f"- confirm_token_required_for_apply: `{report['confirm_token_required_for_apply']}`",
        "",
        "## Targets",
        "",
        "| Role | Kind | Alias | Collection | Points | Expected | Current Alias Target |",
        "| --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for target in report["targets"]:
        health = target["qdrant_health"]
        lines.append(
            f"| `{target['role']}` | `{target['kind']}` | `{target['alias']}` | `{target['collection']}` | "
            f"{int(health.get('points_count') or 0)} | {int(target['expected_count'] or 0)} | `{target.get('current_alias_target') or ''}` |"
        )
    lines.extend(["", "## Hard Gates", ""])
    if report["hard_gates_remaining"]:
        for gate in report["hard_gates_remaining"]:
            lines.append(f"- `{gate}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_qdrant(args.qdrant_url)
    reject_d_root(args.out_dir, "out_dir")
    targets = targets_from_role_reports(args.role_report)
    aliases_before = qdrant_aliases(args.qdrant_url)
    validated_targets, hard_gates = validate_targets(args.qdrant_url, targets, aliases_before)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": not hard_gates,
        "decision": "qdrant_role_alias_gate_ready_report_only" if not hard_gates else "qdrant_role_alias_gate_blocked",
        "qdrant_url": args.qdrant_url,
        "targets": validated_targets,
        "aliases_before": aliases_before,
        "planned_actions": build_actions(validated_targets, aliases_before),
        "rollback_actions_if_applied_later": build_rollback_actions(validated_targets, aliases_before),
        "hard_gates_remaining": hard_gates,
        "confirm_token_required_for_apply": CONFIRM_TOKEN,
        "writes": "report_only_no_alias_apply",
        "safety": {
            "model_loaded": False,
            "embedding_call_executed": False,
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "production_publish_executed": False,
            "d_scan_executed": False,
        },
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "qdrant_role_alias_gate.json", report)
    write_markdown(args.out_dir / "qdrant_role_alias_gate.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "hard_gates_remaining": len(hard_gates),
                "report": str(args.out_dir / "qdrant_role_alias_gate.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--role-report",
        action="append",
        required=True,
        help="Role full-wave report as role=path. May be repeated.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
