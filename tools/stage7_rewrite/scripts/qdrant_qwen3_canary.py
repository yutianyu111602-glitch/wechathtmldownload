"""Write a bounded Qwen3 vector artifact sample to isolated Qdrant canary collections.

Default mode is dry-run. Canary writes require an explicit confirmation token.
This script never promotes aliases and never touches production SQLite, Neo4j,
graph, mem0, OCR/Dajiala, paid APIs, or D: data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

import numpy as np
import requests


DEFAULT_VECTOR_DIR = Path("reports/vector_full_qwen3_4b_1024_20260514")
DEFAULT_OUT_DIR = Path("reports/qdrant_qwen3_canary_20260514")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
CONFIRM_TOKEN = "ENABLE_QDRANT_CANARY_WRITE"
KINDS = ("article", "entity", "event")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def slug_model(model: str) -> str:
    text = model.lower().replace("qwen/", "").replace("-", "_").replace("/", "_")
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text).strip("_")


def collection_name(kind: str, model: str, dim: int, stamp: str) -> str:
    return f"wechat_stage7_{kind}_{slug_model(model)}_{dim}_{stamp}_canary"


def point_id(card_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"stage7-qwen3-vector:{card_id}"))


def text_sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def iter_card_rows(card_texts_path: Path):
    with card_texts_path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            line = line.strip()
            if line:
                row = json.loads(line)
                row["_vector_index"] = idx
                yield row


def select_sample_cards(card_texts_path: Path, per_kind: int) -> dict[str, list[dict[str, Any]]]:
    selected: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    for row in iter_card_rows(card_texts_path):
        kind = str(row.get("type") or "")
        if kind in selected and len(selected[kind]) < per_kind:
            selected[kind].append(row)
        if all(len(rows) >= per_kind for rows in selected.values()):
            break
    return selected


def qdrant_request(method: str, url: str, **kwargs):
    response = requests.request(method, url, timeout=60, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed {response.status_code}: {response.text[:500]}")
    return response.json() if response.text else {}


def collection_exists(qdrant_url: str, name: str) -> bool:
    response = requests.get(f"{qdrant_url.rstrip('/')}/collections/{quote(name)}", timeout=15)
    if response.status_code == 404:
        return False
    if response.status_code >= 400:
        raise RuntimeError(f"GET collection failed {response.status_code}: {response.text[:500]}")
    return True


def create_collection(qdrant_url: str, name: str, dim: int, recreate: bool) -> str:
    base = qdrant_url.rstrip("/")
    exists = collection_exists(base, name)
    if exists and not recreate:
        return "exists"
    if exists and recreate:
        qdrant_request("DELETE", f"{base}/collections/{quote(name)}")
    qdrant_request(
        "PUT",
        f"{base}/collections/{quote(name)}",
        json={"vectors": {"size": dim, "distance": "Cosine"}},
    )
    return "created"


def payload_for(row: dict[str, Any], metadata: dict[str, Any], collection: str) -> dict[str, Any]:
    text = str(row.get("text") or "")
    return {
        "card_id": row.get("id"),
        "card_type": row.get("type"),
        "article_uid": row.get("article_uid"),
        "source_account": row.get("source_account"),
        "title": row.get("title"),
        "name": row.get("name"),
        "text_sha1": text_sha1(text),
        "text_preview": text[:500],
        "collection": collection,
        "model": metadata.get("model"),
        "dim": metadata.get("dim"),
        "vector_artifact": str(DEFAULT_VECTOR_DIR),
    }


def upsert_points(
    qdrant_url: str,
    collection: str,
    rows: list[dict[str, Any]],
    vectors: Any,
    metadata: dict[str, Any],
    batch_size: int,
) -> int:
    base = qdrant_url.rstrip("/")
    points = []
    for row in rows:
        vector = np.asarray(vectors[int(row["_vector_index"])], dtype="float32").tolist()
        points.append(
            {
                "id": point_id(str(row["id"])),
                "vector": vector,
                "payload": payload_for(row, metadata, collection),
            }
        )
    written = 0
    for start in range(0, len(points), batch_size):
        qdrant_request(
            "PUT",
            f"{base}/collections/{quote(collection)}/points?wait=true",
            json={"points": points[start : start + batch_size]},
        )
        written += len(points[start : start + batch_size])
    return written


def search_top1(qdrant_url: str, collection: str, vector: list[float]) -> dict[str, Any]:
    base = qdrant_url.rstrip("/")
    body = {"vector": vector, "limit": 1, "with_payload": True}
    response = requests.post(f"{base}/collections/{quote(collection)}/points/search", json=body, timeout=30)
    if response.status_code == 404:
        response = requests.post(f"{base}/collections/{quote(collection)}/points/query", json={"query": vector, "limit": 1, "with_payload": True}, timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant search failed {response.status_code}: {response.text[:500]}")
    data = response.json()
    result = data.get("result")
    if isinstance(result, dict):
        result = result.get("points")
    return (result or [{}])[0]


def verify_self_hits(
    qdrant_url: str,
    collections: dict[str, str],
    selected: dict[str, list[dict[str, Any]]],
    vectors: Any,
    limit_per_kind: int,
) -> dict[str, Any]:
    details = []
    exact_ok = 0
    equivalent_ok = 0
    total = 0
    for kind, rows in selected.items():
        collection = collections[kind]
        for row in rows[:limit_per_kind]:
            total += 1
            vector = np.asarray(vectors[int(row["_vector_index"])], dtype="float32").tolist()
            hit = search_top1(qdrant_url, collection, vector)
            payload = hit.get("payload") or {}
            exact_matched = payload.get("card_id") == row.get("id")
            equivalent_matched = exact_matched or (
                payload.get("card_type") == row.get("type")
                and payload.get("text_sha1") == text_sha1(str(row.get("text") or ""))
            )
            exact_ok += int(exact_matched)
            equivalent_ok += int(equivalent_matched)
            details.append(
                {
                    "kind": kind,
                    "expected_card_id": row.get("id"),
                    "hit_card_id": payload.get("card_id"),
                    "expected_text_sha1": text_sha1(str(row.get("text") or "")),
                    "hit_text_sha1": payload.get("text_sha1"),
                    "score": hit.get("score"),
                    "exact_matched": exact_matched,
                    "equivalent_matched": equivalent_matched,
                }
            )
    return {
        "checked": total,
        "exact_matched": exact_ok,
        "equivalent_matched": equivalent_ok,
        "exact_match_rate": round(exact_ok / max(total, 1), 4),
        "equivalent_match_rate": round(equivalent_ok / max(total, 1), 4),
        "details": details,
    }


def build_plan(args: argparse.Namespace, metadata: dict[str, Any], selected: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    model = str(metadata.get("model") or args.model)
    dim = int(metadata.get("dim") or args.dim)
    collections = {kind: collection_name(kind, model, dim, args.stamp) for kind in KINDS}
    return {
        "schema_version": "stage7_qdrant_qwen3_canary_plan.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": args.mode,
        "qdrant_url": args.qdrant_url,
        "vector_dir": str(args.vector_dir),
        "model": model,
        "dim": dim,
        "card_count": metadata.get("card_count"),
        "sample_per_kind": args.sample_per_kind,
        "selected_counts": {kind: len(rows) for kind, rows in selected.items()},
        "collections": collections,
        "confirm_token_required_for_writes": CONFIRM_TOKEN,
        "writes": "dry-run writes only this plan; canary writes isolated Qdrant collections with no alias promote",
    }


def run(args: argparse.Namespace) -> int:
    metadata = read_json(args.vector_dir / "metadata.json")
    selected = select_sample_cards(args.vector_dir / "card_texts.jsonl", args.sample_per_kind)
    plan = build_plan(args, metadata, selected)
    write_json(args.out_dir / "qdrant_canary_plan.json", plan)

    if args.mode == "dry-run":
        print(json.dumps({"ok": True, **plan}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.confirm_token != CONFIRM_TOKEN:
        raise SystemExit(f"--confirm-token {CONFIRM_TOKEN} required for canary writes")

    vectors = np.load(args.vector_dir / "vectors.npy", mmap_mode="r")
    if int(vectors.shape[1]) != int(plan["dim"]):
        raise ValueError(f"vector dim {vectors.shape[1]} != plan dim {plan['dim']}")

    collection_status = {}
    write_counts = {}
    for kind, collection in plan["collections"].items():
        collection_status[collection] = create_collection(args.qdrant_url, collection, int(plan["dim"]), args.recreate)
        write_counts[kind] = upsert_points(
            args.qdrant_url,
            collection,
            selected[kind],
            vectors,
            metadata,
            args.batch_size,
        )
    verification = verify_self_hits(args.qdrant_url, plan["collections"], selected, vectors, args.verify_per_kind)
    result = {
        "schema_version": "stage7_qdrant_qwen3_canary_result.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "plan": plan,
        "collection_status": collection_status,
        "write_counts": write_counts,
        "verification": verification,
        "no_alias_promote": True,
    }
    write_json(args.out_dir / "qdrant_canary_result.json", result)
    print(json.dumps({
        "ok": True,
        "result": str(args.out_dir / "qdrant_canary_result.json"),
        "exact_match_rate": verification["exact_match_rate"],
        "equivalent_match_rate": verification["equivalent_match_rate"],
    }, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "canary"], default="dry-run")
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--sample-per-kind", type=int, default=30)
    parser.add_argument("--verify-per-kind", type=int, default=10)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--stamp", default="20260514")
    parser.add_argument("--model", default="Qwen/Qwen3-Embedding-4B")
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--recreate", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not (args.vector_dir / "metadata.json").exists():
        raise SystemExit(f"metadata not found under {args.vector_dir}")
    if not (args.vector_dir / "card_texts.jsonl").exists():
        raise SystemExit(f"card_texts not found under {args.vector_dir}")
    if args.mode == "canary" and not (args.vector_dir / "vectors.npy").exists():
        raise SystemExit(f"vectors.npy not found under {args.vector_dir}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
