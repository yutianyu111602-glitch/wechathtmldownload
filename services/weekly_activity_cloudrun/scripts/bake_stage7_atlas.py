#!/usr/bin/env python3
"""Bake Stage7 atlas data into the CloudRun Docker context.

The CloudRun image is built from services/weekly_activity_cloudrun, so files
under tools/stage7_rewrite/reports are not available after deploy. This script
copies the frozen Stage7 atlas release plus report-backed recommendation/RAG
evidence into data/stage7_atlas and rewrites the release pointer to use local
relative paths.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
REPO_ROOT = PROJECT_DIR.parents[1]
STAGE7_ROOT = REPO_ROOT / "tools" / "stage7_rewrite"

DEFAULT_POINTER = STAGE7_ROOT / "reports" / "consumer_release_pack_full_unknown_time_20260517" / "release_pointer.staging.json"
DEFAULT_RECOMMENDATIONS = STAGE7_ROOT / "reports" / "hybrid_recommend_canary_20260517" / "hybrid_recommend_canary.json"
DEFAULT_GRAPH_RAG = STAGE7_ROOT / "reports" / "graph_rag_answer_20260517" / "graph_rag_answer_drafts.jsonl"
DEFAULT_VECTOR_ROUTER = STAGE7_ROOT / "reports" / "vector_collection_router_smoke_20260518" / "vector_collection_router_smoke.json"
DEFAULT_OUT_DIR = PROJECT_DIR / "data" / "stage7_atlas"
SCHEMA_VERSION = "weekly_cloudrun_stage7_atlas_package.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_source(path_text: str, *, pointer_path: Path, stage7_root: Path) -> Path:
    raw = Path(path_text)
    if raw.is_absolute():
        return raw
    repo_root = stage7_root.parents[1]
    candidates = [repo_root / raw, stage7_root / raw, pointer_path.parent / raw]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def extract_counts(pointer: dict[str, Any]) -> dict[str, int]:
    counts = pointer.get("counts") if isinstance(pointer.get("counts"), dict) else {}
    result: dict[str, int] = {}
    for key in ("articles", "entities", "events", "missing_publish_time_articles"):
        value = counts.get(key) if isinstance(counts, dict) else None
        if value is None:
            value = pointer.get(key)
        if value is not None:
            result[key] = int(value)
    return result


def source_path_text(files: dict[str, Any], key: str, fallback: str) -> str:
    entry = files.get(key)
    if isinstance(entry, dict):
        return str(entry.get("path") or fallback)
    if isinstance(entry, str):
        return entry
    return fallback


def hash_existing(path: Path) -> dict[str, Any]:
    return {"bytes": path.stat().st_size, "sha256": sha256_file(path)}


def copy_file(src: Path, dst: Path, *, dry_run: bool, gzip_payload: bool = False) -> dict[str, Any]:
    if not src.exists():
        raise FileNotFoundError(src)
    final_dst = dst.with_suffix(dst.suffix + ".gz") if gzip_payload else dst
    if not dry_run:
        final_dst.parent.mkdir(parents=True, exist_ok=True)
        if gzip_payload:
            with src.open("rb") as source, gzip.open(final_dst, "wb", compresslevel=6) as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
        else:
            shutil.copy2(src, final_dst)
        final_stats = hash_existing(final_dst)
    else:
        final_stats = hash_existing(src)
    result = {
        "source": str(src),
        "path": str(final_dst),
        "bytes": final_stats["bytes"],
        "sha256": final_stats["sha256"],
        "gzip_payload": gzip_payload,
        "copied": not dry_run,
    }
    return result


def build_package(
    *,
    pointer_path: Path,
    recommendations_path: Path,
    graph_rag_path: Path,
    vector_router_path: Path,
    out_dir: Path,
    stage7_root: Path,
    dry_run: bool = False,
    compress_jsonl: bool = True,
) -> dict[str, Any]:
    pointer = read_json(pointer_path)
    files = pointer.get("files") if isinstance(pointer.get("files"), dict) else {}
    counts = extract_counts(pointer)
    required_keys = {"articles": "articles.jsonl", "entities": "entities.jsonl", "events": "events.jsonl"}
    blockers: list[str] = []
    copied: dict[str, Any] = {}
    rewritten_pointer = json.loads(json.dumps(pointer, ensure_ascii=False))
    rewritten_pointer["counts"] = counts
    if not isinstance(rewritten_pointer.get("files"), dict):
        rewritten_pointer["files"] = {}

    if not dry_run:
        if out_dir.exists() and out_dir.name == "stage7_atlas":
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    for key, filename in required_keys.items():
        source_path = resolve_source(source_path_text(files, key, filename), pointer_path=pointer_path, stage7_root=stage7_root)
        try:
            copied[key] = copy_file(
                source_path,
                out_dir / filename,
                dry_run=dry_run,
                gzip_payload=compress_jsonl and source_path.suffix == ".jsonl",
            )
            rewritten_pointer.setdefault("files", {})[key] = {
                "path": Path(copied[key]["path"]).name,
                "bytes": copied[key]["bytes"],
                "sha256": copied[key]["sha256"],
            }
        except FileNotFoundError:
            blockers.append(f"missing_{key}_source:{source_path}")

    source_manifest = pointer_path if pointer_path.name == "manifest.json" else pointer_path.parent / "manifest.json"
    extra_sources = {
        "source_manifest": (source_manifest, "source_manifest.json"),
        "recommendations": (recommendations_path, "recommendations.json"),
        "graph_rag_answers": (graph_rag_path, "graph_rag_answer_drafts.jsonl"),
        "vector_router": (vector_router_path, "vector_collection_router_smoke.json"),
    }
    for key, (src, filename) in extra_sources.items():
        try:
            copied[key] = copy_file(src, out_dir / filename, dry_run=dry_run)
        except FileNotFoundError:
            blockers.append(f"missing_{key}_source:{src}")

    rewritten_pointer["packaged_for"] = "weekly_activity_cloudrun"
    rewritten_pointer["packaged_at"] = now_iso()
    rewritten_pointer["packaged_from_pointer"] = str(pointer_path)
    if not dry_run and not blockers:
        write_json(out_dir / "release_pointer.staging.json", rewritten_pointer)

    package_manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": not blockers,
        "decision": "stage7_atlas_package_ready" if not blockers else "stage7_atlas_package_blocked",
        "dry_run": dry_run,
        "out_dir": str(out_dir),
        "compress_jsonl": compress_jsonl,
        "pointer": str(pointer_path),
        "counts": counts,
        "copied": copied,
        "required_files": [
            "release_pointer.staging.json",
            "articles.jsonl",
            "entities.jsonl",
            "events.jsonl",
            "recommendations.json",
            "graph_rag_answer_drafts.jsonl",
            "vector_collection_router_smoke.json",
        ],
        "blockers": blockers,
        "safety": {
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
    if not dry_run:
        write_json(out_dir / "package_manifest.json", package_manifest)
    return package_manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--recommendations", type=Path, default=DEFAULT_RECOMMENDATIONS)
    parser.add_argument("--graph-rag", type=Path, default=DEFAULT_GRAPH_RAG)
    parser.add_argument("--vector-router", type=Path, default=DEFAULT_VECTOR_ROUTER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--stage7-root", type=Path, default=STAGE7_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-compress-jsonl", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_package(
        pointer_path=args.pointer,
        recommendations_path=args.recommendations,
        graph_rag_path=args.graph_rag,
        vector_router_path=args.vector_router,
        out_dir=args.out_dir,
        stage7_root=args.stage7_root,
        dry_run=args.dry_run,
        compress_jsonl=not args.no_compress_jsonl,
    )
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "dry_run": report["dry_run"],
                "out_dir": report["out_dir"],
                "blockers": report["blockers"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
