"""Verify the full Qdrant staging collections with counts and self-query smoke.

This is report-only. It does not write points, promote aliases, start Neo4j,
touch production SQLite, or scan D:.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import numpy as np
import requests


DEFAULT_VECTOR_DIR = Path("reports/vector_full_qwen3_4b_1024_20260514")
DEFAULT_OUT_DIR = Path("reports/qdrant_full_qwen3_4b_1024_20260514")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
KINDS = ("article", "entity", "event")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def require_local_qdrant(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Qdrant URL must be local for this smoke check: {url}")


def slug_model(model: str) -> str:
    text = model.lower().replace("qwen/", "").replace("-", "_").replace("/", "_")
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text).strip("_")


def collection_name(kind: str, model: str, dim: int, stamp: str) -> str:
    return f"wechat_stage7_{kind}_{slug_model(model)}_{dim}_{stamp}_full_staging"


def text_sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()


def collection_info(qdrant_url: str, name: str) -> dict[str, Any]:
    response = requests.get(f"{qdrant_url.rstrip('/')}/collections/{quote(name)}", timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(f"GET collection {name} failed {response.status_code}: {response.text[:500]}")
    return response.json().get("result") or {}


def collection_health(qdrant_url: str, name: str) -> dict[str, Any]:
    info = collection_info(qdrant_url, name)
    optimizer_status = info.get("optimizer_status")
    healthy = info.get("status") == "green" and (optimizer_status == "ok" or optimizer_status is None)
    return {
        "healthy": healthy,
        "status": info.get("status"),
        "optimizer_status": optimizer_status,
        "points_count": int(info.get("points_count") or 0),
        "indexed_vectors_count": int(info.get("indexed_vectors_count") or 0),
        "segments_count": int(info.get("segments_count") or 0),
        "indexing_threshold": (((info.get("config") or {}).get("optimizer_config") or {}).get("indexing_threshold")),
        "full_scan_threshold": (((info.get("config") or {}).get("hnsw_config") or {}).get("full_scan_threshold")),
    }


def iter_card_rows(card_texts_path: Path):
    with card_texts_path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            stripped = line.strip()
            if stripped:
                row = json.loads(stripped)
                row["_vector_index"] = idx
                yield row


def select_rows(card_texts_path: Path, per_kind: int) -> dict[str, list[dict[str, Any]]]:
    selected: dict[str, list[dict[str, Any]]] = {kind: [] for kind in KINDS}
    for row in iter_card_rows(card_texts_path):
        kind = str(row.get("type") or "")
        if kind in selected and len(selected[kind]) < per_kind:
            selected[kind].append(row)
        if all(len(rows) >= per_kind for rows in selected.values()):
            break
    return selected


def search_top1(qdrant_url: str, collection: str, vector: list[float]) -> dict[str, Any]:
    base = qdrant_url.rstrip("/")
    response = requests.post(
        f"{base}/collections/{quote(collection)}/points/search",
        json={"vector": vector, "limit": 1, "with_payload": True},
        timeout=180,
    )
    if response.status_code == 404:
        response = requests.post(
            f"{base}/collections/{quote(collection)}/points/query",
            json={"query": vector, "limit": 1, "with_payload": True},
            timeout=180,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant search failed {response.status_code}: {response.text[:500]}")
    result = response.json().get("result")
    if isinstance(result, dict):
        result = result.get("points")
    return (result or [{}])[0]


def verify_self_queries(
    qdrant_url: str,
    collections: dict[str, str],
    selected: dict[str, list[dict[str, Any]]],
    vectors: Any,
) -> dict[str, Any]:
    details = []
    exact = 0
    equivalent = 0
    total = 0
    for kind, rows in selected.items():
        for row in rows:
            total += 1
            vector = np.asarray(vectors[int(row["_vector_index"])], dtype="float32").tolist()
            hit = search_top1(qdrant_url, collections[kind], vector)
            payload = hit.get("payload") or {}
            expected_hash = text_sha1(str(row.get("text") or ""))
            exact_ok = payload.get("card_id") == row.get("id")
            equivalent_ok = exact_ok or (
                payload.get("card_type") == row.get("type")
                and payload.get("text_sha1") == expected_hash
            )
            exact += int(exact_ok)
            equivalent += int(equivalent_ok)
            details.append(
                {
                    "kind": kind,
                    "expected_card_id": row.get("id"),
                    "hit_card_id": payload.get("card_id"),
                    "expected_text_sha1": expected_hash,
                    "hit_text_sha1": payload.get("text_sha1"),
                    "score": hit.get("score"),
                    "exact_ok": exact_ok,
                    "equivalent_ok": equivalent_ok,
                }
            )
    return {
        "checked": total,
        "exact": exact,
        "equivalent": equivalent,
        "exact_rate": round(exact / max(total, 1), 4),
        "equivalent_rate": round(equivalent / max(total, 1), 4),
        "details": details,
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Qdrant Full Staging Smoke",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- ok: `{report['ok']}`",
        f"- expected_total: `{report['expected_total']}`",
        f"- actual_total: `{report['actual_total']}`",
        f"- exact_rate: `{report['self_query']['exact_rate']}`",
        f"- equivalent_rate: `{report['self_query']['equivalent_rate']}`",
        "",
        "## Collections",
        "",
        "| Kind | Collection | Healthy | Status | Points | Indexed |",
        "|---|---|---:|---|---:|---:|",
    ]
    for kind, name in report["collections"].items():
        health = report["health"][kind]
        lines.append(
            f"| `{kind}` | `{name}` | `{health['healthy']}` | `{health['status']}` | {health['points_count']} | {health['indexed_vectors_count']} |"
        )
    lines.extend(["", "## Self Queries", ""])
    for item in report["self_query"]["details"]:
        lines.append(
            f"- `{item['kind']}` expected `{item['expected_card_id']}` hit `{item['hit_card_id']}` exact={item['exact_ok']} equivalent={item['equivalent_ok']} score={item['score']}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    require_local_qdrant(args.qdrant_url)
    metadata = read_json(args.vector_dir / "metadata.json")
    model = str(metadata.get("model") or args.model)
    dim = int(metadata.get("dim") or args.dim)
    collections = {kind: collection_name(kind, model, dim, args.stamp) for kind in KINDS}
    expected_counts = {
        "article": int((metadata.get("card_stats") or {}).get("article") or 0),
        "entity": int((metadata.get("card_stats") or {}).get("entity") or 0),
        "event": int((metadata.get("card_stats") or {}).get("event") or 0),
    }
    health = {kind: collection_health(args.qdrant_url, name) for kind, name in collections.items()}
    selected = select_rows(args.vector_dir / "card_texts.jsonl", args.self_query_per_kind)
    vectors = np.load(args.vector_dir / "vectors.npy", mmap_mode="r")
    self_query = verify_self_queries(args.qdrant_url, collections, selected, vectors)
    actual_total = sum(item["points_count"] for item in health.values())
    expected_total = int(metadata.get("card_count") or sum(expected_counts.values()))
    count_ok = all(health[kind]["points_count"] == expected_counts[kind] for kind in KINDS)
    health_ok = all(item["healthy"] for item in health.values())
    query_ok = self_query["equivalent"] == self_query["checked"]
    report = {
        "schema_version": "stage7_qdrant_full_staging_smoke.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "ok": count_ok and health_ok and query_ok and actual_total == expected_total,
        "vector_dir": str(args.vector_dir),
        "qdrant_url": args.qdrant_url,
        "collections": collections,
        "expected_counts": expected_counts,
        "expected_total": expected_total,
        "actual_total": actual_total,
        "health": health,
        "self_query": self_query,
        "no_alias_promote": True,
    }
    write_json(args.out_dir / "qdrant_full_staging_smoke.json", report)
    write_markdown(args.out_dir / "qdrant_full_staging_smoke.md", report)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["ok"] else 2


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vector-dir", type=Path, default=DEFAULT_VECTOR_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--stamp", default="20260514")
    parser.add_argument("--model", default="Qwen/Qwen3-Embedding-4B")
    parser.add_argument("--dim", type=int, default=1024)
    parser.add_argument("--self-query-per-kind", type=int, default=1)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not (args.vector_dir / "metadata.json").exists():
        raise SystemExit(f"metadata not found under {args.vector_dir}")
    if not (args.vector_dir / "card_texts.jsonl").exists():
        raise SystemExit(f"card_texts not found under {args.vector_dir}")
    if not (args.vector_dir / "vectors.npy").exists():
        raise SystemExit(f"vectors.npy not found under {args.vector_dir}")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
