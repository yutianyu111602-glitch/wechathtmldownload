#!/usr/bin/env python3
"""Encode a vector role artifact with a local SentenceTransformer model.

Dry-run mode only inspects the role artifact. Build mode loads the configured
local embedding model and writes an embeddings JSONL suitable for isolated
Qdrant staging. It does not write Qdrant, Neo4j, SQLite, mem0, aliases, paid
APIs, or production stores.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from stage7_runtime_guard import enforce_native_heavy_python_guard


DEFAULT_OUT_DIR = Path("reports/vector_role_embedding_canary_20260518")
SCHEMA_VERSION = "stage7_vector_role_embedding_artifact.v1"
MODEL_CONFIGS = {
    "Snowflake/snowflake-arctic-embed-l-v2.0": {
        "local_dir": r"D:\AI\models\embeddings\Snowflake--snowflake-arctic-embed-l-v2.0",
        "family": "snowflake",
        "document_prefix": "passage: ",
    },
    "BAAI/bge-large-en-v1.5": {
        "local_dir": r"D:\AI\models\embeddings\BAAI--bge-large-en-v1.5",
        "family": "bge-en",
        "document_prefix": "",
    },
    "BAAI/bge-m3": {
        "local_dir": r"D:\AI\models\embeddings\BAAI--bge-m3",
        "family": "bge",
        "document_prefix": "",
    },
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_root(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_root(path, "json")
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def iter_jsonl(path: Path, limit: int = 0) -> Iterable[dict[str, Any]]:
    reject_d_root(path, "card_texts")
    emitted = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"invalid JSONL row at {path}:{line_no}")
            yield row
            emitted += 1
            if limit and emitted >= limit:
                break


def slug_model(model: str) -> str:
    text = model.lower().replace("/", "_").replace("-", "_").replace(".", "_")
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text).strip("_")


def collection_name(parent_kind: str, model: str, dim: int, stamp: str, role: str) -> str:
    return f"wechat_stage7_{parent_kind}_{slug_model(model)}_{dim}_{stamp}_{role}_staging"


def vector_is_valid(vector: list[float], expected_dim: int) -> bool:
    if len(vector) != expected_dim:
        return False
    return all(not math.isnan(float(value)) and not math.isinf(float(value)) for value in vector)


def format_document_text(text: str, model: str) -> str:
    config = MODEL_CONFIGS.get(model) or {}
    prefix = str(config.get("document_prefix") or "")
    return prefix + text if prefix else text


def row_to_embedding(card: dict[str, Any], vector: list[float], *, model: str, dim: int, stamp: str) -> dict[str, Any]:
    parent_kind = str(card.get("parent_kind") or card.get("type") or "unknown")
    role = str(card.get("model_role") or "unknown")
    return {
        "job_id": card.get("id"),
        "record_id": card.get("id"),
        "object_kind": parent_kind,
        "object_id": card.get("parent_id"),
        "parent_id": card.get("parent_id"),
        "parent_kind": parent_kind,
        "source_article_uid": card.get("source_article_uid") or "",
        "field_path": card.get("field_path"),
        "lang": card.get("lang"),
        "channel": card.get("channel"),
        "model_role": role,
        "collection": collection_name(parent_kind, model, dim, stamp, role),
        "model": model,
        "dim": dim,
        "text_sha1": card.get("text_sha1"),
        "vector": vector,
        "metadata": {
            "source_artifact": card.get("source_artifact"),
            "source_row_no": card.get("source_row_no"),
            "field_path": card.get("field_path"),
            "lang": card.get("lang"),
            "channel": card.get("channel"),
            "model_role": role,
            "text": str(card.get("text") or "")[:1000],
        },
        "created_at": now_iso(),
    }


def load_cards(role_dir: Path, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata = read_json(role_dir / "metadata.json")
    cards = list(iter_jsonl(role_dir / "card_texts.jsonl", limit=limit))
    return metadata, cards


def build_report(
    *,
    role_dir: Path,
    out_dir: Path,
    mode: str,
    limit: int,
    model: str,
    dim: int,
    cards: list[dict[str, Any]],
    metadata: dict[str, Any],
    local_dir: Path,
    embed_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = embed_result or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "vector_role_embedding_written" if mode == "build" else "vector_role_embedding_dry_run_ready",
        "ok": True,
        "mode": mode,
        "role_dir": str(role_dir),
        "out_dir": str(out_dir),
        "limit": limit,
        "model_role": metadata.get("model_role"),
        "model": model,
        "dim": dim,
        "local_dir": str(local_dir),
        "local_dir_exists": local_dir.exists(),
        "input_card_count": len(cards),
        "source_card_count": metadata.get("card_count"),
        "embedding_count": result.get("embedding_count", 0),
        "failed_count": result.get("failed_count", 0),
        "load_sec": result.get("load_sec"),
        "embed_sec": result.get("embed_sec"),
        "cards_per_sec": result.get("cards_per_sec"),
        "outputs": result.get("outputs") or {},
        "counts_by_parent_kind": metadata.get("counts_by_parent_kind") or {},
        "counts_by_field_path": metadata.get("counts_by_field_path") or {},
        "safety": {
            "embedding_call_executed": mode == "build",
            "qdrant_write_executed": False,
            "qdrant_alias_change_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "production_publish_executed": False,
            "d_scan_executed": False,
        },
    }


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# Vector Role Embedding Artifact",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- model_role: `{report['model_role']}`",
        f"- model: `{report['model']}`",
        f"- dim: `{report['dim']}`",
        f"- input_card_count: `{report['input_card_count']}`",
        f"- embedding_count: `{report['embedding_count']}`",
        f"- failed_count: `{report['failed_count']}`",
        f"- cards_per_sec: `{report['cards_per_sec']}`",
        "",
        "## Safety",
        "",
    ]
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def encode_cards(
    *,
    cards: list[dict[str, Any]],
    model_name: str,
    dim: int,
    local_dir: Path,
    out_path: Path,
    batch_size: int,
    device: str,
    trust_remote_code: bool,
) -> dict[str, Any]:
    enforce_native_heavy_python_guard("embed_vector_role_artifact.encode_cards")
    import torch  # noqa: PLC0415
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    load_started = time.perf_counter()
    model = SentenceTransformer(
        str(local_dir) if local_dir.exists() else model_name,
        device=device,
        trust_remote_code=trust_remote_code,
        local_files_only=local_dir.exists(),
    )
    load_sec = time.perf_counter() - load_started

    out_path.parent.mkdir(parents=True, exist_ok=True)
    failed = 0
    written = 0
    embed_started = time.perf_counter()
    with out_path.open("w", encoding="utf-8") as handle:
        for start in range(0, len(cards), max(1, batch_size)):
            batch = cards[start : start + max(1, batch_size)]
            texts = [format_document_text(str(card.get("text") or ""), model_name) for card in batch]
            vectors_array = model.encode(
                texts,
                batch_size=max(1, batch_size),
                normalize_embeddings=True,
                truncate_dim=dim,
                convert_to_numpy=True,
                show_progress_bar=False,
            )
            for card, vector_values in zip(batch, vectors_array.tolist()):
                vector = [float(value) for value in vector_values]
                if not vector_is_valid(vector, dim):
                    failed += 1
                    continue
                handle.write(
                    json.dumps(row_to_embedding(card, vector, model=model_name, dim=dim, stamp="20260518"), ensure_ascii=False)
                    + "\n"
                )
                written += 1
    embed_sec = time.perf_counter() - embed_started
    return {
        "embedding_count": written,
        "failed_count": failed,
        "load_sec": round(load_sec, 3),
        "embed_sec": round(embed_sec, 3),
        "cards_per_sec": round(written / max(embed_sec, 0.001), 3),
        "cuda_available": bool(torch.cuda.is_available()),
        "outputs": {"embeddings": str(out_path)},
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--role-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--mode", choices=["dry-run", "build"], default="dry-run")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--model", default="")
    parser.add_argument("--dim", type=int, default=0)
    parser.add_argument("--local-dir", type=Path, default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--trust-remote-code", action="store_true", default=True)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    reject_d_root(args.out_dir, "out_dir")
    metadata, cards = load_cards(args.role_dir, args.limit)
    model_name = args.model or str(metadata.get("model") or "")
    dim = int(args.dim or metadata.get("dim") or 0)
    if not model_name:
        raise SystemExit("model is required or must be present in metadata.json")
    if dim <= 0:
        raise SystemExit("dim is required or must be present in metadata.json")
    config = MODEL_CONFIGS.get(model_name) or {}
    local_dir = args.local_dir or Path(str(config.get("local_dir") or model_name))
    embeddings_path = args.out_dir / str(metadata.get("model_role") or "role") / "embeddings.jsonl"
    embed_result = None
    if args.mode == "build":
        embed_result = encode_cards(
            cards=cards,
            model_name=model_name,
            dim=dim,
            local_dir=local_dir,
            out_path=embeddings_path,
            batch_size=max(1, int(args.batch_size)),
            device=args.device,
            trust_remote_code=bool(args.trust_remote_code),
        )
    report = build_report(
        role_dir=args.role_dir,
        out_dir=args.out_dir,
        mode=args.mode,
        limit=args.limit,
        model=model_name,
        dim=dim,
        cards=cards,
        metadata=metadata,
        local_dir=local_dir,
        embed_result=embed_result,
    )
    report_dir = args.out_dir / str(metadata.get("model_role") or "role")
    write_json(report_dir / "embedding_report.json", report)
    write_markdown(report_dir / "embedding_report.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "model_role": report["model_role"],
                "input_card_count": report["input_card_count"],
                "embedding_count": report["embedding_count"],
                "failed_count": report["failed_count"],
                "report": str(report_dir / "embedding_report.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if int(report["failed_count"] or 0) == 0 else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
