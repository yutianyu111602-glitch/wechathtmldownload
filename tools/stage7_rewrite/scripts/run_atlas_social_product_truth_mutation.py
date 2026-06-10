#!/usr/bin/env python3
"""Execute or verify the Atlas social product-truth staging metadata mutation.

Default mode is dry-run. Mutating modes require an explicit confirm token and
only operate on local Neo4j Stage7Staging HAS_PROFILE edges listed in the
Q5/Q6 product-truth mutation packet.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib import parse, request


STAGE7_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGETS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_product_truth_mutation_packet_q5_q6_20260525"
    / "atlas_social_product_truth_mutation_targets.jsonl"
)
DEFAULT_OUT_DIR = (
    STAGE7_ROOT / "reports" / "atlas_social_product_truth_mutation_apply_q5_q6_20260525"
)
DEFAULT_NEO4J_URI = "http://127.0.0.1:7474"
DEFAULT_DATABASE = "neo4j"
CONFIRM_TOKEN = "ENABLE_ATLAS_SOCIAL_PRODUCT_TRUTH_STAGING_METADATA_WRITE"
SCHEMA_VERSION = "stage7_atlas_social_product_truth_mutation_runner.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for product-truth mutation: {path}")


def require_local_neo4j(uri: str) -> None:
    parsed = parse.urlparse(uri)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise ValueError(f"Neo4j URI must be local for product-truth staging metadata: {uri}")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "targets")
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


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def target_selector(row: dict[str, Any]) -> dict[str, str]:
    selector = row.get("target_selector") or {}
    return {
        "run_id": str(selector.get("p1_social_run_id") or ""),
        "edge_id": str(selector.get("edge_id") or ""),
        "subject_name": str(selector.get("subject_name") or ""),
        "object_url": str(selector.get("object_url") or ""),
        "mutation_id": str(row.get("mutation_id") or ""),
    }


def validate_target_rows(rows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    seen: set[tuple[str, str]] = set()
    for index, row in enumerate(rows):
        selector = target_selector(row)
        key = (selector["run_id"], selector["edge_id"])
        if row.get("target_namespace") != "local_neo4j_stage7_staging_social_profile_edge":
            failures.append(f"row_{index}_target_namespace_not_allowed")
        if not selector["run_id"]:
            failures.append(f"row_{index}_run_id_missing")
        if not selector["edge_id"]:
            failures.append(f"row_{index}_edge_id_missing")
        if not selector["mutation_id"]:
            failures.append(f"row_{index}_mutation_id_missing")
        if selector["object_url"] and not selector["object_url"].startswith("https://soundcloud.com/"):
            failures.append(f"row_{index}_object_url_not_soundcloud_https")
        if key in seen:
            failures.append(f"row_{index}_duplicate_selector")
        seen.add(key)
        for gate in [
            "public_surface_exposure_allowed",
            "qdrant_write_allowed",
            "sqlite_serving_write_allowed",
            "public_pointer_update_allowed",
            "memory_write_allowed",
        ]:
            if row.get(gate) is not False:
                failures.append(f"row_{index}_{gate}_not_false")
        planned = row.get("planned_set_properties") or {}
        for gate in [
            "identity_proof_promoted",
            "avatar_display_allowed",
            "public_serving_field_allowed",
            "production_graph_label_allowed",
        ]:
            if planned.get(gate) is not False:
                failures.append(f"row_{index}_{gate}_planned_not_false")
    return failures


def neo4j_commit(uri: str, database: str, statements: list[dict[str, Any]]) -> dict[str, Any]:
    payload = json.dumps({"statements": statements}, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{uri.rstrip('/')}/db/{database}/tx/commit",
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def row_query(statement: str, selector: dict[str, str]) -> dict[str, Any]:
    return {
        "statement": statement,
        "parameters": {
            "run_id": selector["run_id"],
            "edge_id": selector["edge_id"],
            "mutation_id": selector["mutation_id"],
        },
    }


def prewrite_statement(selector: dict[str, str]) -> dict[str, Any]:
    return row_query(
        (
            "MATCH (:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(:Stage7Staging:SocialSource) "
            "WHERE r.p1_social_run_id = $run_id AND r.edge_id = $edge_id "
            "RETURN count(r) AS count, coalesce(r.staging_only,false) AS staging_only, "
            "coalesce(r.product_truth_candidate,false) AS product_truth_candidate, "
            "coalesce(r.product_truth_mutation_id,'') AS product_truth_mutation_id, "
            "coalesce(r.identity_proof_promoted,false) AS identity_proof_promoted, "
            "coalesce(r.avatar_display_allowed,false) AS avatar_display_allowed, "
            "coalesce(r.public_serving_field_allowed,false) AS public_serving_field_allowed, "
            "coalesce(r.production_graph_label_allowed,false) AS production_graph_label_allowed"
        ),
        selector,
    )


def mutation_statement(selector: dict[str, str]) -> dict[str, Any]:
    return row_query(
        (
            "MATCH (:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(:Stage7Staging:SocialSource) "
            "WHERE r.p1_social_run_id = $run_id AND r.edge_id = $edge_id "
            "SET r.product_truth_review_status = 'accepted_profile_identity_for_later_promotion', "
            "r.product_truth_candidate = true, r.product_truth_mutation_id = $mutation_id, "
            "r.identity_proof_promoted = false, r.avatar_display_allowed = false, "
            "r.public_serving_field_allowed = false, r.production_graph_label_allowed = false, "
            "r.updated_at = datetime() "
            "RETURN count(r) AS count"
        ),
        selector,
    )


def rollback_statement(selector: dict[str, str]) -> dict[str, Any]:
    return row_query(
        (
            "MATCH (:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(:Stage7Staging:SocialSource) "
            "WHERE r.p1_social_run_id = $run_id AND r.edge_id = $edge_id "
            "REMOVE r.product_truth_review_status, r.product_truth_candidate, r.product_truth_mutation_id "
            "SET r.identity_proof_promoted = false, r.avatar_display_allowed = false, "
            "r.public_serving_field_allowed = false, r.production_graph_label_allowed = false, "
            "r.updated_at = datetime() "
            "RETURN count(r) AS count"
        ),
        selector,
    )


def non_target_statements(run_id: str, edge_ids: list[str], mutation_id: str) -> list[dict[str, Any]]:
    return [
        {
            "statement": (
                "MATCH (:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(:Stage7Staging:SocialSource) "
                "WHERE r.p1_social_run_id = $run_id AND coalesce(r.product_truth_candidate,false) = true "
                "AND NOT r.edge_id IN $edge_ids RETURN count(r) AS count"
            ),
            "parameters": {"run_id": run_id, "edge_ids": edge_ids},
        },
        {
            "statement": (
                "MATCH (:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(:Stage7Staging:SocialSource) "
                "WHERE r.p1_social_run_id = $run_id AND coalesce(r.product_truth_mutation_id,'') = $mutation_id "
                "RETURN count(r) AS count"
            ),
            "parameters": {"run_id": run_id, "mutation_id": mutation_id},
        },
        {
            "statement": (
                "MATCH (:Stage7Staging:SocialSubject)-[r:HAS_PROFILE]->(:Stage7Staging:SocialSource) "
                "WHERE r.p1_social_run_id = $run_id AND ("
                "coalesce(r.identity_proof_promoted,false) = true OR "
                "coalesce(r.avatar_display_allowed,false) = true OR "
                "coalesce(r.public_serving_field_allowed,false) = true OR "
                "coalesce(r.production_graph_label_allowed,false) = true"
                ") RETURN count(r) AS count"
            ),
            "parameters": {"run_id": run_id},
        },
    ]


def result_rows(result: dict[str, Any], index: int) -> list[list[Any]]:
    return [item["row"] for item in result["results"][index]["data"]]


def result_count(result: dict[str, Any], index: int) -> int:
    rows = result_rows(result, index)
    return int(rows[0][0]) if rows else 0


def readback_ok(rows: list[list[Any]], *, expect_candidate: bool, mutation_id: str = "") -> bool:
    if len(rows) != 1:
        return False
    row = rows[0]
    count = int(row[0])
    staging_only = bool(row[1])
    product_truth_candidate = bool(row[2])
    product_truth_mutation_id = str(row[3] or "")
    public_flags_false = all(not bool(value) for value in row[4:8])
    if count != 1 or not staging_only or product_truth_candidate is not expect_candidate:
        return False
    if expect_candidate and product_truth_mutation_id != mutation_id:
        return False
    if not expect_candidate and product_truth_mutation_id:
        return False
    return public_flags_false


def selectors_from_targets(targets: list[dict[str, Any]]) -> list[dict[str, str]]:
    selectors = [target_selector(row) for row in targets]
    run_ids = {selector["run_id"] for selector in selectors}
    mutation_ids = {selector["mutation_id"] for selector in selectors}
    if len(run_ids) != 1:
        raise ValueError(f"targets must use exactly one run_id: {sorted(run_ids)}")
    if len(mutation_ids) != 1:
        raise ValueError(f"targets must use exactly one mutation_id: {sorted(mutation_ids)}")
    return selectors


def build_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Atlas Social Product-Truth Staging Mutation",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- mode: `{report['mode']}`",
        f"- decision: `{report['decision']}`",
        f"- mutation_id: `{report['mutation_id']}`",
        f"- run_id: `{report['run_id']}`",
        f"- target_count: `{report['target_count']}`",
        f"- mutation_executed: `{str(report['mutation_executed']).lower()}`",
        f"- rollback_executed: `{str(report['rollback_executed']).lower()}`",
        f"- ok: `{str(report['ok']).lower()}`",
        "",
        "## Counts",
        "",
    ]
    for key, value in sorted((report.get("counts") or {}).items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Local Neo4j only.",
            "- Writes only `product_truth_candidate` review metadata on existing `Stage7Staging` HAS_PROFILE edges.",
            "- Identity proof, avatar display, public serving fields, production graph labels, Qdrant, SQLite, public pointer, deploy/upload/review, and memory writes remain closed.",
            "- If postwrite verification fails after apply, rollback is attempted immediately.",
            "",
        ]
    )
    if report.get("rollback_command"):
        lines.extend(["## Rollback", "", f"`{report['rollback_command']}`", ""])
    return "\n".join(lines)


def run(args: argparse.Namespace) -> dict[str, Any]:
    require_local_neo4j(args.neo4j_uri)
    reject_d_path(args.out_dir, "out_dir")
    if args.mode in {"apply", "rollback"} and args.confirm_token != CONFIRM_TOKEN:
        raise SystemExit(f"--confirm-token {CONFIRM_TOKEN} required for product-truth staging mutation")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    targets = read_jsonl(args.targets)
    validation_failures = validate_target_rows(targets)
    selectors = selectors_from_targets(targets) if not validation_failures else []
    run_id = selectors[0]["run_id"] if selectors else ""
    mutation_id = selectors[0]["mutation_id"] if selectors else ""
    edge_ids = [selector["edge_id"] for selector in selectors]

    prewrite_result: dict[str, Any] | None = None
    postwrite_result: dict[str, Any] | None = None
    mutation_result: dict[str, Any] | None = None
    rollback_result: dict[str, Any] | None = None
    mutation_executed = False
    rollback_executed = False
    decision = "blocked_by_target_validation"
    ok = False
    counts: dict[str, int] = {}

    if not validation_failures:
        prewrite_result = neo4j_commit(
            args.neo4j_uri,
            args.database,
            [prewrite_statement(selector) for selector in selectors],
        )
        pre_errors = prewrite_result.get("errors") or []
        pre_ok = not pre_errors and all(
            readback_ok(result_rows(prewrite_result, index), expect_candidate=False)
            for index, _selector in enumerate(selectors)
        )

        if args.mode == "dry-run":
            ok = pre_ok
            decision = "dry_run_prewrite_ready" if pre_ok else "dry_run_prewrite_blocked"
        elif args.mode == "rollback":
            rollback_result = neo4j_commit(
                args.neo4j_uri,
                args.database,
                [rollback_statement(selector) for selector in selectors],
            )
            rollback_executed = True
            postwrite_result = neo4j_commit(
                args.neo4j_uri,
                args.database,
                [prewrite_statement(selector) for selector in selectors]
                + non_target_statements(run_id, edge_ids, mutation_id),
            )
            post_errors = postwrite_result.get("errors") or []
            post_ok = not post_errors and all(
                readback_ok(result_rows(postwrite_result, index), expect_candidate=False)
                for index, _selector in enumerate(selectors)
            )
            counts = {
                "non_target_product_truth_count": result_count(postwrite_result, len(selectors)),
                "target_mutation_id_count": result_count(postwrite_result, len(selectors) + 1),
                "public_gate_violation_count": result_count(postwrite_result, len(selectors) + 2),
            }
            ok = post_ok and counts["target_mutation_id_count"] == 0 and counts["public_gate_violation_count"] == 0
            decision = "rollback_verified" if ok else "rollback_verification_failed"
        elif pre_ok:
            mutation_result = neo4j_commit(
                args.neo4j_uri,
                args.database,
                [mutation_statement(selector) for selector in selectors],
            )
            mutation_executed = True
            postwrite_result = neo4j_commit(
                args.neo4j_uri,
                args.database,
                [prewrite_statement(selector) for selector in selectors]
                + non_target_statements(run_id, edge_ids, mutation_id),
            )
            post_errors = postwrite_result.get("errors") or []
            post_ok = not post_errors and all(
                readback_ok(result_rows(postwrite_result, index), expect_candidate=True, mutation_id=mutation_id)
                for index, _selector in enumerate(selectors)
            )
            counts = {
                "non_target_product_truth_count": result_count(postwrite_result, len(selectors)),
                "target_mutation_id_count": result_count(postwrite_result, len(selectors) + 1),
                "public_gate_violation_count": result_count(postwrite_result, len(selectors) + 2),
            }
            ok = (
                post_ok
                and counts["non_target_product_truth_count"] == 0
                and counts["target_mutation_id_count"] == len(selectors)
                and counts["public_gate_violation_count"] == 0
            )
            if ok:
                decision = "product_truth_staging_metadata_write_verified"
            else:
                rollback_result = neo4j_commit(
                    args.neo4j_uri,
                    args.database,
                    [rollback_statement(selector) for selector in selectors],
                )
                rollback_executed = True
                decision = "postwrite_failed_rollback_attempted"
        else:
            decision = "apply_blocked_by_prewrite_readback"

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "mode": args.mode,
        "decision": decision,
        "ok": ok,
        "targets": str(args.targets),
        "out_dir": str(args.out_dir),
        "neo4j_uri": args.neo4j_uri,
        "database": args.database,
        "run_id": run_id,
        "mutation_id": mutation_id,
        "target_count": len(selectors),
        "target_edge_ids": edge_ids,
        "target_subjects": [selector["subject_name"] for selector in selectors],
        "validation_failures": validation_failures,
        "mutation_executed": mutation_executed,
        "rollback_executed": rollback_executed,
        "counts": counts,
        "neo4j_errors": {
            "prewrite": (prewrite_result or {}).get("errors") if prewrite_result else None,
            "mutation": (mutation_result or {}).get("errors") if mutation_result else None,
            "postwrite": (postwrite_result or {}).get("errors") if postwrite_result else None,
            "rollback": (rollback_result or {}).get("errors") if rollback_result else None,
        },
        "rollback_command": (
            f"python tools\\stage7_rewrite\\scripts\\run_atlas_social_product_truth_mutation.py "
            f"--mode rollback --targets {args.targets} --out-dir {args.out_dir}\\rollback "
            f"--confirm-token {CONFIRM_TOKEN}"
        ),
        "safety": {
            "local_neo4j_only": True,
            "secret_value_read_or_printed": False,
            "identity_proof_write_executed": False,
            "avatar_display_write_executed": False,
            "public_serving_field_write_executed": False,
            "production_graph_label_write_executed": False,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
            "public_pointer_update_executed": False,
            "cloudrun_or_vps_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "mem0_or_agentmemory_write_executed": False,
            "d_scan_executed": False,
        },
    }
    write_json(args.out_dir / "atlas_social_product_truth_mutation_run.json", report)
    write_text(args.out_dir / "atlas_social_product_truth_mutation_run.md", build_markdown(report) + "\n")
    print(
        json.dumps(
            {
                "ok": ok,
                "mode": args.mode,
                "decision": decision,
                "report": str(args.out_dir / "atlas_social_product_truth_mutation_run.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["dry-run", "apply", "rollback"], default="dry-run")
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--neo4j-uri", default=DEFAULT_NEO4J_URI)
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--confirm-token", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
