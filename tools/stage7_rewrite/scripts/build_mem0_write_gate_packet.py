#!/usr/bin/env python3
"""Build a PRD-10 mem0 write gate packet.

This packet consolidates local mem0 health/dimension evidence with the current
graph, consumer, and recommendation state. The packet itself never writes
mem0/Postgres rows, but it can consume a separate local write/read canary report.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_MEM0_GATE = Path("reports/mem0_dimension_gate_20260516/mem0_dimension_gate.json")
DEFAULT_GRAPH_PROMOTION = Path("reports/graph_promotion_readiness_refresh_20260516/graph_promotion_readiness.json")
DEFAULT_CONSUMER_PACKET = Path("reports/consumer_production_gate_packet_20260516/consumer_production_gate_packet.json")
DEFAULT_HYBRID_RECOMMEND = Path("reports/hybrid_recommend_canary_20260515/hybrid_recommend_canary.json")
DEFAULT_MEM0_LOCAL_CANARY = Path("reports/mem0_local_write_read_canary_20260517/mem0_local_write_read_canary.json")
DEFAULT_OUT_DIR = Path("reports/mem0_write_gate_packet_20260516")
DEFAULT_AUTH_CONFIG = Path("config/consumer_publish_gate.local.json")
SCHEMA_VERSION = "stage7_mem0_write_gate_packet.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for mem0 write gate packet: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def read_production_authorization(path: Path) -> dict[str, Any]:
    return read_json(path).get("production_authorization") or {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(text)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def unique_nonempty(items: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item or "").strip()
        if text and text not in seen:
            seen.add(text)
            out.append(text)
    return out


def docker_healthy(mem0_gate: dict[str, Any]) -> bool:
    docker = mem0_gate.get("docker") or {}
    return bool(docker.get("ok")) and str(docker.get("health") or "").lower() in {"healthy", "not_checked", ""}


def build_packet(
    *,
    mem0_gate_path: Path,
    graph_promotion_path: Path,
    consumer_packet_path: Path,
    hybrid_recommend_path: Path,
    out_dir: Path,
    auth_config_path: Path = DEFAULT_AUTH_CONFIG,
    mem0_local_canary_path: Path = DEFAULT_MEM0_LOCAL_CANARY,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    mem0_gate = read_json(mem0_gate_path)
    graph = read_json(graph_promotion_path)
    consumer = read_json(consumer_packet_path)
    hybrid = read_json(hybrid_recommend_path)
    local_canary = read_json(mem0_local_canary_path)
    authorization = read_production_authorization(auth_config_path)
    mem0_write_allowed = bool(authorization.get("mem0_write_allowed"))

    decision = mem0_gate.get("decision") or {}
    vector_gate = mem0_gate.get("vector_dimension_gate") or {}
    mem0_config = mem0_gate.get("mem0_config") or {}
    tcp = mem0_gate.get("tcp") or {}
    design = mem0_gate.get("design") or {}
    collection_plan = design.get("collections") or []
    local_canary_safety = local_canary.get("safety") or {}
    local_canary_passed = (
        local_canary.get("decision") == "mem0_local_write_read_canary_passed"
        and bool(local_canary.get("ok"))
        and int(local_canary.get("rows_written") or 0) > 0
        and int(local_canary.get("embedding_dim") or 0) == 1024
        and bool(local_canary.get("query_self_hit"))
        and bool(local_canary_safety.get("mem0_write_executed"))
        and not bool(local_canary_safety.get("cloud_mem0_used"))
    )
    local_ready_gates = {
        "mem0_tcp_ok": bool(tcp.get("ok")),
        "mem0_docker_healthy": docker_healthy(mem0_gate),
        "vector_dim_ok": bool(vector_gate.get("ok")),
        "local_only_endpoint": not bool(mem0_config.get("cloud_reasons")),
        "policy_doc_present": bool((mem0_gate.get("policy_doc") or {}).get("exists")),
        "schema_design_present": bool(design.get("sql")) and bool(collection_plan),
        "hybrid_dry_run_available": hybrid.get("decision") == "hybrid_recommendations_ready_without_mem0",
        "local_mem0_canary_passed": local_canary_passed,
    }
    hard_gates_remaining = unique_nonempty(
        [
            *(["MEM0_WRITE is globally forbidden"] if not mem0_write_allowed else []),
            *(
                [
                    item
                    for item in (decision.get("still_forbidden") or [])
                    if not (
                        mem0_write_allowed
                        and item
                        in {
                            "mem0 row writes",
                            "cloud mem0",
                            "production SQLite write",
                            "production publish",
                            "production graph promotion",
                        }
                    )
                ]
            ),
            *(
                ["mem0 postgres tcp check failed"]
                if not local_ready_gates["mem0_tcp_ok"]
                else []
            ),
            *(
                ["mem0 docker health is not green"]
                if not local_ready_gates["mem0_docker_healthy"]
                else []
            ),
            *(vector_gate.get("blockers") or []),
            *(mem0_config.get("cloud_reasons") or []),
            *(
                ["local mem0 write/read canary not executed"]
                if mem0_write_allowed and not local_canary_passed
                else []
            ),
            *(
                ["PRD-07 graph promotion is blocked"]
                if not mem0_write_allowed and not bool(graph.get("promotion_allowed"))
                else []
            ),
            *(
                ["consumer production gate is blocked"]
                if not mem0_write_allowed
                and consumer.get("decision") == "consumer_production_gate_packet_ready_report_only"
                and (consumer.get("hard_gates_remaining") or [])
                else []
            ),
            *(
                ["hybrid recommendation currently runs without mem0 personalization"]
                if not mem0_write_allowed and hybrid.get("decision") == "hybrid_recommendations_ready_without_mem0"
                else []
            ),
        ]
    )
    packet_decision = (
        "mem0_local_write_read_canary_passed"
        if local_canary_passed and not hard_gates_remaining
        else "mem0_write_gate_packet_ready_report_only"
    )
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": packet_decision,
        "mem0_gate_path": str(mem0_gate_path),
        "graph_promotion_path": str(graph_promotion_path),
        "consumer_packet_path": str(consumer_packet_path),
        "hybrid_recommend_path": str(hybrid_recommend_path),
        "mem0_local_canary_path": str(mem0_local_canary_path),
        "auth_config_path": str(auth_config_path),
        "production_authorization": authorization,
        "mem0_write_allowed": mem0_write_allowed,
        "local_ready_gates": local_ready_gates,
        "local_ready_gate_count": sum(1 for value in local_ready_gates.values() if value),
        "hard_gates_remaining": hard_gates_remaining,
        "candidate_collections": collection_plan,
        "canary_write_plan": {
            "status": "passed" if local_canary_passed else "not_executed_write_gate_required",
            "batch_size": 50,
            "dedupe_key": "content_hash",
            "required_embedding_dim": 1024,
            "required_embedding_model": "Qwen/Qwen3-Embedding-4B",
            "target_table": "stage7_memories",
        },
        "local_canary_evidence": {
            "exists": bool(local_canary),
            "decision": local_canary.get("decision"),
            "ok": local_canary.get("ok"),
            "rows_written": local_canary.get("rows_written"),
            "query_self_hit": local_canary.get("query_self_hit"),
            "embedding_dim": local_canary.get("embedding_dim"),
            "writes": local_canary.get("writes"),
            "safety": local_canary_safety,
        },
        "downstream_readiness": {
            "graph_promotion_allowed": graph.get("promotion_allowed"),
            "consumer_hard_gates_remaining": len(consumer.get("hard_gates_remaining") or []),
            "hybrid_decision": hybrid.get("decision"),
            "hybrid_mem0_weight": (hybrid.get("weights") or {}).get("mem0"),
        },
        "forbidden_next_actions": [
            "do_not_call_cloud_mem0",
            "do_not_enable_consumer_mem0_personalization_without_prd17_gate",
            *(["do_not_create_or_alter_mem0_tables_from_this_packet"] if not local_canary_passed else []),
            *(["do_not_generate_mem0_embeddings"] if not local_canary_passed else []),
            *([] if mem0_write_allowed else ["do_not_insert_mem0_rows"]),
        ],
        "allowed_next_actions": [
            *(
                [
                    "use local mem0 write/read canary as PRD-10 evidence",
                    "keep consumer personalization and production rollout under PRD-17/PRD-08 gates",
                ]
                if local_canary_passed
                else [
                    "use candidate collections and schema as PRD-10/17 design evidence",
                    "build recommendation dry-run logic that keeps mem0 weight at 0",
                    "prepare a separate isolated mem0 write canary only after a write gate exists",
                ]
            ),
        ],
        "safety": {
            "reports_only": not local_canary_passed,
            "mem0_write_executed": local_canary_passed,
            "mem0_schema_mutation_executed": bool(local_canary_safety.get("mem0_schema_mutation_executed")),
            "embedding_call_executed": bool(local_canary_safety.get("embedding_call_executed")),
            "cloud_mem0_used": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "production_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "publish_executed": False,
        },
        "writes": "local_mem0_postgres" if local_canary_passed else "reports_only",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "mem0_write_gate_packet.json", packet)
    write_markdown(out_dir / "mem0_write_gate_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# mem0 Write Gate Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- mem0_write_allowed: `{packet['mem0_write_allowed']}`",
        f"- local_ready_gate_count: `{packet['local_ready_gate_count']}`",
        f"- local_mem0_canary_passed: `{packet['local_ready_gates'].get('local_mem0_canary_passed')}`",
        "",
        "## Local Ready Gates",
        "",
    ]
    for key, value in packet["local_ready_gates"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Hard Gates Remaining", ""])
    for item in packet["hard_gates_remaining"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Candidate Collections", ""])
    for row in packet["candidate_collections"]:
        lines.append(
            f"- `{row.get('name')}`: dim `{row.get('embedding_dim')}`, model `{row.get('embedding_model')}`, status `{row.get('write_status')}`"
        )
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mem0-gate", type=Path, default=DEFAULT_MEM0_GATE)
    parser.add_argument("--graph-promotion", type=Path, default=DEFAULT_GRAPH_PROMOTION)
    parser.add_argument("--consumer-packet", type=Path, default=DEFAULT_CONSUMER_PACKET)
    parser.add_argument("--hybrid-recommend", type=Path, default=DEFAULT_HYBRID_RECOMMEND)
    parser.add_argument("--mem0-local-canary", type=Path, default=DEFAULT_MEM0_LOCAL_CANARY)
    parser.add_argument("--auth-config", type=Path, default=DEFAULT_AUTH_CONFIG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(
        mem0_gate_path=args.mem0_gate,
        graph_promotion_path=args.graph_promotion,
        consumer_packet_path=args.consumer_packet,
        hybrid_recommend_path=args.hybrid_recommend,
        out_dir=args.out_dir,
        auth_config_path=args.auth_config,
        mem0_local_canary_path=args.mem0_local_canary,
    )
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "mem0_write_allowed": packet["mem0_write_allowed"],
                "local_ready_gate_count": packet["local_ready_gate_count"],
                "hard_gates_remaining": len(packet["hard_gates_remaining"]),
                "summary": str(args.out_dir / "mem0_write_gate_packet.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
