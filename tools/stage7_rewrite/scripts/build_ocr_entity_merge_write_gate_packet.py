#!/usr/bin/env python3
"""Build a report-only PRD-13 OCR entity Neo4j write gate packet.

This packet consumes the verified OCR entity extraction and dry-run merge plan.
It performs only local Neo4j read checks and never applies MERGE/SET/REMOVE.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_ENTITY_EXTRACTION = Path(
    "reports/dajiala_paid_wave01_07_verified_ocr_entity_extraction_20260518/ocr_entity_extraction_summary.json"
)
DEFAULT_MERGE_REPORT = Path(
    "reports/dajiala_paid_wave01_07_verified_ocr_entity_merge_plan_20260518/ocr_entity_merge_report.json"
)
DEFAULT_GRAPH_PROMOTION = Path("reports/graph_promotion_readiness_refresh_20260516/graph_promotion_readiness.json")
DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_OUT_DIR = Path("reports/ocr_entity_merge_write_gate_packet_wave01_07_20260518")
DEFAULT_AUTH_CONFIG = Path("config/consumer_publish_gate.local.json")
DEFAULT_REVIEW_PACKET = Path(
    "reports/dajiala_paid_wave01_07_verified_ocr_entity_merge_review_packet_20260518/ocr_entity_merge_review_packet.json"
)
DEFAULT_STAGING_REPORT = Path(
    "reports/dajiala_paid_wave01_07_verified_ocr_entity_merge_20260518/ocr_entity_merge_report.json"
)
SCHEMA_VERSION = "stage7_ocr_entity_merge_write_gate_packet.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for OCR entity write gate packet: {path}")


def require_local_neo4j(uri: str) -> None:
    parsed = urlparse(uri)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError(f"Neo4j URI must be local for OCR entity write gate checks: {uri}")


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


def neo4j_read_state(neo4j_uri: str, database: str, run_id: str) -> dict[str, Any]:
    require_local_neo4j(neo4j_uri)
    state = {
        "uri": neo4j_uri,
        "database": database,
        "read_ok": False,
        "run_id": run_id,
        "staging_ocr_poster_entities": None,
        "all_ocr_poster_entities_with_run_id": None,
        "error": "",
    }
    statements = [
        {
            "statement": "MATCH (n:Stage7Staging:OcrPosterEntity {run_id:$run_id}) RETURN count(n)",
            "parameters": {"run_id": run_id},
        },
        {
            "statement": "MATCH (n:OcrPosterEntity {run_id:$run_id}) RETURN count(n)",
            "parameters": {"run_id": run_id},
        },
    ]
    try:
        response = requests.post(
            f"{neo4j_uri.rstrip('/')}/db/{database}/tx/commit",
            json={"statements": statements},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errors"):
            raise RuntimeError(json.dumps(payload["errors"][:3], ensure_ascii=False))
        values = []
        for result in payload.get("results") or []:
            data = result.get("data") or []
            values.append(int(((data[0].get("row") if data else [0]) or [0])[0] or 0))
        state["read_ok"] = True
        state["staging_ocr_poster_entities"] = values[0] if values else 0
        state["all_ocr_poster_entities_with_run_id"] = values[1] if len(values) > 1 else 0
    except Exception as exc:  # pragma: no cover - integration path.
        state["error"] = str(exc)[:500]
    return state


def build_packet(
    *,
    entity_extraction_path: Path,
    merge_report_path: Path,
    graph_promotion_path: Path,
    neo4j_uri: str,
    database: str,
    out_dir: Path,
    auth_config_path: Path = DEFAULT_AUTH_CONFIG,
    review_packet_path: Path = DEFAULT_REVIEW_PACKET,
    staging_report_path: Path = DEFAULT_STAGING_REPORT,
    neo4j_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    extraction = read_json(entity_extraction_path)
    merge = read_json(merge_report_path)
    review = read_json(review_packet_path)
    staging = read_json(staging_report_path)
    graph = read_json(graph_promotion_path)
    authorization = read_production_authorization(auth_config_path)
    neo4j_write_allowed = bool(authorization.get("neo4j_staging_write_allowed"))
    production_label_write_allowed = bool(authorization.get("production_graph_labels_allowed"))
    run_id = str(merge.get("run_id") or "")
    state = neo4j_state if neo4j_state is not None else neo4j_read_state(neo4j_uri, database, run_id)
    plan_path = Path(str(merge.get("plan_path") or ""))
    if not plan_path.is_absolute():
        plan_path = Path.cwd() / plan_path
    would_merge = int(merge.get("would_merge_entities") or 0)
    entities_seen = int(merge.get("entities_seen") or 0)
    review_accepted = (
        review.get("decision") == "ocr_entity_merge_review_accepted_for_staging"
        and bool(review.get("ok"))
        and str(review.get("run_id") or "") == run_id
        and int(review.get("accepted_plan_rows") or 0) == would_merge
        and not (review.get("blockers") or [])
    )
    staging_verification = staging.get("verification") or {}
    staging_counts = staging_verification.get("counts") or {}
    staging_written = (
        staging.get("decision") == "ocr_entity_merge_staging_written"
        and bool(staging.get("mutation_executed"))
        and str(staging.get("run_id") or "") == run_id
        and int(staging.get("nodes_written") or 0) == would_merge
        and bool(staging_verification.get("ok"))
        and int(staging_counts.get("staging_ocr_poster_entities") or 0) == would_merge
        and int(staging_counts.get("non_staging_only_nodes") or 0) == 0
    )
    local_ready_gates = {
        "entity_extraction_ready": extraction.get("decision") == "ocr_entity_extraction_ready",
        "entity_gate_met": bool(extraction.get("gate_met")),
        "merge_dry_run_ready": merge.get("decision") == "ocr_entity_merge_dry_run_ready",
        "would_merge_nonzero": would_merge > 0,
        "mutation_not_executed": not bool(merge.get("mutation_executed")),
        "plan_file_exists": plan_path.exists(),
        "neo4j_read_ok": bool(state.get("read_ok")),
        "staging_only_safety_present": "staging_only" in (merge.get("safety") or []),
        "review_accepted": review_accepted,
        "staging_apply_written": staging_written,
    }
    hard_gates_remaining = unique_nonempty(
        [
            *(
                ["NEO4J_OCR_ENTITY_STAGING_WRITE confirm token is required before apply"]
                if not neo4j_write_allowed
                else []
            ),
            *(["NEO4J_WRITE is forbidden for this run"] if not neo4j_write_allowed else []),
            *(["production graph labels are forbidden for this run"] if not production_label_write_allowed else []),
            *(["OCR entity merge plan requires review before apply"] if not review_accepted else []),
            *(
                ["Neo4j read check failed"]
                if not local_ready_gates["neo4j_read_ok"]
                else []
            ),
            *(
                ["PRD-07 graph promotion is blocked"]
                if not bool(graph.get("promotion_allowed"))
                else []
            ),
        ]
    )
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": "ocr_entity_merge_staging_written" if staging_written else "ocr_entity_merge_write_gate_packet_ready_report_only",
        "entity_extraction_path": str(entity_extraction_path),
        "merge_report_path": str(merge_report_path),
        "review_packet_path": str(review_packet_path),
        "staging_report_path": str(staging_report_path),
        "graph_promotion_path": str(graph_promotion_path),
        "auth_config_path": str(auth_config_path),
        "production_authorization": authorization,
        "neo4j_uri": neo4j_uri,
        "database": database,
        "run_id": run_id,
        "entities_seen": entities_seen,
        "would_merge_entities": would_merge,
        "skipped": merge.get("skipped") or {},
        "entity_type_counts": merge.get("entity_type_counts") or {},
        "neo4j_read_state": state,
        "review_evidence": {
            "decision": review.get("decision"),
            "ok": review.get("ok"),
            "accepted_plan_rows": review.get("accepted_plan_rows"),
            "blockers": review.get("blockers") or [],
            "review_accepted": review_accepted,
        },
        "staging_apply_evidence": {
            "decision": staging.get("decision"),
            "mutation_executed": staging.get("mutation_executed"),
            "nodes_written": staging.get("nodes_written"),
            "verification": staging_verification,
            "staging_written": staging_written,
        },
        "neo4j_write_allowed": neo4j_write_allowed,
        "production_label_write_allowed": production_label_write_allowed,
        "local_ready_gates": local_ready_gates,
        "local_ready_gate_count": sum(1 for value in local_ready_gates.values() if value),
        "hard_gates_remaining": hard_gates_remaining,
        "rollback_command": merge.get("rollback_command"),
        "forbidden_next_actions": [
            "do_not_write_qdrant_or_mem0_from_this_packet",
            "do_not_treat_ocr_entities_as_reviewed_graph_facts",
            *([] if neo4j_write_allowed else ["do_not_apply_ocr_entity_merge_from_this_packet"]),
            *([] if production_label_write_allowed else ["do_not_set_production_labels_from_this_packet"]),
        ],
        "allowed_next_actions": [
            "use merge plan as PRD-13 review input",
            "prepare a separate staging write canary only after the Neo4j write gate exists",
            "keep rollback command with the merge report for future gated apply",
        ],
        "safety": {
            "reports_only": True,
            "neo4j_read_only_check": True,
            "neo4j_write_executed": staging_written,
            "production_label_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "paid_api_used": False,
            "d_scan_executed": False,
            "publish_executed": False,
        },
        "writes": "local_neo4j_ocr_staging" if staging_written else "reports_only",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "ocr_entity_merge_write_gate_packet.json", packet)
    write_markdown(out_dir / "ocr_entity_merge_write_gate_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# OCR Entity Merge Write Gate Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- run_id: `{packet['run_id']}`",
        f"- entities_seen: `{packet['entities_seen']}`",
        f"- would_merge_entities: `{packet['would_merge_entities']}`",
        f"- neo4j_write_allowed: `{packet['neo4j_write_allowed']}`",
        f"- local_ready_gate_count: `{packet['local_ready_gate_count']}`",
        "",
        "## Hard Gates Remaining",
        "",
    ]
    for item in packet["hard_gates_remaining"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Entity Types", ""])
    for key, value in sorted(packet["entity_type_counts"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--entity-extraction", type=Path, default=DEFAULT_ENTITY_EXTRACTION)
    parser.add_argument("--merge-report", type=Path, default=DEFAULT_MERGE_REPORT)
    parser.add_argument("--graph-promotion", type=Path, default=DEFAULT_GRAPH_PROMOTION)
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--database", default="neo4j")
    parser.add_argument("--auth-config", type=Path, default=DEFAULT_AUTH_CONFIG)
    parser.add_argument("--review-packet", type=Path, default=DEFAULT_REVIEW_PACKET)
    parser.add_argument("--staging-report", type=Path, default=DEFAULT_STAGING_REPORT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(
        entity_extraction_path=args.entity_extraction,
        merge_report_path=args.merge_report,
        graph_promotion_path=args.graph_promotion,
        neo4j_uri=args.neo4j_uri,
        database=args.database,
        out_dir=args.out_dir,
        auth_config_path=args.auth_config,
        review_packet_path=args.review_packet,
        staging_report_path=args.staging_report,
    )
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "would_merge_entities": packet["would_merge_entities"],
                "local_ready_gate_count": packet["local_ready_gate_count"],
                "hard_gates_remaining": len(packet["hard_gates_remaining"]),
                "summary": str(args.out_dir / "ocr_entity_merge_write_gate_packet.json"),
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
