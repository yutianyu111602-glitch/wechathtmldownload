#!/usr/bin/env python3
"""Stream a vector-role artifact into local Qdrant full-wave staging.

This runner is for isolated 1024-d language-role vector waves: BGE-M3
multilingual/OCR baseline, Snowflake canary, and BGE English sidecar. It loads
one local SentenceTransformer model, reads role cards incrementally, embeds a
bounded chunk, writes directly to isolated local Qdrant staging collections,
and checkpoints after each successful chunk. It never promotes aliases, writes
Neo4j/SQLite/mem0, calls paid APIs, publishes, or scans D: roots.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
import uuid
from collections import Counter, defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlparse

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import embed_vector_role_artifact as embed_role
import qdrant_full_staging_writer as qdrant_full
from stage7_runtime_guard import enforce_native_heavy_python_guard


DEFAULT_ROLE_DIR = Path("reports/vector_role_artifacts_20260518/snowflake_canary")
DEFAULT_OUT_DIR = Path("reports/vector_role_full_wave_20260518")
DEFAULT_QDRANT_URL = "http://127.0.0.1:6333"
CONFIRM_TOKEN = "ENABLE_VECTOR_ROLE_FULL_WAVE_QDRANT_WRITE"
SCHEMA_VERSION = "stage7_vector_role_full_wave.v1"
ALLOWED_KINDS = {"article", "entity", "event", "poster"}
MODEL_SLUGS = {
    "Snowflake/snowflake-arctic-embed-l-v2.0": "snowflake_arctic_embed_l_v2_0",
    "BAAI/bge-large-en-v1.5": "bge_large_en_v1_5",
    "BAAI/bge-m3": "bge_m3",
}
ROLE_SUFFIXES = {
    "snowflake_canary": "full_staging",
    "english_sidecar": "en_sidecar",
    "multilingual_baseline": "baseline",
    "ocr_baseline": "ocr_staging",
}


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
        raise ValueError(f"Qdrant URL must be local for vector role full wave: {url}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_root(path, "json")
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def slug_model(model: str) -> str:
    if model in MODEL_SLUGS:
        return MODEL_SLUGS[model]
    text = model.lower().replace("/", "_").replace("-", "_").replace(".", "_")
    return "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in text).strip("_")


def collection_name(kind: str, model: str, dim: int, stamp: str, role: str) -> str:
    suffix = ROLE_SUFFIXES.get(role, f"{role}_staging")
    return f"wechat_stage7_{kind}_{slug_model(model)}_{dim}_{stamp}_{suffix}"


def role_kinds(metadata: dict[str, Any]) -> list[str]:
    counts = metadata.get("counts_by_parent_kind") if isinstance(metadata.get("counts_by_parent_kind"), dict) else {}
    kinds = [str(kind) for kind, count in sorted(counts.items()) if int(count or 0) > 0]
    if not kinds:
        kinds = ["article", "entity", "event"]
    invalid = [kind for kind in kinds if kind not in ALLOWED_KINDS]
    if invalid:
        raise ValueError(f"unsupported parent kinds for role full wave: {invalid}")
    return kinds


def iter_role_cards(card_texts_path: Path, *, start_index: int = 0, limit: int = 0) -> Iterable[dict[str, Any]]:
    reject_d_root(card_texts_path, "card_texts")
    emitted = 0
    with card_texts_path.open("r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            if index < start_index:
                continue
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"invalid JSONL row at {card_texts_path}:{index + 1}")
            row["_source_index"] = index
            yield row
            emitted += 1
            if limit and emitted >= limit:
                break


def vector_is_valid(vector: list[float], dim: int) -> bool:
    if len(vector) != dim:
        return False
    return all(not math.isnan(float(value)) and not math.isinf(float(value)) for value in vector)


def point_id(card: dict[str, Any]) -> str:
    key = str(card.get("id") or card.get("text_sha1") or card.get("_source_index") or "")
    role = str(card.get("model_role") or "")
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"stage7-vector-role-full-wave:{role}:{key}"))


def payload_for(card: dict[str, Any], *, metadata: dict[str, Any], collection: str) -> dict[str, Any]:
    text = str(card.get("text") or "")
    parent_kind = str(card.get("parent_kind") or card.get("type") or "unknown")
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
        "model_role": card.get("model_role") or metadata.get("model_role"),
        "text_sha1": card.get("text_sha1"),
        "collection": collection,
        "model": metadata.get("model"),
        "dim": metadata.get("dim"),
        "source_artifact": card.get("source_artifact"),
        "source_row_no": card.get("source_row_no"),
        "source_index": card.get("_source_index"),
        "text": text[:1000],
        "stage": "vector_role_full_wave",
    }


def make_point(card: dict[str, Any], vector: list[float], *, metadata: dict[str, Any], collection: str) -> dict[str, Any]:
    return {"id": point_id(card), "vector": vector, "payload": payload_for(card, metadata=metadata, collection=collection)}


def qdrant_request(method: str, url: str, **kwargs):
    response = requests.request(method, url, timeout=kwargs.pop("timeout", 180), **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed {response.status_code}: {response.text[:500]}")
    return response.json() if response.text else {}


def ensure_collections(qdrant_url: str, collections: dict[str, str], dim: int, recreate: bool) -> dict[str, str]:
    return {kind: qdrant_full.ensure_collection(qdrant_url, name, dim, recreate) for kind, name in collections.items()}


def upsert_points(qdrant_url: str, collection: str, points: list[dict[str, Any]], batch_size: int) -> int:
    written = 0
    for start in range(0, len(points), max(1, batch_size)):
        chunk = points[start : start + max(1, batch_size)]
        qdrant_request(
            "PUT",
            f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points?wait=true",
            json={"points": chunk},
            timeout=240,
        )
        written += len(chunk)
    return written


def search_top1(qdrant_url: str, collection: str, vector: list[float]) -> dict[str, Any]:
    response = requests.post(
        f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/search",
        json={"vector": vector, "limit": 1, "with_payload": True},
        timeout=60,
    )
    if response.status_code == 404:
        response = requests.post(
            f"{qdrant_url.rstrip('/')}/collections/{quote(collection)}/points/query",
            json={"query": vector, "limit": 1, "with_payload": True},
            timeout=60,
        )
    if response.status_code >= 400:
        raise RuntimeError(f"Qdrant search failed {response.status_code}: {response.text[:500]}")
    result = response.json().get("result")
    if isinstance(result, dict):
        result = result.get("points")
    return (result or [{}])[0]


def verify_samples(qdrant_url: str, samples: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for collection, rows in samples.items():
        checked = 0
        matched = 0
        for row in rows:
            checked += 1
            hit = search_top1(qdrant_url, collection, row["vector"])
            payload = hit.get("payload") or {}
            ok = payload.get("job_id") == row.get("job_id") or payload.get("text_sha1") == row.get("text_sha1")
            matched += int(ok)
        out[collection] = {
            "checked": checked,
            "matched": matched,
            "match_rate": round(matched / max(checked, 1), 4),
        }
    return out


def build_plan(args: argparse.Namespace, metadata: dict[str, Any]) -> dict[str, Any]:
    model = args.model or str(metadata.get("model") or "")
    dim = int(args.dim or metadata.get("dim") or 0)
    role = str(metadata.get("model_role") or args.role or args.role_dir.name)
    if not model:
        raise ValueError("model is required or must be present in metadata.json")
    if dim <= 0:
        raise ValueError("dim is required or must be present in metadata.json")
    kinds = role_kinds(metadata)
    collections = {kind: collection_name(kind, model, dim, args.stamp, role) for kind in kinds}
    return {
        "schema_version": f"{SCHEMA_VERSION}.plan",
        "generated_at": now_iso(),
        "mode": args.mode,
        "role_dir": str(args.role_dir),
        "out_dir": str(args.out_dir),
        "qdrant_url": args.qdrant_url,
        "model_role": role,
        "model": model,
        "dim": dim,
        "card_count": metadata.get("card_count"),
        "card_texts": str(args.role_dir / "card_texts.jsonl"),
        "collections": collections,
        "chunk_size": args.chunk_size,
        "batch_size": args.batch_size,
        "limit": args.limit,
        "resume": args.resume,
        "stamp": args.stamp,
        "confirm_token_required_for_writes": CONFIRM_TOKEN,
        "bulk_load_config": qdrant_full.bulk_collection_config(dim),
        "no_alias_promote": True,
    }


def initial_state(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": f"{SCHEMA_VERSION}.state",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "role_dir": plan["role_dir"],
        "model_role": plan["model_role"],
        "model": plan["model"],
        "dim": plan["dim"],
        "collections": plan["collections"],
        "next_index": 0,
        "written_counts": {kind: 0 for kind in plan["collections"]},
        "skipped_counts": {},
        "failed_count": 0,
        "complete": False,
    }


def load_state(path: Path, plan: dict[str, Any], resume: bool) -> dict[str, Any]:
    if resume and path.exists():
        state = read_json(path)
        for key in ("role_dir", "model_role", "model", "dim", "collections"):
            if state.get(key) != plan.get(key):
                raise ValueError(f"state {key} mismatch: {state.get(key)} != {plan.get(key)}")
        return state
    return initial_state(plan)


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    plan = report["plan"]
    state = report["state"]
    lines = [
        "# Vector Role Full Wave",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{report['decision']}`",
        f"- model_role: `{plan['model_role']}`",
        f"- model: `{plan['model']}`",
        f"- dim: `{plan['dim']}`",
        f"- complete: `{state.get('complete')}`",
        f"- next_index: `{state.get('next_index')}` / `{plan.get('card_count')}`",
        f"- processed_this_run: `{state.get('processed_this_run')}`",
        f"- failed_count: `{state.get('failed_count')}`",
        f"- cards_per_sec: `{state.get('cards_per_sec')}`",
        f"- error: `{report.get('error')}`",
        "",
        "## Collections",
        "",
        "| Kind | Collection | Written | Qdrant Count | Status | Optimizer |",
        "|---|---|---:|---:|---|---|",
    ]
    for kind, collection in sorted(plan["collections"].items()):
        health = (report.get("qdrant_health") or {}).get(kind) or {}
        optimizer = health.get("optimizer_status")
        if isinstance(optimizer, dict):
            optimizer = json.dumps(optimizer, ensure_ascii=False)
        lines.append(
            f"| `{kind}` | `{collection}` | {state.get('written_counts', {}).get(kind, 0)} | "
            f"{health.get('points_count')} | `{health.get('status')}` | `{optimizer}` |"
        )
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report(plan: dict[str, Any], state: dict[str, Any], *, qdrant_url: str, error: str | None = None) -> dict[str, Any]:
    health = qdrant_full.collections_health(qdrant_url, plan["collections"])
    complete = bool(state.get("complete"))
    no_failed = int(state.get("failed_count") or 0) == 0
    return {
        "schema_version": f"{SCHEMA_VERSION}.report",
        "generated_at": now_iso(),
        "decision": "vector_role_full_wave_complete" if complete and no_failed and not error else "vector_role_full_wave_in_progress_or_blocked",
        "ok": bool((complete or state.get("processed_this_run")) and no_failed and not error),
        "plan": plan,
        "state": state,
        "qdrant_health": health,
        "verification": state.get("verification") or {},
        "error": error,
        "safety": {
            "embedding_call_executed": bool(state.get("embedding_call_executed")),
            "qdrant_write_executed": bool(state.get("qdrant_write_executed")),
            "qdrant_alias_change_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "production_publish_executed": False,
            "d_scan_executed": False,
        },
    }


def encode_and_write_chunk(
    *,
    model: Any,
    cards: list[dict[str, Any]],
    plan: dict[str, Any],
    metadata: dict[str, Any],
    qdrant_url: str,
    batch_size: int,
    samples: dict[str, list[dict[str, Any]]],
    verify_limit: int,
) -> tuple[Counter, Counter, int]:
    texts = [embed_role.format_document_text(str(card.get("text") or ""), plan["model"]) for card in cards]
    vectors_array = model.encode(
        texts,
        batch_size=max(1, batch_size),
        normalize_embeddings=True,
        truncate_dim=int(plan["dim"]),
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    points_by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped = Counter()
    failed = 0
    for card, vector_values in zip(cards, vectors_array.tolist()):
        vector = [float(value) for value in vector_values]
        if not vector_is_valid(vector, int(plan["dim"])):
            failed += 1
            skipped["invalid_vector"] += 1
            continue
        kind = str(card.get("parent_kind") or card.get("type") or "")
        collection = (plan.get("collections") or {}).get(kind)
        if not collection:
            skipped[kind or "missing_kind"] += 1
            continue
        point = make_point(card, vector, metadata=metadata, collection=collection)
        points_by_kind[kind].append(point)
        if verify_limit and len(samples[collection]) < verify_limit:
            samples[collection].append({"job_id": card.get("id"), "text_sha1": card.get("text_sha1"), "vector": vector})
    written = Counter()
    for kind, points in points_by_kind.items():
        written[kind] += upsert_points(qdrant_url, plan["collections"][kind], points, batch_size)
    return written, skipped, failed


def run(args: argparse.Namespace) -> int:
    require_local_qdrant(args.qdrant_url)
    reject_d_root(args.role_dir, "role_dir")
    reject_d_root(args.out_dir, "out_dir")
    metadata = read_json(args.role_dir / "metadata.json")
    plan = build_plan(args, metadata)
    role_out_dir = args.out_dir / str(plan["model_role"])
    role_out_dir.mkdir(parents=True, exist_ok=True)
    write_json(role_out_dir / "qdrant_vector_role_full_wave_plan.json", plan)

    state_path = role_out_dir / "qdrant_vector_role_full_wave_state.json"
    if args.mode == "dry-run":
        state = load_state(state_path, plan, args.resume)
        report = build_report(plan, state, qdrant_url=args.qdrant_url)
        report["decision"] = "vector_role_full_wave_dry_run_ready"
        report["ok"] = True
        write_json(role_out_dir / "qdrant_vector_role_full_wave_report.json", report)
        write_markdown(role_out_dir / "qdrant_vector_role_full_wave_report.md", report)
        print(json.dumps({"ok": True, "decision": report["decision"], "plan": str(role_out_dir / "qdrant_vector_role_full_wave_plan.json")}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.confirm_token != CONFIRM_TOKEN:
        raise SystemExit(f"--confirm-token {CONFIRM_TOKEN} required for vector role full-wave Qdrant writes")

    state = load_state(state_path, plan, args.resume)
    if args.recreate and int(state.get("next_index") or 0) > 0:
        raise SystemExit("--recreate refused because resume state already has progress; use a fresh out-dir or --no-resume")
    config = embed_role.MODEL_CONFIGS.get(plan["model"]) or {}
    local_dir = args.local_dir or Path(str(config.get("local_dir") or plan["model"]))
    reject_d_root(local_dir, "local_model_dir")
    if not local_dir.exists():
        raise SystemExit(f"local model dir not found: {local_dir}")

    enforce_native_heavy_python_guard("run_vector_role_full_wave.build")
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415

    load_started = time.perf_counter()
    model = SentenceTransformer(str(local_dir), device=args.device, trust_remote_code=True, local_files_only=True)
    load_sec = round(time.perf_counter() - load_started, 3)
    collection_status = ensure_collections(args.qdrant_url, plan["collections"], int(plan["dim"]), args.recreate)
    state.update(
        {
            "collection_status": collection_status,
            "complete": False,
            "embedding_call_executed": True,
            "qdrant_write_executed": False,
            "load_sec": load_sec,
            "updated_at": now_iso(),
        }
    )
    write_json(state_path, state)

    started = time.perf_counter()
    start_index = int(state.get("next_index") or 0)
    processed_this_run = 0
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    chunk: list[dict[str, Any]] = []
    error: str | None = None
    try:
        for card in iter_role_cards(args.role_dir / "card_texts.jsonl", start_index=start_index, limit=args.limit):
            chunk.append(card)
            if len(chunk) < max(1, args.chunk_size):
                continue
            written, skipped, failed = encode_and_write_chunk(
                model=model,
                cards=chunk,
                plan=plan,
                metadata=metadata,
                qdrant_url=args.qdrant_url,
                batch_size=max(1, args.batch_size),
                samples=samples,
                verify_limit=max(0, args.verify_limit),
            )
            state = update_state_after_chunk(state, chunk, written, skipped, failed, started, processed_this_run)
            processed_this_run = int(state["processed_this_run"])
            write_json(state_path, state)
            print(json.dumps({"ok": True, "model_role": plan["model_role"], "next_index": state["next_index"], "written_counts": state["written_counts"]}, ensure_ascii=False), flush=True)
            chunk = []
        if chunk:
            written, skipped, failed = encode_and_write_chunk(
                model=model,
                cards=chunk,
                plan=plan,
                metadata=metadata,
                qdrant_url=args.qdrant_url,
                batch_size=max(1, args.batch_size),
                samples=samples,
                verify_limit=max(0, args.verify_limit),
            )
            state = update_state_after_chunk(state, chunk, written, skipped, failed, started, processed_this_run)
            processed_this_run = int(state["processed_this_run"])
            write_json(state_path, state)
    except Exception as exc:
        error = str(exc)
        state["stop_reason"] = "exception"
        state["updated_at"] = now_iso()
        write_json(state_path, state)
        raise
    finally:
        if samples and not error:
            state["verification"] = verify_samples(args.qdrant_url, samples)

    expected_done = int(plan.get("card_count") or 0)
    if args.limit:
        expected_done = min(expected_done, start_index + int(args.limit))
    state["complete"] = int(state.get("next_index") or 0) >= expected_done
    state["updated_at"] = now_iso()
    state["qdrant_write_executed"] = bool(sum(int(v) for v in (state.get("written_counts") or {}).values()))
    state["elapsed_sec"] = round(time.perf_counter() - started, 3)
    state["processed_this_run"] = processed_this_run
    state["cards_per_sec"] = round(processed_this_run / max(float(state["elapsed_sec"]), 0.001), 3)
    write_json(state_path, state)

    report = build_report(plan, state, qdrant_url=args.qdrant_url)
    write_json(role_out_dir / "qdrant_vector_role_full_wave_report.json", report)
    write_markdown(role_out_dir / "qdrant_vector_role_full_wave_report.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "model_role": plan["model_role"],
                "complete": state["complete"],
                "next_index": state["next_index"],
                "report": str(role_out_dir / "qdrant_vector_role_full_wave_report.json"),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report["ok"] and int(state.get("failed_count") or 0) == 0 else 1


def update_state_after_chunk(
    state: dict[str, Any],
    chunk: list[dict[str, Any]],
    written: Counter,
    skipped: Counter,
    failed: int,
    started: float,
    processed_before: int,
) -> dict[str, Any]:
    for kind, count in written.items():
        state["written_counts"][kind] = int(state["written_counts"].get(kind, 0)) + int(count)
    skipped_counts = Counter(state.get("skipped_counts") or {})
    skipped_counts.update(skipped)
    state["skipped_counts"] = dict(sorted(skipped_counts.items()))
    state["failed_count"] = int(state.get("failed_count") or 0) + int(failed)
    state["next_index"] = int(chunk[-1]["_source_index"]) + 1
    state["last_job_id"] = chunk[-1].get("id")
    processed = int(processed_before) + len(chunk)
    state["processed_this_run"] = processed
    elapsed = time.perf_counter() - started
    state["elapsed_sec"] = round(elapsed, 3)
    state["cards_per_sec"] = round(processed / max(elapsed, 0.001), 3)
    state["updated_at"] = now_iso()
    state["qdrant_write_executed"] = True
    return state


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "build"], default="dry-run")
    parser.add_argument("--role-dir", type=Path, default=DEFAULT_ROLE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--qdrant-url", default=DEFAULT_QDRANT_URL)
    parser.add_argument("--model", default="")
    parser.add_argument("--role", default="")
    parser.add_argument("--dim", type=int, default=0)
    parser.add_argument("--local-dir", type=Path, default=None)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--limit", type=int, default=0, help="0 means process all remaining rows.")
    parser.add_argument("--verify-limit", type=int, default=5)
    parser.add_argument("--stamp", default="20260518")
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--no-resume", dest="resume", action="store_false")
    parser.add_argument("--recreate", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not (args.role_dir / "metadata.json").exists():
        raise SystemExit(f"metadata not found under {args.role_dir}")
    if not (args.role_dir / "card_texts.jsonl").exists():
        raise SystemExit(f"card_texts not found under {args.role_dir}")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
