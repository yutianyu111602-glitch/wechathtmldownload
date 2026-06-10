#!/usr/bin/env python3
"""Freeze the current Stage7 full-pipeline artifact set as a release candidate.

The manifest records hashes for controller artifacts and reuses the release
pointer's own hashes for the large JSONL payloads. It is a local manifest only:
no publish, no production SQLite write, no graph/vector mutation, no paid API,
and no D: scan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_POINTER = Path("reports/consumer_release_pack_full_unknown_time_20260517/release_pointer.staging.json")
DEFAULT_LAUNCH_PACKET = Path("reports/full_pipeline_launch_packet_20260517/full_pipeline_launch_packet.json")
DEFAULT_FINAL_READINESS = Path("reports/final_full_pipeline_readiness_20260517_verified/final_full_pipeline_readiness.json")
DEFAULT_PRD_STATUS = Path("reports/prd_longrun_status_20260517_verified/prd_longrun_status.json")
DEFAULT_E2E_FULL = Path("reports/e2e_integration_full_20260517/e2e_integration_report.json")
DEFAULT_CONSUMER_GATE = Path("reports/consumer_production_gate_packet_20260517/consumer_production_gate_packet.json")
DEFAULT_OUT_DIR = Path("reports/full_pipeline_release_candidate_20260517")
SCHEMA_VERSION = "stage7_full_pipeline_release_candidate.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def build_manifest(
    *,
    rc_id: str,
    pointer_path: Path,
    launch_packet_path: Path,
    final_readiness_path: Path,
    prd_status_path: Path,
    e2e_full_path: Path,
    consumer_gate_path: Path,
) -> dict[str, Any]:
    pointer = read_json(pointer_path)
    launch_packet = read_json(launch_packet_path)
    final_readiness = read_json(final_readiness_path)
    prd_status = read_json(prd_status_path)
    e2e_full = read_json(e2e_full_path)
    consumer_gate = read_json(consumer_gate_path)

    gate_results = {
        "pointer_release_ready": bool(pointer.get("release_ready")),
        "launch_allowed": bool(launch_packet.get("launch_allowed")),
        "final_full_pipeline_allowed": bool(final_readiness.get("full_pipeline_run_allowed")),
        "prd_production_ready": bool(prd_status.get("production_ready")),
        "e2e_full_ok": bool(e2e_full.get("ok")),
        "consumer_hard_gates_clear": not bool(consumer_gate.get("hard_gates_remaining")),
    }
    blockers = [name for name, value in gate_results.items() if not value]
    decision = "release_candidate_frozen" if not blockers else "release_candidate_blocked"
    previous_pointer = pointer.get("previous_pointer") or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "rc_id": rc_id,
        "ok": not blockers,
        "decision": decision,
        "blockers": blockers,
        "gate_results": gate_results,
        "counts": pointer.get("counts") or {},
        "release_pointer": artifact(pointer_path),
        "release_payload_files_from_pointer": pointer.get("files") or {},
        "rollback": {
            "previous_pointer_path": previous_pointer.get("pack_dir")
            or "reports/consumer_release_pack_full_unknown_time_20260514/release_pointer.staging.json",
            "previous_pointer_embedded": bool(previous_pointer),
            "procedure": "Restore the previous staging pointer or keep consumers on the prior pack.",
        },
        "controller_artifacts": {
            "launch_packet": artifact(launch_packet_path),
            "final_readiness": artifact(final_readiness_path),
            "prd_status": artifact(prd_status_path),
            "e2e_full": artifact(e2e_full_path),
            "consumer_gate": artifact(consumer_gate_path),
        },
        "known_limitations": final_readiness.get("known_limitations") or [],
        "safety": {
            "manifest_only": True,
            "production_publish_executed": False,
            "production_sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
        "writes": "release_candidate_manifest_only",
    }


def write_markdown(path: Path, manifest: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Full Pipeline Release Candidate",
        "",
        f"- generated_at: `{manifest['generated_at']}`",
        f"- rc_id: `{manifest['rc_id']}`",
        f"- decision: `{manifest['decision']}`",
        f"- ok: `{manifest['ok']}`",
        "",
        "## Gate Results",
        "",
    ]
    for name, value in manifest["gate_results"].items():
        lines.append(f"- {name}: `{value}`")
    lines.extend(["", "## Counts", ""])
    for name, value in manifest["counts"].items():
        lines.append(f"- {name}: `{value}`")
    lines.extend(["", "## Blockers", ""])
    if manifest["blockers"]:
        for blocker in manifest["blockers"]:
            lines.append(f"- `{blocker}`")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Rollback",
            "",
            f"- previous_pointer_path: `{manifest['rollback']['previous_pointer_path']}`",
            f"- procedure: {manifest['rollback']['procedure']}",
            "",
            "## Safety",
            "",
            "- Manifest only. No publish, production SQLite write, graph/vector mutation, mem0 write, paid API, or D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rc-id", default="stage7-full-pipeline-rc-20260517")
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--launch-packet", type=Path, default=DEFAULT_LAUNCH_PACKET)
    parser.add_argument("--final-readiness", type=Path, default=DEFAULT_FINAL_READINESS)
    parser.add_argument("--prd-status", type=Path, default=DEFAULT_PRD_STATUS)
    parser.add_argument("--e2e-full", type=Path, default=DEFAULT_E2E_FULL)
    parser.add_argument("--consumer-gate", type=Path, default=DEFAULT_CONSUMER_GATE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    manifest = build_manifest(
        rc_id=args.rc_id,
        pointer_path=args.pointer,
        launch_packet_path=args.launch_packet,
        final_readiness_path=args.final_readiness,
        prd_status_path=args.prd_status,
        e2e_full_path=args.e2e_full,
        consumer_gate_path=args.consumer_gate,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "release_candidate_manifest.json", manifest)
    write_markdown(args.out_dir / "release_candidate_manifest.md", manifest)
    print(
        json.dumps(
            {
                "ok": manifest["ok"],
                "decision": manifest["decision"],
                "rc_id": manifest["rc_id"],
                "blockers": manifest["blockers"],
                "manifest": str(args.out_dir / "release_candidate_manifest.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if manifest["ok"] else 2


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
