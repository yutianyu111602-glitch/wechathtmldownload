#!/usr/bin/env python3
"""Build a report-only graph/write gate packet for the YYYY identity row.

This gate consumes the YYYY identity acceptance ready row and converts it into
a staging-only HAS_PROFILE manifest that the existing Neo4j staging writer can
validate in dry-run mode. It does not mutate Neo4j, Qdrant, SQLite, mem0, or
any public serving pointer.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_YYYY_READY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_yyyy_identity_acceptance_q6_20260525"
    / "atlas_social_yyyy_identity_acceptance_ready.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_yyyy_graph_write_gate_q6_20260525"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_YYYY_GRAPH_WRITE_GATE_PACKET_20260525.md"
DEFAULT_RUN_ID = "atlas_q6_yyyy_social_graph_write_gate_20260525"
SCHEMA_VERSION = "stage7_atlas_social_yyyy_graph_write_gate.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for YYYY graph/write gate: {path}")


def host_of(url: str) -> str:
    host = parse.urlparse(compact(url)).netloc.casefold()
    return host[4:] if host.startswith("www.") else host


def public_soundcloud_url(url: str) -> bool:
    parsed = parse.urlparse(compact(url))
    return parsed.scheme == "https" and host_of(url) == "soundcloud.com" and bool(parsed.path.strip("/"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "yyyy_ready")
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
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


def stable_edge_id(row: dict[str, Any]) -> str:
    raw = "\x1f".join(
        [
            "atlas_q6_yyyy_social_graph",
            compact(row.get("entity_search_id")).casefold(),
            compact(row.get("name")).casefold(),
            compact(row.get("target_url")).casefold(),
        ]
    )
    return "atlas_q6_yyyy_social_profile_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def graph_requirement_failures(row: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if row.get("identity_acceptance_passed") is not True:
        failures.append("identity_acceptance_passed_not_true")
    if compact(row.get("identity_acceptance_decision")) != "identity_candidate_accepted_for_staging_review":
        failures.append("identity_acceptance_decision_not_staging_review")
    if compact(row.get("rendered_evidence_decision")) != "rendered_profile_evidence_review_ready":
        failures.append("rendered_profile_evidence_not_review_ready")
    if not compact(row.get("entity_search_id")):
        failures.append("missing_entity_search_id")
    if not compact(row.get("name")):
        failures.append("missing_name")
    if int(row.get("exact_event_count") or 0) <= 0:
        failures.append("missing_exact_atlas_event_context")
    if int(row.get("exact_source_article_count") or 0) <= 0:
        failures.append("missing_exact_atlas_source_article_context")
    target_url = compact(row.get("target_url"))
    if not public_soundcloud_url(target_url):
        failures.append("target_url_not_public_https_soundcloud_profile")
    image_ref = compact(row.get("profile_image_url_or_hash"))
    if not image_ref.startswith("sha256:"):
        failures.append("profile_image_reference_not_hash")
    signals = row.get("signals") if isinstance(row.get("signals"), dict) else {}
    for key in [
        "manual_source_context_accepted",
        "exact_atlas_event_context_present",
        "exact_atlas_source_context_present",
        "canonical_or_final_url_matches_candidate",
        "rendered_profile_metadata_present",
        "subject_in_rendered_public_profile",
        "profile_image_hash_present",
        "previous_product_truth_not_promoted",
    ]:
        if signals.get(key) is not True:
            failures.append(f"signal_{key}_not_true")
    if row.get("accepted_for_graph") is True:
        failures.append("input_already_claims_graph_acceptance")
    if row.get("graph_write_allowed") is True:
        failures.append("input_already_claims_graph_write_allowed")
    if row.get("identity_proof_promoted") is True:
        failures.append("input_already_claims_identity_proof_promoted")
    if row.get("avatar_display_allowed") is True:
        failures.append("input_already_claims_avatar_display_allowed")
    if row.get("public_serving_field_allowed") is True:
        failures.append("input_already_claims_public_serving_field_allowed")
    return failures


def edge_row(row: dict[str, Any], generated_at: str) -> dict[str, Any]:
    subject = compact(row.get("name"))
    target_url = compact(row.get("target_url"))
    entity_id = compact(row.get("entity_search_id"))
    edge_id = stable_edge_id(row)
    return {
        "schema_version": SCHEMA_VERSION + ".edge_row",
        "generated_at": generated_at,
        "source_scope": "atlas_q6_yyyy_identity_acceptance",
        "source_row_id": entity_id,
        "source_candidate_id": f"atlas_q6_yyyy:{entity_id}",
        "source_edge_id": edge_id,
        "edge_id": edge_id,
        "edge_type": "HAS_PROFILE",
        "subject_name": subject,
        "source_family": "atlas_q6_yyyy_soundcloud",
        "object_url": target_url,
        "object_platform": "soundcloud",
        "evidence_url": target_url,
        "confidence": 0.86,
        "proof_tier": "yyyy_identity_acceptance_rendered_public_profile_staging",
        "review_status": "accepted_for_staging",
        "review_reason": "YYYY has exact Atlas source context plus rendered public SoundCloud profile evidence; staging-only dry-run gate.",
        "staging_only": True,
        "write_allowed": False,
        "rollback_key": f"atlas_q6_yyyy_social_graph:{entity_id}:{edge_id}",
        "atlas_dj_id": "",
        "atlas_display_name": subject,
        "atlas_event_count": int(row.get("exact_event_count") or 0),
        "atlas_source_article_count": int(row.get("exact_source_article_count") or 0),
        "profile_image_hash": compact(row.get("profile_image_url_or_hash")),
        "identity_proof_promoted": False,
        "avatar_display_allowed": False,
        "public_serving_field_allowed": False,
        "production_graph_label_allowed": False,
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


def build_gate(
    *,
    yyyy_ready_path: Path,
    out_dir: Path,
    report_path: Path,
    run_id: str = DEFAULT_RUN_ID,
    execute_writer_dry_run: bool = True,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report_path, "report_path")
    generated_at = now_iso()
    source_rows = read_jsonl(yyyy_ready_path)
    reviewed_rows: list[dict[str, Any]] = []
    edge_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    for row in source_rows:
        failures = graph_requirement_failures(row)
        reviewed = {
            "schema_version": SCHEMA_VERSION + ".review_row",
            "generated_at": generated_at,
            "entity_search_id": compact(row.get("entity_search_id")),
            "name": compact(row.get("name")),
            "target_url": compact(row.get("target_url")),
            "graph_gate_status": "ready_for_staging_writer_dry_run" if not failures else "blocked",
            "graph_requirement_failures": failures,
            "accepted_for_staging_manifest": not failures,
            "accepted_for_graph": False,
            "identity_proof_promoted": False,
            "avatar_display_allowed": False,
            "public_serving_field_allowed": False,
            "graph_write_allowed": False,
            "neo4j_staging_writer_dry_run_allowed": not failures,
        }
        reviewed_rows.append(reviewed)
        if failures:
            blocked_rows.append(reviewed)
        else:
            edge_rows.append(edge_row(row, generated_at))

    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "atlas_social_yyyy_graph_write_gate_review.jsonl"
    manifest_path = out_dir / "atlas_social_yyyy_identity_edges_for_neo4j_staging.jsonl"
    blocked_path = out_dir / "atlas_social_yyyy_graph_write_gate_blocked.jsonl"
    summary_path = out_dir / "atlas_social_yyyy_graph_write_gate_summary.json"
    write_jsonl(review_path, reviewed_rows)
    write_jsonl(manifest_path, edge_rows)
    write_jsonl(blocked_path, blocked_rows)

    writer_out_dir = out_dir / "neo4j_writer_dry_run"
    writer_report: dict[str, Any] = {}
    if execute_writer_dry_run:
        writer_report = run_writer_dry_run(manifest_path=manifest_path, out_dir=writer_out_dir, run_id=run_id)
    writer_report_path = writer_out_dir / "neo4j_p1_social_staging_report.json"
    writer_would_write = int(writer_report.get("would_write_edges") or 0)
    no_mutation = bool(writer_report) and not bool(writer_report.get("mutation_executed"))
    writer_canary_out_dir = out_dir / "neo4j_writer_canary"
    writer_canary_report_path = writer_canary_out_dir / "neo4j_p1_social_staging_report.json"
    canary_verification_path = writer_canary_out_dir / "canary_verification.json"
    writer_canary_report = read_json(writer_canary_report_path)
    canary_verification = read_json(canary_verification_path)
    canary_mutation_executed = bool(writer_canary_report.get("mutation_executed"))
    canary_edges_written = int(writer_canary_report.get("edges_written") or 0)
    canary_verification_ok = bool(canary_verification.get("ok"))
    rollback_command = (
        writer_canary_report.get("rollback_command")
        or writer_report.get("rollback_command")
        or (
            "python scripts\\neo4j_p1_social_staging_writer.py --mode rollback "
            f"--run-id {run_id} --confirm-token ENABLE_NEO4J_P1_SOCIAL_STAGING_WRITE"
        )
    )
    status_counts = Counter(row["graph_gate_status"] for row in reviewed_rows)
    edge_counts_by_platform = Counter(row["object_platform"] for row in edge_rows)
    local_ready_gates = {
        "source_rows_present": bool(source_rows),
        "no_blocked_rows": bool(source_rows) and not blocked_rows,
        "manifest_rows_present": bool(edge_rows),
        "review_file_written": review_path.exists(),
        "manifest_written": manifest_path.exists(),
        "all_manifest_rows_staging_only": all(bool(row.get("staging_only")) for row in edge_rows),
        "rollback_metadata_present": all(compact(row.get("rollback_key")) and compact(row.get("edge_id")) for row in edge_rows),
        "writer_dry_run_report_created": bool(writer_report) and writer_report_path.exists(),
        "writer_dry_run_matches_manifest": bool(writer_report) and writer_would_write == len(edge_rows),
        "no_mutation_executed": no_mutation,
    }
    ready = bool(edge_rows) and all(local_ready_gates.values())
    if ready and canary_mutation_executed and canary_verification_ok:
        decision = "atlas_social_yyyy_graph_write_gate_canary_written_verified"
    elif ready and canary_mutation_executed:
        decision = "atlas_social_yyyy_graph_write_gate_canary_written_unverified"
    elif ready:
        decision = "atlas_social_yyyy_graph_write_gate_ready_report_only"
    else:
        decision = "atlas_social_yyyy_graph_write_gate_incomplete_report_only"
    if canary_mutation_executed and canary_verification_ok:
        hard_gates_remaining = [
            "Staging-only Neo4j canary is written and verified; production graph labels remain a separate PRD-07/T5 gate.",
            "No Qdrant alias, SQLite serving pointer, avatar display, public serving field, public pointer, or memory write is authorized by this packet.",
            "Identity proof is not promoted; YYYY remains staging evidence until a separate product-truth promotion gate.",
            "Rollback command is recorded and must be used if the staging canary is superseded or rejected.",
        ]
    else:
        hard_gates_remaining = [
            "This packet allows only staging-only Neo4j writer dry-run evidence.",
            "Neo4j staging mutation requires a separate confirmed canary run plus post-write verification and rollback evidence.",
            "No production graph labels, Qdrant alias, SQLite serving pointer, avatar display, public serving field, public pointer, or memory write is authorized by this packet.",
            "Identity proof is not promoted; YYYY remains staging evidence until a separate product-truth promotion gate.",
        ]
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": decision,
        "run_id": run_id,
        "yyyy_ready_path": str(yyyy_ready_path),
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "review_path": str(review_path),
        "manifest_path": str(manifest_path),
        "blocked_path": str(blocked_path),
        "writer_dry_run_out_dir": str(writer_out_dir),
        "writer_dry_run_report_path": str(writer_report_path),
        "writer_canary_out_dir": str(writer_canary_out_dir),
        "writer_canary_report_path": str(writer_canary_report_path),
        "canary_verification_report_path": str(canary_verification_path),
        "input_rows_total": len(source_rows),
        "graph_gate_ready_edges": len(edge_rows),
        "blocked_rows": len(blocked_rows),
        "writer_would_write_edges": writer_would_write,
        "neo4j_staging_canary_executed": canary_mutation_executed,
        "canary_edges_written": canary_edges_written,
        "canary_verification_ok": canary_verification_ok,
        "canary_verification_counts": canary_verification.get("counts") or {},
        "status_counts": dict(sorted(status_counts.items())),
        "edge_counts_by_platform": dict(sorted(edge_counts_by_platform.items())),
        "accepted_subjects": sorted({row["subject_name"] for row in edge_rows}),
        "local_ready_gates": local_ready_gates,
        "local_ready_gate_count": sum(1 for value in local_ready_gates.values() if value),
        "hard_gates_remaining": hard_gates_remaining,
        "writer_dry_run_command": (
            "python scripts\\neo4j_p1_social_staging_writer.py --mode dry-run "
            f"--accepted-edges {manifest_path} --out-dir {writer_out_dir} --run-id {run_id}"
        ),
        "mutation_command_requires_confirm_token": (
            "python scripts\\neo4j_p1_social_staging_writer.py --mode canary "
            f"--accepted-edges {manifest_path} --out-dir {out_dir / 'neo4j_writer_canary'} --run-id {run_id} "
            "--confirm-token ENABLE_NEO4J_P1_SOCIAL_STAGING_WRITE"
        ),
        "rollback_command": rollback_command,
        "safety": {
            "report_only": not canary_mutation_executed,
            "writer_mode": "canary" if canary_mutation_executed else "dry-run" if writer_report else "not_run",
            "graph_write_executed": False,
            "neo4j_write_executed": canary_mutation_executed,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "production_publish_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "secret_value_read_or_printed": False,
            "d_scan_executed": False,
        },
        "writes": "staging_only_neo4j_canary" if canary_mutation_executed else "reports_only",
    }
    write_json(summary_path, summary)
    write_markdown(out_dir / "atlas_social_yyyy_graph_write_gate_summary.md", summary)
    write_markdown(report_path, summary, top_level=True)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], top_level: bool = False) -> None:
    title = "Atlas T6 YYYY Graph/Write Gate Packet" if top_level else "Atlas Social YYYY Graph/Write Gate"
    lines = [
        f"# {title}",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_rows_total: `{summary['input_rows_total']}`",
        f"- graph_gate_ready_edges: `{summary['graph_gate_ready_edges']}`",
        f"- blocked_rows: `{summary['blocked_rows']}`",
        f"- writer_would_write_edges: `{summary['writer_would_write_edges']}`",
        f"- neo4j_staging_canary_executed: `{summary['neo4j_staging_canary_executed']}`",
        f"- canary_edges_written: `{summary['canary_edges_written']}`",
        f"- canary_verification_ok: `{summary['canary_verification_ok']}`",
        f"- manifest_path: `{summary['manifest_path']}`",
        f"- writer_dry_run_report_path: `{summary['writer_dry_run_report_path']}`",
        f"- writer_canary_report_path: `{summary['writer_canary_report_path']}`",
        f"- canary_verification_report_path: `{summary['canary_verification_report_path']}`",
        "",
        "## Accepted Subjects",
        "",
    ]
    lines.extend(f"- `{item}`" for item in summary["accepted_subjects"])
    lines.extend(["", "## Local Ready Gates", ""])
    for key, value in sorted(summary["local_ready_gates"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Hard Gates Remaining", ""])
    for item in summary["hard_gates_remaining"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yyyy-ready", type=Path, default=DEFAULT_YYYY_READY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--skip-writer-dry-run", action="store_true")
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    summary = build_gate(
        yyyy_ready_path=args.yyyy_ready,
        out_dir=args.out_dir,
        report_path=args.report,
        run_id=args.run_id,
        execute_writer_dry_run=not args.skip_writer_dry_run,
    )
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "input_rows_total": summary["input_rows_total"],
                "graph_gate_ready_edges": summary["graph_gate_ready_edges"],
                "writer_would_write_edges": summary["writer_would_write_edges"],
                "summary": str(args.out_dir / "atlas_social_yyyy_graph_write_gate_summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    return run(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
