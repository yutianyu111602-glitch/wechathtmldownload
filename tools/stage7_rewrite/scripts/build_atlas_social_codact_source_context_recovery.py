#!/usr/bin/env python3
"""Build a report-only recovery packet for Cod.Act source-context blockage.

The packet reconciles existing Q6 blocked source-context rows, public profile
metadata candidates, and the local selected Atlas serving SQLite. It does not
fetch network content and does not promote identity, graph, or product truth.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]

DEFAULT_TARGET_NAME = "Cod.Act"
DEFAULT_TARGET_ENTITY_ID = "4983592d896c5d68e0a429a6"
DEFAULT_REMAINING_BLOCKED = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_blocked_source_context_acceptance_q6_20260525"
    / "atlas_social_blocked_source_context_acceptance_remaining_blocked.jsonl"
)
DEFAULT_FOLLOWUP_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_blocked_source_context_followup_q6_20260525"
    / "atlas_social_blocked_source_context_followup_summary.json"
)
DEFAULT_IDENTITY_CANDIDATES = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_identity_review_criteria_q6_20260524_0028"
    / "atlas_social_identity_review_candidates.jsonl"
)
DEFAULT_PUBLIC_SEARCH = (
    STAGE7_ROOT
    / "reports"
    / "atlas_entity_public_search_content_evidence_full_138102_20260521"
    / "atlas_public_search_content_evidence.jsonl"
)
DEFAULT_CROSS_VALIDATED = (
    STAGE7_ROOT
    / "reports"
    / "atlas_cross_validation_20260521"
    / "atlas_cross_validated_queue.jsonl"
)
DEFAULT_SERVING_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_field_repair_fullcomplete_strict_20260523-1658"
    / "atlas_serving.sqlite"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_codact_source_context_recovery_q6_20260525"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_CODACT_SOURCE_CONTEXT_RECOVERY_20260525.md"

SCHEMA_VERSION = "stage7_atlas_social_codact_source_context_recovery.v1"
DEFAULT_SERVING_TABLES = [
    "dj_profile",
    "canonical_subject",
    "search_document",
    "evidence_ref",
    "performance_event",
    "activity_event_detail",
    "activity_evidence_ref",
]
TEXT_COLUMN_HINTS = [
    "name",
    "title",
    "alias",
    "normalized",
    "snippet",
    "quote",
    "field_value",
    "subject",
    "source_account",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value).casefold())


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Cod.Act source-context recovery: {path}")


def read_json(path: Path) -> dict[str, Any]:
    reject_d_path(path, "json")
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8-sig"))
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


def matches_target(row: dict[str, Any], target_name: str, target_entity_id: str) -> bool:
    if target_entity_id and compact(row.get("entity_search_id")) == target_entity_id:
        return True
    for key in ["name", "entity_name", "display_name"]:
        if normalize(row.get(key)) == normalize(target_name):
            return True
    return False


def first_matching(rows: list[dict[str, Any]], target_name: str, target_entity_id: str) -> dict[str, Any] | None:
    for row in rows:
        if matches_target(row, target_name, target_entity_id):
            return row
    return None


def matching_rows(rows: list[dict[str, Any]], target_name: str, target_entity_id: str) -> list[dict[str, Any]]:
    return [row for row in rows if matches_target(row, target_name, target_entity_id)]


def table_names(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"pragma table_info({table})")]


def text_columns(cols: list[str]) -> list[str]:
    return [col for col in cols if any(hint in col.casefold() for hint in TEXT_COLUMN_HINTS)]


def row_preview(row: sqlite3.Row, max_keys: int = 14) -> dict[str, Any]:
    data = dict(row)
    return {key: data.get(key) for key in list(data)[:max_keys]}


def search_serving_db(
    *,
    db_path: Path,
    target_name: str,
    variants: list[str],
    tables: list[str],
    max_scan_rows_per_column: int,
) -> dict[str, Any]:
    reject_d_path(db_path, "serving_db")
    result: dict[str, Any] = {
        "db_path": str(db_path),
        "db_exists": db_path.exists(),
        "target_name": target_name,
        "target_normalized": normalize(target_name),
        "variants": variants,
        "table_results": [],
        "contains_hit_count": 0,
        "normalized_exact_hit_count": 0,
        "profile_or_subject_exact_hit_count": 0,
    }
    if not db_path.exists():
        return result

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    available_tables = table_names(conn)
    target_norm = normalize(target_name)

    for table in tables:
        if table not in available_tables:
            continue
        columns = table_columns(conn, table)
        searchable = text_columns(columns)
        table_result: dict[str, Any] = {
            "table": table,
            "text_columns": searchable,
            "contains_hits": [],
            "normalized_exact_hits": [],
        }
        for column in searchable:
            for variant in variants:
                for row in conn.execute(f"select * from {table} where {column} like ? limit 20", (f"%{variant}%",)):
                    table_result["contains_hits"].append(
                        {"column": column, "variant": variant, "row": row_preview(row)}
                    )

            scanned = 0
            for row in conn.execute(f"select * from {table} where {column} is not null limit ?", (max_scan_rows_per_column,)):
                scanned += 1
                value = row[column]
                if normalize(value) == target_norm:
                    table_result["normalized_exact_hits"].append(
                        {"column": column, "value": value, "row": row_preview(row)}
                    )
            table_result.setdefault("scanned_rows_by_column", {})[column] = scanned

        table_result["contains_hit_count"] = len(table_result["contains_hits"])
        table_result["normalized_exact_hit_count"] = len(table_result["normalized_exact_hits"])
        result["contains_hit_count"] += table_result["contains_hit_count"]
        result["normalized_exact_hit_count"] += table_result["normalized_exact_hit_count"]
        if table in {"dj_profile", "canonical_subject", "search_document"}:
            result["profile_or_subject_exact_hit_count"] += table_result["normalized_exact_hit_count"]
        result["table_results"].append(table_result)

    return result


def summarize_public_candidate(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"found": False}
    return {
        "found": True,
        "target_url": compact(row.get("target_url") or row.get("best_url"), 500),
        "final_url": compact(row.get("final_url") or row.get("best_url"), 500),
        "status_code": row.get("status_code"),
        "page_title": compact(row.get("page_title") or row.get("best_title"), 500),
        "og_title": compact(row.get("og_title"), 500),
        "meta_description": compact(row.get("meta_description"), 500),
        "manual_review_required": bool(row.get("manual_review_required", True)),
        "accepted_for_graph": bool(row.get("accepted_for_graph")),
        "identity_proof": bool(row.get("identity_proof")),
        "graph_write_allowed": bool(row.get("graph_write_allowed")),
    }


def build_packet(
    *,
    target_name: str,
    target_entity_id: str,
    remaining_blocked_path: Path,
    followup_summary_path: Path,
    identity_candidates_path: Path,
    public_search_path: Path,
    cross_validated_path: Path,
    serving_db_path: Path,
    out_dir: Path,
    report_path: Path,
    max_scan_rows_per_column: int,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    generated_at = now_iso()
    remaining_blocked = read_jsonl(remaining_blocked_path)
    followup_summary = read_json(followup_summary_path)
    identity_candidates = matching_rows(read_jsonl(identity_candidates_path), target_name, target_entity_id)
    public_candidates = matching_rows(read_jsonl(public_search_path), target_name, target_entity_id)
    cross_validated = first_matching(read_jsonl(cross_validated_path), target_name, target_entity_id)

    variants = sorted({target_name, target_name.upper(), target_name.replace(".", " "), target_name.replace(".", ""), normalize(target_name)})
    serving_search = search_serving_db(
        db_path=serving_db_path,
        target_name=target_name,
        variants=variants,
        tables=DEFAULT_SERVING_TABLES,
        max_scan_rows_per_column=max_scan_rows_per_column,
    )
    remaining_row = first_matching(remaining_blocked, target_name, target_entity_id)
    public_candidate = identity_candidates[0] if identity_candidates else (public_candidates[0] if public_candidates else None)

    if not remaining_row:
        decision = "atlas_social_codact_source_context_recovery_target_not_in_remaining_blocked"
    elif serving_search["profile_or_subject_exact_hit_count"] > 0:
        decision = "atlas_social_codact_source_context_recovery_serving_exact_profile_review_needed_report_only"
    else:
        decision = "atlas_social_codact_source_context_recovery_blocked_report_only"

    evidence_path = out_dir / "atlas_social_codact_source_context_recovery_evidence.json"
    serving_path = out_dir / "atlas_social_codact_serving_db_search.json"
    summary_path = out_dir / "atlas_social_codact_source_context_recovery_summary.json"
    public_rows_path = out_dir / "atlas_social_codact_public_profile_candidates.jsonl"

    evidence = {
        "schema_version": SCHEMA_VERSION + ".evidence",
        "generated_at": generated_at,
        "target_name": target_name,
        "target_entity_id": target_entity_id,
        "remaining_blocked_row": remaining_row,
        "followup_summary": {
            "path": str(followup_summary_path),
            "decision": followup_summary.get("decision"),
            "context_rows_scanned": followup_summary.get("context_rows_scanned"),
            "entities_remaining_without_context": followup_summary.get("entities_remaining_without_context"),
            "selected_candidate_rows": followup_summary.get("selected_candidate_rows"),
        },
        "public_profile_candidate": summarize_public_candidate(public_candidate),
        "cross_validated_entity": cross_validated,
        "identity_candidate_count": len(identity_candidates),
        "public_search_candidate_count": len(public_candidates),
    }
    write_json(evidence_path, evidence)
    write_json(serving_path, serving_search)
    write_jsonl(public_rows_path, identity_candidates + public_candidates)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": decision,
        "target_name": target_name,
        "target_entity_id": target_entity_id,
        "remaining_blocked_path": str(remaining_blocked_path),
        "followup_summary_path": str(followup_summary_path),
        "identity_candidates_path": str(identity_candidates_path),
        "public_search_path": str(public_search_path),
        "cross_validated_path": str(cross_validated_path),
        "serving_db_path": str(serving_db_path),
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "summary_path": str(summary_path),
        "evidence_path": str(evidence_path),
        "serving_db_search_path": str(serving_path),
        "public_profile_candidates_path": str(public_rows_path),
        "remaining_blocked_row_found": remaining_row is not None,
        "public_profile_candidate_found": public_candidate is not None,
        "public_profile_target_url": summarize_public_candidate(public_candidate).get("target_url"),
        "serving_contains_hit_count": serving_search["contains_hit_count"],
        "serving_normalized_exact_hit_count": serving_search["normalized_exact_hit_count"],
        "serving_profile_or_subject_exact_hit_count": serving_search["profile_or_subject_exact_hit_count"],
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "avatar_display_allowed": 0,
        "public_serving_field_allowed": 0,
        "graph_write_allowed": 0,
        "safety": {
            "report_only": True,
            "network_call_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_or_agentmemory_write_executed": False,
            "cloudrun_or_vps_deploy_executed": False,
            "mini_program_upload_or_review_executed": False,
            "secret_value_read_or_printed": False,
            "d_scan_executed": False,
        },
        "next_gate": "Do not promote Cod.Act until exact Atlas source context or canonical DJ/entity id evidence exists.",
    }
    write_json(summary_path, summary)
    write_markdown(report_path, summary, evidence, serving_search)
    return summary


def write_markdown(
    report_path: Path,
    summary: dict[str, Any],
    evidence: dict[str, Any],
    serving_search: dict[str, Any],
) -> None:
    public_candidate = evidence["public_profile_candidate"]
    lines = [
        "# Atlas T6 Cod.Act Source-Context Recovery",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- target: `{summary['target_name']}` / `{summary['target_entity_id']}`",
        f"- remaining_blocked_row_found: `{summary['remaining_blocked_row_found']}`",
        f"- public_profile_candidate_found: `{summary['public_profile_candidate_found']}`",
        f"- serving_contains_hit_count: `{summary['serving_contains_hit_count']}`",
        f"- serving_normalized_exact_hit_count: `{summary['serving_normalized_exact_hit_count']}`",
        f"- serving_profile_or_subject_exact_hit_count: `{summary['serving_profile_or_subject_exact_hit_count']}`",
        "",
        "## Evidence",
        "",
        f"- Remaining blocked source-context row: `{summary['remaining_blocked_path']}`",
        f"- Follow-up summary: `{summary['followup_summary_path']}`",
        f"- Public identity candidate rows: `{summary['identity_candidates_path']}` and `{summary['public_search_path']}`",
        f"- Cross-validated entity queue: `{summary['cross_validated_path']}`",
        f"- Selected serving DB searched: `{summary['serving_db_path']}`",
        f"- Packet evidence JSON: `{summary['evidence_path']}`",
        f"- Serving DB search JSON: `{summary['serving_db_search_path']}`",
        "",
        "## Public Candidate",
        "",
        f"- target_url: `{public_candidate.get('target_url')}`",
        f"- page_title: `{public_candidate.get('page_title')}`",
        f"- identity_proof: `{public_candidate.get('identity_proof')}`",
        f"- accepted_for_graph: `{public_candidate.get('accepted_for_graph')}`",
        f"- graph_write_allowed: `{public_candidate.get('graph_write_allowed')}`",
        "",
        "## Serving DB Search",
        "",
    ]
    for table_result in serving_search.get("table_results", []):
        lines.append(
            f"- `{table_result['table']}`: contains `{table_result['contains_hit_count']}`, "
            f"normalized exact `{table_result['normalized_exact_hit_count']}`."
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This packet is report-only local reconciliation.",
            "- Public SoundCloud metadata is not Atlas source context, canonical target id evidence, identity proof, public serving permission, or graph/write permission.",
            "- No network/model/paid API call, Neo4j/Qdrant/SQLite write, public pointer update, CloudRun/VPS deploy, mini-program upload/review, memory write, credential read, destructive Git, 9router use, or D: root scan occurred.",
            "",
            "## STOP_REASON / WAIT_REASON",
            "",
            "- `STOP_REASON`: `Cod.Act` remains blocked for product/public/graph promotion.",
            "- `WAIT_REASON`: no exact local Atlas source context and no exact selected serving DJ/profile/subject id was found for `Cod.Act`; only public profile metadata exists.",
            "",
            "## Next Resume Cursor",
            "",
            "Continue T6 external source-context recovery for `Cod.Act` or switch T0 to Q3 weekly backend logic audit while keeping `Cod.Act` blocked.",
            "",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-name", default=DEFAULT_TARGET_NAME)
    parser.add_argument("--target-entity-id", default=DEFAULT_TARGET_ENTITY_ID)
    parser.add_argument("--remaining-blocked", type=Path, default=DEFAULT_REMAINING_BLOCKED)
    parser.add_argument("--followup-summary", type=Path, default=DEFAULT_FOLLOWUP_SUMMARY)
    parser.add_argument("--identity-candidates", type=Path, default=DEFAULT_IDENTITY_CANDIDATES)
    parser.add_argument("--public-search", type=Path, default=DEFAULT_PUBLIC_SEARCH)
    parser.add_argument("--cross-validated", type=Path, default=DEFAULT_CROSS_VALIDATED)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-scan-rows-per-column", type=int, default=200000)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    summary = build_packet(
        target_name=args.target_name,
        target_entity_id=args.target_entity_id,
        remaining_blocked_path=args.remaining_blocked,
        followup_summary_path=args.followup_summary,
        identity_candidates_path=args.identity_candidates,
        public_search_path=args.public_search,
        cross_validated_path=args.cross_validated,
        serving_db_path=args.serving_db,
        out_dir=args.out_dir,
        report_path=args.report,
        max_scan_rows_per_column=args.max_scan_rows_per_column,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "target_name": summary["target_name"],
                "serving_contains_hit_count": summary["serving_contains_hit_count"],
                "serving_normalized_exact_hit_count": summary["serving_normalized_exact_hit_count"],
                "public_profile_candidate_found": summary["public_profile_candidate_found"],
                "summary": summary["summary_path"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
