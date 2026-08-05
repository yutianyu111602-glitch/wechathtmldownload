#!/usr/bin/env python3
"""Recover external current_release from a local package proven identical to production."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


SCHEMA_VERSION = "huaidj_weekly_authoritative_base_recovery.v1"
DEFAULT_PUBLIC_BASE = "https://weekly-api-255880-4-1371956557.sh.run.tcloudbase.com"
DEFAULT_DATA_ROOT = Path(r"F:\DevData\HuaidjRuntime\state\weekly_activity_cloudrun\data")


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return value


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def item_ids(payload: dict[str, Any]) -> list[str]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("current payload has no items array")
    ids = [str(item.get("id") or "") for item in items if isinstance(item, dict)]
    if not ids or any(not item_id for item_id in ids):
        raise RuntimeError("current payload contains a missing activity id")
    if len(set(ids)) != len(ids):
        raise RuntimeError("current payload contains duplicate activity ids")
    return ids


def id_sha256(ids: list[str]) -> str:
    return hashlib.sha256(("\n".join(sorted(ids)) + "\n").encode("utf-8")).hexdigest()


def make_json_fetcher(proxy_url: str = "") -> Callable[[str], dict[str, Any]]:
    handlers: list[Any] = []
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    opener = urllib.request.build_opener(*handlers)

    def fetch(url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "huaidj-authoritative-recovery/1"})
        with opener.open(request, timeout=30) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"public endpoint returned a non-object payload: {url}")
        return value

    return fetch


def fetch_public_package(
    public_base: str,
    fetch_json: Callable[[str], dict[str, Any]],
    *,
    max_pages: int = 1000,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = public_base.rstrip("/")
    manifest = fetch_json(f"{base}/api/v1/weekly/manifest")
    rows: list[dict[str, Any]] = []
    cursor = "0"
    seen: set[str] = set()
    for _ in range(max_pages):
        if cursor in seen:
            raise RuntimeError(f"public pagination cursor repeated: {cursor}")
        seen.add(cursor)
        query = urllib.parse.urlencode({"scope": "package", "limit": 100, "cursor": cursor})
        payload = fetch_json(f"{base}/api/v1/weekly/current?{query}")
        page_rows = payload.get("items")
        if not isinstance(page_rows, list):
            raise RuntimeError("public package page has no items array")
        rows.extend(item for item in page_rows if isinstance(item, dict))
        page = payload.get("page") if isinstance(payload.get("page"), dict) else {}
        next_cursor = str(page.get("nextCursor") or "").strip()
        if not next_cursor:
            break
        cursor = next_cursor
    else:
        raise RuntimeError(f"public pagination exceeded max_pages={max_pages}")
    return manifest, rows


def validate_candidate(
    source_api_dir: Path,
    public_manifest: dict[str, Any],
    public_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    source_manifest = read_json(source_api_dir / "manifest.json")
    source_current = read_json(source_api_dir / "current.json")
    source_ids = item_ids(source_current)
    public_ids = item_ids({"items": public_rows})
    source_count = len(source_ids)
    public_count = len(public_ids)
    failures: list[str] = []
    if int(source_manifest.get("item_count") or 0) != source_count:
        failures.append("source_manifest_current_count_mismatch")
    if int(public_manifest.get("item_count") or 0) != public_count:
        failures.append("public_manifest_package_count_mismatch")
    if source_count != public_count:
        failures.append("source_public_item_count_mismatch")
    source_hash = id_sha256(source_ids)
    public_hash = id_sha256(public_ids)
    if source_hash != public_hash:
        failures.append("source_public_activity_id_digest_mismatch")
    source_generated = str(source_manifest.get("generated_at") or source_current.get("generated_at") or "")
    public_generated = str(public_manifest.get("generated_at") or "")
    if source_generated and public_generated and source_generated != public_generated:
        failures.append("source_public_generated_at_mismatch")
    return {
        "ok": not failures,
        "source_api_dir": str(source_api_dir.resolve()),
        "source_item_count": source_count,
        "public_item_count": public_count,
        "source_activity_id_sha256": source_hash,
        "public_activity_id_sha256": public_hash,
        "source_generated_at": source_generated,
        "public_generated_at": public_generated,
        "club_overviews_present": (source_api_dir / "club_overviews.json").is_file(),
        "failures": failures,
    }


def promote_candidate(source_api_dir: Path, data_root: Path) -> dict[str, Any]:
    source = source_api_dir.resolve()
    root = data_root.resolve()
    target = root / "current_release"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stage = root / f".authoritative_recovery_stage_{stamp}_{os.getpid()}"
    backup_root = root / "recovery_backups"
    backup = backup_root / f"current_release_{stamp}"
    if stage.exists() or backup.exists():
        raise RuntimeError("recovery stage or backup path already exists")
    root.mkdir(parents=True, exist_ok=True)
    backup_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, stage)
    staged_manifest = read_json(stage / "manifest.json")
    staged_current = read_json(stage / "current.json")
    if int(staged_manifest.get("item_count") or 0) != len(item_ids(staged_current)):
        shutil.rmtree(stage)
        raise RuntimeError("staged package failed manifest/current count verification")

    moved_old = False
    try:
        if target.exists():
            os.replace(target, backup)
            moved_old = True
        os.replace(stage, target)
    except Exception:
        if target.exists() and not moved_old:
            shutil.rmtree(target, ignore_errors=True)
        if moved_old and backup.exists() and not target.exists():
            os.replace(backup, target)
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return {
        "target": str(target),
        "backup": str(backup) if moved_old else "",
        "backup_recoverable": moved_old,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-api-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--public-base", default=DEFAULT_PUBLIC_BASE)
    parser.add_argument("--proxy-url", default=os.environ.get("HUAIDJ_PROXY_URL", ""))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest, rows = fetch_public_package(args.public_base, make_json_fetcher(args.proxy_url))
    validation = validate_candidate(args.source_api_dir, manifest, rows)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decision": "candidate_matches_public_package" if validation["ok"] else "blocked",
        "apply_requested": bool(args.apply),
        "applied": False,
        "validation": validation,
        "promotion": {},
    }
    if args.apply and validation["ok"]:
        report["promotion"] = promote_candidate(args.source_api_dir, args.data_root)
        target_current = read_json(args.data_root / "current_release" / "current.json")
        target_hash = id_sha256(item_ids(target_current))
        if target_hash != validation["public_activity_id_sha256"]:
            raise RuntimeError("promoted current_release failed public activity-ID digest readback")
        report["applied"] = True
        report["decision"] = "authoritative_base_recovered"
        report["target_activity_id_sha256"] = target_hash
    write_json_atomic(args.report, report)
    print(json.dumps(report, ensure_ascii=False))
    return 0 if validation["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
