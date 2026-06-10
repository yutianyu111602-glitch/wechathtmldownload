#!/usr/bin/env python3
"""Verify that Stage7 atlas data is packaged inside the CloudRun Docker context.

This is a report-only deploy gate. It proves that the Stage7 endpoints can use
files copied under services/weekly_activity_cloudrun/data/stage7_atlas instead
of relying on tools/stage7_rewrite paths that are outside the Docker build
context.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SERVICE_ROOT = Path("../../services/weekly_activity_cloudrun")
DEFAULT_OUT_DIR = Path("reports/cloudrun_stage7_packaging_20260518")
REQUIRED_STATIC_FILES = [
    "release_pointer.staging.json",
    "recommendations.json",
    "graph_rag_answer_drafts.jsonl",
    "vector_collection_router_smoke.json",
    "identity_review_workbench.json",
    "package_manifest.json",
]


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


def has_text(path: Path, needle: str) -> bool:
    return path.exists() and needle in path.read_text(encoding="utf-8", errors="replace")


def verify(service_root: Path) -> dict[str, Any]:
    package_dir = service_root / "data" / "stage7_atlas"
    dockerfile = service_root / "Dockerfile"
    store_path = service_root / "src" / "stage7AtlasStore.mjs"
    bake_script = service_root / "scripts" / "bake_and_deploy.py"
    package_manifest_path = package_dir / "package_manifest.json"
    pointer_path = package_dir / "release_pointer.staging.json"

    file_status = {}
    blockers: list[str] = []
    for name in REQUIRED_STATIC_FILES:
        path = package_dir / name
        exists = path.exists()
        file_status[name] = {"path": str(path), "exists": exists, "bytes": path.stat().st_size if exists else 0}
        if not exists:
            blockers.append(f"missing_packaged_file:{name}")

    pointer_counts: dict[str, Any] = {}
    pointer_paths_ok = False
    if pointer_path.exists():
        pointer = read_json(pointer_path)
        pointer_counts = pointer.get("counts") or {}
        pointer_files = pointer.get("files") if isinstance(pointer.get("files"), dict) else {}
        required_pointer_files = ["articles", "entities", "events"]
        for key in required_pointer_files:
            rel_path = str(pointer_files.get(key, {}).get("path") or "")
            path = package_dir / rel_path
            exists = bool(rel_path and path.exists())
            file_status[f"{key}_payload"] = {
                "path": str(path),
                "exists": exists,
                "bytes": path.stat().st_size if exists else 0,
            }
        pointer_paths_ok = all(file_status[f"{key}_payload"]["exists"] for key in required_pointer_files)
        if not pointer_paths_ok:
            blockers.append("pointer_paths_do_not_resolve_inside_package")

    package_manifest_ok = False
    if package_manifest_path.exists():
        package_manifest = read_json(package_manifest_path)
        package_manifest_ok = bool(package_manifest.get("ok"))
        if not package_manifest_ok:
            blockers.append("package_manifest_not_ok")

    docker_copies_data = has_text(dockerfile, "COPY data ./data")
    store_uses_packaged_default = (
        has_text(store_path, "../data/stage7_atlas")
        and has_text(store_path, "vector_collection_router_smoke.json")
        and has_text(store_path, "identity_review_workbench.json")
    )
    bake_requires_stage7_flag = has_text(bake_script, "--require-stage7-atlas")

    if not docker_copies_data:
        blockers.append("dockerfile_does_not_copy_data")
    if not store_uses_packaged_default:
        blockers.append("stage7_store_default_not_packaged")
    if not bake_requires_stage7_flag:
        blockers.append("bake_script_missing_stage7_required_flag")

    return {
        "schema_version": "cloudrun_stage7_packaging_gate.v1",
        "generated_at": now_iso(),
        "ok": not blockers,
        "decision": "cloudrun_stage7_packaging_ready" if not blockers else "cloudrun_stage7_packaging_blocked",
        "service_root": str(service_root),
        "package_dir": str(package_dir),
        "file_status": file_status,
        "pointer_counts": pointer_counts,
        "gates": {
            "package_manifest_ok": package_manifest_ok,
            "pointer_paths_ok": pointer_paths_ok,
            "docker_copies_data": docker_copies_data,
            "store_uses_packaged_default": store_uses_packaged_default,
            "bake_requires_stage7_flag": bake_requires_stage7_flag,
        },
        "blockers": blockers,
        "safety": {
            "report_only": True,
            "cloud_deploy_executed": False,
            "production_publish_executed": False,
            "sqlite_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# CloudRun Stage7 Packaging Gate",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- decision: `{report['decision']}`",
        "",
        "## Gates",
        "",
    ]
    for name, ok in report["gates"].items():
        lines.append(f"- `{name}`: `{ok}`")
    lines.extend(["", "## Files", ""])
    for name, status in report["file_status"].items():
        lines.append(f"- `{name}` exists=`{status['exists']}` bytes=`{status['bytes']}`")
    lines.extend(["", "## Counts", ""])
    for name, value in report["pointer_counts"].items():
        lines.append(f"- `{name}`: `{value}`")
    lines.extend(["", "## Blockers", ""])
    if report["blockers"]:
        lines.extend(f"- `{item}`" for item in report["blockers"])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report only. No deploy, production publish, SQLite write, graph/vector/mem0 write, paid API, or D: scan.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-root", type=Path, default=DEFAULT_SERVICE_ROOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-only-exit-zero", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = verify(args.service_root)
    write_json(args.out_dir / "cloudrun_stage7_packaging.json", report)
    write_markdown(args.out_dir / "cloudrun_stage7_packaging.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "blockers": report["blockers"],
                "report": str(args.out_dir / "cloudrun_stage7_packaging.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if report["ok"] or args.report_only_exit_zero:
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
