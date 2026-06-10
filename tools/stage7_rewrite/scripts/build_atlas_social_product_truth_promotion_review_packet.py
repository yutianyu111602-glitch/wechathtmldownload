#!/usr/bin/env python3
"""Build a report-only Atlas social product-truth promotion review packet.

This packet consumes the verified Q6 staging-only HAS_PROFILE canary evidence
and decides whether rows are ready for a later product-truth promotion packet.
It never promotes identity proof, avatar display, public serving fields,
production graph labels, Qdrant, SQLite, public pointers, or memory state.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_GRAPH_GATE_DIR = STAGE7_ROOT / "reports" / "atlas_social_graph_write_gate_q6_20260524"
DEFAULT_GRAPH_GATE_SUMMARY = DEFAULT_GRAPH_GATE_DIR / "atlas_social_graph_write_gate_summary.json"
DEFAULT_STAGING_MANIFEST = DEFAULT_GRAPH_GATE_DIR / "atlas_social_identity_edges_for_neo4j_staging.jsonl"
DEFAULT_CANARY_VERIFY = DEFAULT_GRAPH_GATE_DIR / "neo4j_writer_canary" / "canary_verification.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_product_truth_promotion_review_q5_q6_20260524"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_Q5_Q6_PRODUCT_TRUTH_PROMOTION_REVIEW_PACKET_20260524.md"
SCHEMA_VERSION = "stage7_atlas_social_product_truth_promotion_review.v1"
ACCEPTED_GRAPH_GATE_DECISIONS = {
    "atlas_social_graph_write_gate_canary_written_verified",
    "atlas_social_yyyy_graph_write_gate_canary_written_verified",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Atlas product-truth promotion review: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    return value if isinstance(value, dict) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


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


def row_failures(row: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if compact(row.get("edge_type")) != "HAS_PROFILE":
        failures.append("edge_type_not_has_profile")
    if compact(row.get("review_status")) != "accepted_for_staging":
        failures.append("review_status_not_accepted_for_staging")
    if row.get("staging_only") is not True:
        failures.append("staging_only_not_true")
    if row.get("write_allowed") is not False:
        failures.append("write_allowed_not_false")
    if row.get("identity_proof_promoted") is not False:
        failures.append("identity_proof_already_promoted")
    if row.get("avatar_display_allowed") is not False:
        failures.append("avatar_display_already_allowed")
    if row.get("public_serving_field_allowed") is not False:
        failures.append("public_serving_field_already_allowed")
    if row.get("production_graph_label_allowed") is not False:
        failures.append("production_graph_label_already_allowed")
    if compact(row.get("object_platform")) != "soundcloud":
        failures.append("object_platform_not_soundcloud")
    if not compact(row.get("object_url")).startswith("https://soundcloud.com/"):
        failures.append("object_url_not_public_soundcloud_https")
    if not compact(row.get("profile_image_hash")).startswith("sha256:"):
        failures.append("profile_image_hash_missing")
    if not compact(row.get("rollback_key")):
        failures.append("rollback_key_missing")
    if not compact(row.get("edge_id")):
        failures.append("edge_id_missing")
    if int(row.get("atlas_event_count") or 0) <= 0:
        failures.append("atlas_event_context_missing")
    if int(row.get("atlas_source_article_count") or 0) <= 0:
        failures.append("atlas_source_article_context_missing")
    if float(row.get("confidence") or 0.0) < 0.85:
        failures.append("confidence_below_product_truth_review_floor")
    return failures


def build_review_row(row: dict[str, Any], generated_at: str, failures: list[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".review_row",
        "generated_at": generated_at,
        "subject_name": compact(row.get("subject_name")),
        "atlas_dj_id": compact(row.get("atlas_dj_id")),
        "edge_id": compact(row.get("edge_id")),
        "object_url": compact(row.get("object_url")),
        "profile_image_hash": compact(row.get("profile_image_hash")),
        "promotion_review_status": (
            "ready_for_separate_product_truth_promotion_packet" if not failures else "blocked"
        ),
        "promotion_requirement_failures": failures,
        "ready_for_later_product_truth_packet": not failures,
        "identity_proof_promoted": False,
        "avatar_display_allowed": False,
        "public_serving_field_allowed": False,
        "production_graph_label_allowed": False,
        "qdrant_write_allowed": False,
        "sqlite_serving_write_allowed": False,
        "public_pointer_update_allowed": False,
        "memory_write_allowed": False,
    }


def build_packet(
    *,
    graph_gate_summary_path: Path,
    staging_manifest_path: Path,
    canary_verification_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    graph_summary = read_json(graph_gate_summary_path)
    canary_verification = read_json(canary_verification_path)
    edge_rows = read_jsonl(staging_manifest_path)

    review_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    ready_rows: list[dict[str, Any]] = []
    for row in edge_rows:
        failures = row_failures(row)
        reviewed = build_review_row(row, generated_at, failures)
        review_rows.append(reviewed)
        if failures:
            blocked_rows.append(reviewed)
        else:
            ready_rows.append(reviewed)

    canary_counts = canary_verification.get("counts") or {}
    cross_gate_failures: list[str] = []
    if graph_summary.get("decision") not in ACCEPTED_GRAPH_GATE_DECISIONS:
        cross_gate_failures.append("graph_write_gate_not_canary_written_verified")
    if canary_verification.get("ok") is not True:
        cross_gate_failures.append("canary_verification_not_ok")
    if int(canary_counts.get("has_profile_edges") or 0) != len(edge_rows):
        cross_gate_failures.append("canary_has_profile_count_mismatch")
    if int(canary_counts.get("staging_only_edges") or 0) != len(edge_rows):
        cross_gate_failures.append("canary_staging_only_count_mismatch")
    if int(canary_counts.get("non_staging_only_edges") or 0) != 0:
        cross_gate_failures.append("canary_contains_non_staging_edges")
    if int(graph_summary.get("blocked_rows") or 0) != 0:
        cross_gate_failures.append("upstream_graph_gate_has_blocked_rows")
    if int(graph_summary.get("graph_gate_ready_edges") or 0) != len(edge_rows):
        cross_gate_failures.append("graph_gate_ready_edge_count_mismatch")

    out_dir.mkdir(parents=True, exist_ok=True)
    review_path = out_dir / "atlas_social_product_truth_promotion_review.jsonl"
    ready_path = out_dir / "atlas_social_product_truth_promotion_ready.jsonl"
    blocked_path = out_dir / "atlas_social_product_truth_promotion_blocked.jsonl"
    summary_path = out_dir / "atlas_social_product_truth_promotion_review_summary.json"
    write_jsonl(review_path, review_rows)
    write_jsonl(ready_path, ready_rows)
    write_jsonl(blocked_path, blocked_rows)

    local_ready_gates = {
        "graph_gate_summary_present": bool(graph_summary),
        "graph_gate_canary_written_verified": graph_summary.get("decision") in ACCEPTED_GRAPH_GATE_DECISIONS,
        "canary_verification_present": bool(canary_verification),
        "canary_verification_ok": canary_verification.get("ok") is True,
        "manifest_rows_present": bool(edge_rows),
        "no_row_level_blocks": bool(edge_rows) and not blocked_rows,
        "no_cross_gate_failures": not cross_gate_failures,
        "all_ready_rows_keep_product_truth_closed": all(
            row.get("identity_proof_promoted") is False
            and row.get("avatar_display_allowed") is False
            and row.get("public_serving_field_allowed") is False
            and row.get("production_graph_label_allowed") is False
            for row in ready_rows
        ),
        "review_files_written": review_path.exists() and ready_path.exists() and blocked_path.exists(),
    }
    ready = bool(ready_rows) and all(local_ready_gates.values())
    decision = (
        "atlas_social_product_truth_promotion_review_ready_report_only"
        if ready
        else "atlas_social_product_truth_promotion_review_blocked_report_only"
    )
    status_counts = Counter(row["promotion_review_status"] for row in review_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": decision,
        "graph_gate_summary_path": str(graph_gate_summary_path),
        "staging_manifest_path": str(staging_manifest_path),
        "canary_verification_path": str(canary_verification_path),
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "review_path": str(review_path),
        "ready_path": str(ready_path),
        "blocked_path": str(blocked_path),
        "input_edges": len(edge_rows),
        "promotion_review_ready_rows": len(ready_rows),
        "blocked_rows": len(blocked_rows),
        "accepted_subjects": sorted({row["subject_name"] for row in ready_rows}),
        "status_counts": dict(sorted(status_counts.items())),
        "cross_gate_failures": cross_gate_failures,
        "canary_counts": canary_counts,
        "local_ready_gates": local_ready_gates,
        "local_ready_gate_count": sum(1 for value in local_ready_gates.values() if value),
        "hard_gates_remaining": [
            "This packet authorizes only a later product-truth promotion packet design; it does not write product truth.",
            "Identity proof, avatar display, public serving fields, production graph labels, Qdrant, SQLite serving pointer, public pointer, and memory writes remain closed.",
            "A later mutation packet must define exact write targets, rollback command, post-write readback checks, and public-safe leak/noise checks.",
            "Q5 public Stage7 target identity remains blocked by 403/session-gated API behavior and cannot be treated as remote-effective evidence.",
        ],
        "next_packet_requirements": [
            "Map each ready edge to the exact product surface field and graph label target.",
            "Provide rollback/readback commands for every target namespace before any mutation.",
            "Verify post-write counts for the ready subjects and prove non-target row count remains unchanged.",
            "Run public-safe leak/noise/search smoke before exposing any public field.",
            "Keep Qdrant/SQLite/public pointer changes out unless their own staging and rollback evidence exists.",
        ],
        "safety": {
            "report_only": True,
            "identity_proof_write_executed": False,
            "avatar_display_write_executed": False,
            "public_serving_field_write_executed": False,
            "production_graph_label_write_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
            "public_pointer_update_executed": False,
            "cloudrun_or_vps_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "mem0_or_agentmemory_write_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "secret_value_read_or_printed": False,
            "d_scan_executed": False,
        },
        "writes": "reports_only",
    }
    write_json(summary_path, summary)
    write_markdown(out_dir / "atlas_social_product_truth_promotion_review_summary.md", summary)
    write_markdown(report_path, summary, top_level=True)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], top_level: bool = False) -> None:
    title = "Atlas Q5/Q6 Product-Truth Promotion Review Packet" if top_level else "Atlas Social Product-Truth Promotion Review"
    lines = [
        f"# {title}",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- input_edges: `{summary['input_edges']}`",
        f"- promotion_review_ready_rows: `{summary['promotion_review_ready_rows']}`",
        f"- blocked_rows: `{summary['blocked_rows']}`",
        f"- local_ready_gate_count: `{summary['local_ready_gate_count']}`",
        f"- review_path: `{summary['review_path']}`",
        f"- ready_path: `{summary['ready_path']}`",
        f"- blocked_path: `{summary['blocked_path']}`",
        "",
        "## Accepted Subjects",
        "",
    ]
    lines.extend(f"- `{item}`" for item in summary["accepted_subjects"])
    lines.extend(["", "## Cross Gate Failures", ""])
    if summary["cross_gate_failures"]:
        lines.extend(f"- {item}" for item in summary["cross_gate_failures"])
    else:
        lines.append("- none")
    lines.extend(["", "## Local Ready Gates", ""])
    for key, value in sorted(summary["local_ready_gates"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Hard Gates Remaining", ""])
    for item in summary["hard_gates_remaining"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Next Packet Requirements", ""])
    for item in summary["next_packet_requirements"]:
        lines.append(f"- {item}")
    lines.extend(["", "## Safety", ""])
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph-gate-summary", type=Path, default=DEFAULT_GRAPH_GATE_SUMMARY)
    parser.add_argument("--staging-manifest", type=Path, default=DEFAULT_STAGING_MANIFEST)
    parser.add_argument("--canary-verification", type=Path, default=DEFAULT_CANARY_VERIFY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def run(args: argparse.Namespace) -> int:
    summary = build_packet(
        graph_gate_summary_path=args.graph_gate_summary,
        staging_manifest_path=args.staging_manifest,
        canary_verification_path=args.canary_verification,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(
        json.dumps(
            {
                "ok": summary["ok"],
                "decision": summary["decision"],
                "input_edges": summary["input_edges"],
                "promotion_review_ready_rows": summary["promotion_review_ready_rows"],
                "summary": str(args.out_dir / "atlas_social_product_truth_promotion_review_summary.json"),
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
