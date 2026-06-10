#!/usr/bin/env python3
"""Build a report-only PRD-03/PRD-08 consumer production gate packet.

The packet consolidates publish-gate, deploy-readiness, graph-promotion, and
weekly-path blockers into an explicit pre-production checklist. It never changes
publish config, never accepts unknown-time policy, and never deploys.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_PUBLISH_GATE = Path("reports/consumer_publish_gate_review_20260515/consumer_publish_gate_review.json")
DEFAULT_DEPLOY_READINESS = Path("reports/consumer_deploy_readiness_20260515/consumer_deploy_readiness.json")
DEFAULT_GRAPH_PROMOTION = Path("reports/graph_promotion_readiness_refresh_20260516/graph_promotion_readiness.json")
DEFAULT_WEEKLY_PATH = Path("reports/weekly_publish_path_decision_20260515/weekly_publish_path_decision.json")
DEFAULT_PUBLISH_CONFIG = Path("config/consumer_publish_gate.local.json")
DEFAULT_OUT_DIR = Path("reports/consumer_production_gate_packet_20260516")
SCHEMA_VERSION = "stage7_consumer_production_gate_packet.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for consumer production gate packet: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


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


def unique_nonempty(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = first_text(item)
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def acceptance_state(config: dict[str, Any]) -> dict[str, Any]:
    acceptance = config.get("unknown_time_business_acceptance") or {}
    return {
        "accepted": bool(acceptance.get("accepted")),
        "accepted_by": first_text(acceptance.get("accepted_by")),
        "accepted_at": first_text(acceptance.get("accepted_at")),
        "user_visible_policy": first_text(acceptance.get("user_visible_policy")),
    }


def build_packet(
    *,
    publish_gate_path: Path,
    deploy_readiness_path: Path,
    graph_promotion_path: Path,
    weekly_path_path: Path,
    publish_config_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    publish_gate = read_json(publish_gate_path)
    deploy = read_json(deploy_readiness_path)
    graph = read_json(graph_promotion_path)
    weekly = read_json(weekly_path_path)
    config = read_json(publish_config_path)
    acceptance = acceptance_state(config)
    deploy_gates = deploy.get("gates") or {}
    hard_gate_items = unique_nonempty(
        [
            *(publish_gate.get("blocking_reasons") or []),
            *(deploy.get("blockers") or []),
            *(graph.get("blockers") or []),
            *(
                ["unknown_time_business_acceptance.accepted is false"]
                if not acceptance["accepted"]
                else []
            ),
            *(
                ["unknown_time_business_acceptance.accepted_at missing"]
                if not acceptance["accepted_at"]
                else []
            ),
        ]
    )
    local_ready_gates = {
        "release_pointer_ok": bool(deploy_gates.get("release_pointer_ok")),
        "unknown_time_staging_compatible": bool(deploy_gates.get("unknown_time_ok")),
        "qdrant_aliases_present": bool(deploy_gates.get("qdrant_aliases_present")),
        "local_e2e_ready": bool(deploy_gates.get("local_e2e_ready")),
        "cloudrun_local_ready": bool(deploy_gates.get("cloudrun_local_ready")),
        "weekly_route_ready": bool(deploy_gates.get("weekly_route_ready")),
    }
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "consumer_production_gate_packet_ready_report_only",
        "publish_gate_path": str(publish_gate_path),
        "deploy_readiness_path": str(deploy_readiness_path),
        "graph_promotion_path": str(graph_promotion_path),
        "weekly_path_path": str(weekly_path_path),
        "publish_config_path": str(publish_config_path),
        "publish_gate": {
            "decision": publish_gate.get("decision"),
            "dry_run_ready": publish_gate.get("dry_run_ready"),
            "publish_allowed": publish_gate.get("publish_allowed"),
            "blocking_reasons": publish_gate.get("blocking_reasons") or [],
            "counts": publish_gate.get("counts") or {},
        },
        "deploy_readiness": {
            "decision": deploy.get("decision"),
            "deploy_allowed": deploy.get("deploy_allowed"),
            "gates": deploy_gates,
        },
        "graph_promotion": {
            "decision": graph.get("decision"),
            "promotion_allowed": graph.get("promotion_allowed"),
            "gates": graph.get("gates") or {},
        },
        "weekly_path": {
            "decision": weekly.get("decision"),
            "production_ready": weekly.get("production_ready"),
            "recommended_path": weekly.get("recommended_path"),
        },
        "unknown_time_business_acceptance": acceptance,
        "local_ready_gates": local_ready_gates,
        "local_ready_gate_count": sum(1 for value in local_ready_gates.values() if value),
        "hard_gates_remaining": hard_gate_items,
        "manual_decisions_required": [
            "Explicitly accept or reject production publish with unknown publish_time for 45568 articles.",
            "Configure production CloudRun/CloudBase endpoint and post-deploy smoke target.",
            "Lift production publish and production SQLite write bans only in a separate production gate.",
            "Resolve graph promotion policy or keep consumer on staging/read-only graph labels.",
            "Keep rollback pointer and old stella aliases available before deploy.",
        ],
        "forbidden_next_actions": [
            "do_not_flip_unknown_time_business_acceptance_without_explicit_business_gate",
            "do_not_publish_or_upload_cloudrun_from_this_packet",
            "do_not_write_production_sqlite",
            "do_not_promote_graph_labels",
        ],
        "safety": {
            "reports_only": True,
            "config_modified": False,
            "production_publish_executed": False,
            "cloud_deploy_executed": False,
            "production_sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
        "writes": "reports_only",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "consumer_production_gate_packet.json", packet)
    write_markdown(out_dir / "consumer_production_gate_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# Consumer Production Gate Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- publish_allowed: `{packet['publish_gate']['publish_allowed']}`",
        f"- deploy_allowed: `{packet['deploy_readiness']['deploy_allowed']}`",
        f"- local_ready_gate_count: `{packet['local_ready_gate_count']}`",
        "",
        "## Hard Gates Remaining",
        "",
    ]
    for item in packet["hard_gates_remaining"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Manual Decisions Required", ""])
    for item in packet["manual_decisions_required"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish-gate", type=Path, default=DEFAULT_PUBLISH_GATE)
    parser.add_argument("--deploy-readiness", type=Path, default=DEFAULT_DEPLOY_READINESS)
    parser.add_argument("--graph-promotion", type=Path, default=DEFAULT_GRAPH_PROMOTION)
    parser.add_argument("--weekly-path", type=Path, default=DEFAULT_WEEKLY_PATH)
    parser.add_argument("--publish-config", type=Path, default=DEFAULT_PUBLISH_CONFIG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(
        publish_gate_path=args.publish_gate,
        deploy_readiness_path=args.deploy_readiness,
        graph_promotion_path=args.graph_promotion,
        weekly_path_path=args.weekly_path,
        publish_config_path=args.publish_config,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "local_ready_gate_count": packet["local_ready_gate_count"],
                "hard_gates_remaining": len(packet["hard_gates_remaining"]),
                "summary": str(args.out_dir / "consumer_production_gate_packet.json"),
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
