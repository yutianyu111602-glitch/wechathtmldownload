#!/usr/bin/env python3
"""Build the Stage7 full-pipeline production operation packet.

The packet starts from the frozen full-pipeline release candidate and maps it to
the executable production surfaces that actually exist today. It never deploys,
never writes production SQLite, never mutates Neo4j/Qdrant/mem0, and never calls
paid APIs. It is intended to prevent two common mistakes:

* claiming the full Stage7 atlas JSONL pack has a CloudRun deploy job when it
  only has a release pointer;
* using the direct Stage7 events as weekly_event_published.v1 production data.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_RC = Path("reports/full_pipeline_release_candidate_20260517/release_candidate_manifest.json")
DEFAULT_CONSUMER_GATE = Path("reports/consumer_production_gate_packet_20260517/consumer_production_gate_packet.json")
DEFAULT_PUBLISH_CONFIG = Path("config/consumer_publish_gate.local.json")
DEFAULT_CLOUDRUN_SERVICE_ROOT = Path("../../services/weekly_activity_cloudrun")
DEFAULT_WEEKLY_BAKE_SCRIPT = Path("../../services/weekly_activity_cloudrun/scripts/bake_and_deploy.py")
DEFAULT_WEEKLY_RELEASE_DIR = Path("../../services/weekly_activity_cloudrun/data/releases/release_lineup_guard_20260517_57")
DEFAULT_STAGE7_PACKAGING = Path("reports/cloudrun_stage7_packaging_20260518/cloudrun_stage7_packaging.json")
DEFAULT_OUT_DIR = Path("reports/full_pipeline_production_operation_packet_20260517")
SCHEMA_VERSION = "stage7_full_pipeline_production_operation_packet.v1"


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


def resolve_under(base: Path, path_text: str | Path) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else base / path


def existing_child(base: Path, name: str) -> bool:
    return (base / name).exists()


def probe_weekly_release(release_dir: Path) -> dict[str, Any]:
    manifest_path = release_dir / "manifest.json"
    current_path = release_dir / "current.json"
    required = {
        "manifest": manifest_path.exists(),
        "current": current_path.exists(),
        "by_city": (release_dir / "by-city").is_dir(),
        "by_date": (release_dir / "by-date").is_dir(),
        "by_id": (release_dir / "by-id").is_dir(),
    }
    manifest: dict[str, Any] = {}
    current: dict[str, Any] = {}
    if manifest_path.exists():
        manifest = read_json(manifest_path)
    if current_path.exists():
        current = read_json(current_path)
    current_items = current.get("items") if isinstance(current.get("items"), list) else []
    return {
        "path": str(release_dir),
        "exists": release_dir.exists(),
        "compatible_with_bake_and_deploy": bool(release_dir.exists() and all(required.values())),
        "required_items": required,
        "manifest_item_count": manifest.get("item_count") or manifest.get("items_total") or 0,
        "current_item_count": len(current_items),
        "schema_version": manifest.get("schema_version") or current.get("schema_version") or "",
        "source_url_map_present": existing_child(release_dir / "source_actions", "source_url_map.json"),
    }


def probe_bake_script(script_path: Path) -> dict[str, Any]:
    exists = script_path.exists()
    text = script_path.read_text(encoding="utf-8", errors="replace") if exists else ""
    return {
        "path": str(script_path),
        "exists": exists,
        "supports_dry_run": "--dry-run" in text and "dry_run" in text,
        "supports_stage7_atlas_required_gate": "--require-stage7-atlas" in text,
        "supports_deprecated_cloudrun_fallback": "run:deprecated" in text and "version" in text and "create" in text,
        "supports_deprecated_image_upload": "run:deprecated" in text and "image" in text and "upload" in text,
        "accepts_release_dir": "--release-dir" in text,
        "accepts_deploy_mode": "--deploy-mode" in text,
        "deploys_cloudrun": "run" in text and "deploy" in text and "weekly-api" in text,
    }


def read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return read_json(path)


def probe_stage7_cloudrun_adapter(service_root: Path) -> dict[str, Any]:
    store_path = service_root / "src" / "stage7AtlasStore.mjs"
    server_path = service_root / "src" / "server.mjs"
    store_text = store_path.read_text(encoding="utf-8", errors="replace") if store_path.exists() else ""
    server_text = server_path.read_text(encoding="utf-8", errors="replace") if server_path.exists() else ""
    endpoints = [
        "/api/v1/stage7/manifest",
        "/api/v1/stage7/search",
        "/api/v1/stage7/recommendations",
        "/api/v1/stage7/graph-rag/answers",
    ]
    endpoint_presence = {endpoint: endpoint in server_text for endpoint in endpoints}
    return {
        "service_root": str(service_root),
        "store_path": str(store_path),
        "server_path": str(server_path),
        "store_exists": store_path.exists(),
        "server_exists": server_path.exists(),
        "release_pointer_reader_present": "release_pointer" in store_text and "Stage7AtlasStore" in store_text,
        "streaming_jsonl_reader_present": "createReadStream" in store_text and "createInterface" in store_text,
        "endpoint_presence": endpoint_presence,
        "ready": bool(
            store_path.exists()
            and server_path.exists()
            and "Stage7AtlasStore" in store_text
            and "createReadStream" in store_text
            and all(endpoint_presence.values())
        ),
    }


def pointer_pack_dir_from_rc(rc: dict[str, Any], base: Path) -> Path:
    pointer = rc.get("release_pointer") or {}
    pointer_path = resolve_under(base, pointer.get("path") or "")
    if pointer_path.name:
        return pointer_path.parent
    files = rc.get("release_payload_files_from_pointer") or {}
    for item in files.values():
        if isinstance(item, dict) and item.get("path"):
            return resolve_under(base, item["path"]).parent
    return base


def probe_stage7_full_atlas(rc: dict[str, Any], base: Path) -> dict[str, Any]:
    pack_dir = pointer_pack_dir_from_rc(rc, base)
    required_payloads = {
        "manifest_json": (pack_dir / "manifest.json").exists(),
        "articles_jsonl": (pack_dir / "articles.jsonl").exists(),
        "entities_jsonl": (pack_dir / "entities.jsonl").exists(),
        "events_jsonl": (pack_dir / "events.jsonl").exists(),
        "release_pointer": (pack_dir / "release_pointer.staging.json").exists(),
    }
    weekly_shape = {
        "current_json": (pack_dir / "current.json").exists(),
        "by_city": (pack_dir / "by-city").is_dir(),
        "by_date": (pack_dir / "by-date").is_dir(),
        "by_id": (pack_dir / "by-id").is_dir(),
    }
    return {
        "pack_dir": str(pack_dir),
        "counts": rc.get("counts") or {},
        "artifact_release_ready": bool(rc.get("ok")) and not bool(rc.get("blockers")),
        "required_payloads": required_payloads,
        "payload_complete": all(required_payloads.values()),
        "direct_weekly_deploy_shape": weekly_shape,
        "direct_weekly_deploy_compatible": all(weekly_shape.values()),
    }


def build_packet(
    *,
    rc_path: Path,
    consumer_gate_path: Path,
    publish_config_path: Path,
    cloudrun_service_root: Path,
    weekly_bake_script_path: Path,
    weekly_release_dir: Path,
    stage7_packaging_path: Path,
    out_dir: Path,
    weekly_bake_dry_run_log: Path | None = None,
) -> dict[str, Any]:
    root = Path.cwd()
    rc = read_json(rc_path)
    consumer_gate = read_json(consumer_gate_path)
    publish_config = read_json(publish_config_path)
    stage7_adapter = probe_stage7_cloudrun_adapter(cloudrun_service_root)
    bake_script = probe_bake_script(weekly_bake_script_path)
    weekly_release = probe_weekly_release(weekly_release_dir)
    full_atlas = probe_stage7_full_atlas(rc, root)
    stage7_packaging = read_optional_json(stage7_packaging_path)

    publish_target = publish_config.get("publish_target") or {}
    production_authorization = publish_config.get("production_authorization") or {}
    hard_gates: list[str] = []
    if not bool(rc.get("ok")) or rc.get("blockers"):
        hard_gates.append("release_candidate_not_green")
    if consumer_gate.get("hard_gates_remaining"):
        hard_gates.append("consumer_hard_gates_remaining")
    if not bool((consumer_gate.get("publish_gate") or {}).get("publish_allowed")):
        hard_gates.append("consumer_publish_gate_not_allowed")
    if not bool(production_authorization.get("production_publish_allowed")):
        hard_gates.append("production_publish_not_authorized_in_config")
    if not bake_script["exists"]:
        hard_gates.append("weekly_bake_and_deploy_script_missing")
    if bake_script["exists"] and not bake_script["supports_dry_run"]:
        hard_gates.append("weekly_bake_and_deploy_dry_run_missing")
    if not weekly_release["compatible_with_bake_and_deploy"]:
        hard_gates.append("weekly_release_not_bake_compatible")
    if not bake_script.get("supports_stage7_atlas_required_gate"):
        hard_gates.append("weekly_bake_and_deploy_stage7_package_gate_missing")
    if not bake_script.get("supports_deprecated_cloudrun_fallback"):
        hard_gates.append("weekly_bake_and_deploy_deprecated_fallback_missing")
    if not bake_script.get("supports_deprecated_image_upload"):
        hard_gates.append("weekly_bake_and_deploy_image_upload_fallback_missing")
    if not bool(stage7_packaging.get("ok")):
        hard_gates.append("cloudrun_stage7_packaging_not_ready")

    adapter_gap = not stage7_adapter["ready"]
    weekly_dry_run_command = [
        "python",
        str(weekly_bake_script_path),
        "--release-dir",
        str(weekly_release_dir),
        "--dry-run",
        "--no-qr",
        "--require-stage7-atlas",
        "--deploy-mode",
        "image-upload",
    ]
    decision = (
        "production_operation_blocked"
        if hard_gates
        else "production_operation_ready_with_stage7_adapter_gap"
        if adapter_gap
        else "production_operation_ready_with_stage7_api_adapter"
    )
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": not hard_gates,
        "decision": decision,
        "hard_gates_remaining": hard_gates,
        "rc": {
            "path": str(rc_path),
            "rc_id": rc.get("rc_id"),
            "decision": rc.get("decision"),
            "blockers": rc.get("blockers") or [],
        },
        "publish_target": publish_target,
        "consumer_gate": {
            "path": str(consumer_gate_path),
            "publish_allowed": (consumer_gate.get("publish_gate") or {}).get("publish_allowed"),
            "deploy_allowed": (consumer_gate.get("deploy_readiness") or {}).get("deploy_allowed"),
            "hard_gates_remaining": consumer_gate.get("hard_gates_remaining") or [],
        },
        "stage7_full_atlas": full_atlas,
        "stage7_cloudrun_adapter": stage7_adapter,
        "weekly_production_release": weekly_release,
        "weekly_bake_script": bake_script,
        "cloudrun_stage7_packaging": {
            "path": str(stage7_packaging_path),
            "ok": stage7_packaging.get("ok"),
            "decision": stage7_packaging.get("decision", ""),
            "blockers": stage7_packaging.get("blockers") or [],
            "pointer_counts": stage7_packaging.get("pointer_counts") or {},
        },
        "stage7_adapter_gap": {
            "present": adapter_gap,
            "reason": (
                "CloudRun Stage7 atlas/search/Graph RAG adapter is missing."
                if adapter_gap
                else ""
            ),
            "required_next_implementation": (
                "Add a CloudRun Stage7 atlas/search/Graph RAG adapter or a separate bake step before treating the full atlas pack as a deployable service payload."
                if adapter_gap
                else ""
            ),
        },
        "weekly_bake_dry_run": {
            "executed_by_this_script": False,
            "log_path": str(weekly_bake_dry_run_log) if weekly_bake_dry_run_log else "",
            "log_present": bool(weekly_bake_dry_run_log and weekly_bake_dry_run_log.exists()),
            "command": weekly_dry_run_command,
        },
        "next_executable_steps": [
            {
                "lane": "weekly_miniprogram",
                "mode": "dry_run",
                "command": weekly_dry_run_command,
                "allowed_now": not hard_gates,
            },
            {
                "lane": "stage7_full_atlas",
                "mode": "implementation",
                "command": ["implement_stage7_cloudrun_adapter_or_bake_step"],
                "allowed_now": adapter_gap and not hard_gates,
            },
            {
                "lane": "stage7_full_atlas",
                "mode": "api_smoke",
                "command": [
                    "GET",
                    "/api/v1/stage7/manifest",
                    "/api/v1/stage7/search?q=dada",
                    "/api/v1/stage7/recommendations",
                    "/api/v1/stage7/graph-rag/answers",
                ],
                "allowed_now": stage7_adapter["ready"] and not hard_gates,
            },
            {
                "lane": "stage7_full_atlas",
                "mode": "release_artifact",
                "command": ["keep_consumers_on_release_pointer", str(rc.get("release_pointer", {}).get("path") or "")],
                "allowed_now": full_atlas["artifact_release_ready"] and not hard_gates,
            },
        ],
        "known_limitations": rc.get("known_limitations") or [],
        "safety": {
            "reports_only": True,
            "cloud_deploy_executed": False,
            "production_publish_executed": False,
            "production_sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "secret_value_read_or_printed": False,
        },
        "writes": "operation_packet_only",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "full_pipeline_production_operation_packet.json", packet)
    write_markdown(out_dir / "full_pipeline_production_operation_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# Stage7 Full Pipeline Production Operation Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- ok: `{packet['ok']}`",
        f"- rc_id: `{packet['rc']['rc_id']}`",
        "",
        "## Hard Gates Remaining",
        "",
    ]
    if packet["hard_gates_remaining"]:
        lines.extend(f"- {item}" for item in packet["hard_gates_remaining"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Stage7 Full Atlas",
            "",
            f"- pack_dir: `{packet['stage7_full_atlas']['pack_dir']}`",
            f"- payload_complete: `{packet['stage7_full_atlas']['payload_complete']}`",
            f"- direct_weekly_deploy_compatible: `{packet['stage7_full_atlas']['direct_weekly_deploy_compatible']}`",
            f"- stage7_cloudrun_adapter_ready: `{packet['stage7_cloudrun_adapter']['ready']}`",
            f"- adapter_gap: `{packet['stage7_adapter_gap']['present']}`",
            "",
            "## Weekly Production Release",
            "",
            f"- release_dir: `{packet['weekly_production_release']['path']}`",
            f"- compatible_with_bake_and_deploy: `{packet['weekly_production_release']['compatible_with_bake_and_deploy']}`",
            f"- manifest_item_count: `{packet['weekly_production_release']['manifest_item_count']}`",
            f"- current_item_count: `{packet['weekly_production_release']['current_item_count']}`",
            f"- bake_script_supports_dry_run: `{packet['weekly_bake_script']['supports_dry_run']}`",
            f"- bake_script_requires_stage7_atlas_flag: `{packet['weekly_bake_script']['supports_stage7_atlas_required_gate']}`",
            f"- bake_script_deprecated_cloudrun_fallback: `{packet['weekly_bake_script']['supports_deprecated_cloudrun_fallback']}`",
            f"- bake_script_deprecated_image_upload: `{packet['weekly_bake_script']['supports_deprecated_image_upload']}`",
            f"- dry_run_log_present: `{packet['weekly_bake_dry_run']['log_present']}`",
            "",
            "## CloudRun Stage7 Packaging",
            "",
            f"- decision: `{packet['cloudrun_stage7_packaging']['decision']}`",
            f"- ok: `{packet['cloudrun_stage7_packaging']['ok']}`",
            "",
            "## Next Executable Steps",
            "",
        ]
    )
    for item in packet["next_executable_steps"]:
        lines.append(
            f"- `{item['lane']}` / `{item['mode']}` / allowed_now=`{item['allowed_now']}`: "
            f"`{' '.join(item['command'])}`"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Packet only. No deploy, production publish, SQLite write, graph/vector/mem0 write, paid API, D: scan, or secret read.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rc", type=Path, default=DEFAULT_RC)
    parser.add_argument("--consumer-gate", type=Path, default=DEFAULT_CONSUMER_GATE)
    parser.add_argument("--publish-config", type=Path, default=DEFAULT_PUBLISH_CONFIG)
    parser.add_argument("--cloudrun-service-root", type=Path, default=DEFAULT_CLOUDRUN_SERVICE_ROOT)
    parser.add_argument("--weekly-bake-script", type=Path, default=DEFAULT_WEEKLY_BAKE_SCRIPT)
    parser.add_argument("--weekly-release-dir", type=Path, default=DEFAULT_WEEKLY_RELEASE_DIR)
    parser.add_argument("--stage7-packaging", type=Path, default=DEFAULT_STAGE7_PACKAGING)
    parser.add_argument("--weekly-bake-dry-run-log", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(
        rc_path=args.rc,
        consumer_gate_path=args.consumer_gate,
        publish_config_path=args.publish_config,
        cloudrun_service_root=args.cloudrun_service_root,
        weekly_bake_script_path=args.weekly_bake_script,
        weekly_release_dir=args.weekly_release_dir,
        stage7_packaging_path=args.stage7_packaging,
        weekly_bake_dry_run_log=args.weekly_bake_dry_run_log,
        out_dir=args.out_dir,
    )
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "hard_gates_remaining": packet["hard_gates_remaining"],
                "stage7_adapter_gap": packet["stage7_adapter_gap"]["present"],
                "weekly_release_items": packet["weekly_production_release"]["manifest_item_count"],
                "packet": str(args.out_dir / "full_pipeline_production_operation_packet.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if packet["ok"] else 2


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
