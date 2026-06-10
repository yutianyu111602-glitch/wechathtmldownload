#!/usr/bin/env python3
"""Build PRD-12 poster OCR text vector jobs from a verified OCR index.

This script is report-only. It materializes embedding job inputs from real
poster OCR text, but it never calls an embedding endpoint and never writes
Qdrant, Neo4j, SQLite, mem0, production data, aliases, or paid APIs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

if __name__ == "__main__" and not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stage7.vector_plan.schemas import VectorJob


DEFAULT_POINTER = Path("reports/dajiala_paid_wave01_04_verified_combined_ocr_index_20260516/ocr_file_index_latest.json")
DEFAULT_OUT_DIR = Path("reports/dajiala_paid_wave01_04_verified_poster_text_vector_jobs_20260516")
DEFAULT_MODEL = "Qwen/Qwen3-Embedding-4B"
DEFAULT_DIM = 1024
DEFAULT_COLLECTION = "wechat_stage8_poster_text_qwen3_embedding_4b_1024"
DEFAULT_ENDPOINT = "EMBEDDING_GATE_REQUIRED_NOT_CALLED"
SCHEMA_VERSION = "stage7_prd12_poster_text_vector_jobs.v1"
MAX_CANONICAL_CHARS = 2000


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"} or raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} refuses broad D root: {path}")


def read_json(path: Path) -> Any:
    reject_d_path(path, "json")
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if isinstance(row, dict):
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


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def resolve_path(value: Any, root: Path, *, relative_to: Path | None = None) -> Path:
    raw = str(value or "").strip()
    if not raw:
        return Path()
    path = Path(raw)
    if path.is_absolute():
        return path
    if relative_to is not None and (relative_to / path).exists():
        return relative_to / path
    rooted = root / path
    if rooted.exists():
        return rooted
    parts = path.parts
    marker = ("tools", "stage7_rewrite")
    for index in range(0, max(0, len(parts) - 1)):
        if tuple(parts[index : index + 2]) == marker:
            candidate = root.joinpath(*parts[index + 2 :])
            if candidate.exists():
                return candidate
    return rooted


def first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def text_from_blocks(blocks: Any) -> tuple[list[str], list[float]]:
    texts: list[str] = []
    scores: list[float] = []
    if not isinstance(blocks, list):
        return texts, scores
    for block in blocks:
        if isinstance(block, str):
            text = block
            score = None
        elif isinstance(block, dict):
            text = first_text(block.get("text"), block.get("ocr_text"), block.get("content"))
            score = block.get("score") or block.get("confidence")
        else:
            continue
        if text:
            texts.append(text)
        if isinstance(score, (int, float)):
            scores.append(float(score))
    return texts, scores


def extract_ocr_text(payload: dict[str, Any]) -> tuple[str, int, float | None]:
    plain_text = first_text(payload.get("plain_text"), payload.get("ocr_text"), payload.get("text"))
    block_texts, scores = text_from_blocks(payload.get("blocks"))
    if plain_text:
        text = plain_text
    else:
        text = " ".join(block_texts)
    average_score = round(sum(scores) / len(scores), 6) if scores else None
    return text.strip(), len(block_texts), average_score


def sha256_file(path: Path) -> tuple[str, int]:
    if not path.exists() or not path.is_file():
        return "", 0
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def canonical_text(row: dict[str, Any], meta: dict[str, Any], ocr_text: str) -> str:
    lines = [
        ("object", "poster_text_card"),
        ("source_account", first_text(row.get("source_account"), meta.get("account_name"), meta.get("source_account"))),
        ("article_title", first_text(meta.get("title"), meta.get("article_title"))),
        ("article_uid", first_text(row.get("article_uid"))),
        ("publish_time", first_text(meta.get("publish_time_iso"), meta.get("publish_time"))),
        ("poster_ocr_text", ocr_text),
    ]
    text = "\n".join(f"{key}: {value}" for key, value in lines if value)
    if len(text) <= MAX_CANONICAL_CHARS:
        return text
    return text[: MAX_CANONICAL_CHARS - 3] + "..."


def build_jobs(
    pointer_path: Path,
    out_dir: Path,
    *,
    model: str,
    dim: int,
    collection: str,
    endpoint: str,
    limit: int,
    min_text_chars: int,
    root: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    pointer = read_json(pointer_path)
    index_path = resolve_path(pointer.get("index_path"), root)
    rows = read_jsonl(index_path)

    jobs: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    accounts: Counter[str] = Counter()
    text_sha1s: Counter[str] = Counter()
    image_exists_count = 0
    image_sha256_count = 0

    for row in rows:
        if limit and len(jobs) >= limit:
            skipped["limit_reached"] += 1
            continue
        if first_text(row.get("ocr_status")) != "complete":
            skipped["ocr_status_not_complete"] += 1
            continue
        poster_ocr_path = resolve_path(row.get("poster_ocr_path"), root)
        if not poster_ocr_path.exists():
            skipped["missing_poster_ocr"] += 1
            continue
        poster_ocr = read_json(poster_ocr_path)
        if not isinstance(poster_ocr, dict):
            skipped["invalid_poster_ocr"] += 1
            continue
        ocr_text, block_count, average_score = extract_ocr_text(poster_ocr)
        if len(ocr_text) < min_text_chars:
            skipped["text_below_min_chars"] += 1
            continue

        meta_path = resolve_path(row.get("meta_path"), root)
        meta = read_json(meta_path) if meta_path.exists() else {}
        if not isinstance(meta, dict):
            meta = {}
        image_path = resolve_path(poster_ocr.get("image_path"), root, relative_to=poster_ocr_path.parent)
        image_sha256, image_bytes = sha256_file(image_path) if image_path else ("", 0)
        image_exists = bool(image_path and image_path.exists())
        if image_exists:
            image_exists_count += 1
        if image_sha256:
            image_sha256_count += 1

        account = first_text(row.get("source_account"), meta.get("account_name"), meta.get("source_account"))
        article_id = first_text(row.get("article_id"), meta.get("article_id"))
        article_uid = first_text(row.get("article_uid"), f"{account}/{article_id}".strip("/"))
        ctext = canonical_text(row, meta, ocr_text)
        job = VectorJob(
            job_id=f"{account}:{article_id}:poster_text:{hashlib.sha1(ctext.encode('utf-8')).hexdigest()[:12]}",
            object_kind="poster_text",
            object_id=article_uid,
            article_id=article_id,
            source_path=str(poster_ocr_path),
            model=model,
            endpoint=endpoint,
            dim=dim,
            collection=collection,
            canonical_text=ctext,
            metadata={
                "source_account": account,
                "article_uid": article_uid,
                "article_title": first_text(meta.get("title"), meta.get("article_title")),
                "publish_time": first_text(meta.get("publish_time_iso"), meta.get("publish_time")),
                "source_url": first_text(meta.get("source_url"), meta.get("url")),
                "poster_ocr_path": str(poster_ocr_path),
                "image_path": str(image_path) if image_path else "",
                "image_exists": image_exists,
                "image_sha256": image_sha256,
                "image_bytes": image_bytes,
                "ocr_backend": first_text(poster_ocr.get("backend")),
                "ocr_block_count": block_count,
                "ocr_average_score": average_score,
                "quality_grade": first_text(row.get("quality_grade")),
                "embedding_calls": False,
                "qdrant_write_allowed": False,
            },
        ).to_dict()
        jobs.append(job)
        accounts[account or "unknown"] += 1
        text_sha1s[str(job["text_sha1"])] += 1

    out_dir.mkdir(parents=True, exist_ok=True)
    jobs_path = out_dir / "poster_text_vector_jobs.jsonl"
    manifest_path = out_dir / "poster_text_vector_manifest.json"
    summary_path = out_dir / "poster_text_vector_jobs_summary.json"
    write_jsonl(jobs_path, jobs)

    duplicate_text_sha1_count = sum(count - 1 for count in text_sha1s.values() if count > 1)
    decision = "poster_text_vector_jobs_ready_report_only" if jobs else "poster_text_vector_jobs_blocked"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": decision,
        "ok": bool(jobs),
        "pointer_path": str(pointer_path),
        "index_path": str(index_path),
        "input_rows": len(rows),
        "job_count": len(jobs),
        "jobs_path": str(jobs_path),
        "manifest_path": str(manifest_path),
        "model": model,
        "dim": dim,
        "collection": collection,
        "endpoint": endpoint,
        "object_kind": "poster_text",
        "min_text_chars": min_text_chars,
        "skipped": dict(skipped),
        "top_source_accounts": dict(accounts.most_common(20)),
        "unique_text_sha1": len(text_sha1s),
        "duplicate_text_sha1_count": duplicate_text_sha1_count,
        "image_exists_count": image_exists_count,
        "image_sha256_count": image_sha256_count,
        "future_execution_gate": {
            "embedding_endpoint_required": True,
            "qdrant_write_gate_required": True,
            "suggested_embedding_command": (
                "python -m stage7.vector_plan.embed_runner "
                f"--output {out_dir} --jobs {jobs_path} --resume --batch-size 1"
            ),
            "suggested_qdrant_collection": collection,
        },
        "safety": {
            "reports_only": True,
            "embedding_calls": False,
            "qdrant_write": False,
            "alias_change": False,
            "neo4j_write": False,
            "mem0_write": False,
            "paid_api": False,
            "d_scan": False,
            "publish": False,
        },
    }
    manifest = {
        "schema_version": "stage7_prd12_poster_text_vector_manifest.v1",
        "created_at": summary["generated_at"],
        "source_index": str(index_path),
        "job_count": len(jobs),
        "by_unit_type": {"poster_text": len(jobs)},
        "embedding_models": [model],
        "dim": dim,
        "collection": collection,
        "endpoint": endpoint,
        "jobs_path": str(jobs_path),
        "summary_path": str(summary_path),
        "safety": summary["safety"],
    }
    write_json(manifest_path, manifest)
    write_json(summary_path, summary)
    write_markdown(out_dir / "poster_text_vector_jobs_summary.md", summary)
    return summary


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# PRD-12 Poster Text Vector Jobs",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- job_count: `{summary['job_count']}`",
        f"- model: `{summary['model']}`",
        f"- dim: `{summary['dim']}`",
        f"- collection: `{summary['collection']}`",
        f"- endpoint: `{summary['endpoint']}`",
        f"- image_exists_count: `{summary['image_exists_count']}`",
        f"- duplicate_text_sha1_count: `{summary['duplicate_text_sha1_count']}`",
        "",
        "## Safety",
        "",
        "- Report-only job packaging.",
        "- No embedding calls, Qdrant writes, alias changes, Neo4j writes, mem0 writes, paid API calls, D: scans, or publish.",
        "",
        "## Skipped",
        "",
    ]
    if summary["skipped"]:
        for key, value in sorted(summary["skipped"].items()):
            lines.append(f"- `{key}`: `{value}`")
    else:
        lines.append("- none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pointer", type=Path, default=DEFAULT_POINTER)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dim", type=int, default=DEFAULT_DIM)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--limit", type=int, default=0, help="0 means all eligible rows")
    parser.add_argument("--min-text-chars", type=int, default=4)
    parser.add_argument("--root", type=Path, default=Path("."))
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_jobs(
        pointer_path=args.pointer,
        out_dir=args.out_dir,
        model=args.model,
        dim=args.dim,
        collection=args.collection,
        endpoint=args.endpoint,
        limit=max(0, int(args.limit)),
        min_text_chars=max(1, int(args.min_text_chars)),
        root=args.root,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "job_count": summary["job_count"],
                "jobs_path": summary["jobs_path"],
                "summary": str(args.out_dir / "poster_text_vector_jobs_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if summary["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
