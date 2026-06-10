"""Build full Qdrant staging collections from release-scoped staging collections.

Qdrant aliases point at one collection. The production writer intentionally
writes release-scoped staging collections, so alias promotion needs a separate
materialized full collection per object kind before any alias swap.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


DEFAULT_PRODUCTION_DB = Path(r"D:\downstream_results\stage7_rewrite\stage8\production\pc_vector_production.sqlite")
DEFAULT_MODEL_SLUG = "stella_large_zh_v2"
DEFAULT_DIM = 1024
KINDS = ["article", "claim", "entity_identity", "entity_mention", "event", "relation"]


def source_collection(kind: str, release_id: str, model_slug: str, dim: int) -> str:
    return f"wechat_prod_{kind}_{model_slug}_{dim}_{release_id}_staging"


def target_collection(kind: str, target_release_id: str, model_slug: str, dim: int) -> str:
    return f"wechat_prod_{kind}_{model_slug}_{dim}_{target_release_id}_full_staging"


def read_pc_expected_counts(db_path: Path, release_ids: list[str]) -> dict[str, int]:
    if not db_path.exists():
        return {}
    placeholders = ",".join("?" for _ in release_ids)
    query = (
        "SELECT object_kind, COUNT(*) FROM vector_write_ledger "
        f"WHERE release_id IN ({placeholders}) GROUP BY object_kind"
    )
    conn = sqlite3.connect(db_path)
    try:
        return {str(kind): int(count) for kind, count in conn.execute(query, release_ids).fetchall()}
    finally:
        conn.close()


def inspect_sources(client: Any, release_ids: list[str], model_slug: str, dim: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for release_id in release_ids:
        for kind in KINDS:
            name = source_collection(kind, release_id, model_slug, dim)
            if not client.collection_exists(name):
                continue
            info = client.get_collection(name)
            rows.append(
                {
                    "release_id": release_id,
                    "kind": kind,
                    "collection": name,
                    "points_count": int(getattr(info, "points_count", 0) or 0),
                    "status": str(getattr(info, "status", "")),
                }
            )
    return rows


def ensure_target(client: Any, collection_name: str, dim: int) -> None:
    from qdrant_client import models

    if client.collection_exists(collection_name):
        return
    client.create_collection(
        collection_name=collection_name,
        vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
    )


def scroll_points(client: Any, collection_name: str, limit: int):
    offset = None
    while True:
        points, offset = client.scroll(
            collection_name=collection_name,
            limit=limit,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not points:
            break
        yield points
        if offset is None:
            break


def copy_kind_sources(
    client: Any,
    sources: list[dict[str, Any]],
    target_name: str,
    *,
    dim: int,
    scroll_limit: int,
    batch_size: int,
) -> int:
    from qdrant_client import models

    ensure_target(client, target_name, dim)
    copied = 0
    for source in sources:
        source_name = source["collection"]
        for points in scroll_points(client, source_name, scroll_limit):
            batch = []
            for point in points:
                payload = dict(getattr(point, "payload", {}) or {})
                payload["full_source_collection"] = source_name
                payload["full_source_release_id"] = source["release_id"]
                payload["full_source_point_id"] = str(point.id)
                batch.append(models.PointStruct(id=point.id, vector=point.vector, payload=payload))
            for start in range(0, len(batch), batch_size):
                client.upsert(collection_name=target_name, points=batch[start:start + batch_size], wait=True)
            copied += len(batch)
    return copied


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=args.qdrant_url, timeout=120)
    release_ids = list(dict.fromkeys(args.source_release_id))
    source_rows = inspect_sources(client, release_ids, args.model_slug, args.dim)
    expected_counts = read_pc_expected_counts(Path(args.pc_db), release_ids)
    source_counts: dict[str, int] = {}
    for row in source_rows:
        source_counts[row["kind"]] = source_counts.get(row["kind"], 0) + int(row["points_count"])

    target_rows: list[dict[str, Any]] = []
    writes = []
    if args.mode == "build":
        for kind in sorted(source_counts):
            target_name = target_collection(kind, args.target_release_id, args.model_slug, args.dim)
            kind_sources = [row for row in source_rows if row["kind"] == kind]
            copied = copy_kind_sources(
                client,
                kind_sources,
                target_name,
                dim=args.dim,
                scroll_limit=args.scroll_limit,
                batch_size=args.batch_size,
            )
            info = client.get_collection(target_name)
            points_count = int(getattr(info, "points_count", 0) or 0)
            target_rows.append(
                {
                    "kind": kind,
                    "collection": target_name,
                    "copied_points": copied,
                    "points_count": points_count,
                    "matches_source_count": points_count == source_counts[kind],
                }
            )
            writes.append(target_name)

    mismatches = []
    for kind, source_count in sorted(source_counts.items()):
        expected = int(expected_counts.get(kind, source_count))
        if source_count != expected:
            mismatches.append({"kind": kind, "qdrant_source_count": source_count, "pc_expected_count": expected})
    for row in target_rows:
        if not row["matches_source_count"]:
            mismatches.append(
                {
                    "kind": row["kind"],
                    "target_count": row["points_count"],
                    "qdrant_source_count": source_counts[row["kind"]],
                }
            )

    report = {
        "schema_version": "stage8_vector_full_collection_builder.v1",
        "mode": args.mode,
        "qdrant_url": args.qdrant_url,
        "model_slug": args.model_slug,
        "dim": args.dim,
        "source_release_ids": release_ids,
        "target_release_id": args.target_release_id,
        "source_collections": source_rows,
        "source_counts_by_kind": source_counts,
        "pc_expected_counts_by_kind": expected_counts,
        "target_collections": target_rows,
        "written_collections": writes,
        "mismatches": mismatches,
        "ok": not mismatches,
    }
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "full_collection_builder_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    write_markdown(out_dir / "FULL_COLLECTION_BUILDER_REPORT.md", report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Stage8 Full Qdrant Collection Builder",
        "",
        f"- mode: `{report['mode']}`",
        f"- ok: `{report['ok']}`",
        f"- target_release_id: `{report['target_release_id']}`",
        f"- source_release_ids: `{', '.join(report['source_release_ids'])}`",
        f"- mismatches: `{len(report['mismatches'])}`",
        "",
        "## Source Counts",
        "",
        "| Kind | Qdrant Source Count | PC Expected Count |",
        "|---|---:|---:|",
    ]
    expected = report["pc_expected_counts_by_kind"]
    for kind, count in sorted(report["source_counts_by_kind"].items()):
        lines.append(f"| `{kind}` | {count} | {expected.get(kind, count)} |")
    if report["target_collections"]:
        lines.extend(["", "## Target Collections", "", "| Kind | Collection | Points |", "|---|---|---:|"])
        for row in report["target_collections"]:
            lines.append(f"| `{row['kind']}` | `{row['collection']}` | {row['points_count']} |")
    if report["mismatches"]:
        lines.extend(["", "## Mismatches", "", "```json", json.dumps(report["mismatches"], ensure_ascii=False, indent=2), "```"])
    path.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dry-run", "build"], default="dry-run")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--pc-db", default=str(DEFAULT_PRODUCTION_DB))
    parser.add_argument("--source-release-id", action="append", required=True)
    parser.add_argument("--target-release-id", required=True)
    parser.add_argument("--model-slug", default=DEFAULT_MODEL_SLUG)
    parser.add_argument("--dim", type=int, default=DEFAULT_DIM)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--scroll-limit", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args(argv)
    report = build_report(args)
    print(json.dumps({"ok": report["ok"], "out_dir": args.out_dir, "mismatches": report["mismatches"]}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
