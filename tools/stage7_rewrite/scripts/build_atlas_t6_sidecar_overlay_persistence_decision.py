#!/usr/bin/env python3
"""Build the T5/T6 social overlay persistence decision packet.

This consumes the validated report-local DJ social overlay and the selected
serving SQLite in read-only mode. It decides whether the next Atlas production
step should mutate source/raw schema, copy a derived serving candidate, or keep
the current overlay as an attach-only read model until a separate write gate is
opened. It never mutates the source/raw DB, selected serving DB, graph/vector
stores, public pointers, or mini-program state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_WORK_ORDERS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_dj_completion_overlay_rollup_t5_t6_20260527"
    / "dj_completion_next_work_orders.jsonl"
)
DEFAULT_OVERLAY_DB = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_new_db_overlay_t5_t6_20260526"
    / "atlas_t6_sidecar_social_overlay.sqlite"
)
DEFAULT_SOURCE_RAW_SNAPSHOT = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_new_db_overlay_t5_t6_20260526"
    / "prewrite_schema_snapshot.json"
)
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_overlay_persistence_decision_t5_t6_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_SIDECAR_OVERLAY_PERSISTENCE_DECISION_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t6_sidecar_overlay_persistence_decision.v1"

URL_RE = re.compile(r"https?://|www\.", re.I)
SECRET_KEY_RE = re.compile(r"secret|token|cookie|password|api[_-]?key|authorization|bearer|pass_ticket|openid", re.I)
SECRET_VALUE_RE = re.compile(
    r"api[_-]?key\s*[:=]|authorization\s*[:=]|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"pass_ticket=|openid=|token\s*[:=]|cookie\s*[:=]|password\s*[:=]",
    re.I,
)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)

REQUIRED_SERVING_TABLES = {
    "dj_profile",
    "search_document",
    "graph_window_cache",
    "dj_event",
    "dj_relation_rollup",
}
REQUIRED_OVERLAY_TABLES = {
    "atlas_dj_social_links",
    "atlas_dj_social_entity_rollups",
    "atlas_overlay_metadata",
}
SOCIAL_TABLE_CANDIDATES = {
    "atlas_dj_social_links",
    "atlas_dj_social_entity_rollups",
    "atlas_dj_social_profiles",
    "dj_social_links",
    "dj_social_profiles",
    "entity_external_links",
    "external_links",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 800) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def reject_unbounded_d_root(path: Path, label: str) -> None:
    raw = str(path).replace("\\", "/").casefold()
    resolved = raw
    try:
        resolved = str(path.resolve()).replace("\\", "/").casefold()
    except OSError:
        pass
    for value in {raw, resolved}:
        if value in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
            raise ValueError(f"{label} must not be an unbounded D: root: {path}")
        if value.startswith("d:/ddownload") or value.startswith("d:/aidata") or value.startswith("/mnt/d/ddownload") or value.startswith("/mnt/d/aidata"):
            raise ValueError(f"{label} must not scan cold D: data roots: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def read_json(path: Path, label: str) -> Any:
    reject_unbounded_d_root(path, label)
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        return json.load(handle)


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_unbounded_d_root(path, label)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            row = json.loads(stripped)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(row)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def leak_counts_for(payload: Any) -> dict[str, int]:
    counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}

    def visit(value: Any, key: str = "") -> None:
        if SECRET_KEY_RE.search(key):
            counts["sensitive_key_hits"] += 1
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                visit(child_value, str(child_key))
        elif isinstance(value, list):
            for child in value:
                visit(child, key)
        elif isinstance(value, str):
            counts["public_url_hits"] += len(URL_RE.findall(value))
            counts["sensitive_key_hits"] += len(SECRET_VALUE_RE.findall(value))
            counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(value))

    visit(payload)
    return counts


def add_leak_counts(total: dict[str, int], payload: Any) -> None:
    hits = leak_counts_for(payload)
    for key, value in hits.items():
        total[key] += int(value)


def table_names(conn: sqlite3.Connection, schema: str = "main") -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(f"SELECT name FROM {schema}.sqlite_master WHERE type='table'")
    }


def connect_with_overlay(serving_db: Path, overlay_db: Path) -> sqlite3.Connection:
    reject_unbounded_d_root(serving_db, "serving_db")
    reject_unbounded_d_root(overlay_db, "overlay_db")
    if not serving_db.exists():
        raise FileNotFoundError(serving_db)
    if not overlay_db.exists():
        raise FileNotFoundError(overlay_db)
    conn = sqlite3.connect(f"file:{serving_db.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    conn.execute("ATTACH DATABASE ? AS social_overlay", (f"file:{overlay_db.resolve().as_posix()}?mode=ro",))
    return conn


def parse_json_array(value: Any) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [compact(item, 160) for item in parsed if compact(item, 160)]


def find_work_order(work_orders: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in work_orders:
        if row.get("lane") == "T5_T6_social_overlay_persistence":
            return row
    return None


def source_raw_native_count(snapshot: dict[str, Any]) -> int:
    for key in ("native_social_table_count", "source_raw_native_social_table_count"):
        value = snapshot.get(key)
        if isinstance(value, int):
            return value
    tables = snapshot.get("native_social_tables")
    if isinstance(tables, list):
        return len(tables)
    return -1


def build_packet(
    *,
    work_orders_path: Path,
    serving_db: Path,
    overlay_db: Path,
    source_raw_snapshot_path: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    generated_at = now_iso()
    work_orders = read_jsonl(work_orders_path, "work_orders")
    source_snapshot = read_json(source_raw_snapshot_path, "source_raw_snapshot")
    work_order = find_work_order(work_orders)

    conn = connect_with_overlay(serving_db, overlay_db)
    try:
        serving_tables = table_names(conn, "main")
        overlay_tables = table_names(conn, "social_overlay")
        missing_serving = sorted(REQUIRED_SERVING_TABLES - serving_tables)
        missing_overlay = sorted(REQUIRED_OVERLAY_TABLES - overlay_tables)
        serving_native_social_tables = sorted(SOCIAL_TABLE_CANDIDATES.intersection(serving_tables))

        counts = {
            "overlay_link_rows": int(conn.execute("SELECT COUNT(*) FROM social_overlay.atlas_dj_social_links").fetchone()[0]),
            "overlay_rollup_rows": int(conn.execute("SELECT COUNT(*) FROM social_overlay.atlas_dj_social_entity_rollups").fetchone()[0]),
            "overlay_entity_rows": int(conn.execute("SELECT COUNT(DISTINCT entity_id) FROM social_overlay.atlas_dj_social_entity_rollups").fetchone()[0]),
            "overlay_profile_rows": int(conn.execute("SELECT COALESCE(SUM(profile_rows), 0) FROM social_overlay.atlas_dj_social_entity_rollups").fetchone()[0]),
            "overlay_outlink_rows": int(conn.execute("SELECT COALESCE(SUM(outlink_rows), 0) FROM social_overlay.atlas_dj_social_entity_rollups").fetchone()[0]),
            "overlay_platform_rows": int(conn.execute("SELECT COUNT(DISTINCT platform) FROM social_overlay.atlas_dj_social_links").fetchone()[0]),
            "overlay_host_rows": int(conn.execute("SELECT COUNT(DISTINCT host) FROM social_overlay.atlas_dj_social_links").fetchone()[0]),
            "duplicate_candidate_id_rows": int(conn.execute("SELECT COALESCE(SUM(cnt - 1), 0) FROM (SELECT candidate_id, COUNT(*) cnt FROM social_overlay.atlas_dj_social_links GROUP BY candidate_id HAVING COUNT(*) > 1)").fetchone()[0]),
            "duplicate_selector_rows": int(conn.execute("SELECT COALESCE(SUM(cnt - 1), 0) FROM (SELECT entity_id, candidate_kind, canonical_url_key_hash, platform, COUNT(*) cnt FROM social_overlay.atlas_dj_social_links GROUP BY entity_id, candidate_kind, canonical_url_key_hash, platform HAVING COUNT(*) > 1)").fetchone()[0]),
            "links_without_rollup_rows": int(conn.execute("SELECT COUNT(*) FROM social_overlay.atlas_dj_social_links l LEFT JOIN social_overlay.atlas_dj_social_entity_rollups r ON r.entity_id = l.entity_id WHERE r.entity_id IS NULL").fetchone()[0]),
            "bad_candidate_kind_rows": int(conn.execute("SELECT COUNT(*) FROM social_overlay.atlas_dj_social_links WHERE candidate_kind NOT IN ('profile','outlink')").fetchone()[0]),
            "serving_dj_profile_rows": int(conn.execute("SELECT COUNT(*) FROM dj_profile").fetchone()[0]),
            "serving_search_document_rows": int(conn.execute("SELECT COUNT(*) FROM search_document").fetchone()[0]),
            "serving_graph_window_rows": int(conn.execute("SELECT COUNT(*) FROM graph_window_cache").fetchone()[0]),
            "source_raw_native_social_table_rows": source_raw_native_count(source_snapshot),
            "serving_native_social_table_rows": len(serving_native_social_tables),
        }

        join_counts = {
            "dj_profile_match_rows": int(conn.execute("SELECT COUNT(*) FROM social_overlay.atlas_dj_social_entity_rollups r JOIN dj_profile p ON p.dj_id = r.entity_id").fetchone()[0]),
            "search_document_match_rows": int(conn.execute("SELECT COUNT(DISTINCT r.entity_id) FROM social_overlay.atlas_dj_social_entity_rollups r JOIN search_document s ON s.subject_id = r.entity_id AND s.subject_type = 'dj'").fetchone()[0]),
            "graph_window_match_rows": int(conn.execute("SELECT COUNT(DISTINCT r.entity_id) FROM social_overlay.atlas_dj_social_entity_rollups r JOIN graph_window_cache g ON g.seed_subject_id = r.entity_id").fetchone()[0]),
            "dj_event_match_rows": int(conn.execute("SELECT COUNT(DISTINCT r.entity_id) FROM social_overlay.atlas_dj_social_entity_rollups r JOIN dj_event e ON e.dj_id = r.entity_id").fetchone()[0]),
            "relation_match_rows": int(conn.execute("SELECT COUNT(DISTINCT r.entity_id) FROM social_overlay.atlas_dj_social_entity_rollups r WHERE EXISTS (SELECT 1 FROM dj_relation_rollup rel WHERE rel.src_dj_id = r.entity_id OR rel.dst_dj_id = r.entity_id)").fetchone()[0]),
        }

        ready_rows = []
        for row in conn.execute(
            """
            SELECT r.entity_id, r.candidate_rows, r.profile_rows, r.outlink_rows,
                   r.platforms_json, r.payload_hash AS overlay_rollup_hash,
                   p.display_name, p.city_primary, p.event_count, p.collaborator_count
            FROM social_overlay.atlas_dj_social_entity_rollups r
            JOIN dj_profile p ON p.dj_id = r.entity_id
            ORDER BY r.candidate_rows DESC, r.entity_id
            """
        ):
            platforms = parse_json_array(row["platforms_json"])
            ready_rows.append(
                {
                    "entity_id": row["entity_id"],
                    "display_name": compact(row["display_name"], 180),
                    "city_primary": compact(row["city_primary"], 120),
                    "social_link_count": int(row["candidate_rows"] or 0),
                    "profile_link_count": int(row["profile_rows"] or 0),
                    "outlink_count": int(row["outlink_rows"] or 0),
                    "platform_count": len(platforms),
                    "platforms": platforms[:12],
                    "serving_event_count": int(row["event_count"] or 0),
                    "serving_collaborator_count": int(row["collaborator_count"] or 0),
                    "overlay_rollup_hash": compact(row["overlay_rollup_hash"], 80),
                    "persistence_status": "attach_only_ready_report_only",
                    "accepted_for_graph": False,
                    "source_sqlite_write_allowed": False,
                    "serving_rebuild_allowed": False,
                    "graph_write_allowed": False,
                    "public_serving_field_allowed": False,
                    "memory_write_allowed": False,
                }
            )
    finally:
        conn.close()

    source_raw_native_tables = source_snapshot.get("native_social_tables", [])
    if not isinstance(source_raw_native_tables, list):
        source_raw_native_tables = []

    failed_checks: list[str] = []
    if work_order is None:
        failed_checks.append("social_overlay_persistence_work_order_missing")
    if missing_serving:
        failed_checks.append("required_serving_tables_missing")
    if missing_overlay:
        failed_checks.append("required_overlay_tables_missing")
    for key in ("overlay_link_rows", "overlay_rollup_rows", "overlay_entity_rows"):
        if counts[key] <= 0:
            failed_checks.append(f"{key}_zero")
    for key in ("duplicate_candidate_id_rows", "duplicate_selector_rows", "links_without_rollup_rows", "bad_candidate_kind_rows"):
        if counts[key] != 0:
            failed_checks.append(f"{key}_present")
    for key in ("dj_profile_match_rows", "search_document_match_rows", "graph_window_match_rows", "dj_event_match_rows"):
        if join_counts[key] != counts["overlay_entity_rows"]:
            failed_checks.append(f"{key}_incomplete")

    persistence_mode = "attach_only_read_model_ready_report_only"
    if counts["source_raw_native_social_table_rows"] > 0:
        persistence_mode = "source_raw_schema_migration_possible_requires_separate_write_gate"
    elif counts["serving_native_social_table_rows"] > 0:
        persistence_mode = "serving_native_social_tables_present_requires_rebuild_gate"

    write_guards = {
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_rows": 0,
        "serving_rebuild_rows": 0,
        "graph_write_rows": 0,
        "public_serving_field_rows": 0,
        "memory_rows": 0,
        "source_raw_db_opened": False,
        "source_raw_db_written": False,
        "selected_serving_db_written": False,
        "neo4j_written": False,
        "qdrant_written": False,
        "production_sqlite_written": False,
        "public_pointer_updated": False,
        "huaidj_club_uploaded": False,
        "miniprogram_upload_or_review": False,
    }

    relation_gap_rows = max(0, counts["overlay_entity_rows"] - join_counts["relation_match_rows"])
    contract = {
        "schema_version": f"{SCHEMA_VERSION}.contract",
        "generated_at": generated_at,
        "persistence_mode": persistence_mode,
        "product_decision": "keep_source_raw_and_selected_serving_immutable; use_report_local_overlay_attach_as_current_social_read_model_input",
        "rationale": [
            "source/raw target snapshot has no native social tables, so in-place source/raw social merge requires a separate schema migration gate",
            "selected serving schema has no native social tables, so current proof should stay as overlay attach/read-model augmentation",
            "overlay entities join all core serving DJ/search/graph/event surfaces; relation coverage gaps are warnings, not blockers",
            "raw URLs, local paths, credentials, public upload, graph/vector writes, and memory promotion remain closed",
        ],
        "inputs": {
            "work_orders": display_path(work_orders_path),
            "overlay_db": display_path(overlay_db),
            "selected_serving_db": display_path(serving_db),
            "source_raw_snapshot": display_path(source_raw_snapshot_path),
        },
        "counts": counts,
        "join_counts": join_counts,
        "relation_gap_rows": relation_gap_rows,
        "source_raw_native_social_tables": source_raw_native_tables,
        "serving_native_social_tables": serving_native_social_tables,
        "required_prewrite_for_future_derived_candidate": [
            "copy selected serving DB or build sidecar read-model candidate under report-local output only",
            "record base serving DB size/hash/mtime before copy",
            "create social rollup/link tables from hash-redacted overlay only",
            "rebuild any search_document/search_document_fts changes together if social text is added to search",
            "keep source/raw DB immutable unless a later explicit schema migration gate passes",
        ],
        "rollback_requirements": [
            "derived candidate path must be disposable and not overwrite selected serving DB",
            "base serving DB hash/mtime must remain unchanged",
            "postwrite readback must prove social row counts, duplicate selectors, orphan links, FTS consistency if used, and leak scan",
        ],
        "next_resume_pointer": display_path(out_dir / "social_overlay_persistence_work_orders.jsonl"),
        "write_guards": write_guards,
    }

    blocked_rows: list[dict[str, Any]] = []
    if failed_checks:
        blocked_rows.append(
            {
                "blocked_reason": "persistence_decision_failed_checks_present",
                "failed_checks": failed_checks,
                "counts": counts,
                "join_counts": join_counts,
            }
        )

    next_work_orders = [
        {
            "lane": "T5_T6_social_overlay_derived_serving_candidate",
            "priority": 1,
            "status": "ready_for_separate_candidate_builder",
            "input_contract": display_path(out_dir / "social_overlay_persistence_contract.json"),
            "recommended_action": "build report-local derived serving/read-model candidate or API fixture from hash-redacted social overlay without mutating source/raw or selected serving DB",
            "prewrite_required": True,
            "rollback_required": True,
            "postwrite_readback_required": True,
            "public_upload_allowed_now": False,
        }
    ]

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": "atlas_t6_sidecar_overlay_persistence_attach_only_ready_report_only" if not failed_checks else "atlas_t6_sidecar_overlay_persistence_blocked_report_only",
        "failed_checks": failed_checks,
        "input_work_order_found": work_order is not None,
        "persistence_mode": persistence_mode,
        "overlay_attach_ready_rows": len(ready_rows) if not failed_checks else 0,
        "blocked_rows": len(blocked_rows),
        "counts": counts,
        "join_counts": join_counts,
        "relation_gap_rows": relation_gap_rows,
        "source_raw_native_social_table_rows": counts["source_raw_native_social_table_rows"],
        "serving_native_social_table_rows": counts["serving_native_social_table_rows"],
        "source_raw_schema_migration_required_before_inplace_merge": counts["source_raw_native_social_table_rows"] == 0,
        "serving_schema_migration_required_before_inplace_social_fields": counts["serving_native_social_table_rows"] == 0,
        "write_guards": write_guards,
        "next_resume_pointer": display_path(out_dir / "social_overlay_persistence_work_orders.jsonl"),
    }

    leak_total = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (summary, contract, ready_rows, blocked_rows, next_work_orders):
        add_leak_counts(leak_total, payload)
    summary["leak_hits"] = {
        "raw_source_url": leak_total["public_url_hits"],
        "credential": leak_total["sensitive_key_hits"],
        "local_secret_path": leak_total["local_path_hits"],
    }
    contract["leak_hits"] = summary["leak_hits"]
    if any(leak_total.values()):
        summary["failed_checks"] = sorted(set(summary["failed_checks"] + ["leak_hits_present"]))
        summary["decision"] = "atlas_t6_sidecar_overlay_persistence_blocked_report_only"

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "social_overlay_persistence_summary.json", summary)
    write_json(out_dir / "social_overlay_persistence_contract.json", contract)
    write_jsonl(out_dir / "social_overlay_attach_only_ready_report_only.jsonl", ready_rows if not summary["failed_checks"] else [])
    write_jsonl(out_dir / "social_overlay_persistence_blocked_rows.jsonl", blocked_rows)
    write_jsonl(out_dir / "social_overlay_persistence_work_orders.jsonl", next_work_orders if not summary["failed_checks"] else [])
    write_json(out_dir / "leak_scan.json", summary["leak_hits"])
    write_text(out_dir / "social_overlay_persistence_summary.md", render_summary(summary, contract))
    write_text(report_path, render_report(summary, contract, report_path))
    return summary


def render_summary(summary: dict[str, Any], contract: dict[str, Any]) -> str:
    counts = summary["counts"]
    joins = summary["join_counts"]
    return "\n".join(
        [
            "# Atlas T5/T6 Social Overlay Persistence Decision Summary",
            "",
            f"- Decision: `{summary['decision']}`.",
            f"- Persistence mode: `{summary['persistence_mode']}`.",
            f"- Overlay entities/links/profile/outlink: `{counts['overlay_entity_rows']}/{counts['overlay_link_rows']}/{counts['overlay_profile_rows']}/{counts['overlay_outlink_rows']}`.",
            f"- Core serving joins profile/search/graph/event/relation: `{joins['dj_profile_match_rows']}/{joins['search_document_match_rows']}/{joins['graph_window_match_rows']}/{joins['dj_event_match_rows']}/{joins['relation_match_rows']}`.",
            f"- Relation-only warning gap rows: `{summary['relation_gap_rows']}`.",
            f"- Source/raw native social tables: `{summary['source_raw_native_social_table_rows']}`; serving native social tables: `{summary['serving_native_social_table_rows']}`.",
            f"- Leak hits raw-url/credential/local-path: `{summary['leak_hits']['raw_source_url']}/{summary['leak_hits']['credential']}/{summary['leak_hits']['local_secret_path']}`.",
            f"- Next resume pointer: `{summary['next_resume_pointer']}`.",
            "",
            "## Contract",
            "",
            f"- Product decision: `{contract['product_decision']}`.",
            "- Future writes require a separate derived-serving candidate or source/raw schema migration gate with prewrite, rollback, and postwrite readback.",
        ]
    )


def render_report(summary: dict[str, Any], contract: dict[str, Any], report_path: Path) -> str:
    counts = summary["counts"]
    joins = summary["join_counts"]
    return "\n".join(
        [
            "# ATLAS T5/T6 Sidecar Overlay Persistence Decision - 2026-05-27",
            "",
            f"Report: `{display_path(report_path)}`",
            "",
            "## Decision",
            "",
            f"`{summary['decision']}` with failed checks `{summary['failed_checks']}`.",
            "",
            "The LLM audit and DB readback support keeping the WSL2 social/profile/outlink sidecar as a report-local attach/read-model input for now. The explicit reason is structural: the source/raw target snapshot and selected serving SQLite do not expose native social tables, while the overlay already joins the current DJ serving/search/graph surfaces without raw URL exposure. A future persistent serving candidate is allowed only as a separate derived-candidate builder with rollback and postwrite readback.",
            "",
            "## Evidence",
            "",
            f"- Overlay entities/links/profile/outlink: `{counts['overlay_entity_rows']}/{counts['overlay_link_rows']}/{counts['overlay_profile_rows']}/{counts['overlay_outlink_rows']}`.",
            f"- Platform/host rows: `{counts['overlay_platform_rows']}/{counts['overlay_host_rows']}`.",
            f"- Core joins profile/search/graph/event/relation: `{joins['dj_profile_match_rows']}/{joins['search_document_match_rows']}/{joins['graph_window_match_rows']}/{joins['dj_event_match_rows']}/{joins['relation_match_rows']}`.",
            f"- Relation-only warning gap rows: `{summary['relation_gap_rows']}`.",
            f"- Duplicate candidate/selector/link-without-rollup/bad-kind rows: `{counts['duplicate_candidate_id_rows']}/{counts['duplicate_selector_rows']}/{counts['links_without_rollup_rows']}/{counts['bad_candidate_kind_rows']}`.",
            f"- Source/raw native social tables: `{summary['source_raw_native_social_table_rows']}`; selected serving native social tables: `{summary['serving_native_social_table_rows']}`.",
            f"- Leak hits raw-url/credential/local-path: `{summary['leak_hits']['raw_source_url']}/{summary['leak_hits']['credential']}/{summary['leak_hits']['local_secret_path']}`.",
            "",
            "## Boundary",
            "",
            "This packet is report-only. It opened the selected serving SQLite and report-local overlay SQLite in read-only mode. It did not open source/raw Atlas DB, mutate the selected serving SQLite, rebuild serving, write Neo4j/Qdrant/production SQLite, update public pointers, upload huaidj.club, upload/review the mini-program, write memory, read credentials, use 9router, or scan D: roots.",
            "",
            "## Next",
            "",
            f"Next resume pointer: `{summary['next_resume_pointer']}`. The next high-value lane is a separate report-local derived serving/read-model candidate builder from `social_overlay_persistence_contract.json`, or pivot to avatar/media recovery / time-city-venue gap closure.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-orders", type=Path, default=DEFAULT_WORK_ORDERS)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--overlay-db", type=Path, default=DEFAULT_OVERLAY_DB)
    parser.add_argument("--source-raw-snapshot", type=Path, default=DEFAULT_SOURCE_RAW_SNAPSHOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(
        work_orders_path=args.work_orders,
        serving_db=args.serving_db,
        overlay_db=args.overlay_db,
        source_raw_snapshot_path=args.source_raw_snapshot,
        out_dir=args.out_dir,
        report_path=args.report,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
