#!/usr/bin/env python3
"""Build vector cards from stable Stage7 extracts.

Safe defaults:
- `--help` and `--mode dry-run` do not import torch, numpy, or embedding models.
- Reads one stable JSONL artifact instead of repeatedly scanning shard trees.
- Writes only local report/vector artifacts; no Qdrant/Neo4j/production DB writes.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from stage7_runtime_guard import enforce_native_heavy_python_guard


DEFAULT_STABLE_JSONL = (
    "reports/fullmap_47k_ready_text_authok_20260513_174006/"
    "stable_extract_v1/stable_articles.jsonl"
)
DEFAULT_MODEL = "Qwen/Qwen3-Embedding-4B"


def compact(value: Any, limit: int = 120) -> str:
    return " ".join(str(value or "").split())[:limit]


def text_card(kind: str, *parts: str) -> str:
    return " | ".join([kind, *[part for part in parts if part]])


def build_cards_from_article(row: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    uid = str(row.get("article_uid") or "")
    account = compact(row.get("source_account"), 80)
    title = compact(row.get("title"), 120)
    cards = [text_card("文章", f"公众号:{account}", f"标题:{title}")]
    meta = [
        {
            "type": "article",
            "article_uid": uid,
            "article_id": row.get("article_id"),
            "source_account": account,
            "title": title,
        }
    ]

    for ent in row.get("entities") or []:
        if not isinstance(ent, dict):
            continue
        name = compact(ent.get("name"), 120)
        if not name:
            continue
        etype = compact(ent.get("type") or "unknown", 40)
        bio = compact(ent.get("bio"), 120)
        cards.append(text_card("实体", f"名称:{name}", f"类型:{etype}", f"简介:{bio}" if bio else ""))
        meta.append({"type": "entity", "article_uid": uid, "name": name, "entity_type": etype})

    for event in row.get("events") or []:
        if not isinstance(event, dict):
            continue
        name = compact(event.get("name"), 120)
        if not name:
            continue
        time_text = compact(event.get("time_text") or event.get("time"), 80)
        place_text = compact(event.get("place_text") or event.get("place"), 100)
        cards.append(text_card("活动", f"名称:{name}", f"时间:{time_text}" if time_text else "", f"地点:{place_text}" if place_text else ""))
        meta.append({"type": "event", "article_uid": uid, "name": name, "time": time_text, "place": place_text})

    return cards, meta


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                yield line_no, json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_no}: {exc}") from exc


def build_cards(stable_jsonl: Path, *, limit: int = 0) -> tuple[list[str], list[dict[str, Any]], dict[str, Any]]:
    cards: list[str] = []
    metadata: list[dict[str, Any]] = []
    stats = Counter()
    for index, (_line_no, row) in enumerate(iter_jsonl(stable_jsonl), start=1):
        if limit and index > limit:
            break
        row_cards, row_meta = build_cards_from_article(row)
        cards.extend(row_cards)
        metadata.extend(row_meta)
        stats["articles"] += 1
        for item in row_meta:
            stats[item["type"]] += 1
    return cards, metadata, dict(stats)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_card_texts(path: Path, cards: list[str], metadata: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for index, (card, meta) in enumerate(zip(cards, metadata)):
            row = dict(meta)
            row["id"] = f"card_{index:08d}"
            row["text"] = card
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stable-jsonl", default=DEFAULT_STABLE_JSONL)
    parser.add_argument("--out-dir", default="reports/vector_canary_stable_47k")
    parser.add_argument("--mode", choices=["dry-run", "build"], default="dry-run")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--truncate-dim", type=int, default=1024, help="Optional MRL truncate dimension; use 0 for native dimension.")
    parser.add_argument("--normalize", action="store_true", default=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    stable_jsonl = Path(args.stable_jsonl)
    if not stable_jsonl.exists():
        raise SystemExit(f"stable jsonl not found: {stable_jsonl}")
    out_dir = Path(args.out_dir)
    cards, metadata, card_stats = build_cards(stable_jsonl, limit=args.limit)
    plan = {
        "schema_version": "stage7_vectorize_plan.v1",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": args.mode,
        "stable_jsonl": str(stable_jsonl),
        "out_dir": str(out_dir),
        "limit": args.limit,
        "model": args.model,
        "device": args.device,
        "batch_size": args.batch_size,
        "truncate_dim": args.truncate_dim or None,
        "execution_host_policy": "local RTX 4090 only; Mac vector endpoints are historical references and not fallbacks",
        "card_count": len(cards),
        "card_stats": card_stats,
        "writes": "dry-run writes only this plan and card text preview; build writes vectors.npy/card_texts.jsonl/metadata.json",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "vectorize_plan.json", plan)
    write_card_texts(out_dir / "card_texts.preview.jsonl", cards[: min(len(cards), 5000)], metadata[: min(len(metadata), 5000)])
    if args.mode == "dry-run":
        print(json.dumps({"ok": True, **plan}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    # Heavy imports are intentionally below the dry-run gate.
    enforce_native_heavy_python_guard("run_full_vectorize.build")
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    print(f"Loading {args.model} on {args.device}...")
    started = time.perf_counter()
    model = SentenceTransformer(args.model, device=args.device)
    load_sec = time.perf_counter() - started
    if args.device == "cuda" and torch.cuda.is_available():
        print(f"loaded in {load_sec:.1f}s, vram={torch.cuda.memory_allocated()/1024**3:.1f}GB")
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    embeddings = model.encode(
        cards,
        batch_size=args.batch_size,
        normalize_embeddings=args.normalize,
        truncate_dim=args.truncate_dim or None,
        show_progress_bar=True,
    )
    elapsed = time.perf_counter() - started
    np.save(out_dir / "vectors.npy", embeddings)
    write_card_texts(out_dir / "card_texts.jsonl", cards, metadata)
    metadata_json = {
        **plan,
        "mode": "build",
        "dim": int(embeddings.shape[1]),
        "embedding_shape": list(embeddings.shape),
        "load_sec": round(load_sec, 3),
        "embed_sec": round(elapsed, 3),
        "cards_per_sec": round(len(cards) / max(elapsed, 0.001), 3),
        "vram_peak_gb": round(torch.cuda.max_memory_allocated() / 1024**3, 3) if args.device == "cuda" and torch.cuda.is_available() else None,
        "outputs": {
            "vectors": str(out_dir / "vectors.npy"),
            "card_texts": str(out_dir / "card_texts.jsonl"),
            "metadata": str(out_dir / "metadata.json"),
        },
    }
    write_json(out_dir / "metadata.json", metadata_json)
    print(json.dumps({"ok": True, **metadata_json}, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
