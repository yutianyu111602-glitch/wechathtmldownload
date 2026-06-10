#!/usr/bin/env python3
"""Build a report-only Neo4j staging gate packet for accepted identity edges.

This script converts already accepted PRD-02/PRD-16 identity rows into the
HAS_PROFILE manifest accepted by neo4j_p1_social_staging_writer.py, then runs
that writer in dry-run mode. It does not write Neo4j, Qdrant, mem0, SQLite, or
production publish state.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_STRICT_SOCIAL = Path(
    "reports/social_identity_strict_acceptance_review_20260517/accepted_social_edges_strict.jsonl"
)
DEFAULT_CDCR_STRICT = Path(
    "reports/cdcr_strict_acceptance_review_20260517/accepted_cdcr_graph_edges_strict.jsonl"
)
DEFAULT_OUT_DIR = Path("reports/identity_neo4j_staging_gate_packet_20260517")
DEFAULT_AUTH_CONFIG = Path("config/consumer_publish_gate.local.json")
DEFAULT_RUN_ID = "stage7_identity_acceptance_20260517"
SCHEMA_VERSION = "stage7_identity_neo4j_staging_gate_packet.v1"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").lower()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for identity Neo4j staging gate: {path}")


def first_text(value: Any) -> str:
    return str(value or "").strip()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def read_json_file(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def read_production_authorization(path: Path) -> dict[str, Any]:
    return read_json_file(path).get("production_authorization") or {}


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


def stable_edge_id(scope: str, subject: str, object_url: str, source_row_id: str) -> str:
    raw = "\x1f".join([scope, subject.casefold(), object_url.casefold(), source_row_id])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    return f"stage7_identity_{scope}_{digest}"


def infer_source_family(row: dict[str, Any], *, fallback: str) -> str:
    explicit = first_text(row.get("source_family"))
    if explicit:
        return explicit.casefold()
    haystack = " ".join(
        [
            first_text(row.get("evidence_url")),
            first_text(row.get("object_url")),
            first_text(row.get("primary_profile_url")),
            " ".join(first_text(item) for item in (row.get("source_urls") or []) if item),
        ]
    ).casefold()
    if "byyb.live" in haystack:
        return "byyb"
    if "slowthrecords.com" in haystack or "cdcr" in haystack:
        return "cdcr"
    if "baihui" in haystack:
        return "baihui"
    return fallback


def writer_valid_edge(edge: dict[str, Any]) -> bool:
    return (
        first_text(edge.get("review_status")) == "accepted_for_staging"
        and bool(edge.get("staging_only"))
        and first_text(edge.get("edge_type")) == "HAS_PROFILE"
        and bool(first_text(edge.get("subject_name")))
        and bool(first_text(edge.get("object_url")))
    )


def convert_social_row(row: dict[str, Any]) -> dict[str, Any] | None:
    subject = first_text(row.get("subject_name"))
    object_url = first_text(row.get("object_url"))
    if not subject or not object_url or first_text(row.get("review_status")) != "accepted_for_staging":
        return None
    scope = "strict_prd16"
    source_row_id = first_text(row.get("source_row_id"))
    return {
        "schema_version": SCHEMA_VERSION + ".edge_row",
        "source_scope": scope,
        "source_row_id": source_row_id,
        "source_candidate_id": first_text(row.get("acceptance_gate_id")),
        "source_edge_id": source_row_id,
        "edge_id": stable_edge_id(scope, subject, object_url, source_row_id),
        "edge_type": "HAS_PROFILE",
        "subject_name": subject,
        "source_family": infer_source_family(row, fallback="social_identity"),
        "object_url": object_url,
        "object_platform": first_text(row.get("object_platform")),
        "evidence_url": first_text(row.get("evidence_url")),
        "confidence": float(row.get("confidence") or 0.95),
        "proof_tier": first_text(row.get("proof_tier")),
        "review_status": "accepted_for_staging",
        "review_reason": first_text(row.get("review_reason")),
        "staging_only": True,
        "write_allowed": False,
        "rollback_key": first_text(row.get("rollback_key")),
    }


def convert_cdcr_row(row: dict[str, Any]) -> dict[str, Any] | None:
    subject = first_text(row.get("subject_name"))
    object_url = first_text(row.get("primary_profile_url"))
    if not subject or not object_url or first_text(row.get("review_status")) != "accepted_for_staging":
        return None
    scope = "cdcr_strict"
    source_row_id = first_text(row.get("acceptance_gate_id")) or subject
    return {
        "schema_version": SCHEMA_VERSION + ".edge_row",
        "source_scope": scope,
        "source_row_id": source_row_id,
        "source_candidate_id": first_text(row.get("acceptance_gate_id")),
        "source_edge_id": stable_edge_id(scope, subject, object_url, source_row_id),
        "edge_id": stable_edge_id(scope, subject, object_url, source_row_id),
        "edge_type": "HAS_PROFILE",
        "subject_name": subject,
        "source_family": infer_source_family(row, fallback="cdcr"),
        "object_url": object_url,
        "object_platform": first_text(row.get("primary_profile_source_type")) or "direct_profile",
        "evidence_url": object_url,
        "confidence": float(row.get("confidence") or 0.92),
        "proof_tier": first_text(row.get("proof_tier")),
        "review_status": "accepted_for_staging",
        "review_reason": first_text(row.get("review_reason")),
        "staging_only": True,
        "write_allowed": False,
        "rollback_key": first_text(row.get("rollback_key")),
    }


def load_staging_writer():
    writer_path = Path(__file__).resolve().with_name("neo4j_p1_social_staging_writer.py")
    spec = importlib.util.spec_from_file_location("neo4j_p1_social_staging_writer", writer_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load Neo4j staging writer from {writer_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_writer_dry_run(*, manifest_path: Path, out_dir: Path, run_id: str) -> dict[str, Any]:
    writer = load_staging_writer()
    args = writer.parse_args(
        [
            "--mode",
            "dry-run",
            "--accepted-edges",
            str(manifest_path),
            "--out-dir",
            str(out_dir),
            "--run-id",
            run_id,
        ]
    )
    return writer.run(args)


def build_packet(
    *,
    strict_social_path: Path,
    cdcr_strict_path: Path,
    out_dir: Path,
    run_id: str = DEFAULT_RUN_ID,
    execute_writer_dry_run: bool = True,
    auth_config_path: Path = DEFAULT_AUTH_CONFIG,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    authorization = read_production_authorization(auth_config_path)
    neo4j_staging_write_allowed = bool(authorization.get("neo4j_staging_write_allowed"))
    production_label_write_allowed = bool(authorization.get("production_graph_labels_allowed"))
    production_publish_allowed = bool(authorization.get("production_publish_allowed"))
    social_rows = read_jsonl(strict_social_path)
    cdcr_rows = read_jsonl(cdcr_strict_path)
    converted_rows = [
        row
        for row in [*(convert_social_row(row) for row in social_rows), *(convert_cdcr_row(row) for row in cdcr_rows)]
        if row is not None
    ]
    writer_valid_rows = [row for row in converted_rows if writer_valid_edge(row)]
    edge_counts_by_scope = Counter(first_text(row.get("source_scope")) for row in converted_rows)
    edge_counts_by_family = Counter(first_text(row.get("source_family")) for row in converted_rows)
    edge_counts_by_platform = Counter(first_text(row.get("object_platform")) for row in converted_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "accepted_identity_edges_for_neo4j_staging.jsonl"
    write_jsonl(manifest_path, converted_rows)

    writer_out_dir = out_dir / "neo4j_writer_dry_run"
    writer_report: dict[str, Any] = {}
    if execute_writer_dry_run:
        writer_report = run_writer_dry_run(manifest_path=manifest_path, out_dir=writer_out_dir, run_id=run_id)

    writer_report_path = writer_out_dir / "neo4j_p1_social_staging_report.json"
    writer_canary_out_dir = out_dir / "neo4j_writer_canary"
    writer_canary_report_path = writer_canary_out_dir / "neo4j_p1_social_staging_report.json"
    writer_canary_report = read_json_file(writer_canary_report_path)
    writer_would_write = int(writer_report.get("would_write_edges") or 0)
    writer_canary_would_write = int(writer_canary_report.get("would_write_edges") or 0)
    canary_mutation_executed = bool(writer_canary_report.get("mutation_executed"))
    no_mutation = not bool(writer_report.get("mutation_executed"))
    local_ready_gates = {
        "accepted_identity_rows_present": len(social_rows) + len(cdcr_rows) > 0,
        "all_input_rows_converted": len(converted_rows) == len(social_rows) + len(cdcr_rows),
        "all_converted_edges_writer_valid": len(writer_valid_rows) == len(converted_rows),
        "manifest_written": manifest_path.exists(),
        "writer_dry_run_report_created": bool(writer_report) and writer_report_path.exists(),
        "writer_dry_run_matches_manifest": bool(writer_report) and writer_would_write == len(writer_valid_rows),
        "no_mutation_executed": bool(writer_report) and no_mutation,
        "staging_only_rows": all(bool(row.get("staging_only")) for row in converted_rows),
        "rollback_metadata_present": all(first_text(row.get("rollback_key")) and first_text(row.get("edge_id")) for row in converted_rows),
    }
    packet_ready = bool(converted_rows) and all(local_ready_gates.values())
    hard_gates_remaining = [
        *(
            ["Neo4j staging write requires --confirm-token ENABLE_NEO4J_P1_SOCIAL_STAGING_WRITE"]
            if not neo4j_staging_write_allowed
            else []
        ),
        *(["Neo4j staging write remains forbidden in this longrun slice"] if not neo4j_staging_write_allowed else []),
        *(["production graph labels are forbidden for this run"] if not production_label_write_allowed else []),
        *(["consumer production publish gate is blocked"] if not production_publish_allowed else []),
    ]
    packet = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "ok": True,
        "decision": (
            "identity_neo4j_staging_canary_written"
            if packet_ready and canary_mutation_executed
            else
            "identity_neo4j_staging_gate_packet_ready_report_only"
            if packet_ready
            else "identity_neo4j_staging_gate_packet_incomplete_report_only"
        ),
        "run_id": run_id,
        "strict_social_path": str(strict_social_path),
        "cdcr_strict_path": str(cdcr_strict_path),
        "auth_config_path": str(auth_config_path),
        "production_authorization": authorization,
        "neo4j_staging_write_allowed": neo4j_staging_write_allowed,
        "production_label_write_allowed": production_label_write_allowed,
        "manifest_path": str(manifest_path),
        "writer_dry_run_out_dir": str(writer_out_dir),
        "writer_dry_run_report_path": str(writer_report_path),
        "writer_canary_out_dir": str(writer_canary_out_dir),
        "writer_canary_report_path": str(writer_canary_report_path),
        "input_rows_total": len(social_rows) + len(cdcr_rows),
        "input_rows_by_scope": {
            "strict_prd16": len(social_rows),
            "cdcr_strict": len(cdcr_rows),
        },
        "converted_edges": len(converted_rows),
        "writer_valid_edges": len(writer_valid_rows),
        "writer_would_write_edges": writer_would_write,
        "writer_canary_would_write_edges": writer_canary_would_write,
        "neo4j_staging_canary_executed": canary_mutation_executed,
        "writer_canary_report": {
            "mode": writer_canary_report.get("mode"),
            "edges_seen": writer_canary_report.get("edges_seen"),
            "would_write_edges": writer_canary_report.get("would_write_edges"),
            "mutation_executed": writer_canary_report.get("mutation_executed"),
            "report_path": str(writer_canary_report_path) if writer_canary_report else "",
        },
        "edge_counts_by_scope": dict(edge_counts_by_scope),
        "edge_counts_by_family": dict(edge_counts_by_family),
        "edge_counts_by_platform": dict(edge_counts_by_platform),
        "accepted_subjects": sorted({first_text(row.get("subject_name")) for row in converted_rows if row.get("subject_name")}),
        "local_ready_gates": local_ready_gates,
        "local_ready_gate_count": sum(1 for value in local_ready_gates.values() if value),
        "hard_gates_remaining": hard_gates_remaining,
        "writer_dry_run_command": (
            "python scripts\\neo4j_p1_social_staging_writer.py --mode dry-run "
            f"--accepted-edges {manifest_path} --out-dir {writer_out_dir} --run-id {run_id}"
        ),
        "mutation_command_requires_confirm_token": (
            "python scripts\\neo4j_p1_social_staging_writer.py --mode canary "
            f"--accepted-edges {manifest_path} --out-dir {writer_out_dir} --run-id {run_id} "
            "--confirm-token ENABLE_NEO4J_P1_SOCIAL_STAGING_WRITE"
        ),
        "safety": {
            "reports_only": not canary_mutation_executed,
            "writer_mode": "canary" if canary_mutation_executed else "dry-run" if writer_report else "not_run",
            "neo4j_write_executed": canary_mutation_executed,
            "production_label_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "sqlite_write_executed": False,
            "paid_api_used": False,
            "network_calls": False,
            "d_scan_executed": False,
            "publish_executed": False,
        },
        "writes": "staging_only_neo4j_canary" if canary_mutation_executed else "reports_only",
    }
    write_json(out_dir / "identity_neo4j_staging_gate_packet.json", packet)
    write_markdown(out_dir / "identity_neo4j_staging_gate_packet.md", packet)
    return packet


def write_markdown(path: Path, packet: dict[str, Any]) -> None:
    lines = [
        "# Identity Neo4j Staging Gate Packet",
        "",
        f"- generated_at: `{packet['generated_at']}`",
        f"- decision: `{packet['decision']}`",
        f"- input_rows_total: `{packet['input_rows_total']}`",
        f"- converted_edges: `{packet['converted_edges']}`",
        f"- writer_valid_edges: `{packet['writer_valid_edges']}`",
        f"- writer_would_write_edges: `{packet['writer_would_write_edges']}`",
        f"- neo4j_staging_canary_executed: `{packet['neo4j_staging_canary_executed']}`",
        f"- manifest_path: `{packet['manifest_path']}`",
        f"- writer_dry_run_report_path: `{packet['writer_dry_run_report_path']}`",
        f"- writer_canary_report_path: `{packet['writer_canary_report_path']}`",
        "",
        "## Hard Gates Remaining",
        "",
    ]
    lines.extend(f"- {item}" for item in packet["hard_gates_remaining"])
    lines.extend(["", "## Local Ready Gates", ""])
    for key, value in sorted(packet["local_ready_gates"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Edge Counts By Scope", ""])
    for key, value in sorted(packet["edge_counts_by_scope"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(packet["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-social", type=Path, default=DEFAULT_STRICT_SOCIAL)
    parser.add_argument("--cdcr-strict", type=Path, default=DEFAULT_CDCR_STRICT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--auth-config", type=Path, default=DEFAULT_AUTH_CONFIG)
    parser.add_argument("--skip-writer-dry-run", action="store_true")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    packet = build_packet(
        strict_social_path=args.strict_social,
        cdcr_strict_path=args.cdcr_strict,
        out_dir=args.out_dir,
        run_id=args.run_id,
        execute_writer_dry_run=not args.skip_writer_dry_run,
        auth_config_path=args.auth_config,
    )
    print(
        json.dumps(
            {
                "ok": packet["ok"],
                "decision": packet["decision"],
                "input_rows_total": packet["input_rows_total"],
                "converted_edges": packet["converted_edges"],
                "writer_valid_edges": packet["writer_valid_edges"],
                "writer_would_write_edges": packet["writer_would_write_edges"],
                "summary": str(args.out_dir / "identity_neo4j_staging_gate_packet.json"),
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
