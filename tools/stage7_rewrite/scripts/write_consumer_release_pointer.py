#!/usr/bin/env python3
"""Write a staging release pointer and rollback note for a consumer pack."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_PACK_DIR = Path("reports/consumer_release_pack_full_unknown_time_20260514")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for consumer release pointer: {path}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def build_pointer(pack_dir: Path, channel: str, previous_pointer: Path | None = None) -> dict[str, Any]:
    reject_d_path(pack_dir, "pack_dir")
    manifest_path = pack_dir / "manifest.json"
    manifest = read_json(manifest_path)
    files = {
        "manifest": manifest_path,
        "articles": pack_dir / "articles.jsonl",
        "entities": pack_dir / "entities.jsonl",
        "events": pack_dir / "events.jsonl",
    }
    missing = [name for name, path in files.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"missing release pack files: {missing}")
    previous = {}
    if previous_pointer and previous_pointer.exists():
        previous = read_json(previous_pointer)
    return {
        "schema_version": "stage7_consumer_release_pointer.v1",
        "generated_at": now_iso(),
        "channel": channel,
        "pack_dir": str(pack_dir),
        "release_ready": bool(manifest.get("release_ready")),
        "decision": manifest.get("decision"),
        "counts": {
            "articles": manifest.get("articles"),
            "entities": manifest.get("entities"),
            "events": manifest.get("events"),
            "missing_publish_time_articles": manifest.get("missing_publish_time_articles"),
        },
        "publish_time_policy": {
            "allow_unknown_publish_time": bool(manifest.get("allow_unknown_publish_time")),
            "status_field": "publish_time_status",
            "fallback_evidence_field": "source_archived_at",
        },
        "files": {
            name: {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for name, path in files.items()
        },
        "previous_pointer": previous,
        "writes": "local pointer only; no publish or production DB writes",
    }


def write_markdown(path: Path, pointer: dict[str, Any]) -> None:
    lines = [
        "# Consumer Release Pointer",
        "",
        f"- generated_at: `{pointer['generated_at']}`",
        f"- channel: `{pointer['channel']}`",
        f"- pack_dir: `{pointer['pack_dir']}`",
        f"- release_ready: `{pointer['release_ready']}`",
        f"- decision: `{pointer['decision']}`",
        f"- articles: `{pointer['counts']['articles']}`",
        f"- entities: `{pointer['counts']['entities']}`",
        f"- events: `{pointer['counts']['events']}`",
        f"- missing_publish_time_articles: `{pointer['counts']['missing_publish_time_articles']}`",
        "",
        "## Rollback",
        "",
        "- This pointer is local staging only.",
        "- Rollback means restoring the previous pointer file or leaving consumers on the prior pack.",
        "- No production publish or SQLite write has been performed by this command.",
        "",
        "## Files",
        "",
    ]
    for name, info in pointer["files"].items():
        lines.append(f"- `{name}`: `{info['path']}` bytes=`{info['bytes']}` sha256=`{info['sha256'][:16]}...`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(pack_dir: Path, channel: str, previous_pointer: Path | None = None) -> dict[str, Any]:
    pointer = build_pointer(pack_dir, channel, previous_pointer)
    write_json(pack_dir / f"release_pointer.{channel}.json", pointer)
    write_markdown(pack_dir / f"release_pointer.{channel}.md", pointer)
    return pointer


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=DEFAULT_PACK_DIR)
    parser.add_argument("--channel", default="staging")
    parser.add_argument("--previous-pointer", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    pointer = run(args.pack_dir, args.channel, args.previous_pointer)
    print(json.dumps({"channel": pointer["channel"], "release_ready": pointer["release_ready"], "pack_dir": pointer["pack_dir"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
