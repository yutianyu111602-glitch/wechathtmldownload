"""Run Stage 8 embedding jobs against Mac-hosted vector endpoints."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


@dataclass
class RunVectorStats:
    jobs_path: str
    embeddings_path: str
    failures_path: str
    total_jobs: int
    skipped_existing: int
    succeeded: int
    failed: int
    endpoint_count: int
    batch_size: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "jobs_path": self.jobs_path,
            "embeddings_path": self.embeddings_path,
            "failures_path": self.failures_path,
            "total_jobs": self.total_jobs,
            "skipped_existing": self.skipped_existing,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "endpoint_count": self.endpoint_count,
            "batch_size": self.batch_size,
        }


def text_sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
            rows.append(row)
    return rows


def load_existing_sha1s(path: Path) -> set[str]:
    if not path.exists():
        return set()
    existing: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            sha1 = str(row.get("text_sha1") or "").strip()
            if sha1:
                existing.add(sha1)
    return existing


def parse_vectors(payload: dict[str, Any]) -> list[list[float]]:
    embeddings = payload.get("embeddings") or payload.get("embedding") or payload.get("data")
    if embeddings is None:
        raise ValueError(f"No embedding field in response keys={list(payload.keys())}")
    if (
        isinstance(embeddings, list)
        and embeddings
        and isinstance(embeddings[0], dict)
        and isinstance(embeddings[0].get("embedding"), list)
    ):
        return [[float(item) for item in row["embedding"]] for row in embeddings]
    if isinstance(embeddings, list) and embeddings and isinstance(embeddings[0], list):
        return [[float(item) for item in vector] for vector in embeddings]
    if isinstance(embeddings, list):
        return [[float(item) for item in embeddings]]
    raise ValueError(f"Unexpected embedding shape: {type(embeddings).__name__}")


def parse_vector(payload: dict[str, Any]) -> list[float]:
    vectors = parse_vectors(payload)
    if not vectors:
        raise ValueError("empty_embedding_response")
    return vectors[0]


def validate_vector(vector: list[float], expected_dim: int) -> None:
    if len(vector) != expected_dim:
        raise ValueError(f"dim_mismatch expected={expected_dim} got={len(vector)}")
    for index, value in enumerate(vector):
        if math.isnan(value):
            raise ValueError(f"nan_at_index_{index}")
        if math.isinf(value):
            raise ValueError(f"inf_at_index_{index}")


async def resolve_endpoint_dim(client: httpx.AsyncClient, endpoint: str, expected_dim: int) -> int:
    resp = await client.get(f"{endpoint.rstrip('/')}/meta")
    resp.raise_for_status()
    meta = resp.json()
    dim = meta.get("dim") or meta.get("dimension") or meta.get("embedding_dim")
    if dim is None:
        raise RuntimeError(f"{endpoint} /meta missing dimension: {meta}")
    dim = int(dim)
    if dim != int(expected_dim):
        raise RuntimeError(f"{endpoint} dimension mismatch: jobs={expected_dim}, meta={dim}")
    return dim


async def embed_one(client: httpx.AsyncClient, job: dict[str, Any]) -> dict[str, Any]:
    endpoint = str(job["endpoint"]).rstrip("/")
    model = str(job["model"])
    canonical_text = str(job.get("canonical_text") or "")
    expected_dim = int(job["dim"])
    if not canonical_text.strip():
        raise ValueError("empty_canonical_text")

    resp = await client.post(
        f"{endpoint}/v1/embeddings",
        json={"model": model, "input": [canonical_text]},
    )
    if resp.status_code == 404:
        resp = await client.post(
            f"{endpoint}/embed",
            json={"model": model, "texts": [canonical_text]},
        )
        if resp.status_code == 404:
            resp = await client.post(
                f"{endpoint}/api/embed",
                json={"model": model, "input": canonical_text},
            )
    resp.raise_for_status()
    vector = parse_vector(resp.json())
    validate_vector(vector, expected_dim)

    return {
        "job_id": job["job_id"],
        "object_kind": job.get("object_kind"),
        "object_id": job.get("object_id"),
        "article_id": job.get("article_id"),
        "source_path": job.get("source_path"),
        "collection": job.get("collection"),
        "model": model,
        "dim": expected_dim,
        "endpoint": endpoint,
        "text_sha1": job.get("text_sha1") or text_sha1(canonical_text),
        "vector": vector,
        "metadata": job.get("metadata") or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def embedding_row(job: dict[str, Any], vector: list[float]) -> dict[str, Any]:
    canonical_text = str(job.get("canonical_text") or "")
    expected_dim = int(job["dim"])
    validate_vector(vector, expected_dim)
    return {
        "job_id": job["job_id"],
        "object_kind": job.get("object_kind"),
        "object_id": job.get("object_id"),
        "article_id": job.get("article_id"),
        "source_path": job.get("source_path"),
        "collection": job.get("collection"),
        "model": str(job["model"]),
        "dim": expected_dim,
        "endpoint": str(job["endpoint"]).rstrip("/"),
        "text_sha1": job.get("text_sha1") or text_sha1(canonical_text),
        "vector": vector,
        "metadata": job.get("metadata") or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


async def embed_batch(client: httpx.AsyncClient, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not jobs:
        return []
    first = jobs[0]
    endpoint = str(first["endpoint"]).rstrip("/")
    model = str(first["model"])
    expected_dim = int(first["dim"])
    texts: list[str] = []
    for job in jobs:
        if str(job["endpoint"]).rstrip("/") != endpoint or str(job["model"]) != model or int(job["dim"]) != expected_dim:
            raise ValueError("embedding batch contains mixed endpoint/model/dim")
        canonical_text = str(job.get("canonical_text") or "")
        if not canonical_text.strip():
            raise ValueError("empty_canonical_text")
        texts.append(canonical_text)

    resp = await client.post(
        f"{endpoint}/v1/embeddings",
        json={"model": model, "input": texts},
    )
    if resp.status_code == 404:
        resp = await client.post(
            f"{endpoint}/embed",
            json={"model": model, "texts": texts},
        )
        if resp.status_code == 404:
            resp = await client.post(
                f"{endpoint}/api/embed",
                json={"model": model, "input": texts},
            )
    resp.raise_for_status()
    vectors = parse_vectors(resp.json())
    if len(vectors) != len(jobs):
        raise ValueError(f"embedding_count_mismatch expected={len(jobs)} got={len(vectors)}")
    return [embedding_row(job, vector) for job, vector in zip(jobs, vectors)]


def batch_jobs(jobs: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    size = max(1, int(batch_size))
    batches: list[list[dict[str, Any]]] = []
    open_batches: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for job in jobs:
        key = (str(job["endpoint"]).rstrip("/"), str(job["model"]), int(job["dim"]))
        batch = open_batches.get(key)
        if batch is None or len(batch) >= size:
            batch = []
            open_batches[key] = batch
            batches.append(batch)
        batch.append(job)
    return batches


async def run_vector_jobs_async(
    jobs_path: Path,
    embeddings_path: Path,
    failures_path: Path,
    *,
    concurrency: int = 4,
    limit: int | None = None,
    resume: bool = False,
    timeout_sec: int = 120,
    batch_size: int = 1,
) -> RunVectorStats:
    jobs = load_jsonl(jobs_path)
    if limit is not None:
        jobs = jobs[:limit]

    embeddings_path.parent.mkdir(parents=True, exist_ok=True)
    failures_path.parent.mkdir(parents=True, exist_ok=True)

    existing_sha1s = load_existing_sha1s(embeddings_path) if resume else set()
    pending_jobs = []
    skipped_existing = 0
    for job in jobs:
        sha1 = str(job.get("text_sha1") or text_sha1(str(job.get("canonical_text") or "")))
        job["text_sha1"] = sha1
        if resume and sha1 in existing_sha1s:
            skipped_existing += 1
            continue
        pending_jobs.append(job)

    endpoints = {(str(job["endpoint"]).rstrip("/"), int(job["dim"])) for job in pending_jobs}
    limits = httpx.Limits(max_connections=max(concurrency * 2, 8))
    async with httpx.AsyncClient(timeout=timeout_sec, limits=limits) as client:
        for endpoint, dim in sorted(endpoints):
            await resolve_endpoint_dim(client, endpoint, dim)

        queue: asyncio.Queue[list[dict[str, Any]] | None] = asyncio.Queue()
        for batch in batch_jobs(pending_jobs, batch_size):
            queue.put_nowait(batch)
        for _ in range(max(1, concurrency)):
            queue.put_nowait(None)

        write_lock = asyncio.Lock()
        succeeded = 0
        failed = 0

        async def append_jsonl(path: Path, row: dict[str, Any]) -> None:
            async with write_lock:
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")

        async def worker() -> None:
            nonlocal succeeded, failed
            while True:
                batch = await queue.get()
                if batch is None:
                    return
                try:
                    rows = await embed_batch(client, batch)
                    for row in rows:
                        await append_jsonl(embeddings_path, row)
                    succeeded += len(rows)
                except Exception as exc:
                    for job in batch:
                        fail_row = {
                            "job_id": job.get("job_id"),
                            "object_kind": job.get("object_kind"),
                            "article_id": job.get("article_id"),
                            "endpoint": job.get("endpoint"),
                            "model": job.get("model"),
                            "dim": job.get("dim"),
                            "text_sha1": job.get("text_sha1"),
                            "error_type": type(exc).__name__,
                            "error_message": str(exc),
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                        await append_jsonl(failures_path, fail_row)
                    failed += len(batch)

        await asyncio.gather(*(worker() for _ in range(max(1, concurrency))))

    return RunVectorStats(
        jobs_path=str(jobs_path),
        embeddings_path=str(embeddings_path),
        failures_path=str(failures_path),
        total_jobs=len(jobs),
        skipped_existing=skipped_existing,
        succeeded=succeeded,
        failed=failed,
        endpoint_count=len(endpoints),
        batch_size=max(1, int(batch_size)),
    )


def default_embedding_paths(output_root: Path, jobs_path: Path) -> tuple[Path, Path]:
    suffix = jobs_path.stem.replace("vector_jobs", "").strip(".")
    suffix_part = f".{suffix}" if suffix else ""
    embed_dir = output_root / "stage8" / "embeddings"
    return (
        embed_dir / f"vector_embeddings{suffix_part}.jsonl",
        embed_dir / f"vector_failures{suffix_part}.jsonl",
    )


def find_latest_jobs(output_root: Path) -> Path:
    jobs_dir = output_root / "stage8" / "jobs"
    candidates = sorted(jobs_dir.glob("vector_jobs*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"No vector_jobs*.jsonl found in {jobs_dir}")
    return candidates[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stage 8 vector embedding jobs")
    parser.add_argument("--output", default=r"D:\downstream_results\stage7_rewrite", help="Stage output root")
    parser.add_argument("--jobs", default=None, help="vector_jobs JSONL path")
    parser.add_argument("--embeddings", default=None, help="Output embeddings JSONL")
    parser.add_argument("--failures", default=None, help="Output failures JSONL")
    parser.add_argument("--limit", type=int, default=None, help="Limit jobs")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrent embedding requests")
    parser.add_argument("--batch-size", type=int, default=1, help="Texts per embedding request; keep 1 unless the endpoint has a green batch bench")
    parser.add_argument("--resume", action="store_true", help="Skip existing text_sha1 rows in embeddings output")
    parser.add_argument("--timeout-sec", type=int, default=120, help="HTTP timeout seconds")
    args = parser.parse_args(argv)

    output_root = Path(args.output)
    jobs_path = Path(args.jobs) if args.jobs else find_latest_jobs(output_root)
    embeddings_path, failures_path = default_embedding_paths(output_root, jobs_path)
    if args.embeddings:
        embeddings_path = Path(args.embeddings)
    if args.failures:
        failures_path = Path(args.failures)

    stats = asyncio.run(
        run_vector_jobs_async(
            jobs_path,
            embeddings_path,
            failures_path,
            concurrency=max(1, int(args.concurrency)),
            limit=args.limit,
            resume=args.resume,
            timeout_sec=args.timeout_sec,
            batch_size=max(1, int(args.batch_size)),
        )
    )
    print(json.dumps(stats.to_dict(), ensure_ascii=False, indent=2))
    return 0 if stats.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
