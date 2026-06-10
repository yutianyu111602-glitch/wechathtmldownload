#!/usr/bin/env python3
"""Build an auditable packet for the user-authorized production gate cancellation.

The packet records that production/write gates are authorized open by config and
current controller evidence. It does not publish, deploy, write databases,
promote aliases, call paid APIs, or read secrets.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = Path("config/consumer_publish_gate.local.json")
DEFAULT_OPERATION_PACKET = Path(
    "reports/full_pipeline_production_operation_packet_20260517/full_pipeline_production_operation_packet.json"
)
DEFAULT_LAUNCH_PACKET = Path("reports/full_pipeline_launch_packet_20260517/full_pipeline_launch_packet.json")
DEFAULT_RC_MANIFEST = Path("reports/full_pipeline_release_candidate_20260517/release_candidate_manifest.json")
DEFAULT_OUT_DIR = Path("reports/production_gate_cancellation_20260518")
SCHEMA_VERSION = "stage7_production_gate_cancellation_packet.v1"

REQUIRED_AUTH_FLAGS = [
    "production_publish_allowed",
    "production_sqlite_write_allowed",
    "production_graph_labels_allowed",
    "neo4j_staging_write_allowed",
    "qdrant_write_allowed",
    "qdrant_alias_change_allowed",
    "mem0_write_allowed",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for production gate cancellation: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def first_text(value: Any) -> str:
    return str(value or "").strip()


def build_packet(
    *,
    config_path: Path,
    operation_packet_path: Path,
    launch_packet_path: Path,
    rc_manifest_path: Path,
    out_dir: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    config = read_json(config_path)
    operation = read_json(operation_packet_path)
    launch = read_json(launch_packet_path)
    rc = read_json(rc_manifest_path)

    authorization = config.get("production_authorization") or {}
    unknown_time = config.get("unknown_time_business_acceptance") or {}
    missing_flags = [flag for flag in REQUIRED_AUTH_FLAGS if not bool(authorization.get(flag))]
    hard_gates_remaining: list[str] = []

    if missing_flags:
        hard_gates_remaining.append("production_authorization missing true flags: " + ", ".join(missing_flags))
    if not bool(unknown_time.get("accepted")):
        hard_gates_remaining.append("unknown_time_business_acceptance.accepted is not true")
    if operation.get("hard_gates_remaining") not in ([], None):
        hard_gates_remaining.append("operation packet still reports hard gates")
    if operation.get("stage7_adapter_gap") is True:
        hard_gates_remaining.append("operation packet still reports stage7 adapter gap")
    if not bool(launch.get("launch_allowed")):
        hard_gates_remaining.append("launch packet is not launch_allowed")
    if rc.get("blockers") not in ([], None):
        hard_gates_remaining.append("release candidate manifest still has blockers")

    gates_cancelled = not hard_gates_remaining
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": (
            "production_gates_cancelled_authorized"
            if gates_cancelled
            else "production_gates_cancellation_blocked"
        ),
        "gates_cancelled": gates_cancelled,
        "execution_authorized": gates_cancelled,
        "hard_gates_remaining": hard_gates_remaining,
        "config_path": str(config_path),
        "operation_packet_path": str(operation_packet_path),
        "launch_packet_path": str(launch_packet_path),
        "rc_manifest_path": str(rc_manifest_path),
        "unknown_time_business_acceptance": {
            "accepted": bool(unknown_time.get("accepted")),
            "accepted_by": first_text(unknown_time.get("accepted_by")),
            "accepted_at": first_text(unknown_time.get("accepted_at")),
            "user_visible_policy": first_text(unknown_time.get("user_visible_policy")),
        },
        "production_authorization": {
            flag: bool(authorization.get(flag)) for flag in REQUIRED_AUTH_FLAGS
        },
        "authorization_scope": first_text(authorization.get("scope")),
        "current_evidence": {
            "operation_decision": operation.get("decision"),
            "operation_hard_gates_remaining": operation.get("hard_gates_remaining") or [],
            "stage7_adapter_gap": operation.get("stage7_adapter_gap"),
            "launch_decision": launch.get("decision"),
            "launch_allowed": launch.get("launch_allowed"),
            "release_candidate_decision": rc.get("decision"),
            "release_candidate_blockers": rc.get("blockers") or [],
        },
        "write_doors_opened": [
            "production_publish",
            "production_sqlite",
            "production_graph_labels",
            "neo4j_staging_write",
            "qdrant_write",
            "qdrant_alias_change",
            "mem0_write",
            "unknown_publish_time_business_acceptance",
        ],
        "safety": {
            "packet_only": True,
            "production_publish_executed": False,
            "cloud_deploy_executed": False,
            "production_sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "secret_read_or_printed": False,
            "d_scan_executed": False,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "production_gate_cancellation_packet.json", packet)
    write_markdown(out_dir / "production_gate_cancellation_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# Production Gate Cancellation Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- gates_cancelled: `{packet['gates_cancelled']}`",
        f"- execution_authorized: `{packet['execution_authorized']}`",
        "",
        "## Write Doors Opened",
        "",
    ]
    for item in packet["write_doors_opened"]:
        lines.append(f"- `{item}`")
    lines.extend(["", "## Hard Gates Remaining", ""])
    if packet["hard_gates_remaining"]:
        for item in packet["hard_gates_remaining"]:
            lines.append(f"- {item}")
    else:
        lines.append("- none")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--operation-packet", type=Path, default=DEFAULT_OPERATION_PACKET)
    parser.add_argument("--launch-packet", type=Path, default=DEFAULT_LAUNCH_PACKET)
    parser.add_argument("--rc-manifest", type=Path, default=DEFAULT_RC_MANIFEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(
        config_path=args.config,
        operation_packet_path=args.operation_packet,
        launch_packet_path=args.launch_packet,
        rc_manifest_path=args.rc_manifest,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "gates_cancelled": packet["gates_cancelled"],
                "hard_gates_remaining": packet["hard_gates_remaining"],
                "summary": str(args.out_dir / "production_gate_cancellation_packet.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if packet["gates_cancelled"] else 2


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
