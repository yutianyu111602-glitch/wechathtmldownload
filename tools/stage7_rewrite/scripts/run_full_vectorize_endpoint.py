#!/usr/bin/env python3
"""Build Qwen3 full-vector artifacts through the local embedding endpoint.

This keeps the artifact contract used by qdrant_full_staging_writer.py:
vectors.npy, card_texts.jsonl, and metadata.json. Unlike run_full_vectorize.py,
build mode does not import torch or sentence-transformers in this process; it
calls the already-running local /v1/embeddings service instead.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np
import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_full_vectorize as full_vectorize  # noqa: E402


DEFAULT_ENDPOINT = "http://127.0.0.1:11441"
DEFAULT_OUT_DIR = "reports/vector_full_qwen3_4b_1024_endpoint_20260518"
DEFAULT_MODEL = "Qwen/Qwen3-Embedding-4B"
DEFAULT_DIM = 1024


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require_local_endpoint(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    host = (parsed.hostname or "").lower().strip("[]")
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"embedding endpoint must be local: {endpoint}")


def endpoint_json(method: str, url: str, *, timeout_sec: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if method == "GET":
        response = requests.get(url, timeout=timeout_sec)
    elif method == "POST":
        response = requests.post(url, json=payload, timeout=timeout_sec)
    else:
        raise ValueError(f"unsupported method: {method}")
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed {response.status_code}: {response.text[:500]}")
    data = response.json()
    return data if isinstance(data, dict) else {}


def endpoint_meta(endpoint: str, timeout_sec: int) -> dict[str, Any]:
    return endpoint_json("GET", endpoint.rstrip("/") + "/meta", timeout_sec=timeout_sec)


def validate_vectors(vectors: Any, *, expected_count: int, expected_dim: int) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise ValueError(
            f"embedding_count_mismatch expected={expected_count} got={len(vectors) if isinstance(vectors, list) else type(vectors).__name__}"
        )
    out: list[list[float]] = []
    for row_index, vector in enumerate(vectors):
        if not isinstance(vector, list) or len(vector) != expected_dim:
            raise ValueError(
                f"dim_mismatch row={row_index} expected={expected_dim} got={len(vector) if isinstance(vector, list) else type(vector).__name__}"
            )
        clean = []
        for value_index, value in enumerate(vector):
            number = float(value)
            if math.isnan(number) or math.isinf(number):
                raise ValueError(f"invalid_float row={row_index} index={value_index}")
            clean.append(number)
        out.append(clean)
    return out


def embed_texts(endpoint: str, model: str, texts: list[str], *, expected_dim: int, timeout_sec: int) -> list[list[float]]:
    payload = {"model": model, "input": texts}
    data = endpoint_json("POST", endpoint.rstrip("/") + "/v1/embeddings", timeout_sec=timeout_sec, payload=payload)
    rows = data.get("data")
    if not isinstance(rows, list):
        raise ValueError("embedding response missing data list")
    rows_sorted = sorted(rows, key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0)
    vectors = [item.get("embedding") for item in rows_sorted if isinstance(item, dict)]
    return validate_vectors(vectors, expected_count=len(texts), expected_dim=expected_dim)


def build_plan(args: argparse.Namespace, out_dir: Path, cards: list[str], card_stats: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "stage7_vectorize_endpoint_plan.v1",
        "generated_at": now_iso(),
        "mode": args.mode,
        "stable_jsonl": str(args.stable_jsonl),
        "out_dir": str(out_dir),
        "limit": args.limit,
        "model": args.model,
        "endpoint": args.endpoint,
        "batch_size": args.batch_size,
        "timeout_sec": args.timeout_sec,
        "truncate_dim": args.dim,
        "card_count": len(cards),
        "card_stats": card_stats,
        "execution_host_policy": "local Qwen3 embedding endpoint only; no 9router, no direct torch/sentence-transformers import in this process",
        "writes": "dry-run writes plan/preview; build writes vectors.npy/card_texts.jsonl/metadata.json",
    }


def initial_state(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "stage7_vectorize_endpoint_state.v1",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "stable_jsonl": plan["stable_jsonl"],
        "out_dir": plan["out_dir"],
        "model": plan["model"],
        "endpoint": plan["endpoint"],
        "dim": plan["truncate_dim"],
        "card_count": plan["card_count"],
        "next_index": 0,
        "complete": False,
        "embedding_call_executed": False,
        "native_model_import_executed": False,
    }


def load_state(state_path: Path, plan: dict[str, Any], resume: bool) -> dict[str, Any]:
    if not resume or not state_path.exists():
        return initial_state(plan)
    state = read_json(state_path)
    for key in ("stable_jsonl", "out_dir", "model", "endpoint", "card_count"):
        if state.get(key) != plan.get(key):
            raise ValueError(f"state {key} mismatch: {state.get(key)} != {plan.get(key)}")
    if int(state.get("dim") or 0) != int(plan["truncate_dim"]):
        raise ValueError(f"state dim mismatch: {state.get('dim')} != {plan['truncate_dim']}")
    return state


def write_metadata(
    *,
    out_dir: Path,
    plan: dict[str, Any],
    state: dict[str, Any],
    endpoint_meta_payload: dict[str, Any],
    embed_sec: float,
) -> dict[str, Any]:
    metadata = {
        **plan,
        "schema_version": "stage7_vectorize_endpoint_plan.v1",
        "generated_at": now_iso(),
        "mode": "build",
        "dim": int(plan["truncate_dim"]),
        "embedding_shape": [int(plan["card_count"]), int(plan["truncate_dim"])],
        "embed_sec": round(embed_sec, 3),
        "cards_per_sec": round(int(plan["card_count"]) / max(embed_sec, 0.001), 3),
        "endpoint_meta": {
            key: endpoint_meta_payload.get(key)
            for key in ("ok", "model", "dim", "dimension", "embedding_dim", "device")
        },
        "state": state,
        "outputs": {
            "vectors": str(out_dir / "vectors.npy"),
            "card_texts": str(out_dir / "card_texts.jsonl"),
            "metadata": str(out_dir / "metadata.json"),
        },
        "safety": {
            "embedding_endpoint_call_executed": True,
            "native_model_import_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
        },
    }
    write_json(out_dir / "metadata.json", metadata)
    return metadata


def run(args: argparse.Namespace) -> int:
    require_local_endpoint(args.endpoint)
    stable_jsonl = Path(args.stable_jsonl)
    if not stable_jsonl.exists():
        raise SystemExit(f"stable jsonl not found: {stable_jsonl}")
    out_dir = Path(args.out_dir)
    cards, metadata_rows, card_stats = full_vectorize.build_cards(stable_jsonl, limit=args.limit)
    plan = build_plan(args, out_dir, cards, card_stats)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "vectorize_endpoint_plan.json", plan)
    full_vectorize.write_card_texts(
        out_dir / "card_texts.preview.jsonl",
        cards[: min(len(cards), 5000)],
        metadata_rows[: min(len(metadata_rows), 5000)],
    )
    if args.mode == "dry-run":
        print(json.dumps({"ok": True, **plan}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    meta = endpoint_meta(args.endpoint, args.timeout_sec)
    endpoint_dim = int(meta.get("dim") or meta.get("dimension") or meta.get("embedding_dim") or 0)
    endpoint_model = str(meta.get("model") or args.model)
    if endpoint_dim != int(args.dim):
        raise ValueError(f"endpoint dim {endpoint_dim} != requested dim {args.dim}")
    if endpoint_model != args.model:
        raise ValueError(f"endpoint model {endpoint_model} != requested model {args.model}")

    full_vectorize.write_card_texts(out_dir / "card_texts.jsonl", cards, metadata_rows)
    state_path = out_dir / "vectorize_endpoint_state.json"
    state = load_state(state_path, plan, args.resume)
    vector_path = out_dir / "vectors.npy"
    if int(state.get("next_index") or 0) == 0 or not vector_path.exists():
        vectors = np.lib.format.open_memmap(vector_path, mode="w+", dtype="float32", shape=(len(cards), int(args.dim)))
        state = initial_state(plan)
    else:
        vectors = np.lib.format.open_memmap(vector_path, mode="r+", dtype="float32", shape=(len(cards), int(args.dim)))
    write_json(state_path, state)

    started = time.perf_counter()
    next_index = int(state.get("next_index") or 0)
    batch_no = 0
    for start in range(next_index, len(cards), max(1, int(args.batch_size))):
        batch_no += 1
        end = min(len(cards), start + max(1, int(args.batch_size)))
        batch_vectors = embed_texts(
            args.endpoint,
            args.model,
            cards[start:end],
            expected_dim=int(args.dim),
            timeout_sec=int(args.timeout_sec),
        )
        vectors[start:end, :] = np.asarray(batch_vectors, dtype="float32")
        vectors.flush()
        state.update(
            {
                "updated_at": now_iso(),
                "next_index": end,
                "complete": end >= len(cards),
                "embedding_call_executed": True,
                "elapsed_sec": round(time.perf_counter() - started, 3),
                "cards_per_sec": round((end - next_index) / max(time.perf_counter() - started, 0.001), 3),
            }
        )
        write_json(state_path, state)
        if batch_no == 1 or end >= len(cards) or (
            args.progress_interval and batch_no % max(1, int(args.progress_interval)) == 0
        ):
            print(json.dumps({"ok": True, "next_index": end, "card_count": len(cards)}, ensure_ascii=False), flush=True)

    metadata = write_metadata(
        out_dir=out_dir,
        plan=plan,
        state=state,
        endpoint_meta_payload=meta,
        embed_sec=float(state.get("elapsed_sec") or 0.0),
    )
    print(json.dumps({"ok": True, "metadata": str(out_dir / "metadata.json"), "card_count": metadata["card_count"]}, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-jsonl", default=full_vectorize.DEFAULT_STABLE_JSONL)
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR)
    parser.add_argument("--mode", choices=["dry-run", "build"], default="dry-run")
    parser.add_argument("--limit", type=int, default=1000, help="0 means full source file.")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--dim", type=int, default=DEFAULT_DIM)
    parser.add_argument("--timeout-sec", type=int, default=180)
    parser.add_argument("--progress-interval", type=int, default=50, help="Print one progress row every N batches; 0 means final only.")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
