#!/usr/bin/env python3
"""Build a bounded recapture queue from Stage7 manifest rows.

Reads only paths named by the manifest rows. It does not scan D: recursively,
call Dajiala/mptext, download assets, or mutate archive/source trees.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def host_path(value: str | Path | None) -> Path:
    raw = str(value or "").replace("\\", "/")
    if os.name == "nt" and raw.startswith("/mnt/") and len(raw) > 7:
        drive = raw[5]
        if raw[6] == "/" and drive.isalpha():
            return Path(f"{drive.upper()}:/" + raw[7:])
    return Path(str(value or ""))


def read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def account_token(row: dict[str, Any]) -> tuple[str, str]:
    account = first_string(row.get("source_account"), row.get("account_key"), row.get("account"))
    token = first_string(row.get("article_id"), row.get("token"))
    uid = first_string(row.get("article_uid"))
    if uid and (not account or not token):
        parts = uid.split("/", 1)
        if len(parts) == 2:
            account = account or parts[0]
            token = token or parts[1]
    return account, token


def build_record(row: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    account, token = account_token(row)
    meta = read_json(host_path(row.get("meta_path")))
    archive_dir = host_path(row.get("archive_dir"))
    archive_meta = read_json(archive_dir / "archive_meta.json") if archive_dir else {}
    source_url = first_string(
        row.get("source_url"),
        row.get("url"),
        meta.get("source_url"),
        meta.get("url"),
        meta.get("final_url"),
        archive_meta.get("source_url"),
        archive_meta.get("final_url"),
    )
    title = first_string(row.get("title"), meta.get("title"), archive_meta.get("title"))
    if not account or not token:
        return None, {**row, "missing_reason": "missing_account_or_token"}
    if not source_url.startswith("http"):
        return None, {**row, "missing_reason": "missing_source_url", "archive_status": archive_meta.get("status", "")}
    record = {
        "account_key": account,
        "token": token,
        "source_account": account,
        "article_uid": f"{account}/{token}",
        "source_url": source_url,
        "url": source_url,
        "title": title,
        "author": first_string(meta.get("author_display"), archive_meta.get("author")),
        "cover_url": first_string(meta.get("og_image"), archive_meta.get("cover_url")),
        "post_time": first_string(meta.get("publish_time_text"), meta.get("publish_time_iso")),
        "post_date": first_string(meta.get("publish_time_iso"), meta.get("publish_time_text")),
        "page": 1,
        "discovered_at": now_iso(),
        "discovery_source": "stage7-corrected-empty-no-local-image-recapture",
        "archive_status": first_string(archive_meta.get("status")),
        "archive_dir": str(archive_dir).replace("\\", "/") if archive_dir else "",
        "manifest_article_uid": first_string(row.get("article_uid")),
        "input_chars": int(row.get("input_chars") or 0),
        "local_image_count": int(row.get("local_image_count") or 0),
    }
    return record, None


def build_queue(manifest: Path, out_dir: Path, canary_size: int, limit: int = 0) -> dict[str, Any]:
    rows = read_jsonl(manifest)
    if limit > 0:
        rows = rows[:limit]
    records: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicate_count = 0
    archive_status_counts: Counter[str] = Counter()
    for row in rows:
        record, miss = build_record(row)
        if miss is not None:
            missing.append(miss)
            continue
        assert record is not None
        key = f"{record['account_key']}/{record['token']}"
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        archive_status_counts[str(record.get("archive_status") or "<missing>")] += 1
        records.append(record)

    out_dir.mkdir(parents=True, exist_ok=True)
    queue_path = out_dir / "recapture_queue.jsonl"
    canary_path = out_dir / f"recapture_queue_canary{canary_size}.jsonl"
    missing_path = out_dir / "recapture_queue_missing.jsonl"
    summary_path = out_dir / "summary.json"
    write_jsonl(queue_path, records)
    write_jsonl(canary_path, records[:canary_size])
    write_jsonl(missing_path, missing)
    summary = {
        "schema_version": "stage7_recapture_queue_from_manifest.v1",
        "generated_at": now_iso(),
        "manifest": str(manifest),
        "input_rows": len(rows),
        "emitted_records": len(records),
        "missing_records": len(missing),
        "duplicate_records": duplicate_count,
        "canary_rows": min(canary_size, len(records)),
        "archive_status_counts": dict(archive_status_counts),
        "outputs": {
            "queue": str(queue_path),
            "canary": str(canary_path),
            "missing": str(missing_path),
            "summary": str(summary_path),
        },
        "writes": "queue/report files only; no API/archive/asset/vector/DB writes",
    }
    write_json(summary_path, summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--canary-size", type=int, default=20)
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_queue(args.manifest, args.out_dir, args.canary_size, args.limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
