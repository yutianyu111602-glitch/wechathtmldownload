"""Resumably upsert the full local Qwen3 vector artifact to Qdrant staging.

Default mode is dry-run. Full writes require an explicit confirmation token.
This script writes isolated full-staging collections only: no alias promotion,
Neo4j, production SQLite, mem0, graph, OCR/Dajiala, paid APIs, or D: scans.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import requests


DEFAULT_VECTOR_DIR = Path("reports/vector_full_qwen3_4b_1024_20260514")
DEFAULT_OUT_DIR = Path("reports/qdrant_full_qwen3_4b_1024_20260514")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
CONFIRM_TOKEN = "ENABLE_QDRANT_FULL_STAGING_WRITE"
KINDS = ("article", "entity", "event")
BULK_LOAD_INDEXING_THRESHOLD = 1_000_000_000
BULK_LOAD_FULL_SCAN_THRESHOLD = 1_000_000_000


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def slug_model(model: str) -> str:
    text = model.lower().replace("qwen/", "").replace("-", "_").replace("/", "_")
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text).strip("_")


def collection_name(kind: str, model: str, dim: int, stamp: str) -> str:
    return f"wechat_stage7_{kind}_{slug_model(model)}_{dim}_{stamp}_full_staging"


def point_id(card_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"stage7-qwen3-full-staging:{card_id}"))


def text_sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def require_local_qdrant(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Qdrant URL must be http(s): {url}")
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Qdrant URL must be local for this staging writer: {url}")


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
        raise RuntimeError(f"GET collection failed {response.status_code}: {response.text[:500]}")
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


def points_count_from_info(info: dict[str, Any]) -> int | None:
    for key in ("points_count", "vectors_count", "indexed_vectors_count"):
        value = info.get(key)
        if value is not None:
            return int(value)
    return None


def bulk_collection_config(dim: int) -> dict[str, Any]:
    return {
        "vectors": {"size": dim, "distance": "Cosine"},
        "on_disk_payload": True,
        # Defer HNSW/index optimization during bulk upload. Qdrant on a Windows
        # bind-mounted HDD can fail segment rename/delete under optimizer churn.
        "optimizers_config": {
            "default_segment_number": 8,
            "indexing_threshold": BULK_LOAD_INDEXING_THRESHOLD,
            "flush_interval_sec": 30,
            "max_optimization_threads": 1,
        },
        "hnsw_config": {
            "full_scan_threshold": BULK_LOAD_FULL_SCAN_THRESHOLD,
        },
    }


def optimizer_status_ok(value: Any) -> bool:
    return value == "ok" or value is None


def collection_health(qdrant_url: str, name: str) -> dict[str, Any]:
    info = collection_info(qdrant_url, name)
    if info is None:
        return {"exists": False, "status": "missing", "optimizer_status": "missing", "points_count": None}
    optimizer_status = info.get("optimizer_status")
    healthy = str(info.get("status")) == "green" and optimizer_status_ok(optimizer_status)
    return {
        "exists": True,
        "healthy": healthy,
        "status": info.get("status"),
        "optimizer_status": optimizer_status,
        "points_count": info.get("points_count"),
        "indexed_vectors_count": info.get("indexed_vectors_count"),
        "segments_count": info.get("segments_count"),
    }


def collections_health(qdrant_url: str, collections: dict[str, str]) -> dict[str, dict[str, Any]]:
    return {kind: collection_health(qdrant_url, name) for kind, name in collections.items()}


def unhealthy_collections(health: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {kind: item for kind, item in health.items() if not item.get("healthy")}


def ensure_collections_healthy(qdrant_url: str, collections: dict[str, str]) -> dict[str, dict[str, Any]]:
    health = collections_health(qdrant_url, collections)
    bad = unhealthy_collections(health)
    if bad:
        raise RuntimeError(f"Qdrant collection health check failed: {json.dumps(bad, ensure_ascii=False)}")
    return health


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
    qdrant_request("PUT", f"{base}/collections/{quote(name)}", json=bulk_collection_config(dim), timeout=120)
    return "created"


def iter_card_rows(card_texts_path: Path, *, start_index: int = 0, limit: int = 0):
    emitted = 0
    with card_texts_path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            if idx < start_index:
                continue
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            row["_vector_index"] = idx
            yield row
            emitted += 1
            if limit and emitted >= limit:
                break


def initial_state(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "stage7_qdrant_full_staging_state.v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "vector_dir": plan["vector_dir"],
        "collections": plan["collections"],
        "next_index": 0,
        "last_card_id": None,
        "written_counts": {kind: 0 for kind in KINDS},
        "skipped_counts": {},
        "complete": False,
    }


def load_state(path: Path, plan: dict[str, Any], resume: bool) -> dict[str, Any]:
    if resume and path.exists():
        state = read_json(path)
        if state.get("vector_dir") != plan["vector_dir"]:
            raise ValueError(f"state vector_dir mismatch: {state.get('vector_dir')} != {plan['vector_dir']}")
        if state.get("collections") != plan["collections"]:
            raise ValueError("state collection mapping differs from current plan")
        return state
    return initial_state(plan)


def payload_for(row: dict[str, Any], metadata: dict[str, Any], collection: str, vector_dir: Path) -> dict[str, Any]:
    text = str(row.get("text") or "")
    return {
        "card_id": row.get("id"),
        "card_type": row.get("type"),
        "article_uid": row.get("article_uid"),
        "article_id": row.get("article_id"),
        "source_account": row.get("source_account"),
        "title": row.get("title"),
        "name": row.get("name"),
        "entity_type": row.get("entity_type"),
        "time": row.get("time"),
        "place": row.get("place"),
        "text": text[:1000],
        "text_sha1": text_sha1(text),
        "collection": collection,
        "model": metadata.get("model"),
        "dim": metadata.get("dim"),
        "vector_artifact": str(vector_dir),
        "stage": "full_staging",
    }


def make_point(row: dict[str, Any], vector: Any, metadata: dict[str, Any], collection: str, vector_dir: Path) -> dict[str, Any]:
    return {
        "id": point_id(str(row["id"])),
        "vector": vector,
        "payload": payload_for(row, metadata, collection, vector_dir),
    }


def upsert_points(qdrant_url: str, collection: str, points: list[dict[str, Any]]) -> int:
    if not points:
        return 0
    qdrant_request(
        "PUT",
        f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points?wait=true",
        json={"points": points},
        timeout=180,
    )
    return len(points)


def flush_chunk(
    *,
    qdrant_url: str,
    collections: dict[str, str],
    rows: list[dict[str, Any]],
    vectors: Any,
    metadata: dict[str, Any],
    vector_dir: Path,
    batch_size: int,
) -> tuple[Counter, Counter]:
    points_by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped = Counter()
    for row in rows:
        kind = str(row.get("type") or "")
        if kind not in collections:
            skipped[kind or "missing"] += 1
            continue
        vector = vectors[int(row["_vector_index"])].astype("float32").tolist()
        points_by_kind[kind].append(make_point(row, vector, metadata, collections[kind], vector_dir))

    written = Counter()
    for kind, points in points_by_kind.items():
        collection = collections[kind]
        for start in range(0, len(points), batch_size):
            written[kind] += upsert_points(qdrant_url, collection, points[start : start + batch_size])
    return written, skipped


def build_plan(args: argparse.Namespace, metadata: dict[str, Any]) -> dict[str, Any]:
    model = str(metadata.get("model") or args.model)
    dim = int(metadata.get("dim") or args.dim)
    collections = {kind: collection_name(kind, model, dim, args.stamp) for kind in KINDS}
    return {
        "schema_version": "stage7_qdrant_full_staging_plan.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": args.mode,
        "qdrant_url": args.qdrant_url,
        "vector_dir": str(args.vector_dir),
        "out_dir": str(args.out_dir),
        "model": model,
        "dim": dim,
        "card_count": metadata.get("card_count"),
        "card_stats": metadata.get("card_stats"),
        "collections": collections,
        "chunk_size": args.chunk_size,
        "batch_size": args.batch_size,
        "limit": args.limit,
        "resume": args.resume,
        "bulk_load_config": {
            "defer_hnsw_indexing": True,
            "optimizer_indexing_threshold": BULK_LOAD_INDEXING_THRESHOLD,
            "hnsw_full_scan_threshold": BULK_LOAD_FULL_SCAN_THRESHOLD,
            "default_segment_number": 8,
            "max_optimization_threads": 1,
        },
        "confirm_token_required_for_writes": CONFIRM_TOKEN,
        "writes": "dry-run writes only this plan; build writes local Qdrant full staging collections and state JSON",
        "no_alias_promote": True,
    }


def collection_counts(qdrant_url: str, collections: dict[str, str]) -> dict[str, int | None]:
    counts = {}
    for kind, name in collections.items():
        info = collection_info(qdrant_url, name)
        counts[kind] = points_count_from_info(info or {}) if info is not None else None
    return counts


def write_report_artifacts(out_dir: Path, report: dict[str, Any]) -> None:
    write_json(out_dir / "qdrant_full_staging_report.json", report)
    write_markdown(out_dir / "qdrant_full_staging_report.md", report)


def build_report(
    *,
    plan: dict[str, Any],
    state: dict[str, Any],
    qdrant_url: str,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "stage7_qdrant_full_staging_report.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "plan": plan,
        "state": state,
        "qdrant_counts": collection_counts(qdrant_url, plan["collections"]),
        "qdrant_health": collections_health(qdrant_url, plan["collections"]),
        "error": error,
        "no_alias_promote": True,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    plan = report["plan"]
    lines = [
        "# Qdrant Full Qwen3 Staging",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- vector_dir: `{plan['vector_dir']}`",
        f"- model: `{plan['model']}`",
        f"- dim: `{plan['dim']}`",
        f"- complete: `{report['state'].get('complete')}`",
        f"- next_index: `{report['state'].get('next_index')}` / `{plan.get('card_count')}`",
        f"- stop_reason: `{report['state'].get('stop_reason')}`",
        f"- error: `{report.get('error')}`",
        "",
        "## Collections",
        "",
        "| Kind | Collection | Status | Optimizer | Written | Qdrant Count |",
        "|---|---|---|---|---:|---:|",
    ]
    for kind, collection in sorted(plan["collections"].items()):
        written = report["state"].get("written_counts", {}).get(kind, 0)
        qcount = report.get("qdrant_counts", {}).get(kind)
        health = report.get("qdrant_health", {}).get(kind, {})
        optimizer_status = health.get("optimizer_status")
        if isinstance(optimizer_status, dict):
            optimizer_status = json.dumps(optimizer_status, ensure_ascii=False)
        lines.append(
            f"| `{kind}` | `{collection}` | `{health.get('status')}` | `{optimizer_status}` | {written} | {qcount} |"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- No alias promotion was performed.",
            "- No Neo4j, production SQLite, mem0, graph, OCR/Dajiala, paid API, or D: scan was performed.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_qdrant(args.qdrant_url)
    metadata = read_json(args.vector_dir / "metadata.json")
    plan = build_plan(args, metadata)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "qdrant_full_staging_plan.json", plan)

    if args.mode == "dry-run":
        print(json.dumps({"ok": True, **plan}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.confirm_token != CONFIRM_TOKEN:
        raise SystemExit(f"--confirm-token {CONFIRM_TOKEN} required for full staging writes")

    import numpy as np  # noqa: PLC0415

    vectors = np.load(args.vector_dir / "vectors.npy", mmap_mode="r")
    if int(vectors.shape[1]) != int(plan["dim"]):
        raise ValueError(f"vector dim {vectors.shape[1]} != plan dim {plan['dim']}")
    if int(vectors.shape[0]) != int(plan["card_count"]):
        raise ValueError(f"vector rows {vectors.shape[0]} != card_count {plan['card_count']}")

    collection_status = {
        kind: ensure_collection(args.qdrant_url, collection, int(plan["dim"]), args.recreate)
        for kind, collection in plan["collections"].items()
    }

    state_path = args.out_dir / "qdrant_full_staging_state.json"
    state = load_state(state_path, plan, args.resume)
    state["collection_status"] = collection_status
    state["complete"] = False
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(state_path, state)
    try:
        state["qdrant_health"] = ensure_collections_healthy(args.qdrant_url, plan["collections"])
    except RuntimeError as exc:
        state["qdrant_health"] = collections_health(args.qdrant_url, plan["collections"])
        state["stop_reason"] = "qdrant_collection_unhealthy_before_write"
        state["updated_at"] = datetime.now().isoformat(timespec="seconds")
        write_json(state_path, state)
        write_report_artifacts(
            args.out_dir,
            build_report(plan=plan, state=state, qdrant_url=args.qdrant_url, error=str(exc)),
        )
        raise

    started = time.perf_counter()
    rows: list[dict[str, Any]] = []
    last_row: dict[str, Any] | None = None
    start_index = int(state.get("next_index") or 0)
    for row in iter_card_rows(args.vector_dir / "card_texts.jsonl", start_index=start_index, limit=args.limit):
        rows.append(row)
        last_row = row
        if len(rows) >= args.chunk_size:
            written, skipped = flush_chunk(
                qdrant_url=args.qdrant_url,
                collections=plan["collections"],
                rows=rows,
                vectors=vectors,
                metadata=metadata,
                vector_dir=args.vector_dir,
                batch_size=args.batch_size,
            )
            for kind, count in written.items():
                state["written_counts"][kind] = int(state["written_counts"].get(kind, 0)) + int(count)
            skipped_counts = Counter(state.get("skipped_counts") or {})
            skipped_counts.update(skipped)
            state["skipped_counts"] = dict(skipped_counts)
            state["next_index"] = int(rows[-1]["_vector_index"]) + 1
            state["last_card_id"] = rows[-1].get("id")
            state["updated_at"] = datetime.now().isoformat(timespec="seconds")
            state["elapsed_sec"] = round(time.perf_counter() - started, 3)
            write_json(state_path, state)
            state["qdrant_health"] = collections_health(args.qdrant_url, plan["collections"])
            bad = unhealthy_collections(state["qdrant_health"])
            if bad:
                state["stop_reason"] = "qdrant_collection_unhealthy_after_chunk"
                state["updated_at"] = datetime.now().isoformat(timespec="seconds")
                write_json(state_path, state)
                error = f"Qdrant collection health check failed after chunk: {json.dumps(bad, ensure_ascii=False)}"
                write_report_artifacts(
                    args.out_dir,
                    build_report(plan=plan, state=state, qdrant_url=args.qdrant_url, error=error),
                )
                raise RuntimeError(error)
            write_json(state_path, state)
            print(json.dumps({"ok": True, "next_index": state["next_index"], "written_counts": state["written_counts"]}, ensure_ascii=False), flush=True)
            rows = []

    if rows:
        written, skipped = flush_chunk(
            qdrant_url=args.qdrant_url,
            collections=plan["collections"],
            rows=rows,
            vectors=vectors,
            metadata=metadata,
            vector_dir=args.vector_dir,
            batch_size=args.batch_size,
        )
        for kind, count in written.items():
            state["written_counts"][kind] = int(state["written_counts"].get(kind, 0)) + int(count)
        skipped_counts = Counter(state.get("skipped_counts") or {})
        skipped_counts.update(skipped)
        state["skipped_counts"] = dict(skipped_counts)
        state["next_index"] = int(rows[-1]["_vector_index"]) + 1
        state["last_card_id"] = rows[-1].get("id")

    expected_done = int(plan["card_count"])
    if args.limit:
        expected_done = min(expected_done, start_index + int(args.limit))
    state["complete"] = int(state.get("next_index") or 0) >= expected_done
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    state["elapsed_sec"] = round(time.perf_counter() - started, 3)
    if last_row is not None:
        state["last_seen_card_id"] = last_row.get("id")
    try:
        state["qdrant_health"] = ensure_collections_healthy(args.qdrant_url, plan["collections"])
    except RuntimeError as exc:
        state["qdrant_health"] = collections_health(args.qdrant_url, plan["collections"])
        state["stop_reason"] = "qdrant_collection_unhealthy_at_finalize"
        write_json(state_path, state)
        write_report_artifacts(
            args.out_dir,
            build_report(plan=plan, state=state, qdrant_url=args.qdrant_url, error=str(exc)),
        )
        raise
    write_json(state_path, state)

    report = build_report(plan=plan, state=state, qdrant_url=args.qdrant_url)
    write_report_artifacts(args.out_dir, report)
    print(json.dumps({"ok": True, "state": str(state_path), "report": str(args.out_dir / "qdrant_full_staging_report.json")}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "build"], default="dry-run")
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--limit", type=int, default=0, help="0 means process all remaining rows.")
    parser.add_argument("--stamp", default="20260514")
    parser.add_argument("--model", default="Qwen/Qwen3-Embedding-4B")
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--recreate", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not (args.vector_dir / "metadata.json").exists():
        raise SystemExit(f"metadata not found under {args.vector_dir}")
    if not (args.vector_dir / "card_texts.jsonl").exists():
        raise SystemExit(f"card_texts not found under {args.vector_dir}")
    if args.mode == "build" and not (args.vector_dir / "vectors.npy").exists():
        raise SystemExit(f"vectors.npy not found under {args.vector_dir}")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
