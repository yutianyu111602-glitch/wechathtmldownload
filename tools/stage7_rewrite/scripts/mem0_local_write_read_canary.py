#!/usr/bin/env python3
"""Run an isolated local mem0 Postgres write/read canary for PRD-10.

The canary writes only deterministic Stage7 test rows into the local Docker
Postgres table. It does not call cloud mem0 and does not store user secrets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import error, request


DEFAULT_OUT_DIR = Path("reports/mem0_local_write_read_canary_20260517")
DEFAULT_ENDPOINT = "http://127.0.0.1:11441"
DEFAULT_MODEL = "Qwen/Qwen3-Embedding-4B"
DEFAULT_DIM = 1024
DEFAULT_CONTAINER = "mem0-dev-postgres-1"
CONFIRM_TOKEN = "ENABLE_MEM0_LOCAL_WRITE"
SCHEMA_VERSION = "stage7_mem0_local_write_read_canary.v1"
SOURCE_RUN_ID = "stage7_mem0_local_canary_20260517"
USER_ID = "stage7_canary_user"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for mem0 canary: {path}")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sql_literal(value: Any) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def vector_literal(vector: list[float]) -> str:
    return "'[" + ",".join(format(float(item), ".9g") for item in vector) + "]'::vector"


def seed_rows() -> list[dict[str, Any]]:
    rows = [
        {
            "memory_id": f"{SOURCE_RUN_ID}:poster_ocr_evidence",
            "memory_type": "stage7_canary",
            "content": "Stage7 canary prefers poster OCR evidence backed by local image files and source paths.",
            "metadata": {"topic": "poster_ocr", "canary": True},
        },
        {
            "memory_id": f"{SOURCE_RUN_ID}:direct_source_citations",
            "memory_type": "stage7_canary",
            "content": "Stage7 canary ranks direct source citations ahead of soft social signals.",
            "metadata": {"topic": "recommendation", "canary": True},
        },
        {
            "memory_id": f"{SOURCE_RUN_ID}:qwen3_1024_text_lane",
            "memory_type": "stage7_canary",
            "content": "Stage7 canary keeps the text embedding lane at Qwen3 1024 dimensions for compatibility.",
            "metadata": {"topic": "embedding", "canary": True},
        },
    ]
    for row in rows:
        row["user_id"] = USER_ID
        row["content_hash"] = sha256_text(f"{row['memory_id']}\n{row['content']}")
    return rows


def http_json(url: str, payload: dict[str, Any] | None, timeout: int) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with request.urlopen(req, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{url} returned non-object JSON")
    return value


def endpoint_meta(endpoint: str, timeout: int) -> dict[str, Any]:
    return http_json(endpoint.rstrip("/") + "/meta", None, timeout)


def embed_texts(endpoint: str, model: str, texts: list[str], timeout: int) -> list[list[float]]:
    payload = {"model": model, "input": texts}
    response = http_json(endpoint.rstrip("/") + "/v1/embeddings", payload, timeout)
    data = response.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise ValueError("embedding response row count mismatch")
    vectors: list[list[float]] = []
    for item in sorted(data, key=lambda row: int(row.get("index", 0))):
        vector = item.get("embedding")
        if not isinstance(vector, list):
            raise ValueError("embedding response missing vector")
        vectors.append([float(value) for value in vector])
    return vectors


def run_psql(sql: str, *, container: str, timeout: int) -> subprocess.CompletedProcess[str]:
    command = [
        "docker",
        "exec",
        "-i",
        container,
        "sh",
        "-lc",
        'psql -v ON_ERROR_STOP=1 -X -qAt -F "|" -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-postgres}"',
    ]
    return subprocess.run(command, input=sql, text=True, capture_output=True, timeout=timeout)


def psql_or_raise(sql: str, *, container: str, timeout: int) -> str:
    result = run_psql(sql, container=container, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "psql failed").strip())
    return result.stdout.strip()


def local_db_probe(container: str, timeout: int) -> dict[str, Any]:
    try:
        output = psql_or_raise(
            "SELECT current_database();\nSELECT extname FROM pg_extension WHERE extname = 'vector';\n",
            container=container,
            timeout=timeout,
        )
        lines = [line for line in output.splitlines() if line.strip()]
        return {
            "ok": True,
            "container": container,
            "database": lines[0] if lines else "",
            "vector_extension_installed": "vector" in lines[1:],
            "error": "",
        }
    except Exception as exc:
        return {"ok": False, "container": container, "database": "", "vector_extension_installed": False, "error": str(exc)}


def schema_sql() -> str:
    return "\n".join(
        [
            "CREATE EXTENSION IF NOT EXISTS vector;",
            "CREATE TABLE IF NOT EXISTS stage7_memories (",
            "  memory_id TEXT PRIMARY KEY,",
            "  user_id TEXT NOT NULL,",
            "  memory_type TEXT NOT NULL,",
            "  content TEXT NOT NULL,",
            "  content_hash TEXT NOT NULL UNIQUE,",
            "  embedding vector(1024) NOT NULL,",
            "  embedding_model TEXT NOT NULL,",
            "  embedding_dim INTEGER NOT NULL CHECK (embedding_dim = 1024),",
            "  metadata JSONB NOT NULL DEFAULT '{}',",
            "  source_run_id TEXT NOT NULL,",
            "  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),",
            "  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()",
            ");",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS memory_id TEXT;",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS user_id TEXT;",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS memory_type TEXT;",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS content TEXT;",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS content_hash TEXT;",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS embedding vector(1024);",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS embedding_model TEXT;",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS embedding_dim INTEGER;",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS source_run_id TEXT;",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();",
            "ALTER TABLE stage7_memories ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_stage7_memories_memory_id ON stage7_memories(memory_id);",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_stage7_memories_content_hash ON stage7_memories(content_hash);",
            "CREATE INDEX IF NOT EXISTS idx_stage7_memories_user_type ON stage7_memories(user_id, memory_type);",
            "CREATE INDEX IF NOT EXISTS idx_stage7_memories_source_run_id ON stage7_memories(source_run_id);",
        ]
    )


def insert_sql(rows: list[dict[str, Any]], vectors: list[list[float]], model: str, dim: int) -> str:
    statements = [schema_sql()]
    for row, vector in zip(rows, vectors, strict=True):
        metadata = json.dumps(row["metadata"], ensure_ascii=False, sort_keys=True)
        statements.append(
            "\n".join(
                [
                    "INSERT INTO stage7_memories (",
                    "  memory_id, user_id, memory_type, content, content_hash, embedding,",
                    "  embedding_model, embedding_dim, metadata, source_run_id, created_at, updated_at",
                    ") VALUES (",
                    f"  {sql_literal(row['memory_id'])}, {sql_literal(row['user_id'])}, {sql_literal(row['memory_type'])},",
                    f"  {sql_literal(row['content'])}, {sql_literal(row['content_hash'])}, {vector_literal(vector)},",
                    f"  {sql_literal(model)}, {int(dim)}, {sql_literal(metadata)}::jsonb, {sql_literal(SOURCE_RUN_ID)}, NOW(), NOW()",
                    ")",
                    "ON CONFLICT (memory_id) DO UPDATE SET",
                    "  user_id = EXCLUDED.user_id,",
                    "  memory_type = EXCLUDED.memory_type,",
                    "  content = EXCLUDED.content,",
                    "  content_hash = EXCLUDED.content_hash,",
                    "  embedding = EXCLUDED.embedding,",
                    "  embedding_model = EXCLUDED.embedding_model,",
                    "  embedding_dim = EXCLUDED.embedding_dim,",
                    "  metadata = EXCLUDED.metadata,",
                    "  source_run_id = EXCLUDED.source_run_id,",
                    "  updated_at = NOW();",
                ]
            )
        )
    return "\n".join(statements)


def query_sql(query_vector: list[float]) -> str:
    return "\n".join(
        [
            "SELECT memory_id, ROUND((1 - (embedding <=> " + vector_literal(query_vector) + "))::numeric, 6)",
            "FROM stage7_memories",
            f"WHERE user_id = {sql_literal(USER_ID)} AND source_run_id = {sql_literal(SOURCE_RUN_ID)}",
            "ORDER BY embedding <=> " + vector_literal(query_vector),
            "LIMIT 3;",
        ]
    )


def parse_query_rows(output: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 1)
        rows.append({"memory_id": parts[0], "similarity": float(parts[1]) if len(parts) > 1 and parts[1] else None})
    return rows


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    reject_d_path(args.out_dir, "out_dir")
    rows = seed_rows()
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": args.mode,
        "ok": False,
        "decision": "mem0_local_write_read_canary_blocked",
        "endpoint": args.endpoint,
        "model": args.model,
        "embedding_dim": args.dim,
        "container": args.container,
        "target_table": "stage7_memories",
        "source_run_id": SOURCE_RUN_ID,
        "user_id": USER_ID,
        "seed_count": len(rows),
        "rows_written": 0,
        "query_self_hit": False,
        "blockers": [],
        "seed_memory_ids": [row["memory_id"] for row in rows],
        "safety": {
            "reports_only": args.mode != "apply",
            "mem0_write_executed": False,
            "mem0_schema_mutation_executed": False,
            "embedding_call_executed": False,
            "cloud_mem0_used": False,
            "production_write_executed": False,
            "paid_api_used": False,
        },
        "writes": "reports_only",
    }

    try:
        meta = endpoint_meta(args.endpoint, args.timeout_sec)
        report["endpoint_meta"] = {key: meta.get(key) for key in ("ok", "model", "dim", "dimension", "embedding_dim", "device")}
        if meta.get("model") != args.model:
            report["blockers"].append(f"embedding model mismatch: {meta.get('model')}")
        if int(meta.get("dim") or meta.get("dimension") or meta.get("embedding_dim") or 0) != args.dim:
            report["blockers"].append(f"embedding dim mismatch: {meta.get('dim')}")
    except (OSError, ValueError, error.URLError) as exc:
        report["endpoint_meta"] = {"ok": False, "error": str(exc)}
        report["blockers"].append("local embedding endpoint unavailable")

    db_probe = local_db_probe(args.container, args.timeout_sec)
    report["local_postgres"] = db_probe
    if not db_probe["ok"]:
        report["blockers"].append("local mem0 postgres unavailable")

    if args.mode != "apply":
        report["ok"] = not report["blockers"]
        report["decision"] = "mem0_local_write_read_canary_ready" if report["ok"] else "mem0_local_write_read_canary_blocked"
        return report

    if args.confirm_token != CONFIRM_TOKEN:
        report["blockers"].append("missing confirm token for local mem0 write")
        return report
    if report["blockers"]:
        return report

    vectors = embed_texts(args.endpoint, args.model, [row["content"] for row in rows], args.timeout_sec)
    report["safety"]["embedding_call_executed"] = True
    bad_dims = [len(vector) for vector in vectors if len(vector) != args.dim]
    if bad_dims:
        report["blockers"].append(f"embedding dim mismatch in vectors: {bad_dims[:3]}")
        return report

    psql_or_raise(insert_sql(rows, vectors, args.model, args.dim), container=args.container, timeout=args.timeout_sec)
    report["safety"]["mem0_schema_mutation_executed"] = True
    report["safety"]["mem0_write_executed"] = True
    report["rows_written"] = len(rows)
    report["writes"] = "local_mem0_postgres"

    query_output = psql_or_raise(query_sql(vectors[0]), container=args.container, timeout=args.timeout_sec)
    query_rows = parse_query_rows(query_output)
    report["query_top3"] = query_rows
    report["query_self_hit"] = bool(query_rows and query_rows[0]["memory_id"] == rows[0]["memory_id"])
    if not report["query_self_hit"]:
        report["blockers"].append("local mem0 vector query did not self-hit")

    report["ok"] = not report["blockers"] and report["rows_written"] == len(rows)
    report["decision"] = "mem0_local_write_read_canary_passed" if report["ok"] else "mem0_local_write_read_canary_failed"
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# mem0 Local Write/Read Canary",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- mode: `{report['mode']}`",
        f"- decision: `{report['decision']}`",
        f"- ok: `{report['ok']}`",
        f"- endpoint: `{report['endpoint']}`",
        f"- model: `{report['model']}`",
        f"- embedding_dim: `{report['embedding_dim']}`",
        f"- rows_written: `{report['rows_written']}`",
        f"- query_self_hit: `{report['query_self_hit']}`",
        f"- writes: `{report['writes']}`",
        "",
        "## Blockers",
        "",
    ]
    for blocker in report["blockers"]:
        lines.append(f"- {blocker}")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(report["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "apply"], default="dry-run")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dim", type=int, default=DEFAULT_DIM)
    parser.add_argument("--container", default=DEFAULT_CONTAINER)
    parser.add_argument("--confirm-token", default="")
    parser.add_argument("--timeout-sec", type=int, default=120)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    try:
        report = build_report(args)
    except Exception as exc:
        report = {
            "schema_version": SCHEMA_VERSION,
            "generated_at": now_iso(),
            "mode": args.mode,
            "ok": False,
            "decision": "mem0_local_write_read_canary_failed",
            "blockers": [str(exc)],
            "safety": {
                "reports_only": args.mode != "apply",
                "mem0_write_executed": False,
                "mem0_schema_mutation_executed": False,
                "embedding_call_executed": False,
                "cloud_mem0_used": False,
                "production_write_executed": False,
                "paid_api_used": False,
            },
            "writes": "reports_only",
        }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "mem0_local_write_read_canary.json", report)
    write_markdown(args.out_dir / "mem0_local_write_read_canary.md", report)
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "decision": report["decision"],
                "rows_written": report.get("rows_written", 0),
                "query_self_hit": report.get("query_self_hit", False),
                "summary": str(args.out_dir / "mem0_local_write_read_canary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["ok"] else 2


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
