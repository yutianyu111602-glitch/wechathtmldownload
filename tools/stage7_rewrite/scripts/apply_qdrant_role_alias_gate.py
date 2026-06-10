#!/usr/bin/env python3
"""Apply a previously verified Qdrant role-alias gate packet.

This is the live write companion for qdrant_role_alias_gate.py. It only
changes Qdrant aliases described by a gate packet that already has zero hard
gates. It does not write vector points, call embedding/model APIs, touch
Neo4j/SQLite/mem0, publish, use paid APIs, read secrets, or scan D:.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


SCHEMA_VERSION = "stage7_qdrant_role_alias_apply.v1"
EXPECTED_GATE_SCHEMA = "stage7_qdrant_role_alias_gate.v1"
DEFAULT_GATE = Path("reports/qdrant_role_alias_gate_47k_delta375_20260519/qdrant_role_alias_gate.json")
DEFAULT_OUT_DIR = Path("reports/qdrant_role_alias_apply_47k_delta375_20260519")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
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
        raise ValueError(f"Qdrant URL must be local for role alias apply: {url}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_root(path, "json")
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


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


def validate_gate(gate: dict[str, Any]) -> list[dict[str, Any]]:
    if gate.get("schema_version") != EXPECTED_GATE_SCHEMA:
        raise ValueError(f"gate schema mismatch: {gate.get('schema_version')}")
    if not gate.get("ok"):
        raise ValueError("gate is not ok")
    if gate.get("hard_gates_remaining"):
        raise ValueError(f"gate still has hard gates: {gate.get('hard_gates_remaining')}")
    if gate.get("confirm_token_required_for_apply") != CONFIRM_TOKEN:
        raise ValueError("gate confirm token does not match this apply script")
    targets = gate.get("targets") or []
    if not isinstance(targets, list) or not targets:
        raise ValueError("gate has no targets")
    required = {"alias", "collection", "expected_count", "dim", "role", "kind"}
    normalized: list[dict[str, Any]] = []
    seen_aliases: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("gate target must be an object")
        missing = sorted(required - set(target))
        if missing:
            raise ValueError(f"gate target missing fields {missing}: {target}")
        alias = str(target["alias"])
        if alias in seen_aliases:
            raise ValueError(f"duplicate target alias: {alias}")
        seen_aliases.add(alias)
        normalized.append({**target, "alias": alias, "collection": str(target["collection"])})
    return normalized


def validate_targets_live(
    qdrant_url: str,
    targets: list[dict[str, Any]],
    live_aliases_before_apply: dict[str, str],
    gate_aliases_before: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str]]:
    hard_gates: list[str] = []
    validated: list[dict[str, Any]] = []
    for target in targets:
        alias = target["alias"]
        collection = target["collection"]
        expected_count = int(target.get("expected_count") or 0)
        dim = int(target.get("dim") or 0)
        health = collection_health(qdrant_url, collection)
        points_count = int(health.get("points_count") or 0)
        current_alias_target = live_aliases_before_apply.get(alias)
        gate_alias_target = gate_aliases_before.get(alias)
        if current_alias_target != collection:
            if gate_alias_target is None and current_alias_target is not None:
                hard_gates.append(f"alias_created_since_gate:{alias}:{current_alias_target}")
            elif gate_alias_target is not None and current_alias_target != gate_alias_target:
                hard_gates.append(f"alias_target_changed_since_gate:{alias}:{current_alias_target}!={gate_alias_target}")
        if not health.get("exists"):
            hard_gates.append(f"missing_collection:{collection}")
        if not health.get("healthy"):
            hard_gates.append(f"unhealthy_collection:{collection}")
        if expected_count and points_count != expected_count:
            hard_gates.append(f"points_count_mismatch:{collection}:{points_count}!={expected_count}")
        if dim != 1024:
            hard_gates.append(f"unexpected_dim:{collection}:{dim}")
        validated.append(
            {
                **target,
                "current_alias_target": current_alias_target,
                "gate_alias_target": gate_alias_target,
                "already_promoted": current_alias_target == collection,
                "qdrant_health": health,
            }
        )
    return validated, sorted(set(hard_gates))


def effective_actions(targets: list[dict[str, Any]], aliases_before: dict[str, str]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for target in targets:
        alias = target["alias"]
        collection = target["collection"]
        if aliases_before.get(alias) == collection:
            continue
        actions.append({"create_alias": {"alias_name": alias, "collection_name": collection}})
    return actions


def rollback_actions(targets: list[dict[str, Any]], aliases_before: dict[str, str]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for target in targets:
        alias = target["alias"]
        collection = target["collection"]
        before = aliases_before.get(alias)
        if before == collection:
            continue
        if before is None:
            actions.append({"delete_alias": {"alias_name": alias}})
        else:
            actions.append({"delete_alias": {"alias_name": alias}})
            actions.append({"create_alias": {"alias_name": alias, "collection_name": before}})
    return actions


def verify_aliases_after(targets: list[dict[str, Any]], aliases_after: dict[str, str]) -> list[str]:
    errors: list[str] = []
    for target in targets:
        actual = aliases_after.get(target["alias"])
        expected = target["collection"]
        if actual != expected:
            errors.append(f"alias_verify_failed:{target['alias']}:{actual}!={expected}")
    return errors


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Qdrant Role Alias Apply",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- ok: `{report['ok']}`",
        f"- applied: `{report['applied']}`",
        f"- action_count: `{len(report['actions'])}`",
        f"- qdrant_url: `{report['qdrant_url']}`",
        f"- gate_path: `{report['gate_path']}`",
        "",
        "## Targets",
        "",
        "| Role | Kind | Alias | Collection | Points | Expected | Alias Before | Alias After |",
        "| --- | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    aliases_after = report["aliases_after"]
    for target in report["targets"]:
        health = target["qdrant_health"]
        alias = target["alias"]
        lines.append(
            f"| `{target['role']}` | `{target['kind']}` | `{alias}` | `{target['collection']}` | "
            f"{int(health.get('points_count') or 0)} | {int(target.get('expected_count') or 0)} | "
            f"`{target.get('current_alias_target') or ''}` | `{aliases_after.get(alias) or ''}` |"
        )
    lines.extend(["", "## Verification", ""])
    if report["verification_errors"]:
        for error in report["verification_errors"]:
            lines.append(f"- `{error}`")
    else:
        lines.append("- all aliases point to expected collections")
    lines.extend(["", "## Rollback", ""])
    lines.append(f"- rollback_action_count: `{len(report['rollback_actions'])}`")
    lines.append(f"- rollback_actions_path: `{report['rollback_actions_path']}`")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_qdrant(args.qdrant_url)
    reject_d_root(args.gate, "gate")
    reject_d_root(args.out_dir, "out_dir")
    if args.confirm != CONFIRM_TOKEN:
        raise SystemExit(f"--confirm {CONFIRM_TOKEN} required for Qdrant role alias apply")

    gate = read_json(args.gate)
    targets = validate_gate(gate)
    aliases_before = qdrant_aliases(args.qdrant_url)
    gate_aliases_before = gate.get("aliases_before") if isinstance(gate.get("aliases_before"), dict) else {}
    gate_aliases_before = {str(key): str(value) for key, value in gate_aliases_before.items()}
    validated_targets, hard_gates = validate_targets_live(args.qdrant_url, targets, aliases_before, gate_aliases_before)
    if hard_gates:
        raise SystemExit(f"live hard gates block alias apply: {json.dumps(hard_gates, ensure_ascii=False)}")

    actions = effective_actions(validated_targets, aliases_before)
    rollback = rollback_actions(validated_targets, aliases_before)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "pre_apply_aliases.json", aliases_before)
    write_json(args.out_dir / "effective_actions.json", actions)
    write_json(args.out_dir / "rollback_actions.json", rollback)

    applied = False
    if actions:
        qdrant_request("POST", f"{args.qdrant_url.rstrip('/')}/collections/aliases", json={"actions": actions}, timeout=60)
        applied = True
    aliases_after = qdrant_aliases(args.qdrant_url)
    verification_errors = verify_aliases_after(validated_targets, aliases_after)
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": not verification_errors,
        "decision": "qdrant_role_alias_apply_complete" if not verification_errors else "qdrant_role_alias_apply_needs_rollback_review",
        "gate_path": str(args.gate),
        "qdrant_url": args.qdrant_url,
        "targets": validated_targets,
        "actions": actions,
        "rollback_actions": rollback,
        "rollback_actions_path": str(args.out_dir / "rollback_actions.json"),
        "applied": applied,
        "aliases_before": aliases_before,
        "aliases_after": aliases_after,
        "verification_errors": verification_errors,
        "safety": {
            "model_loaded": False,
            "embedding_call_executed": False,
            "qdrant_write_executed": bool(actions),
            "qdrant_alias_change_executed": bool(actions),
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
    write_json(args.out_dir / "post_apply_aliases.json", aliases_after)
    write_json(args.out_dir / "qdrant_role_alias_apply_report.json", report)
    write_markdown(args.out_dir / "qdrant_role_alias_apply_report.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "applied": applied,
                "action_count": len(actions),
                "report": str(args.out_dir / "qdrant_role_alias_apply_report.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", type=Path, default=DEFAULT_GATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--confirm", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
