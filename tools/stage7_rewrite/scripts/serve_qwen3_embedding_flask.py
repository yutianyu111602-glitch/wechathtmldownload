#!/usr/bin/env python3
"""Serve Qwen3 embeddings through the Stage7 embedding endpoint contract.

The repo's vector runner expects:
- GET /meta with a dimension field.
- POST /v1/embeddings with OpenAI-compatible {model, input}.

This server is intentionally local-only by default and loads the model once at
startup. It is designed for the known-good WSL + RTX 4090 route documented in
VECTOR_MODEL_RESEARCH_20260514.md.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from stage7_runtime_guard import enforce_native_heavy_python_guard


DEFAULT_MODEL = "Qwen/Qwen3-Embedding-4B"
DEFAULT_DIM = 1024


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_inputs(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item or "") for item in value]
    raise ValueError("input must be a string or list of strings")


def validate_vectors(vectors: Any, expected_count: int, expected_dim: int) -> list[list[float]]:
    if not isinstance(vectors, list) or len(vectors) != expected_count:
        raise ValueError(f"embedding_count_mismatch expected={expected_count} got={len(vectors) if isinstance(vectors, list) else type(vectors).__name__}")
    out: list[list[float]] = []
    for row_index, vector in enumerate(vectors):
        if len(vector) != expected_dim:
            raise ValueError(f"dim_mismatch row={row_index} expected={expected_dim} got={len(vector)}")
        clean = []
        for value_index, value in enumerate(vector):
            number = float(value)
            if math.isnan(number) or math.isinf(number):
                raise ValueError(f"invalid_float row={row_index} index={value_index}")
            clean.append(number)
        out.append(clean)
    return out


def openai_embedding_payload(vectors: list[list[float]], model: str) -> dict[str, Any]:
    return {
        "object": "list",
        "model": model,
        "data": [
            {"object": "embedding", "index": index, "embedding": vector}
            for index, vector in enumerate(vectors)
        ],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11441)
    parser.add_argument("--dim", type=int, default=DEFAULT_DIM)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-inputs", type=int, default=64)
    parser.add_argument("--normalize", action="store_true", default=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    enforce_native_heavy_python_guard("serve_qwen3_embedding_flask.main")
    from flask import Flask, jsonify, request
    from sentence_transformers import SentenceTransformer

    started = time.perf_counter()
    model = SentenceTransformer(args.model, device=args.device)
    load_sec = round(time.perf_counter() - started, 3)

    app = Flask(__name__)

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "model": args.model, "dim": args.dim, "loaded": True})

    @app.get("/meta")
    def meta():
        return jsonify(
            {
                "ok": True,
                "model": args.model,
                "dim": args.dim,
                "dimension": args.dim,
                "embedding_dim": args.dim,
                "device": args.device,
                "load_sec": load_sec,
                "server_time": now_iso(),
            }
        )

    @app.post("/v1/embeddings")
    def embeddings():
        payload = request.get_json(force=True, silent=False) or {}
        requested_model = str(payload.get("model") or args.model)
        if requested_model != args.model:
            return jsonify({"error": f"unsupported model {requested_model}; loaded {args.model}"}), 400
        try:
            texts = normalize_inputs(payload.get("input"))
            if not texts or any(not text.strip() for text in texts):
                return jsonify({"error": "input contains empty text"}), 400
            if len(texts) > args.max_inputs:
                return jsonify({"error": f"too many inputs: {len(texts)} > {args.max_inputs}"}), 400
            vectors_array = model.encode(
                texts,
                batch_size=max(1, int(args.batch_size)),
                normalize_embeddings=bool(args.normalize),
                truncate_dim=int(args.dim),
                show_progress_bar=False,
            )
            vectors = validate_vectors(vectors_array.tolist(), len(texts), int(args.dim))
            return jsonify(openai_embedding_payload(vectors, args.model))
        except Exception as exc:
            return jsonify({"error": f"{type(exc).__name__}: {exc}"}), 500

    print(
        json.dumps(
            {
                "ok": True,
                "model": args.model,
                "dim": args.dim,
                "device": args.device,
                "host": args.host,
                "port": args.port,
                "load_sec": load_sec,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
