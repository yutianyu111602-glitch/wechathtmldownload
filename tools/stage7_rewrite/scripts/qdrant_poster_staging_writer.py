#!/usr/bin/env python3
"""Upsert PRD-12 poster text embeddings to an isolated local Qdrant collection.

Default mode is dry-run. Build mode requires a confirmation token and writes
only the target poster collection, optionally creating the poster alias. It does
not touch Stage7 article/entity/event aliases, Neo4j, SQLite, mem0, paid APIs,
or D: data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


DEFAULT_EMBEDDINGS = Path(
    "reports/dajiala_paid_wave01_04_verified_poster_text_vector_jobs_20260516/poster_text_embeddings.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/qdrant_poster_staging_20260517")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
CONFIRM_TOKEN = "ENABLE_QDRANT_POSTER_STAGING_WRITE"
ALIAS_CONFIRM_TOKEN = "ENABLE_QDRANT_POSTER_ALIAS_WRITE"
DEFAULT_ALIAS = "wechat_stage8_poster_text_qwen3_embedding_4b_1024_current"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def require_local_qdrant(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Qdrant URL must be local for poster staging writer: {url}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "embeddings")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, 1):
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


def text_sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def point_id(row: dict[str, Any]) -> str:
    key = str(row.get("job_id") or row.get("object_id") or row.get("text_sha1") or "")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"stage7-poster-text-vector:{key}"))


def validate_embedding_rows(rows: list[dict[str, Any]], expected_dim: int) -> dict[str, Any]:
    skipped = Counter()
    model_counts = Counter()
    collection_counts = Counter()
    valid = 0
    for row in rows:
        vector = row.get("vector")
        if not isinstance(vector, list):
            skipped["missing_vector"] += 1
            continue
        if len(vector) != expected_dim:
            skipped["dim_mismatch"] += 1
            continue
        if not str(row.get("collection") or "").strip():
            skipped["missing_collection"] += 1
            continue
        valid += 1
        model_counts[str(row.get("model") or "")] += 1
        collection_counts[str(row.get("collection") or "")] += 1
    return {
        "row_count": len(rows),
        "valid_count": valid,
        "skipped": dict(skipped),
        "model_counts": dict(model_counts),
        "collection_counts": dict(collection_counts),
        "single_collection": len(collection_counts) == 1,
        "single_model": len(model_counts) == 1,
    }


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
        return {"exists": False, "healthy": False, "status": "missing", "points_count": None}
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


def aliases(qdrant_url: str) -> dict[str, str]:
    data = qdrant_request("GET", f"{qdrant_url.rstrip('/')}/aliases", timeout=30)
    rows = ((data.get("result") or {}).get("aliases") or [])
    return {str(row.get("alias_name")): str(row.get("collection_name")) for row in rows if isinstance(row, dict)}


def create_alias_if_needed(qdrant_url: str, alias: str, collection: str, *, replace: bool) -> dict[str, Any]:
    before = aliases(qdrant_url)
    existing = before.get(alias)
    actions: list[dict[str, Any]] = []
    if existing == collection:
        return {"alias": alias, "collection": collection, "before": before, "actions": [], "changed": False}
    if existing and not replace:
        raise RuntimeError(f"alias {alias} already points to {existing}; use --replace-alias to replace")
    if existing:
        actions.append({"delete_alias": {"alias_name": alias}})
    actions.append({"create_alias": {"alias_name": alias, "collection_name": collection}})
    qdrant_request("POST", f"{qdrant_url.rstrip('/')}/collections/aliases", json={"actions": actions}, timeout=60)
    return {"alias": alias, "collection": collection, "before": before, "actions": actions, "changed": True, "after": aliases(qdrant_url)}


def payload_for(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    return {
        "job_id": row.get("job_id"),
        "object_kind": row.get("object_kind"),
        "object_id": row.get("object_id"),
        "article_id": row.get("article_id"),
        "article_uid": metadata.get("article_uid"),
        "source_account": metadata.get("source_account"),
        "article_title": metadata.get("article_title"),
        "publish_time": metadata.get("publish_time"),
        "source_url": metadata.get("source_url"),
        "poster_ocr_path": metadata.get("poster_ocr_path"),
        "image_path": metadata.get("image_path"),
        "image_sha256": metadata.get("image_sha256"),
        "ocr_backend": metadata.get("ocr_backend"),
        "ocr_block_count": metadata.get("ocr_block_count"),
        "ocr_average_score": metadata.get("ocr_average_score"),
        "quality_grade": metadata.get("quality_grade"),
        "text_sha1": row.get("text_sha1"),
        "collection": row.get("collection"),
        "model": row.get("model"),
        "dim": row.get("dim"),
        "stage": "poster_text_staging",
    }


def upsert_embeddings(qdrant_url: str, collection: str, rows: list[dict[str, Any]], batch_size: int) -> int:
    points: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("collection") or "") != collection:
            continue
        points.append({"id": point_id(row), "vector": row["vector"], "payload": payload_for(row)})
    written = 0
    for start in range(0, len(points), batch_size):
        qdrant_request(
            "PUT",
            f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points?wait=true",
            json={"points": points[start : start + batch_size]},
            timeout=180,
        )
        written += len(points[start : start + batch_size])
    return written


def search_top1(qdrant_url: str, collection: str, vector: list[float]) -> dict[str, Any]:
    body = {"vector": vector, "limit": 1, "with_payload": True}
    response = requests.post(f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/search", json=body, timeout=30)
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


def verify_self_hits(qdrant_url: str, collection: str, rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    checked = 0
    matched = 0
    details = []
    for row in rows[: max(0, limit)]:
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
    return {
        "checked": checked,
        "matched": matched,
        "match_rate": round(matched / max(checked, 1), 4),
        "details": details,
    }


def build_plan(args: argparse.Namespace, stats: dict[str, Any]) -> dict[str, Any]:
    collection_counts = stats["collection_counts"]
    collection = args.collection or next(iter(collection_counts.keys()), "")
    return {
        "schema_version": "stage7_qdrant_poster_staging_plan.v1",
        "generated_at": now_iso(),
        "mode": args.mode,
        "embeddings_path": str(args.embeddings),
        "out_dir": str(args.out_dir),
        "qdrant_url": args.qdrant_url,
        "collection": collection,
        "alias": args.alias,
        "create_alias": bool(args.create_alias),
        "dim": args.dim,
        "row_stats": stats,
        "confirm_token_required_for_writes": CONFIRM_TOKEN,
        "alias_confirm_token_required": ALIAS_CONFIRM_TOKEN,
        "writes": "dry-run writes only this plan; build writes local poster Qdrant collection and optional poster alias",
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    plan = report["plan"]
    lines = [
        "# Qdrant Poster Text Staging",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- mode: `{plan['mode']}`",
        f"- collection: `{plan['collection']}`",
        f"- alias: `{plan['alias']}`",
        f"- row_count: `{plan['row_stats']['row_count']}`",
        f"- valid_count: `{plan['row_stats']['valid_count']}`",
        f"- written_count: `{report.get('written_count')}`",
        f"- alias_changed: `{(report.get('alias_result') or {}).get('changed')}`",
        f"- self_hit_rate: `{(report.get('verification') or {}).get('match_rate')}`",
        "",
        "## Safety",
        "",
        "- Writes are limited to the poster text staging collection.",
        "- Existing Stage7 article/entity/event aliases are not touched.",
        "- No Neo4j, SQLite, mem0, paid API, D: scan, or publish action is performed.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_qdrant(args.qdrant_url)
    reject_d_path(args.out_dir, "out_dir")
    rows = read_jsonl(args.embeddings)
    stats = validate_embedding_rows(rows, int(args.dim))
    plan = build_plan(args, stats)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "qdrant_poster_staging_plan.json", plan)

    if not rows or stats["valid_count"] != len(rows) or not stats["single_collection"]:
        decision = "qdrant_poster_staging_blocked_invalid_embeddings"
    else:
        decision = "qdrant_poster_staging_ready"

    report: dict[str, Any] = {
        "schema_version": "stage7_qdrant_poster_staging_report.v1",
        "generated_at": now_iso(),
        "decision": decision,
        "ok": decision == "qdrant_poster_staging_ready",
        "plan": plan,
        "collection_status": None,
        "written_count": 0,
        "verification": None,
        "alias_result": None,
        "safety": {
            "qdrant_write": False,
            "alias_change": False,
            "neo4j_write": False,
            "mem0_write": False,
            "sqlite_write": False,
            "paid_api": False,
            "d_scan": False,
            "publish": False,
        },
    }

    if args.mode == "build":
        if args.confirm_token != CONFIRM_TOKEN:
            raise SystemExit(f"--confirm-token {CONFIRM_TOKEN} required for poster Qdrant staging writes")
        if decision != "qdrant_poster_staging_ready":
            raise SystemExit(f"cannot write invalid poster embeddings: {decision}")
        collection = plan["collection"]
        status = ensure_collection(args.qdrant_url, collection, int(args.dim), args.recreate)
        written = upsert_embeddings(args.qdrant_url, collection, rows, max(1, int(args.batch_size)))
        health = collection_health(args.qdrant_url, collection)
        verification = verify_self_hits(args.qdrant_url, collection, rows, max(1, int(args.verify_limit)))
        alias_result = None
        if args.create_alias:
            if args.alias_confirm_token != ALIAS_CONFIRM_TOKEN:
                raise SystemExit(f"--alias-confirm-token {ALIAS_CONFIRM_TOKEN} required for poster alias writes")
            alias_result = create_alias_if_needed(args.qdrant_url, args.alias, collection, replace=args.replace_alias)
        report.update(
            {
                "decision": "qdrant_poster_staging_written",
                "ok": health.get("healthy") and written == len(rows) and verification.get("match_rate") == 1.0,
                "collection_status": {"ensure": status, **health},
                "written_count": written,
                "verification": verification,
                "alias_result": alias_result,
                "safety": {
                    **report["safety"],
                    "qdrant_write": True,
                    "alias_change": bool(alias_result and alias_result.get("changed")),
                },
            }
        )

    write_json(args.out_dir / "qdrant_poster_staging_report.json", report)
    write_markdown(args.out_dir / "qdrant_poster_staging_report.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "collection": plan["collection"],
                "written_count": report["written_count"],
                "self_hit_rate": (report.get("verification") or {}).get("match_rate"),
                "report": str(args.out_dir / "qdrant_poster_staging_report.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "build"], default="dry-run")
    parser.add_argument("--embeddings", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--collection", default="")
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--verify-limit", type=int, default=20)
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--recreate", action="store_true")
    parser.add_argument("--create-alias", action="store_true")
    parser.add_argument("--replace-alias", action="store_true")
    parser.add_argument("--alias", default=DEFAULT_ALIAS)
    parser.add_argument("--alias-confirm-token", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
