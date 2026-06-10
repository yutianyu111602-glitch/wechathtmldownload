#!/usr/bin/env python3
"""Verify vector-role delta points by deterministic Qdrant point id."""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_vector_role_full_wave as role_wave  # noqa: E402


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                row["_line_no"] = line_no
                yield row


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def point_lookup(qdrant_url: str, collection: str, ids: list[str]) -> list[dict[str, Any]]:
    response = requests.post(
        f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points",
        json={"ids": ids, "with_payload": True, "with_vector": False},
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant point lookup failed {response.status_code}: {response.text[:500]}")
    result = response.json().get("result")
    return result if isinstance(result, list) else []


def build_collection_map(role_dir: Path, stamp: str) -> tuple[dict[str, str], dict[str, Any]]:
    metadata = read_json(role_dir / "metadata.json")
    model = str(metadata.get("model") or "")
    dim = int(metadata.get("dim") or 0)
    role = str(metadata.get("model_role") or role_dir.name)
    kinds = role_wave.role_kinds(metadata)
    return {kind: role_wave.collection_name(kind, model, dim, stamp, role) for kind in kinds}, metadata


def verify(role_dir: Path, stamp: str, qdrant_url: str, out_dir: Path, batch_size: int) -> dict[str, Any]:
    collections, metadata = build_collection_map(role_dir, stamp)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for card in iter_jsonl(role_dir / "card_texts.jsonl"):
        kind = str(card.get("parent_kind") or card.get("type") or "unknown")
        collection = collections.get(kind)
        if not collection:
            continue
        grouped[collection].append(card)

    collection_reports: dict[str, Any] = {}
    all_mismatches: list[dict[str, Any]] = []
    for collection, cards in sorted(grouped.items()):
        checked = 0
        matched = 0
        missing = 0
        mismatched = 0
        for start in range(0, len(cards), max(1, batch_size)):
            chunk = cards[start : start + max(1, batch_size)]
            ids = [role_wave.point_id(card) for card in chunk]
            found = {str(item.get("id")): item for item in point_lookup(qdrant_url, collection, ids)}
            for card, point_id in zip(chunk, ids):
                checked += 1
                point = found.get(point_id)
                if not point:
                    missing += 1
                    if len(all_mismatches) < 50:
                        all_mismatches.append({"collection": collection, "point_id": point_id, "reason": "missing"})
                    continue
                payload = point.get("payload") or {}
                if payload.get("job_id") == card.get("id") and payload.get("text_sha1") == card.get("text_sha1"):
                    matched += 1
                else:
                    mismatched += 1
                    if len(all_mismatches) < 50:
                        all_mismatches.append(
                            {
                                "collection": collection,
                                "point_id": point_id,
                                "reason": "payload_mismatch",
                                "expected_job_id": card.get("id"),
                                "actual_job_id": payload.get("job_id"),
                                "expected_text_sha1": card.get("text_sha1"),
                                "actual_text_sha1": payload.get("text_sha1"),
                            }
                        )
        collection_reports[collection] = {
            "checked": checked,
            "matched": matched,
            "missing": missing,
            "mismatched": mismatched,
            "match_rate": round(matched / max(checked, 1), 6),
        }

    total_checked = sum(int(row["checked"]) for row in collection_reports.values())
    total_matched = sum(int(row["matched"]) for row in collection_reports.values())
    summary = {
        "schema_version": "stage7_qdrant_role_delta_point_verify.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": total_checked == total_matched and total_checked > 0,
        "role_dir": str(role_dir),
        "model_role": metadata.get("model_role"),
        "model": metadata.get("model"),
        "stamp": stamp,
        "qdrant_url": qdrant_url,
        "total_checked": total_checked,
        "total_matched": total_matched,
        "collection_reports": collection_reports,
        "mismatches_sample": all_mismatches,
        "safety": {
            "qdrant_read_only": True,
            "qdrant_write_executed": False,
            "alias_change_executed": False,
            "embedding_call_executed": False,
        },
    }
    write_json(out_dir / f"{metadata.get('model_role') or role_dir.name}_point_verify.json", summary)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role-dir", type=Path, required=True)
    parser.add_argument("--stamp", required=True)
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=256)
    args = parser.parse_args(argv)
    summary = verify(args.role_dir, args.stamp, args.qdrant_url, args.out_dir, args.batch_size)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
