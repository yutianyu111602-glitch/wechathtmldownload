from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from atlas_core_common import (  # noqa: E402
    add_common_args,
    connect_readonly,
    default_stage7_reports_root,
    json_dumps,
    row_count,
    table_columns,
    table_exists,
    text,
    utc_now,
    write_json,
)


DEFAULT_OUT_DIR = default_stage7_reports_root() / "atlas_core_migration_readiness_20260604"

LEGACY_CONSUMER_MAP = {
    "atlas_serving.sqlite": [
        "services/weekly_activity_cloudrun/src/stage7AtlasSqliteStore.mjs",
        "services/weekly_activity_cloudrun/scripts/atlasGraphSearchSelfTest.mjs",
        "services/weekly_activity_cloudrun/scripts/atlasServingLocalSmoke.mjs",
        "services/weekly_activity_cloudrun/scripts/prepare_atlas_serving_sqlite_cloudrun_context.py",
        "tools/stage7_rewrite/scripts/build_atlas_miniapp_api_db.py",
        "tools/stage7_rewrite/scripts/validate_atlas_serving_promotion_preflight.py",
    ],
    "atlas_miniapp.sqlite": [
        "tools/stage7_rewrite/scripts/export_atlas_miniapp_json.py",
        "tools/stage7_rewrite/scripts/enrich_atlas_miniapp_bios.py",
        "tools/stage7_rewrite/scripts/fix_atlas_counts.py",
        "tools/stage7_rewrite/scripts/normalize_atlas_entities.py",
        "tools/stage7_rewrite/scripts/normalize_venue_names.py",
        "tools/stage7_rewrite/scripts/run_atlas_identity_redirect_db3_write_s157.py",
        "tools/stage7_rewrite/scripts/run_atlas_symbolic_profile_disposition_s158.py",
        "tools/stage7_rewrite/scripts/audit_atlas_relation_field_integrity.py",
    ],
    "atlas_index.json.gz": [
        "services/weekly_activity_cloudrun/src/miniappAtlasApi.mjs",
        "services/weekly_activity_cloudrun/tests/miniappAtlasApi.test.mjs",
        "tools/stage7_rewrite/scripts/export_atlas_miniapp_json.py",
        "services/weekly_activity_cloudrun/scripts/bake_and_deploy.py",
    ],
    "external_link_sidecar": [
        "tools/stage7_rewrite/docker/openclaw-db2-external-link/db2_external_link_entrypoint.py",
        "tools/stage7_rewrite/scripts/build_external_link_entity_id_mapping_workbench_s128.py",
        "tools/stage7_rewrite/scripts/build_db2_external_link_projection_prewrite_packet.py",
        "apps/weekly_activity_miniprogram/utils/publicExternalLinks.js",
    ],
}


def inventory_sqlite(path: Path, label: str, expected_tables: list[str]) -> dict[str, Any]:
    if not path.exists():
        return {"path": str(path), "exists": False, "tables": {}}
    tables: dict[str, Any] = {}
    conn = connect_readonly(path)
    try:
        for table in expected_tables:
            if table_exists(conn, table):
                tables[table] = {"columns": table_columns(conn, table), "row_count": row_count(conn, table)}
        present = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        return {"path": str(path), "exists": True, "label": label, "tables": tables, "all_table_count": len(present)}
    finally:
        conn.close()


def count_missing(left_values: set[str], right_values: set[str]) -> dict[str, Any]:
    missing = sorted(value for value in left_values if value and value not in right_values)
    total = len([value for value in left_values if value])
    found = max(total - len(missing), 0)
    return {
        "left_count": total,
        "matched_count": found,
        "missing_count": len(missing),
        "coverage": (found / total) if total else 1.0,
        "missing_sample": missing[:20],
    }


def values(conn: sqlite3.Connection, table: str, column: str) -> set[str]:
    if not table_exists(conn, table) or column not in table_columns(conn, table):
        return set()
    return {text(row[0]) for row in conn.execute(f'SELECT DISTINCT "{column}" FROM "{table}" WHERE COALESCE("{column}", "") <> ""')}


def read_redirect_pairs(conn: sqlite3.Connection) -> dict[str, str]:
    if not table_exists(conn, "dj_identity_redirect"):
        return {}
    cols = set(table_columns(conn, "dj_identity_redirect"))
    if "old_dj_id" not in cols or "canonical_dj_id" not in cols:
        return {}
    return {text(row[0]): text(row[1]) for row in conn.execute("SELECT old_dj_id, canonical_dj_id FROM dj_identity_redirect")}


def canonicalize(value: str, redirects: dict[str, str]) -> str:
    seen = set()
    current = value
    while current in redirects and current not in seen:
        seen.add(current)
        current = redirects[current]
    return current


def build_join_coverage(db2: Path, db3: Path, sidecar: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    c2 = connect_readonly(db2) if db2.exists() else None
    c3 = connect_readonly(db3) if db3.exists() else None
    cs = connect_readonly(sidecar) if sidecar.exists() else None
    try:
        redirects = read_redirect_pairs(c3) if c3 else {}
        db3_djs = values(c3, "dj_profile", "dj_id") if c3 else set()
        db3_subjects = values(c3, "subject", "subject_id") if c3 else set()
        db3_identity_ids = db3_djs | db3_subjects | set(redirects.keys()) | set(redirects.values())

        if c2 and c3:
            db2_djs = {canonicalize(value, redirects) for value in values(c2, "dj_profile", "dj_id")}
            out["db2_dj_profile_to_db3_dj_profile"] = count_missing(db2_djs, db3_djs)
            db2_refs = values(c2, "evidence_ref", "source_ref_id")
            db3_refs = values(c3, "source_ref", "source_ref_id")
            out["db2_evidence_ref_to_db3_source_ref"] = count_missing(db2_refs, db3_refs)
            db2_events = values(c2, "performance_event", "event_id")
            db3_events = values(c3, "dj_event", "event_id")
            out["db2_performance_event_to_db3_dj_event"] = count_missing(db2_events, db3_events)

            db2_rel = set()
            if table_exists(c2, "dj_relation_rollup"):
                for row in c2.execute("SELECT src_dj_id, dst_dj_id FROM dj_relation_rollup"):
                    db2_rel.add((canonicalize(text(row[0]), redirects), canonicalize(text(row[1]), redirects)))
            db3_rel = set()
            if table_exists(c3, "dj_collaborator"):
                for row in c3.execute("SELECT src_dj_id, dst_dj_id FROM dj_collaborator"):
                    db3_rel.add((text(row[0]), text(row[1])))
            missing_rel = sorted(pair for pair in db2_rel if pair not in db3_rel)
            out["db2_relation_rollup_to_db3_collaborator"] = {
                "left_count": len(db2_rel),
                "matched_count": max(len(db2_rel) - len(missing_rel), 0),
                "missing_count": len(missing_rel),
                "coverage": ((len(db2_rel) - len(missing_rel)) / len(db2_rel)) if db2_rel else 1.0,
                "missing_sample": [list(pair) for pair in missing_rel[:20]],
            }

        if cs:
            sidecar_ids = values(cs, "external_link_candidates", "entity_search_id")
            out["external_link_entity_search_id_to_entity_legacy_id"] = count_missing(sidecar_ids, db3_identity_ids | (values(c2, "dj_profile", "dj_id") if c2 else set()))
    finally:
        if c2:
            c2.close()
        if c3:
            c3.close()
        if cs:
            cs.close()
    return out


def build_mapping_gaps(join_coverage: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, coverage in join_coverage.items():
        for item in coverage.get("missing_sample", []):
            rows.append({"gap": name, "missing": item, "severity": "blocking" if coverage.get("missing_count", 0) else "info"})
    return rows


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    generated_at = utc_now()
    schema_inventory = {
        "DB1_atlas": inventory_sqlite(args.db1, "DB1_atlas", ["articles", "entities", "events", "atlas_activity_events", "atlas_activity_evidence_refs"]),
        "DB2_serving": inventory_sqlite(args.db2, "DB2_serving", ["canonical_subject", "dj_profile", "performance_event", "dj_event", "dj_relation_rollup", "dj_venue_rollup", "evidence_ref", "search_document", "search_document_fts", "graph_window_cache"]),
        "DB3_miniapp": inventory_sqlite(args.db3, "DB3_miniapp", ["subject", "dj_profile", "dj_event", "dj_collaborator", "dj_venue", "source_ref", "dj_identity_redirect", "dj_identity_profile_disposition"]),
        "S119_external_link_sidecar": inventory_sqlite(args.external_link_sidecar, "S119_external_link_sidecar", ["external_link_candidates"]),
    }
    join_coverage = build_join_coverage(args.db2, args.db3, args.external_link_sidecar)
    mapping_gaps = build_mapping_gaps(join_coverage)
    report = {
        "schema_version": "atlas_core_migration_readiness.v1",
        "decision": "atlas_core_migration_readiness_report_ready",
        "generated_at": generated_at,
        "inputs": {
            "db1": str(args.db1),
            "db2": str(args.db2),
            "db3": str(args.db3),
            "external_link_sidecar": str(args.external_link_sidecar),
        },
        "schema_inventory": {
            key: {
                table: {"columns": value["tables"][table]["columns"], "row_count": value["tables"][table]["row_count"]}
                for table in value.get("tables", {})
            }
            for key, value in schema_inventory.items()
        },
        "legacy_consumer_map": LEGACY_CONSUMER_MAP,
        "join_coverage": join_coverage,
        "mapping_gaps": mapping_gaps,
        "safety": {
            "production_db_write_executed": False,
            "credential_read_required": False,
            "raw_url_output_required": False,
        },
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "atlas_core_migration_readiness.json", report)
    write_json(args.out_dir / "schema_field_inventory.json", schema_inventory)
    write_json(args.out_dir / "legacy_consumer_map.json", LEGACY_CONSUMER_MAP)
    write_json(args.out_dir / "join_coverage_and_missing_identity_map.json", {"join_coverage": join_coverage, "mapping_gaps": mapping_gaps})
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Atlas Core migration readiness without mutating production DBs.")
    add_common_args(parser)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> dict[str, Any]:
    return build_report(parse_args(argv))


if __name__ == "__main__":
    print(json_dumps(main()))
