#!/usr/bin/env python3
"""Build a report-only Atlas social product-truth mutation packet.

This packet consumes the Q5/Q6 product-truth promotion-review rows and turns
them into explicit mutation targets, readback checks, and rollback commands.
It does not execute any DB/vector/public-surface mutation.
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
DEFAULT_REVIEW_DIR = STAGE7_ROOT / "reports" / "atlas_social_product_truth_promotion_review_q5_q6_20260524"
DEFAULT_READY = DEFAULT_REVIEW_DIR / "atlas_social_product_truth_promotion_ready.jsonl"
DEFAULT_REVIEW_SUMMARY = DEFAULT_REVIEW_DIR / "atlas_social_product_truth_promotion_review_summary.json"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_product_truth_mutation_packet_q5_q6_20260525"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_Q5_Q6_PRODUCT_TRUTH_MUTATION_PACKET_20260525.md"
DEFAULT_MUTATION_ID = "atlas_q5_q6_product_truth_mutation_packet_20260525"
DEFAULT_RUN_ID = "atlas_q6_social_graph_write_gate_20260524"
SCHEMA_VERSION = "stage7_atlas_social_product_truth_mutation_packet.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for product-truth mutation packet: {path}")


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
    if row.get("ready_for_later_product_truth_packet") is not True:
        failures.append("ready_for_later_product_truth_packet_not_true")
    if compact(row.get("promotion_review_status")) != "ready_for_separate_product_truth_promotion_packet":
        failures.append("promotion_review_status_not_ready")
    for key in [
        "identity_proof_promoted",
        "avatar_display_allowed",
        "public_serving_field_allowed",
        "production_graph_label_allowed",
        "qdrant_write_allowed",
        "sqlite_serving_write_allowed",
        "public_pointer_update_allowed",
        "memory_write_allowed",
    ]:
        if row.get(key) is not False:
            failures.append(f"{key}_not_false")
    if not compact(row.get("edge_id")):
        failures.append("edge_id_missing")
    if not compact(row.get("atlas_dj_id")):
        failures.append("atlas_dj_id_missing")
    if not compact(row.get("subject_name")):
        failures.append("subject_name_missing")
    if not compact(row.get("object_url")).startswith("https://soundcloud.com/"):
        failures.append("object_url_not_public_soundcloud_https")
    if not compact(row.get("profile_image_hash")).startswith("sha256:"):
        failures.append("profile_image_hash_missing")
    return failures


def mutation_target(row: dict[str, Any], generated_at: str, mutation_id: str, run_id: str) -> dict[str, Any]:
    edge_id = compact(row.get("edge_id"))
    subject = compact(row.get("subject_name"))
    object_url = compact(row.get("object_url"), 3000)
    return {
        "schema_version": SCHEMA_VERSION + ".target_row",
        "generated_at": generated_at,
        "mutation_id": mutation_id,
        "target_namespace": "local_neo4j_stage7_staging_social_profile_edge",
        "target_selector": {
            "p1_social_run_id": run_id,
            "edge_id": edge_id,
            "relationship": "HAS_PROFILE",
            "subject_name": subject,
            "object_url": object_url,
        },
        "planned_set_properties": {
            "product_truth_review_status": "accepted_profile_identity_for_later_promotion",
            "product_truth_candidate": True,
            "product_truth_mutation_id": mutation_id,
            "identity_proof_promoted": False,
            "avatar_display_allowed": False,
            "public_serving_field_allowed": False,
            "production_graph_label_allowed": False,
        },
        "rollback_properties": [
            "product_truth_review_status",
            "product_truth_candidate",
            "product_truth_mutation_id",
        ],
        "must_preserve_false_properties": [
            "identity_proof_promoted",
            "avatar_display_allowed",
            "public_serving_field_allowed",
            "production_graph_label_allowed",
        ],
        "public_surface_exposure_allowed": False,
        "qdrant_write_allowed": False,
        "sqlite_serving_write_allowed": False,
        "public_pointer_update_allowed": False,
        "memory_write_allowed": False,
        "atlas_dj_id": compact(row.get("atlas_dj_id")),
        "subject_name": subject,
        "object_url": object_url,
        "profile_image_hash": compact(row.get("profile_image_hash")),
        "prewrite_readback_cypher": (
            "MATCH (:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(:Stage7Staging:SocialSource) "
            "WHERE r.p1_social_run_id = $run_id AND r.edge_id = $edge_id "
            "RETURN count(r) AS count, r.staging_only AS staging_only, "
            "coalesce(r.product_truth_candidate,false) AS product_truth_candidate"
        ),
        "planned_mutation_cypher": (
            "MATCH (:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(:Stage7Staging:SocialSource) "
            "WHERE r.p1_social_run_id = $run_id AND r.edge_id = $edge_id "
            "SET r.product_truth_review_status = 'accepted_profile_identity_for_later_promotion', "
            "r.product_truth_candidate = true, r.product_truth_mutation_id = $mutation_id, "
            "r.identity_proof_promoted = false, r.avatar_display_allowed = false, "
            "r.public_serving_field_allowed = false, r.production_graph_label_allowed = false"
        ),
        "postwrite_readback_cypher": (
            "MATCH (:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(:Stage7Staging:SocialSource) "
            "WHERE r.p1_social_run_id = $run_id AND r.edge_id = $edge_id "
            "RETURN count(r) AS count, r.product_truth_candidate AS product_truth_candidate, "
            "r.product_truth_mutation_id AS product_truth_mutation_id, "
            "r.identity_proof_promoted AS identity_proof_promoted, "
            "r.avatar_display_allowed AS avatar_display_allowed, "
            "r.public_serving_field_allowed AS public_serving_field_allowed, "
            "r.production_graph_label_allowed AS production_graph_label_allowed"
        ),
        "rollback_cypher": (
            "MATCH (:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(:Stage7Staging:SocialSource) "
            "WHERE r.p1_social_run_id = $run_id AND r.edge_id = $edge_id "
            "REMOVE r.product_truth_review_status, r.product_truth_candidate, r.product_truth_mutation_id "
            "SET r.identity_proof_promoted = false, r.avatar_display_allowed = false, "
            "r.public_serving_field_allowed = false, r.production_graph_label_allowed = false"
        ),
    }


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Atlas Q5/Q6 Product-Truth Mutation Packet",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- mutation_id: `{summary['mutation_id']}`",
        f"- input_rows: `{summary['input_rows']}`",
        f"- mutation_targets: `{summary['mutation_targets']}`",
        f"- blocked_rows: `{summary['blocked_rows']}`",
        f"- target_namespace_counts: `{json.dumps(summary['target_namespace_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Evidence",
        "",
        f"- ready_rows: `{summary['ready_rows_path']}`",
        f"- review_summary: `{summary['review_summary_path']}`",
        f"- mutation_targets_path: `{summary['mutation_targets_path']}`",
        f"- blocked_path: `{summary['blocked_path']}`",
        "",
        "## Planned Target",
        "",
        "- Namespace: `local_neo4j_stage7_staging_social_profile_edge`.",
        "- Selector: `p1_social_run_id + edge_id + HAS_PROFILE`.",
        "- Planned mutation is limited to `product_truth_candidate` review metadata.",
        "- Identity proof, avatar display, public serving fields, production graph labels, Qdrant, SQLite, public pointer, deploy/upload/review, and memory writes remain closed.",
        "",
        "## Required Execution Gate",
        "",
        "- Execute only through a future writer with explicit confirm token.",
        "- Run prewrite readback for every `edge_id` before mutation.",
        "- Run postwrite readback and non-target count checks immediately after mutation.",
        "- Run rollback command if postwrite readback or public-safe leak/noise/search checks fail.",
        "- Do not expose public fields until a separate public serving packet passes remote-effective verification.",
        "",
        "## Safety",
        "",
    ]
    for key, value in sorted((summary.get("safety") or {}).items()):
        lines.append(f"- {key}: `{str(value).lower()}`")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_packet(
    *,
    ready_rows_path: Path,
    review_summary_path: Path,
    out_dir: Path,
    report_path: Path,
    mutation_id: str = DEFAULT_MUTATION_ID,
    run_id: str = DEFAULT_RUN_ID,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    review_summary = read_json(review_summary_path)
    ready_rows = read_jsonl(ready_rows_path)

    targets: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for row in ready_rows:
        failures = row_failures(row)
        if failures:
            blocked.append(
                {
                    "schema_version": SCHEMA_VERSION + ".blocked_row",
                    "generated_at": generated_at,
                    "subject_name": compact(row.get("subject_name")),
                    "edge_id": compact(row.get("edge_id")),
                    "blockers": failures,
                }
            )
        else:
            targets.append(mutation_target(row, generated_at, mutation_id, run_id))

    cross_gate_failures: list[str] = []
    if review_summary.get("decision") != "atlas_social_product_truth_promotion_review_ready_report_only":
        cross_gate_failures.append("upstream_review_not_ready_report_only")
    if int(review_summary.get("promotion_review_ready_rows") or 0) != len(ready_rows):
        cross_gate_failures.append("ready_row_count_mismatch")
    if int(review_summary.get("blocked_rows") or 0) != 0:
        cross_gate_failures.append("upstream_review_has_blocked_rows")
    if not ready_rows:
        cross_gate_failures.append("no_ready_rows")

    out_dir.mkdir(parents=True, exist_ok=True)
    targets_path = out_dir / "atlas_social_product_truth_mutation_targets.jsonl"
    blocked_path = out_dir / "atlas_social_product_truth_mutation_blocked.jsonl"
    summary_path = out_dir / "atlas_social_product_truth_mutation_packet_summary.json"
    write_jsonl(targets_path, targets)
    write_jsonl(blocked_path, blocked)

    local_ready_gates = {
        "review_summary_present": bool(review_summary),
        "upstream_review_ready": review_summary.get("decision")
        == "atlas_social_product_truth_promotion_review_ready_report_only",
        "ready_rows_present": bool(ready_rows),
        "no_row_blocks": not blocked,
        "no_cross_gate_failures": not cross_gate_failures,
        "targets_written": targets_path.exists(),
        "all_targets_keep_public_gates_closed": all(
            target.get("public_surface_exposure_allowed") is False
            and target.get("qdrant_write_allowed") is False
            and target.get("sqlite_serving_write_allowed") is False
            and target.get("public_pointer_update_allowed") is False
            and target.get("memory_write_allowed") is False
            for target in targets
        ),
    }
    ready = bool(targets) and all(local_ready_gates.values())
    decision = (
        "atlas_social_product_truth_mutation_packet_ready_report_only"
        if ready
        else "atlas_social_product_truth_mutation_packet_blocked_report_only"
    )
    target_counts = Counter(str(target.get("target_namespace")) for target in targets)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "ok": ready,
        "mutation_id": mutation_id,
        "run_id": run_id,
        "ready_rows_path": str(ready_rows_path),
        "review_summary_path": str(review_summary_path),
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "summary_path": str(summary_path),
        "mutation_targets_path": str(targets_path),
        "blocked_path": str(blocked_path),
        "input_rows": len(ready_rows),
        "mutation_targets": len(targets),
        "blocked_rows": len(blocked),
        "target_namespace_counts": dict(sorted(target_counts.items())),
        "cross_gate_failures": cross_gate_failures,
        "local_ready_gates": local_ready_gates,
        "local_ready_gate_count": sum(1 for value in local_ready_gates.values() if value),
        "execution_requirements": [
            "future writer must require an explicit confirm token",
            "prewrite readback must find exactly one staging HAS_PROFILE edge per target",
            "postwrite readback must prove only product_truth_candidate metadata changed",
            "rollback must remove product_truth metadata and preserve public gates false",
            "public-safe leak/noise/search smoke must pass before any public exposure",
        ],
        "hard_gates_remaining": [
            "This packet is report-only and does not execute the mutation.",
            "Identity proof, avatar display, public serving fields, production graph labels, Qdrant, SQLite serving pointer, public pointer, CloudRun/VPS deploy, mini-program upload/review, and memory writes remain closed.",
            "Q5 public Stage7 target identity remains blocked by 403/session-gated API behavior.",
        ],
        "safety": {
            "report_only": True,
            "neo4j_write_executed": False,
            "production_graph_label_write_executed": False,
            "identity_proof_write_executed": False,
            "avatar_display_write_executed": False,
            "public_serving_field_write_executed": False,
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
    write_markdown(out_dir / "atlas_social_product_truth_mutation_packet_summary.md", summary)
    write_markdown(report_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ready-rows", type=Path, default=DEFAULT_READY)
    parser.add_argument("--review-summary", type=Path, default=DEFAULT_REVIEW_SUMMARY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--mutation-id", default=DEFAULT_MUTATION_ID)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = build_packet(
        ready_rows_path=args.ready_rows,
        review_summary_path=args.review_summary,
        out_dir=args.out_dir,
        report_path=args.report,
        mutation_id=args.mutation_id,
        run_id=args.run_id,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "ok": summary["ok"],
                "summary": summary["summary_path"],
                "report": summary["report_path"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
