#!/usr/bin/env python3
"""Prepare a CloudRun deploy context that serves the Atlas SQLite read model."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
REPO_ROOT = PROJECT_DIR.parents[1]
DEFAULT_CANDIDATE_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_MANIFEST = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "manifest.json"
DEFAULT_ENTITY_MERGE_GROUPS = REPO_ROOT / "reports" / "atlas_entity_merge_plan_ocr_full_fourthpass_current" / "entity_merge_groups_report_only.jsonl"
DEFAULT_SOUND_SYSTEM_EVIDENCE = REPO_ROOT / "reports" / "atlas_venue_sound_system_evidence_current" / "venue_sound_system_evidence.jsonl"
DEFAULT_CONTEXT_DIR = PROJECT_DIR / "tmp" / "cloudrun_deploy_context_atlas_sqlite_fourthpass_20260527_2008"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_serving_sqlite_cloudrun_context_entity_merge_fourthpass_20260527_2008"
TOP_LEVEL_ITEMS = ["package.json", "Dockerfile", "assets", "src", "scripts"]
STATIC_DATA_DIRS = ["current_release", "source_actions", "stage7_atlas"]
BASE_SQLITE_ENV_LINES = [
    "ENV ATLAS_USE_SERVING_READ_MODEL=1",
    "ENV ATLAS_SQLITE_READONLY=1",
    "ENV STAGE7_ATLAS_SQLITE_DB=/app/data/atlas_serving/atlas_serving.sqlite",
]
ENTITY_MERGE_ENV_LINE = "ENV ATLAS_ENTITY_MERGE_GROUPS_PATH=/app/data/atlas_serving/entity_merge_groups_report_only.jsonl"
SOUND_SYSTEM_ENV_LINE = "ENV ATLAS_VENUE_SOUND_SYSTEM_EVIDENCE_PATH=/app/data/atlas_serving/venue_sound_system_evidence.jsonl"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def source_ref(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.name


def context_ref(path: Path, context_dir: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(context_dir.resolve()).as_posix()
    except ValueError:
        try:
            return resolved.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return resolved.name


def copy_path(src: Path, dst: Path) -> int:
    if not src.exists():
        raise FileNotFoundError(src)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        return sum(path.stat().st_size for path in dst.rglob("*") if path.is_file())
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return dst.stat().st_size


def patch_dockerfile(dockerfile: Path, env_lines: list[str] | None = None) -> None:
    env_lines = env_lines or BASE_SQLITE_ENV_LINES
    text = dockerfile.read_text(encoding="utf-8")
    existing = [line.strip() for line in text.splitlines()]
    missing = [line for line in env_lines if line not in existing]
    if not missing:
        return
    if not text.endswith("\n"):
        text += "\n"
    insertion = "\n# Atlas DJ-first public serving read model.\n" + "\n".join(missing) + "\n"
    marker = "ENV PORT=8787"
    if marker in text:
        text = text.replace(marker, marker + insertion, 1)
    else:
        text += insertion
    dockerfile.write_text(text, encoding="utf-8")


def extract_counts(manifest: dict[str, Any]) -> dict[str, int]:
    counts = manifest.get("counts") if isinstance(manifest.get("counts"), dict) else {}
    result: dict[str, int] = {}
    for key, value in counts.items():
        if isinstance(value, int):
            result[key] = value
    return result


def prepare_context(
    *,
    candidate_db: Path,
    manifest_path: Path,
    entity_merge_groups_path: Path | None = None,
    sound_system_evidence_path: Path | None = None,
    context_dir: Path,
    out_dir: Path,
) -> dict[str, Any]:
    candidate_db = candidate_db.resolve()
    manifest_path = manifest_path.resolve()
    if not candidate_db.exists():
        raise FileNotFoundError(candidate_db)
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)

    if context_dir.exists():
        shutil.rmtree(context_dir)
    context_dir.mkdir(parents=True, exist_ok=True)

    copied: dict[str, Any] = {}
    for name in TOP_LEVEL_ITEMS:
        src = PROJECT_DIR / name
        dst = context_dir / name
        copied[name] = {"path": context_ref(dst, context_dir), "bytes": copy_path(src, dst)}

    for name in STATIC_DATA_DIRS:
        src = PROJECT_DIR / "data" / name
        if not src.exists():
            continue
        dst = context_dir / "data" / name
        copied[f"data/{name}"] = {"path": context_ref(dst, context_dir), "bytes": copy_path(src, dst)}

    serving_dir = context_dir / "data" / "atlas_serving"
    serving_dir.mkdir(parents=True, exist_ok=True)
    staged_db = serving_dir / "atlas_serving.sqlite"
    shutil.copy2(candidate_db, staged_db)
    shutil.copy2(manifest_path, serving_dir / "source_manifest.json")
    candidate_sha = sha256_file(staged_db)
    source_manifest = read_json(manifest_path)
    sidecars: dict[str, Any] = {}
    env_lines = list(BASE_SQLITE_ENV_LINES)
    package_env = {
        "ATLAS_USE_SERVING_READ_MODEL": "1",
        "ATLAS_SQLITE_READONLY": "1",
        "STAGE7_ATLAS_SQLITE_DB": "/app/data/atlas_serving/atlas_serving.sqlite",
    }
    optional_sidecars = [
        (
            "entity_merge_groups",
            entity_merge_groups_path,
            "entity_merge_groups_report_only.jsonl",
            "ATLAS_ENTITY_MERGE_GROUPS_PATH",
            "/app/data/atlas_serving/entity_merge_groups_report_only.jsonl",
            ENTITY_MERGE_ENV_LINE,
        ),
        (
            "venue_sound_system_evidence",
            sound_system_evidence_path,
            "venue_sound_system_evidence.jsonl",
            "ATLAS_VENUE_SOUND_SYSTEM_EVIDENCE_PATH",
            "/app/data/atlas_serving/venue_sound_system_evidence.jsonl",
            SOUND_SYSTEM_ENV_LINE,
        ),
    ]
    for label, source_path, target_name, env_key, container_path, env_line in optional_sidecars:
        source = Path(source_path).resolve() if source_path else None
        if not source or not source.exists():
            sidecars[label] = {
                "copied": False,
                "source_ref": source_ref(source) if source else "",
                "target_path": f"data/atlas_serving/{target_name}",
                "container_path": container_path,
            }
            continue
        target = serving_dir / target_name
        shutil.copy2(source, target)
        sidecars[label] = {
            "copied": True,
            "source_ref": source_ref(source),
            "target_path": context_ref(target, context_dir),
            "container_path": container_path,
            "bytes": target.stat().st_size,
            "sha256": sha256_file(target),
        }
        package_env[env_key] = container_path
        env_lines.append(env_line)
    package_manifest = {
        "schema_version": "atlas_serving_sqlite_cloudrun_package.v1",
        "generated_at": now_iso(),
        "candidate_db_source_ref": source_ref(candidate_db),
        "candidate_db_path": "data/atlas_serving/atlas_serving.sqlite",
        "candidate_db_bytes": staged_db.stat().st_size,
        "candidate_db_sha256": candidate_sha,
        "source_manifest_source_ref": source_ref(manifest_path),
        "source_manifest_path": "data/atlas_serving/source_manifest.json",
        "counts": extract_counts(source_manifest),
        "env": package_env,
        "sidecars": sidecars,
        "safety": {
            "cloud_deploy_executed": False,
            "production_publish_executed": False,
            "sqlite_source_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "secret_read_executed": False,
        },
    }
    write_json(serving_dir / "package_manifest.json", package_manifest)
    copied["data/atlas_serving"] = {
        "path": context_ref(serving_dir, context_dir),
        "bytes": sum(path.stat().st_size for path in serving_dir.rglob("*") if path.is_file()),
    }
    patch_dockerfile(context_dir / "Dockerfile", env_lines)

    dockerfile_text = (context_dir / "Dockerfile").read_text(encoding="utf-8")
    env_ready = all(line in dockerfile_text for line in env_lines)
    report = {
        "schema_version": "atlas_serving_sqlite_cloudrun_context.v1",
        "generated_at": now_iso(),
        "ok": env_ready,
        "decision": "atlas_serving_sqlite_cloudrun_context_ready" if env_ready else "atlas_serving_sqlite_cloudrun_context_blocked",
        "context_dir": source_ref(context_dir),
        "candidate": {
            "source_ref": source_ref(candidate_db),
            "target_path": context_ref(staged_db, context_dir),
            "container_path": "/app/data/atlas_serving/atlas_serving.sqlite",
            "source_manifest_ref": source_ref(manifest_path),
            "source_manifest_path": "data/atlas_serving/source_manifest.json",
            "bytes": staged_db.stat().st_size,
            "sha256": candidate_sha,
            "counts": package_manifest["counts"],
        },
        "sidecars": sidecars,
        "copied": copied,
        "dockerfile_env_ready": env_ready,
        "rollback": {
            "previous_cloudrun_version_capture_required": True,
            "restore_previous_version_or_context_required": True,
            "post_rollback_smoke_required": True,
        },
        "post_deploy_smoke": {
            "required": [
                "GET /healthz",
                "GET /api/v1/stage7/manifest",
                "GET /api/v1/stage7/search?q=MaFoL",
                "GET /api/v1/stage7/graph/profile?q=DaRou",
                "GET /api/v1/stage7/graph/seed?q=SHCR",
                "GET /atlas",
            ]
        },
        "safety": package_manifest["safety"],
    }
    write_json(out_dir / "atlas_serving_sqlite_cloudrun_context.json", report)
    (out_dir / "atlas_serving_sqlite_cloudrun_context.md").write_text(
        "\n".join(
            [
                "# Atlas Serving SQLite CloudRun Context",
                "",
                f"- generated_at: `{report['generated_at']}`",
                f"- decision: `{report['decision']}`",
                f"- context_dir: `{report['context_dir']}`",
                f"- candidate_sha256: `{candidate_sha}`",
                f"- candidate_bytes: `{staged_db.stat().st_size}`",
                f"- dockerfile_env_ready: `{env_ready}`",
                "",
                "Safety: context preparation only; no deploy, production publish, source/raw DB write, graph/vector write, secret read, or D: scan.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-db", type=Path, default=DEFAULT_CANDIDATE_DB)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--entity-merge-groups", type=Path, default=DEFAULT_ENTITY_MERGE_GROUPS)
    parser.add_argument("--sound-system-evidence", type=Path, default=DEFAULT_SOUND_SYSTEM_EVIDENCE)
    parser.add_argument("--context-dir", type=Path, default=DEFAULT_CONTEXT_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = prepare_context(
        candidate_db=args.candidate_db,
        manifest_path=args.manifest,
        entity_merge_groups_path=args.entity_merge_groups,
        sound_system_evidence_path=args.sound_system_evidence,
        context_dir=args.context_dir,
        out_dir=args.out_dir,
    )
    print(json.dumps({"ok": report["ok"], "decision": report["decision"], "context_dir": report["context_dir"]}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
