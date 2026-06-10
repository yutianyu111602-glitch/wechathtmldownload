"""Report-only mem0 local/dimension gate for Stage7 personalization design.

This script intentionally does not write mem0/Postgres rows, create tables,
embed text, call cloud services, or modify consumer code. It verifies the local
preconditions that PRD-10/PRD-17 need before any future write gate exists.
"""

from __future__ import annotations

import argparse
import json
import socket
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_OUT_DIR = Path("reports/mem0_dimension_gate_20260515")
DEFAULT_DESIGN_DIR = Path("reports/mem0_design_20260515")
DEFAULT_VECTOR_METADATA = Path("reports/vector_full_qwen3_4b_1024_20260514/metadata.json")
DEFAULT_POLICY_DOC = Path("docs/LOCAL_MEM0_DIMENSION_POLICY.md")
DEFAULT_MEM0_CONFIG = Path("config/mem0_config.json")
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18432
EXPECTED_MODEL = "Qwen/Qwen3-Embedding-4B"
EXPECTED_DIM = 1024


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def cloud_mem0_reasons(endpoint: str) -> list[str]:
    if not endpoint:
        return []
    reasons = []
    lower = endpoint.casefold()
    if "api.mem0.ai" in lower:
        reasons.append("endpoint_contains_api.mem0.ai")
    if "cloud.mem0" in lower:
        reasons.append("endpoint_contains_cloud.mem0")
    parsed = urlparse(endpoint)
    host = (parsed.hostname or endpoint).casefold().strip("[]")
    local_ok = host in {"127.0.0.1", "localhost", "::1"} or host.startswith("192.168.8.")
    if parsed.scheme in {"http", "https", "postgres", "postgresql", "tcp"} and not local_ok:
        reasons.append("endpoint_host_is_not_allowed_local_host")
    return reasons


def config_endpoint(config: dict[str, Any]) -> str:
    vector_config = ((config.get("vector_store") or {}).get("config") or {})
    for key in ("url", "endpoint", "host"):
        value = vector_config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    for key in ("mem0_url", "mem0_endpoint", "endpoint", "url"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def load_mem0_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False, "path": str(path), "endpoint": "", "cloud_reasons": []}
    data = read_json(path)
    endpoint = config_endpoint(data)
    return {
        "exists": True,
        "path": str(path),
        "endpoint": endpoint,
        "cloud_reasons": cloud_mem0_reasons(endpoint),
    }


def vector_dimension_gate(metadata: dict[str, Any]) -> dict[str, Any]:
    shape = metadata.get("embedding_shape") if isinstance(metadata.get("embedding_shape"), list) else []
    shape_dim = int(shape[1]) if len(shape) > 1 and str(shape[1]).isdigit() else None
    dim = int(metadata.get("dim") or 0)
    truncate_dim = int(metadata.get("truncate_dim") or 0)
    model = str(metadata.get("model") or "")
    ok = model == EXPECTED_MODEL and dim == EXPECTED_DIM and truncate_dim == EXPECTED_DIM and shape_dim == EXPECTED_DIM
    blockers = []
    if model != EXPECTED_MODEL:
        blockers.append(f"unexpected embedding model: {model}")
    if dim != EXPECTED_DIM:
        blockers.append(f"metadata dim mismatch: {dim}")
    if truncate_dim != EXPECTED_DIM:
        blockers.append(f"metadata truncate_dim mismatch: {truncate_dim}")
    if shape_dim != EXPECTED_DIM:
        blockers.append(f"embedding_shape dim mismatch: {shape_dim}")
    return {
        "ok": ok,
        "model": model,
        "expected_model": EXPECTED_MODEL,
        "dim": dim,
        "truncate_dim": truncate_dim,
        "shape_dim": shape_dim,
        "expected_dim": EXPECTED_DIM,
        "blockers": blockers,
        "no_truncate_or_pad_policy": True,
    }


def tcp_check(host: str, port: int, timeout: float = 5.0) -> dict[str, Any]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return {"ok": True, "host": host, "port": port, "error": ""}
    except OSError as exc:
        return {"ok": False, "host": host, "port": port, "error": str(exc)}


def docker_status(container: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{json .State}}", container],
            text=True,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "container": container, "error": str(exc), "state": {}}
    if result.returncode != 0:
        return {"ok": False, "container": container, "error": result.stderr.strip(), "state": {}}
    try:
        state = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        state = {}
    health = (state.get("Health") or {}).get("Status")
    running = bool(state.get("Running"))
    return {
        "ok": running and (health in {"healthy", None, ""}),
        "container": container,
        "running": running,
        "health": health,
        "state": state,
        "error": "",
    }


def build_schema_design() -> dict[str, Any]:
    return {
        "collections": [
            {
                "name": "user_memory_qwen3_1024",
                "embedding_model": EXPECTED_MODEL,
                "embedding_dim": EXPECTED_DIM,
                "purpose": "user query, article view, and explicit preference memory",
                "write_status": "blocked_until_mem0_write_gate",
            },
            {
                "name": "article_index_qwen3_1024",
                "embedding_model": EXPECTED_MODEL,
                "embedding_dim": EXPECTED_DIM,
                "purpose": "optional article memory index for recommendation features",
                "write_status": "design_only",
            },
            {
                "name": "entity_index_qwen3_1024",
                "embedding_model": EXPECTED_MODEL,
                "embedding_dim": EXPECTED_DIM,
                "purpose": "optional high-value entity memory index for recommendation features",
                "write_status": "design_only",
            },
        ],
        "sql": "\n".join(
            [
                "CREATE TABLE IF NOT EXISTS stage7_memories (",
                "  id BIGSERIAL PRIMARY KEY,",
                "  memory_id TEXT UNIQUE NOT NULL,",
                "  user_id TEXT,",
                "  memory_type TEXT NOT NULL,",
                "  content TEXT NOT NULL,",
                "  content_hash TEXT NOT NULL,",
                "  embedding_dim INTEGER NOT NULL,",
                "  embedding_model TEXT NOT NULL,",
                "  metadata JSONB NOT NULL DEFAULT '{}',",
                "  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),",
                "  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),",
                "  CONSTRAINT stage7_memories_dim_check CHECK (embedding_dim = 1024)",
                ");",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_stage7_memories_content_hash ON stage7_memories(content_hash);",
                "CREATE INDEX IF NOT EXISTS idx_stage7_memories_user_type ON stage7_memories(user_id, memory_type);",
            ]
        ),
        "write_policy": {
            "current_status": "blocked",
            "allowed_now": ["local health checks", "dimension policy validation", "schema design reports"],
            "forbidden_now": ["mem0 row writes", "cloud mem0 endpoint", "embedding generation for mem0", "consumer production changes"],
        },
    }


def build_decision(report: dict[str, Any]) -> dict[str, Any]:
    blockers = []
    if report["mem0_config"]["cloud_reasons"]:
        blockers.append("cloud mem0 endpoint detected")
    if not report["vector_dimension_gate"]["ok"]:
        blockers.extend(report["vector_dimension_gate"]["blockers"])
    if not report["tcp"]["ok"]:
        blockers.append("mem0 postgres tcp check failed")
    if blockers:
        status = "blocked"
    else:
        status = "design_ready_write_blocked"
    return {
        "status": status,
        "blockers": blockers,
        "mem0_write_allowed": False,
        "next_allowed": [
            "use this report as PRD-10/PRD-17 dimension gate evidence",
            "build recommendation dry-run logic without mem0 writes",
            "prepare a future isolated mem0 write canary only after a separate write gate exists",
        ],
        "still_forbidden": [
            "mem0 row writes",
            "cloud mem0",
            "production SQLite write",
            "production publish",
            "production graph promotion",
        ],
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    config = load_mem0_config(args.mem0_config)
    metadata = read_json(args.vector_metadata)
    policy_exists = args.policy_doc.exists()
    report = {
        "schema_version": "stage7_mem0_dimension_gate.v1",
        "generated_at": now_iso(),
        "mode": args.mode,
        "mem0_config": config,
        "policy_doc": {"path": str(args.policy_doc), "exists": policy_exists},
        "vector_metadata_path": str(args.vector_metadata),
        "vector_dimension_gate": vector_dimension_gate(metadata),
        "tcp": tcp_check(args.host, args.port, timeout=args.timeout),
        "docker": docker_status(args.container) if args.check_docker else {"checked": False},
        "design": build_schema_design(),
        "safety": {
            "report_only": True,
            "mem0_write_executed": False,
            "cloud_mem0_used": False,
            "embedding_call_executed": False,
            "production_write_executed": False,
        },
    }
    report["decision"] = build_decision(report)
    return report


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    decision = report["decision"]
    design = report["design"]
    lines = [
        "# mem0 Dimension Gate",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- decision: `{decision['status']}`",
        f"- mem0_write_allowed: `{decision['mem0_write_allowed']}`",
        f"- tcp_ok: `{report['tcp']['ok']}`",
        f"- vector_dim_ok: `{report['vector_dimension_gate']['ok']}`",
        f"- cloud_reasons: `{json.dumps(report['mem0_config']['cloud_reasons'], ensure_ascii=False)}`",
        "",
        "## Collections",
        "",
        "| Collection | Dim | Model | Status |",
        "|---|---:|---|---|",
    ]
    for row in design["collections"]:
        lines.append(f"| `{row['name']}` | {row['embedding_dim']} | `{row['embedding_model']}` | `{row['write_status']}` |")
    lines.extend(
        [
            "",
            "## SQL Design",
            "",
            "```sql",
            design["sql"],
            "```",
            "",
            "## Safety",
            "",
            "- This gate performed no mem0 writes, no embedding calls, no production writes, and no cloud mem0 calls.",
            "- Future write canaries must be isolated and separately gated.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_design_markdown(path: Path, report: dict[str, Any]) -> None:
    design = report["design"]
    lines = [
        "# Stage7 mem0 Integration Design",
        "",
        "mem0 remains optional personalization storage. Qdrant stays the primary retrieval store and Neo4j stays the graph source.",
        "",
        "## Write Status",
        "",
        "- Current status: `blocked`.",
        "- This design does not authorize writes.",
        "- Cloud mem0 is forbidden.",
        "",
        "## Collection Plan",
        "",
    ]
    for row in design["collections"]:
        lines.extend(
            [
                f"### {row['name']}",
                "",
                f"- purpose: {row['purpose']}",
                f"- embedding_model: `{row['embedding_model']}`",
                f"- embedding_dim: `{row['embedding_dim']}`",
                f"- write_status: `{row['write_status']}`",
                "",
            ]
        )
    lines.extend(["## Schema", "", "```sql", design["sql"], "```", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> int:
    report = build_report(args)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    args.design_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "mem0_dimension_gate.json", report)
    write_markdown(args.out_dir / "mem0_dimension_gate.md", report)
    write_json(args.design_dir / "mem0_integration_design.json", report["design"])
    write_design_markdown(args.design_dir / "mem0_integration_design.md", report)
    print(
        json.dumps(
            {
                "ok": report["decision"]["status"] != "blocked",
                "decision": report["decision"]["status"],
                "mem0_write_allowed": False,
                "report": str(args.out_dir / "mem0_dimension_gate.json"),
                "design": str(args.design_dir / "mem0_integration_design.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if report["decision"]["status"] != "blocked" else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "design"], default="dry-run")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--design-dir", type=Path, default=DEFAULT_DESIGN_DIR)
    parser.add_argument("--vector-metadata", type=Path, default=DEFAULT_VECTOR_METADATA)
    parser.add_argument("--policy-doc", type=Path, default=DEFAULT_POLICY_DOC)
    parser.add_argument("--mem0-config", type=Path, default=DEFAULT_MEM0_CONFIG)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--container", default="mem0-dev-postgres-1")
    parser.add_argument("--check-docker", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
