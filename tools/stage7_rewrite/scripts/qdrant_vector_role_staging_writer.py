#!/usr/bin/env python3
"""Write vector-role embeddings to isolated local Qdrant staging collections.

Default mode is dry-run. Build mode requires a confirmation token and writes
only the collections named in the embeddings JSONL. It never promotes aliases,
writes Neo4j/SQLite/mem0, calls paid APIs, publishes, or scans D:.
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


DEFAULT_EMBEDDINGS = Path("reports/vector_role_embedding_canary_20260518/snowflake_canary/embeddings.jsonl")
DEFAULT_OUT_DIR = Path("reports/qdrant_vector_role_staging_canary_20260518")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
CONFIRM_TOKEN = "ENABLE_QDRANT_VECTOR_ROLE_STAGING_WRITE"
SCHEMA_VERSION = "stage7_qdrant_vector_role_staging_report.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_root(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def require_local_qdrant(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Qdrant URL must be local for vector role staging writer: {url}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_root(path, "embeddings")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"invalid JSONL row at {path}:{line_no}")
            rows.append(row)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def qdrant_request(method: str, url: str, **kwargs):
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 120), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed {response.status_code}: {response.text[:500]}")
    return response.json() if response.text else {}


def collection_info(qdrant_url: str, name: str) -> dict[str, Any] | None:
    response = requests.get(f"{qdrant_url.rstrip('/')}/collections/{quote(name)}", timeout=30)
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise RuntimeError(f"GET collection {name} failed {response.status_code}: {response.text[:500]}")
    return response.json().get("result") or {}


def vector_size_from_info(info: dict[str, Any]) -> int | None:
    vectors = (((info.get("config") or {}).get("params") or {}).get("vectors") or {})
    if isinstance(vectors, dict) and "size" in vectors:
        return int(vectors["size"])
    if isinstance(vectors, dict):
        for value in vectors.values():
            if isinstance(value, dict) and "size" in value:
                return int(value["size"])
    return None


def collection_health(qdrant_url: str, name: str) -> dict[str, Any]:
    info = collection_info(qdrant_url, name)
    if info is None:
        return {"exists": False, "healthy": False, "status": "missing", "points_count": 0}
    optimizer_status = info.get("optimizer_status")
    return {
        "exists": True,
        "healthy": info.get("status") == "green" and (optimizer_status == "ok" or optimizer_status is None),
        "status": info.get("status"),
        "optimizer_status": optimizer_status,
        "points_count": int(info.get("points_count") or 0),
        "indexed_vectors_count": info.get("indexed_vectors_count"),
        "segments_count": info.get("segments_count"),
    }


def ensure_collection(qdrant_url: str, name: str, dim: int, recreate: bool) -> str:
    base = qdrant_url.rstrip("/")
    info = collection_info(base, name)
    if info is not None and recreate:
        qdrant_request("DELETE", f"{base}/collections/{quote(name)}", timeout=120)
        info = None
    if info is not None:
        existing_dim = vector_size_from_info(info)
        if existing_dim is not None and existing_dim != dim:
            raise ValueError(f"collection {name} has dim={existing_dim}, expected {dim}")
        return "exists"
    qdrant_request(
        "PUT",
        f"{base}/collections/{quote(name)}",
        json={"vectors": {"size": dim, "distance": "Cosine"}, "on_disk_payload": True},
        timeout=120,
    )
    return "created"


def point_id(row: dict[str, Any]) -> str:
    key = str(row.get("job_id") or row.get("record_id") or row.get("text_sha1") or "")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"stage7-vector-role-staging:{key}"))


def valid_vector(vector: Any, dim: int) -> bool:
    if not isinstance(vector, list) or len(vector) != dim:
        return False
    for value in vector:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return False
    return True


def validate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    skipped = Counter()
    collections = Counter()
    models = Counter()
    dims = Counter()
    roles = Counter()
    valid = 0
    for row in rows:
        collection = str(row.get("collection") or "")
        dim = int(row.get("dim") or 0)
        vector = row.get("vector")
        if not collection:
            skipped["missing_collection"] += 1
            continue
        if dim <= 0:
            skipped["missing_dim"] += 1
            continue
        if not valid_vector(vector, dim):
            skipped["invalid_vector"] += 1
            continue
        valid += 1
        collections[collection] += 1
        models[str(row.get("model") or "")] += 1
        dims[str(dim)] += 1
        roles[str(row.get("model_role") or "")] += 1
    return {
        "row_count": len(rows),
        "valid_count": valid,
        "skipped": dict(sorted(skipped.items())),
        "collection_counts": dict(sorted(collections.items())),
        "model_counts": dict(sorted(models.items())),
        "dim_counts": dict(sorted(dims.items())),
        "model_role_counts": dict(sorted(roles.items())),
    }


def payload_for(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return {
        "job_id": row.get("job_id"),
        "record_id": row.get("record_id"),
        "object_kind": row.get("object_kind"),
        "object_id": row.get("object_id"),
        "parent_id": row.get("parent_id"),
        "parent_kind": row.get("parent_kind"),
        "source_article_uid": row.get("source_article_uid"),
        "field_path": row.get("field_path"),
        "lang": row.get("lang"),
        "channel": row.get("channel"),
        "model_role": row.get("model_role"),
        "text_sha1": row.get("text_sha1"),
        "collection": row.get("collection"),
        "model": row.get("model"),
        "dim": row.get("dim"),
        "source_artifact": metadata.get("source_artifact"),
        "source_row_no": metadata.get("source_row_no"),
        "text": metadata.get("text"),
        "stage": "vector_role_staging",
    }


def upsert_rows(qdrant_url: str, collection: str, rows: list[dict[str, Any]], batch_size: int) -> int:
    points = [
        {"id": point_id(row), "vector": row["vector"], "payload": payload_for(row)}
        for row in rows
        if str(row.get("collection") or "") == collection
    ]
    written = 0
    for start in range(0, len(points), max(1, batch_size)):
        chunk = points[start : start + max(1, batch_size)]
        qdrant_request(
            "PUT",
            f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points?wait=true",
            json={"points": chunk},
            timeout=180,
        )
        written += len(chunk)
    return written


def search_top1(qdrant_url: str, collection: str, vector: list[float]) -> dict[str, Any]:
    response = requests.post(
        f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/search",
        json={"vector": vector, "limit": 1, "with_payload": True},
        timeout=30,
    )
    if response.status_code == 404:
        response = requests.post(
            f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/query",
            json={"query": vector, "limit": 1, "with_payload": True},
            timeout=30,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant search failed {response.status_code}: {response.text[:500]}")
    result = response.json().get("result")
    if isinstance(result, dict):
        result = result.get("points")
    return (result or [{}])[0]


def verify_self_hits(qdrant_url: str, rows_by_collection: dict[str, list[dict[str, Any]]], verify_limit: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for collection, rows in rows_by_collection.items():
        checked = 0
        matched = 0
        details = []
        for row in rows[: max(0, verify_limit)]:
            checked += 1
            hit = search_top1(qdrant_url, collection, row["vector"])
            payload = hit.get("payload") or {}
            ok = payload.get("job_id") == row.get("job_id") or payload.get("text_sha1") == row.get("text_sha1")
            matched += int(ok)
            details.append(
                {
                    "expected_job_id": row.get("job_id"),
                    "hit_job_id": payload.get("job_id"),
                    "expected_text_sha1": row.get("text_sha1"),
                    "hit_text_sha1": payload.get("text_sha1"),
                    "matched": ok,
                    "score": hit.get("score"),
                }
            )
        out[collection] = {
            "checked": checked,
            "matched": matched,
            "match_rate": round(matched / max(checked, 1), 4),
            "details": details,
        }
    return out


def group_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("collection") or "")].append(row)
    return dict(grouped)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Qdrant Vector Role Staging",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- mode: `{report['mode']}`",
        f"- valid_count: `{report['row_stats']['valid_count']}`",
        f"- written_count: `{report['written_count']}`",
        "",
        "## Collections",
        "",
    ]
    for collection, count in report["row_stats"]["collection_counts"].items():
        health = (report.get("collection_status") or {}).get(collection) or {}
        lines.append(f"- `{collection}`: rows `{count}`, points `{health.get('points_count')}`, healthy `{health.get('healthy')}`")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_qdrant(args.qdrant_url)
    reject_d_root(args.out_dir, "out_dir")
    rows = read_jsonl(args.embeddings)
    stats = validate_rows(rows)
    valid_ready = rows and stats["valid_count"] == len(rows) and not stats["skipped"]
    decision = "qdrant_vector_role_staging_ready" if valid_ready else "qdrant_vector_role_staging_blocked_invalid_embeddings"
    grouped = group_rows(rows)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": decision == "qdrant_vector_role_staging_ready",
        "mode": args.mode,
        "embeddings": str(args.embeddings),
        "out_dir": str(args.out_dir),
        "qdrant_url": args.qdrant_url,
        "row_stats": stats,
        "collection_status": {},
        "written_count": 0,
        "verification": {},
        "confirm_token_required_for_writes": CONFIRM_TOKEN,
        "safety": {
            "qdrant_write": False,
            "qdrant_alias_change": False,
            "neo4j_write": False,
            "sqlite_write": False,
            "mem0_write": False,
            "paid_api": False,
            "production_publish": False,
            "d_scan": False,
        },
    }
    if args.mode == "build":
        if args.confirm_token != CONFIRM_TOKEN:
            raise SystemExit(f"--confirm-token {CONFIRM_TOKEN} required for vector role Qdrant staging writes")
        if not valid_ready:
            raise SystemExit(f"cannot write invalid embeddings: {decision}")
        written_total = 0
        statuses: dict[str, Any] = {}
        for collection, collection_rows in grouped.items():
            dim = int(collection_rows[0]["dim"])
            ensure_status = ensure_collection(args.qdrant_url, collection, dim, bool(args.recreate))
            written = upsert_rows(args.qdrant_url, collection, collection_rows, max(1, int(args.batch_size)))
            written_total += written
            statuses[collection] = {"ensure": ensure_status, **collection_health(args.qdrant_url, collection)}
        verification = verify_self_hits(args.qdrant_url, grouped, max(1, int(args.verify_limit)))
        report.update(
            {
                "decision": "qdrant_vector_role_staging_written",
                "ok": written_total == len(rows)
                and all(item.get("healthy") for item in statuses.values())
                and all(item.get("match_rate") == 1.0 for item in verification.values()),
                "collection_status": statuses,
                "written_count": written_total,
                "verification": verification,
                "safety": {**report["safety"], "qdrant_write": True},
            }
        )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "qdrant_vector_role_staging_report.json", report)
    write_markdown(args.out_dir / "qdrant_vector_role_staging_report.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "written_count": report["written_count"],
                "collections": list(stats["collection_counts"].keys()),
                "report": str(args.out_dir / "qdrant_vector_role_staging_report.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "build"], default="dry-run")
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--verify-limit", type=int, default=20)
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--recreate", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
