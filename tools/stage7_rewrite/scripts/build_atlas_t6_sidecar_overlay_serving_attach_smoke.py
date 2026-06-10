#!/usr/bin/env python3
"""Build a local serving/search/API attach smoke packet for the T6 sidecar overlay DB.

This opens the selected Atlas serving SQLite and the report-local sidecar overlay
SQLite in read-only mode, attaches the overlay, and proves that DJ social
profile/outlink rows can join to serving DJ/search/graph read models. It does
not rebuild serving, mutate source/raw DB, write graph/vector/public state, or
emit raw URLs.
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
DEFAULT_OVERLAY_DB = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t6_sidecar_new_db_overlay_t5_t6_20260526"
    / "atlas_t6_sidecar_social_overlay.sqlite"
)
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_overlay_serving_attach_smoke_t5_t6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_SIDECAR_OVERLAY_SERVING_ATTACH_SMOKE_20260526.md"
SCHEMA_VERSION = "stage7_atlas_t6_sidecar_overlay_serving_attach_smoke.v1"

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


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
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
        total[key] += value


def connect_serving_with_overlay(serving_db: Path, overlay_db: Path) -> sqlite3.Connection:
    reject_unbounded_d_root(serving_db, "serving_db")
    reject_unbounded_d_root(overlay_db, "overlay_db")
    if not serving_db.exists():
        raise FileNotFoundError(serving_db)
    if not overlay_db.exists():
        raise FileNotFoundError(overlay_db)
    conn = sqlite3.connect(f"file:{serving_db.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    overlay_uri = f"file:{overlay_db.resolve().as_posix()}?mode=ro"
    conn.execute("ATTACH DATABASE ? AS social_overlay", (overlay_uri,))
    return conn


def table_names(conn: sqlite3.Connection, schema: str = "main") -> set[str]:
    return {
        str(row["name"])
        for row in conn.execute(
            f"SELECT name FROM {schema}.sqlite_master WHERE type='table'"
        )
    }


def table_columns(conn: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [compact(row["name"], 120) for row in conn.execute(f'PRAGMA {schema}.table_info("{table}")')]


def rowdict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def chunks(values: list[str], size: int = 450) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def read_metadata(conn: sqlite3.Connection) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for row in conn.execute("SELECT key, value_json FROM social_overlay.atlas_overlay_metadata ORDER BY key"):
        try:
            metadata[str(row["key"])] = json.loads(row["value_json"])
        except json.JSONDecodeError:
            metadata[str(row["key"])] = row["value_json"]
    return metadata


def build_entity_rows(conn: sqlite3.Connection, generated_at: str) -> list[dict[str, Any]]:
    rows = [
        rowdict(row)
        for row in conn.execute(
            """
            SELECT entity_id, candidate_rows, profile_rows, outlink_rows,
                   platforms_json, hosts_json, payload_hash AS overlay_rollup_hash
            FROM social_overlay.atlas_dj_social_entity_rollups
            ORDER BY candidate_rows DESC, entity_id
            """
        )
    ]
    entity_ids = [compact(row.get("entity_id"), 180) for row in rows if compact(row.get("entity_id"), 180)]
    profiles: dict[str, dict[str, Any]] = {}
    search_docs: dict[str, dict[str, Any]] = {}
    graph_windows: dict[str, dict[str, Any]] = {}
    event_counts: Counter[str] = Counter()
    relation_counts: Counter[str] = Counter()

    for chunk in chunks(entity_ids):
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(
            f"""
            SELECT dj_id, display_name, city_primary, event_count, venue_count,
                   collaborator_count, organization_count
            FROM dj_profile
            WHERE dj_id IN ({placeholders})
            """,
            chunk,
        ):
            profiles[compact(row["dj_id"], 180)] = rowdict(row)
        for row in conn.execute(
            f"""
            SELECT subject_id, rank_score
            FROM search_document
            WHERE subject_type='dj' AND subject_id IN ({placeholders})
            """,
            chunk,
        ):
            search_docs[compact(row["subject_id"], 180)] = rowdict(row)
        for row in conn.execute(
            f"""
            SELECT seed_subject_id, MAX(node_count) AS node_count, MAX(edge_count) AS edge_count
            FROM graph_window_cache
            WHERE seed_subject_id IN ({placeholders})
            GROUP BY seed_subject_id
            """,
            chunk,
        ):
            graph_windows[compact(row["seed_subject_id"], 180)] = rowdict(row)
        for row in conn.execute(
            f"SELECT dj_id, COUNT(*) AS c FROM dj_event WHERE dj_id IN ({placeholders}) GROUP BY dj_id",
            chunk,
        ):
            event_counts[compact(row["dj_id"], 180)] += int(row["c"] or 0)
        for row in conn.execute(
            f"SELECT src_dj_id AS dj_id, COUNT(*) AS c FROM dj_relation_rollup WHERE src_dj_id IN ({placeholders}) GROUP BY src_dj_id",
            chunk,
        ):
            relation_counts[compact(row["dj_id"], 180)] += int(row["c"] or 0)
        for row in conn.execute(
            f"SELECT dst_dj_id AS dj_id, COUNT(*) AS c FROM dj_relation_rollup WHERE dst_dj_id IN ({placeholders}) GROUP BY dst_dj_id",
            chunk,
        ):
            relation_counts[compact(row["dj_id"], 180)] += int(row["c"] or 0)

    safe_rows: list[dict[str, Any]] = []
    for row in rows:
        entity_id = compact(row.get("entity_id"), 180)
        profile = profiles.get(entity_id, {})
        search_doc = search_docs.get(entity_id, {})
        graph_window = graph_windows.get(entity_id, {})
        platforms = json.loads(row.pop("platforms_json") or "[]")
        hosts = json.loads(row.pop("hosts_json") or "[]")
        failures: list[str] = []
        if not profile.get("display_name"):
            failures.append("serving_dj_profile_missing")
        if not search_doc.get("subject_id"):
            failures.append("serving_search_document_missing")
        if not graph_window.get("seed_subject_id"):
            failures.append("serving_graph_window_missing")
        if int(row.get("candidate_rows") or 0) <= 0:
            failures.append("overlay_rollup_without_links")
        safe_rows.append(
            {
                "schema_version": SCHEMA_VERSION + ".entity_attach_row",
                "generated_at": generated_at,
                "entity_id": entity_id,
                "display_name": compact(profile.get("display_name"), 220),
                "city_primary": compact(profile.get("city_primary"), 120),
                "overlay_candidate_rows": int(row.get("candidate_rows") or 0),
                "overlay_profile_rows": int(row.get("profile_rows") or 0),
                "overlay_outlink_rows": int(row.get("outlink_rows") or 0),
                "platforms": [compact(value, 80) for value in platforms],
                "hosts": [compact(value, 160) for value in hosts],
                "serving_event_edges": int(event_counts.get(entity_id, 0)),
                "serving_relation_edges": int(relation_counts.get(entity_id, 0)),
                "serving_event_count": int(profile.get("event_count") or 0),
                "serving_venue_count": int(profile.get("venue_count") or 0),
                "serving_collaborator_count": int(profile.get("collaborator_count") or 0),
                "serving_organization_count": int(profile.get("organization_count") or 0),
                "search_document_found": bool(search_doc.get("subject_id")),
                "search_rank_score": float(search_doc.get("rank_score") or 0),
                "graph_window_found": bool(graph_window.get("seed_subject_id")),
                "graph_window_node_count": int(graph_window.get("node_count") or 0),
                "graph_window_edge_count": int(graph_window.get("edge_count") or 0),
                "overlay_rollup_hash": compact(row.get("overlay_rollup_hash"), 80),
                "attach_failures": failures,
                "attach_status": "overlay_serving_attach_ready_local_only" if not failures else "overlay_serving_attach_blocked_report_only",
                "accepted_for_graph": False,
                "source_raw_db_write_allowed": False,
                "serving_rebuild_allowed": False,
                "graph_write_allowed": False,
                "public_serving_field_allowed": False,
                "memory_write_allowed": False,
                "write_status": "report_only",
            }
        )
    return safe_rows


def build_platform_rows(conn: sqlite3.Connection, generated_at: str) -> list[dict[str, Any]]:
    rows = [
        rowdict(row)
        for row in conn.execute(
            """
            SELECT
              platform,
              host,
              COUNT(*) AS link_rows,
              COUNT(DISTINCT entity_id) AS entity_rows,
              SUM(CASE WHEN candidate_kind='profile' THEN 1 ELSE 0 END) AS profile_rows,
              SUM(CASE WHEN candidate_kind='outlink' THEN 1 ELSE 0 END) AS outlink_rows
            FROM social_overlay.atlas_dj_social_links
            GROUP BY platform, host
            ORDER BY link_rows DESC, entity_rows DESC, platform, host
            """
        )
    ]
    return [
        {
            "schema_version": SCHEMA_VERSION + ".platform_rollup_row",
            "generated_at": generated_at,
            "platform": compact(row.get("platform"), 120),
            "host": compact(row.get("host"), 220),
            "link_rows": int(row.get("link_rows") or 0),
            "entity_rows": int(row.get("entity_rows") or 0),
            "profile_rows": int(row.get("profile_rows") or 0),
            "outlink_rows": int(row.get("outlink_rows") or 0),
            "write_status": "report_only",
        }
        for row in rows
    ]


def build_detail_samples(entity_rows: list[dict[str, Any]], conn: sqlite3.Connection, generated_at: str, limit: int = 24) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in [item for item in entity_rows if not item["attach_failures"]][:limit]:
        entity_id = row["entity_id"]
        link_rows = [
            rowdict(link)
            for link in conn.execute(
                """
                SELECT candidate_id, candidate_kind, platform, host, canonical_url_key_hash, payload_hash
                FROM social_overlay.atlas_dj_social_links
                WHERE entity_id=?
                ORDER BY candidate_kind, platform, host, candidate_id
                LIMIT 20
                """,
                (entity_id,),
            )
        ]
        samples.append(
            {
                "schema_version": SCHEMA_VERSION + ".api_detail_sample",
                "generated_at": generated_at,
                "route": "/atlas/dj/{dj_id}/social",
                "method": "GET",
                "params": {"dj_id": entity_id},
                "status": 200,
                "body": {
                    "dj_id": entity_id,
                    "display_name": row["display_name"],
                    "city_primary": row["city_primary"],
                    "social_link_count": row["overlay_candidate_rows"],
                    "platforms": row["platforms"],
                    "hosts": row["hosts"],
                    "link_samples": [
                        {
                            "candidate_id_hash": hashlib.sha256(compact(link.get("candidate_id"), 200).encode("utf-8")).hexdigest()[:16],
                            "candidate_kind": compact(link.get("candidate_kind"), 80),
                            "platform": compact(link.get("platform"), 80),
                            "host": compact(link.get("host"), 160),
                            "canonical_url_key_hash": compact(link.get("canonical_url_key_hash"), 80),
                            "payload_hash": compact(link.get("payload_hash"), 80),
                        }
                        for link in link_rows
                    ],
                    "serving_graph": {
                        "event_edges": row["serving_event_edges"],
                        "relation_edges": row["serving_relation_edges"],
                        "graph_window_node_count": row["graph_window_node_count"],
                        "graph_window_edge_count": row["graph_window_edge_count"],
                    },
                    "write_status": "report_only",
                },
            }
        )
    return samples


def build_api_contract(
    entity_rows: list[dict[str, Any]],
    platform_rows: list[dict[str, Any]],
    counts: dict[str, int],
    outputs: dict[str, str],
    generated_at: str,
) -> dict[str, Any]:
    top_entities = [
        {
            "dj_id": row["entity_id"],
            "display_name": row["display_name"],
            "social_link_count": row["overlay_candidate_rows"],
            "platforms": row["platforms"][:8],
            "graph_window_node_count": row["graph_window_node_count"],
        }
        for row in entity_rows
        if not row["attach_failures"]
    ][:12]
    return {
        "schema_version": SCHEMA_VERSION + ".api_contract",
        "generated_at": generated_at,
        "report_only": True,
        "overview_counts": counts,
        "routes": [
            {"route_id": "social_overview", "method": "GET", "path": "/atlas/social/overview", "write_status": "report_only"},
            {"route_id": "dj_social_detail", "method": "GET", "path": "/atlas/dj/{dj_id}/social", "sample_dj_ids": [row["dj_id"] for row in top_entities], "write_status": "report_only"},
            {"route_id": "social_search", "method": "GET", "path": "/atlas/search?has_social=true", "write_status": "report_only"},
            {"route_id": "graph_with_social", "method": "GET", "path": "/atlas/graph/{dj_id}?include=social", "sample_dj_ids": [row["dj_id"] for row in top_entities[:8]], "write_status": "report_only"},
            {"route_id": "social_platform_facet", "method": "GET", "path": "/atlas/social/platforms/{platform}", "sample_platforms": [row["platform"] for row in platform_rows[:12]], "write_status": "report_only"},
        ],
        "search_facets": {
            "by_platform": {row["platform"]: row["link_rows"] for row in platform_rows[:50]},
            "by_host": {row["host"]: row["link_rows"] for row in platform_rows[:50]},
        },
        "top_social_djs": top_entities,
        "outputs": outputs,
        "write_guards": {
            "accepted_for_graph": False,
            "source_raw_db_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
    }


def collect_counts(
    conn: sqlite3.Connection,
    entity_rows: list[dict[str, Any]],
    platform_rows: list[dict[str, Any]],
) -> dict[str, int]:
    attach_failure_rows = [row for row in entity_rows if row["attach_failures"]]
    write_guard_open_rows = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM social_overlay.atlas_dj_social_links
            WHERE accepted_for_graph<>0 OR source_raw_db_write_executed<>0
               OR serving_rebuild_allowed<>0 OR public_serving_field_allowed<>0
            """
        ).fetchone()[0]
    )
    links_without_rollup = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM social_overlay.atlas_dj_social_links l
            LEFT JOIN social_overlay.atlas_dj_social_entity_rollups r ON r.entity_id=l.entity_id
            WHERE r.entity_id IS NULL
            """
        ).fetchone()[0]
    )
    duplicate_selector_groups = int(
        conn.execute(
            """
            SELECT COUNT(*)
            FROM (
              SELECT entity_id, candidate_kind, canonical_url_key_hash, platform, COUNT(*) AS c
              FROM social_overlay.atlas_dj_social_links
              GROUP BY entity_id, candidate_kind, canonical_url_key_hash, platform
              HAVING c > 1
            )
            """
        ).fetchone()[0]
    )
    return {
        "overlay_link_rows": int(conn.execute("SELECT COUNT(*) FROM social_overlay.atlas_dj_social_links").fetchone()[0]),
        "overlay_rollup_rows": int(conn.execute("SELECT COUNT(*) FROM social_overlay.atlas_dj_social_entity_rollups").fetchone()[0]),
        "overlay_unique_entity_ids": int(conn.execute("SELECT COUNT(DISTINCT entity_id) FROM social_overlay.atlas_dj_social_links").fetchone()[0]),
        "overlay_profile_rows": int(conn.execute("SELECT COUNT(*) FROM social_overlay.atlas_dj_social_links WHERE candidate_kind='profile'").fetchone()[0]),
        "overlay_outlink_rows": int(conn.execute("SELECT COUNT(*) FROM social_overlay.atlas_dj_social_links WHERE candidate_kind='outlink'").fetchone()[0]),
        "platform_host_rows": len(platform_rows),
        "distinct_platforms": len({row["platform"] for row in platform_rows}),
        "distinct_hosts": len({row["host"] for row in platform_rows}),
        "serving_dj_profile_matched_rows": sum(1 for row in entity_rows if row["display_name"]),
        "serving_search_doc_matched_rows": sum(1 for row in entity_rows if row["search_document_found"]),
        "serving_graph_window_matched_rows": sum(1 for row in entity_rows if row["graph_window_found"]),
        "serving_event_edges_for_social_entities": sum(row["serving_event_edges"] for row in entity_rows),
        "serving_relation_edges_for_social_entities": sum(row["serving_relation_edges"] for row in entity_rows),
        "attach_ready_entity_rows": len(entity_rows) - len(attach_failure_rows),
        "attach_blocked_entity_rows": len(attach_failure_rows),
        "links_without_rollup_rows": links_without_rollup,
        "duplicate_selector_groups": duplicate_selector_groups,
        "write_guard_open_rows": write_guard_open_rows,
        "accepted_for_graph_rows": 0,
        "source_raw_db_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }


def build_schema_snapshot(conn: sqlite3.Connection, serving_db: Path, overlay_db: Path) -> dict[str, Any]:
    serving_tables = table_names(conn, "main")
    overlay_tables = table_names(conn, "social_overlay")
    return {
        "serving_db": display_path(serving_db),
        "overlay_db": display_path(overlay_db),
        "serving_db_opened_read_only": True,
        "overlay_db_attached_read_only": True,
        "serving_sqlite_quick_check": "skipped_large_read_only_serving_db",
        "serving_sqlite_quick_check_reason": "selected serving DB is multi-GB; attach smoke uses required-table and join-coverage checks instead of a full physical scan",
        "overlay_sqlite_quick_check": conn.execute("PRAGMA social_overlay.quick_check").fetchone()[0],
        "serving_required_tables_present": sorted(REQUIRED_SERVING_TABLES.intersection(serving_tables)),
        "serving_required_tables_missing": sorted(REQUIRED_SERVING_TABLES - serving_tables),
        "overlay_required_tables_present": sorted(REQUIRED_OVERLAY_TABLES.intersection(overlay_tables)),
        "overlay_required_tables_missing": sorted(REQUIRED_OVERLAY_TABLES - overlay_tables),
        "serving_table_columns": {table: table_columns(conn, table, "main") for table in sorted(REQUIRED_SERVING_TABLES.intersection(serving_tables))},
        "overlay_table_columns": {table: table_columns(conn, table, "social_overlay") for table in sorted(REQUIRED_OVERLAY_TABLES.intersection(overlay_tables))},
    }


def build_packet(serving_db: Path, overlay_db: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    generated_at = now_iso()
    reject_unbounded_d_root(out_dir, "out_dir")
    reject_unbounded_d_root(report_path, "report_path")
    out_dir.mkdir(parents=True, exist_ok=True)

    with connect_serving_with_overlay(serving_db, overlay_db) as conn:
        schema_snapshot = build_schema_snapshot(conn, serving_db, overlay_db)
        metadata = read_metadata(conn)
        failed_checks: list[str] = []
        if schema_snapshot["overlay_sqlite_quick_check"] != "ok":
            failed_checks.append("overlay_db_quick_check_failed")
        if schema_snapshot["serving_required_tables_missing"]:
            failed_checks.append("serving_required_tables_missing")
        if schema_snapshot["overlay_required_tables_missing"]:
            failed_checks.append("overlay_required_tables_missing")

        entity_rows = build_entity_rows(conn, generated_at) if not failed_checks else []
        platform_rows = build_platform_rows(conn, generated_at) if not failed_checks else []
        counts = collect_counts(conn, entity_rows, platform_rows) if not failed_checks else {
            "overlay_link_rows": 0,
            "overlay_rollup_rows": 0,
            "overlay_unique_entity_ids": 0,
            "overlay_profile_rows": 0,
            "overlay_outlink_rows": 0,
            "platform_host_rows": 0,
            "distinct_platforms": 0,
            "distinct_hosts": 0,
            "serving_dj_profile_matched_rows": 0,
            "serving_search_doc_matched_rows": 0,
            "serving_graph_window_matched_rows": 0,
            "serving_event_edges_for_social_entities": 0,
            "serving_relation_edges_for_social_entities": 0,
            "attach_ready_entity_rows": 0,
            "attach_blocked_entity_rows": 0,
            "links_without_rollup_rows": 0,
            "duplicate_selector_groups": 0,
            "write_guard_open_rows": 0,
            "accepted_for_graph_rows": 0,
            "source_raw_db_write_allowed_rows": 0,
            "serving_rebuild_allowed_rows": 0,
            "graph_write_allowed_rows": 0,
            "public_serving_field_allowed_rows": 0,
            "memory_write_allowed_rows": 0,
        }
        detail_samples = build_detail_samples(entity_rows, conn, generated_at) if not failed_checks else []

    failure_counts = Counter(failure for row in entity_rows for failure in row["attach_failures"])
    if counts["attach_blocked_entity_rows"]:
        failed_checks.append("overlay_entity_attach_blocked_rows_present")
    if counts["links_without_rollup_rows"]:
        failed_checks.append("overlay_links_without_rollup_rows_present")
    if counts["duplicate_selector_groups"]:
        failed_checks.append("overlay_duplicate_selector_groups_present")
    if counts["write_guard_open_rows"]:
        failed_checks.append("overlay_write_guard_open_rows_present")

    entity_rows_path = out_dir / "overlay_entity_attach_rows.jsonl"
    ready_rows_path = out_dir / "overlay_entity_attach_ready_report_only.jsonl"
    blocked_rows_path = out_dir / "overlay_entity_attach_blocked_rows.jsonl"
    platform_rows_path = out_dir / "overlay_platform_rollup.jsonl"
    detail_samples_path = out_dir / "overlay_social_api_detail_samples.jsonl"
    api_contract_path = out_dir / "overlay_social_api_contract.json"
    schema_snapshot_path = out_dir / "overlay_serving_schema_snapshot.json"
    summary_path = out_dir / "overlay_serving_attach_smoke_summary.json"
    summary_md_path = out_dir / "overlay_serving_attach_smoke_summary.md"

    outputs = {
        "entity_attach_rows": display_path(entity_rows_path),
        "entity_attach_ready_rows": display_path(ready_rows_path),
        "entity_attach_blocked_rows": display_path(blocked_rows_path),
        "platform_rollup": display_path(platform_rows_path),
        "detail_samples": display_path(detail_samples_path),
        "api_contract": display_path(api_contract_path),
        "schema_snapshot": display_path(schema_snapshot_path),
        "summary_json": display_path(summary_path),
        "summary_md": display_path(summary_md_path),
        "report": display_path(report_path),
    }
    api_contract = build_api_contract(entity_rows, platform_rows, counts, outputs, generated_at)
    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    for payload in (schema_snapshot, metadata, entity_rows, platform_rows, detail_samples, api_contract):
        add_leak_counts(leak_counts, payload)
    if any(leak_counts.values()):
        failed_checks.append("overlay_attach_payload_leak_scan_hits")

    ready_rows = [row for row in entity_rows if not row["attach_failures"]]
    blocked_rows = [row for row in entity_rows if row["attach_failures"]]
    decision = (
        "atlas_t6_sidecar_overlay_serving_attach_smoke_ready_report_only"
        if not failed_checks
        else "atlas_t6_sidecar_overlay_serving_attach_smoke_blocked_report_only"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed_checks)),
        "inputs": {
            "serving_db": display_path(serving_db),
            "serving_db_mode": "read_only",
            "overlay_db": display_path(overlay_db),
            "overlay_db_mode": "attached_read_only",
        },
        "outputs": outputs,
        "counts": counts,
        "attach_failure_counts": dict(sorted(failure_counts.items())),
        "leak_counts": leak_counts,
        "write_guards": {
            "accepted_for_graph": False,
            "source_raw_db_write_allowed": False,
            "source_raw_db_write_executed": False,
            "serving_sqlite_write_executed": False,
            "serving_rebuild_allowed": False,
            "serving_rebuild_executed": False,
            "graph_write_allowed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "public_serving_field_allowed": False,
            "public_pointer_updated": False,
            "huaidj_club_upload_executed": False,
            "mini_program_upload_or_review_executed": False,
            "memory_write_allowed": False,
            "memory_write_executed": False,
        },
        "safety": {
            "report_only": True,
            "serving_sqlite_opened_read_only": True,
            "overlay_sqlite_attached_read_only": True,
            "source_raw_db_opened": False,
            "source_raw_db_write_executed": False,
            "serving_sqlite_rebuild_executed": False,
            "graph_fact_acceptance_executed": False,
            "network_call_executed": False,
            "model_call_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "public_pointer_updated": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "metadata": {
            "overlay_schema_version": metadata.get("schema_version"),
            "overlay_source_raw_target_schema_hash": metadata.get("source_raw_target_schema_hash"),
            "overlay_source_raw_db_write_executed": metadata.get("source_raw_db_write_executed"),
            "overlay_serving_rebuild_executed": metadata.get("serving_rebuild_executed"),
            "overlay_graph_vector_public_write_executed": metadata.get("graph_vector_public_write_executed"),
        },
        "next_resume_pointer": outputs["api_contract"] if not failed_checks else outputs["entity_attach_blocked_rows"],
        "stop_reason": "overlay_serving_attach_smoke_ready_report_only_write_gates_still_closed"
        if not failed_checks
        else "overlay_serving_attach_smoke_blocked_report_only",
        "wait_reason": "This proves local serving/search/API attach behavior only; source/raw schema migration, serving rebuild, graph/vector/public writes, and huaidj.club upload require a later explicit gate.",
    }

    write_jsonl(entity_rows_path, entity_rows)
    write_jsonl(ready_rows_path, ready_rows)
    write_jsonl(blocked_rows_path, blocked_rows)
    write_jsonl(platform_rows_path, platform_rows)
    write_jsonl(detail_samples_path, detail_samples)
    write_json(api_contract_path, api_contract)
    write_json(schema_snapshot_path, schema_snapshot)
    write_json(summary_path, summary)
    write_text(summary_md_path, render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_counts"]
    return "\n".join(
        [
            "# Atlas T5/T6 Sidecar Overlay Serving Attach Smoke Summary",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            f"- Overlay links / rollups / entities: `{counts['overlay_link_rows']}/{counts['overlay_rollup_rows']}/{counts['overlay_unique_entity_ids']}`",
            f"- Serving profile/search/graph matches: `{counts['serving_dj_profile_matched_rows']}/{counts['serving_search_doc_matched_rows']}/{counts['serving_graph_window_matched_rows']}`",
            f"- Platform/host rows: `{counts['platform_host_rows']}`; distinct platforms/hosts `{counts['distinct_platforms']}/{counts['distinct_hosts']}`",
            f"- Ready/blocked entity rows: `{counts['attach_ready_entity_rows']}/{counts['attach_blocked_entity_rows']}`",
            f"- Write guard open rows / duplicate selector groups / links without rollup: `{counts['write_guard_open_rows']}/{counts['duplicate_selector_groups']}/{counts['links_without_rollup_rows']}`",
            f"- Leak hits public/sensitive/local: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
            f"- Next resume pointer: `{summary['next_resume_pointer']}`",
            "",
        ]
    )


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_counts"]
    outputs = summary["outputs"]
    return "\n".join(
        [
            "# Atlas T5/T6 Sidecar Overlay Serving Attach Smoke - 2026-05-26",
            "",
            "## Decision",
            "",
            f"- Decision: `{summary['decision']}`",
            f"- Failed checks: `{json.dumps(summary['failed_checks'], ensure_ascii=False)}`",
            "- LLM audit finding: source/raw DB has no native social tables, so the next high-leverage production step is to prove the report-local overlay can attach to selected serving/search/API read models before any schema migration.",
            "",
            "## Evidence",
            "",
            f"- Serving DB: `{summary['inputs']['serving_db']}` opened read-only.",
            f"- Overlay DB: `{summary['inputs']['overlay_db']}` attached read-only.",
            f"- Overlay links / rollups / entities: `{counts['overlay_link_rows']}/{counts['overlay_rollup_rows']}/{counts['overlay_unique_entity_ids']}`.",
            f"- Overlay profile/outlink rows: `{counts['overlay_profile_rows']}/{counts['overlay_outlink_rows']}`.",
            f"- Serving profile/search/graph matches: `{counts['serving_dj_profile_matched_rows']}/{counts['serving_search_doc_matched_rows']}/{counts['serving_graph_window_matched_rows']}`.",
            f"- Serving event/relation edges for social entities: `{counts['serving_event_edges_for_social_entities']}/{counts['serving_relation_edges_for_social_entities']}`.",
            f"- Platform/host rows: `{counts['platform_host_rows']}`; distinct platforms/hosts `{counts['distinct_platforms']}/{counts['distinct_hosts']}`.",
            f"- Ready/blocked entity rows: `{counts['attach_ready_entity_rows']}/{counts['attach_blocked_entity_rows']}`.",
            f"- Duplicate selector groups / links without rollup / open write guards: `{counts['duplicate_selector_groups']}/{counts['links_without_rollup_rows']}/{counts['write_guard_open_rows']}`.",
            f"- Leak hits public_url/sensitive_key/local_path: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`.",
            "",
            "## Outputs",
            "",
            f"- Summary JSON: `{outputs['summary_json']}`",
            f"- API contract: `{outputs['api_contract']}`",
            f"- Entity attach rows: `{outputs['entity_attach_rows']}`",
            f"- Platform rollup: `{outputs['platform_rollup']}`",
            f"- Detail samples: `{outputs['detail_samples']}`",
            f"- Schema snapshot: `{outputs['schema_snapshot']}`",
            "",
            "## Boundary",
            "",
            "- This is report-only local serving/search/API attach evidence.",
            "- It does not mutate source/raw Atlas DB, rebuild or write serving SQLite, accept graph facts, write Neo4j/Qdrant/production SQLite, update public pointer, upload huaidj.club, upload/review mini-program, write memory, read credentials, use 9router, call network/model APIs, run destructive Git, or scan D: roots.",
            "",
            "## Next Resume Pointer",
            "",
            f"`{summary['next_resume_pointer']}`",
            "",
            "Next gate: use the API contract as the input to a report-local serving-read-model candidate or schema migration packet. Public huaidj.club upload remains disabled until explicitly re-enabled.",
            "",
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--overlay-db", type=Path, default=DEFAULT_OVERLAY_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_packet(args.serving_db, args.overlay_db, args.out_dir, args.report)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "failed_checks": summary["failed_checks"],
                "summary": summary["outputs"]["summary_json"],
                "report": summary["outputs"]["report"],
                "next_resume_pointer": summary["next_resume_pointer"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not summary["failed_checks"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
