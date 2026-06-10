#!/usr/bin/env python3
"""Build a report-local Atlas DJ social overlay DB from validated T6 sidecar rows.

This is the first DB-writing step after the T6 sidecar validation gate, but it
does not mutate the source/raw Atlas DB, serving SQLite, graph stores, vector
stores, or public state. The output is a small report-local SQLite overlay that
can be attached by the later new-Atlas-DB merge/rebuild lane.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_VALIDATION_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_manifest_validation_gate_t5_t6_20260526"
DEFAULT_TARGET_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_sidecar_new_db_overlay_t5_t6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_T6_SIDECAR_NEW_DB_OVERLAY_20260526.md"
SCHEMA_VERSION = "stage7_atlas_t6_sidecar_new_db_overlay.v1"
INPUT_CONTRACT_SCHEMA = "stage7_atlas_t6_sidecar_manifest_validation_gate.v1.merge_contract"
OVERLAY_DB_NAME = "atlas_t6_sidecar_social_overlay.sqlite"

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

NATIVE_SOCIAL_TABLE_CANDIDATES = {
    "atlas_dj_social_links",
    "atlas_dj_social_profiles",
    "entity_external_links",
    "external_links",
    "dj_social_links",
    "dj_social_profiles",
}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def sanitize_identifier(value: str) -> str:
    if SECRET_KEY_RE.search(value):
        return f"redacted_identifier_sha12_{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}"
    return value


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


def stable_hash(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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
                raise ValueError(f"{path}:{line_no}: expected JSON object row")
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
        total[key] += value


def connect_readonly(path: Path, label: str = "target_db") -> sqlite3.Connection:
    reject_unbounded_d_root(path, label)
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def target_schema_snapshot(target_db: Path) -> dict[str, Any]:
    conn = connect_readonly(target_db, "target_db")
    try:
        tables = [str(row["name"]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        table_columns: dict[str, list[dict[str, str]]] = {}
        for table in tables:
            if table.startswith("sqlite_") or table.endswith("_fts_data") or table.endswith("_fts_idx"):
                continue
            cols = [
                {"name": sanitize_identifier(str(row["name"])), "type": str(row["type"])}
                for row in conn.execute(f'PRAGMA table_info("{table}")')
            ]
            table_columns[sanitize_identifier(table)] = cols
        quick_check = str(conn.execute("PRAGMA quick_check").fetchone()[0])
        page_count = int(conn.execute("PRAGMA page_count").fetchone()[0])
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
    finally:
        conn.close()

    stat = target_db.stat()
    native_social_tables = sorted(NATIVE_SOCIAL_TABLE_CANDIDATES.intersection(tables))
    sanitized_tables = [sanitize_identifier(table) for table in tables]
    sanitized_native_social_tables = [sanitize_identifier(table) for table in native_social_tables]
    return {
        "target_db": display_path(target_db),
        "target_db_exists": True,
        "target_db_opened_read_only": True,
        "target_db_size_bytes": int(stat.st_size),
        "target_db_mtime_utc": datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(timespec="seconds"),
        "sqlite_quick_check": quick_check,
        "sqlite_page_count": page_count,
        "sqlite_page_size": page_size,
        "table_count": len(tables),
        "tables": sanitized_tables,
        "table_columns": table_columns,
        "native_social_tables": sanitized_native_social_tables,
        "native_social_table_count": len(native_social_tables),
        "inplace_social_merge_allowed": bool(native_social_tables),
        "target_schema_hash": stable_hash({"tables": sanitized_tables, "table_columns": table_columns}),
    }


def validate_contract(contract: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if contract.get("schema_version") != INPUT_CONTRACT_SCHEMA:
        failures.append("unexpected_merge_contract_schema")
    if contract.get("decision") != "atlas_t6_sidecar_manifest_validation_gate_ready_report_only":
        failures.append("merge_contract_not_validation_ready")
    if contract.get("write_execution_allowed_now") is not False:
        failures.append("upstream_write_execution_unexpectedly_allowed")
    guards = contract.get("write_guards") if isinstance(contract.get("write_guards"), dict) else {}
    if guards.get("source_raw_db_write_executed") is not False or guards.get("serving_rebuild_executed") is not False:
        failures.append("upstream_write_guards_not_closed")
    if contract.get("source_raw_db_target_required") is not True:
        failures.append("source_raw_db_target_not_required_by_contract")
    return failures


def validate_candidates(rows: list[dict[str, Any]]) -> tuple[list[str], dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]:
    failures: list[str] = []
    candidate_id_counts = Counter(str(row.get("candidate_id") or "") for row in rows)
    selector_counts = Counter(
        (
            str(row.get("entity_id") or ""),
            str(row.get("candidate_kind") or ""),
            str(row.get("canonical_url_key") or ""),
            str(row.get("platform") or ""),
        )
        for row in rows
    )
    kind_counts = Counter(str(row.get("candidate_kind") or "") for row in rows)
    duplicate_rows: list[dict[str, Any]] = []
    invalid_rows: list[dict[str, Any]] = []
    for row in rows:
        candidate_id = str(row.get("candidate_id") or "")
        selector = (
            str(row.get("entity_id") or ""),
            str(row.get("candidate_kind") or ""),
            str(row.get("canonical_url_key") or ""),
            str(row.get("platform") or ""),
        )
        row_failures: list[str] = []
        for field in ["candidate_id", "candidate_kind", "canonical_url_key", "entity_id", "host", "platform"]:
            if not str(row.get(field) or "").strip():
                row_failures.append(f"missing_{field}")
        if str(row.get("validation_status") or "") != "merge_precheck_ready_report_only":
            row_failures.append("candidate_not_merge_precheck_ready")
        if row.get("write_execution_allowed_now") is not False:
            row_failures.append("candidate_write_guard_not_closed")
        if any(leak_counts_for(row).values()):
            row_failures.append("candidate_payload_leak")
        if candidate_id_counts[candidate_id] > 1:
            row_failures.append("duplicate_candidate_id")
        if selector_counts[selector] > 1:
            row_failures.append("duplicate_overlay_selector")
        if row_failures:
            invalid = dict(row)
            invalid["overlay_preflight_blockers"] = sorted(set(row_failures))
            invalid_rows.append(invalid)
        if candidate_id_counts[candidate_id] > 1 or selector_counts[selector] > 1:
            duplicate_rows.append(
                {
                    "candidate_id": candidate_id,
                    "entity_id": selector[0],
                    "candidate_kind": selector[1],
                    "canonical_url_key": selector[2],
                    "platform": selector[3],
                    "candidate_id_count": candidate_id_counts[candidate_id],
                    "selector_count": selector_counts[selector],
                }
            )
    if invalid_rows:
        failures.append("invalid_or_duplicate_candidate_rows_present")
    return failures, dict(sorted(kind_counts.items())), duplicate_rows, invalid_rows


def create_overlay_db(
    overlay_db: Path,
    rows: list[dict[str, Any]],
    entity_rollups: list[dict[str, Any]],
    schema_snapshot: dict[str, Any],
    contract: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    overlay_db.parent.mkdir(parents=True, exist_ok=True)
    if overlay_db.exists():
        overlay_db.unlink()
    conn = sqlite3.connect(overlay_db)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            """
            CREATE TABLE atlas_overlay_metadata (
              key TEXT PRIMARY KEY,
              value_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE atlas_dj_social_links (
              candidate_id TEXT PRIMARY KEY,
              entity_id TEXT NOT NULL,
              candidate_kind TEXT NOT NULL,
              platform TEXT NOT NULL,
              host TEXT NOT NULL,
              canonical_url_key TEXT NOT NULL,
              canonical_url_key_hash TEXT NOT NULL,
              validation_status TEXT NOT NULL,
              merge_status TEXT NOT NULL,
              source_context_verified INTEGER NOT NULL DEFAULT 0,
              identity_review_required INTEGER NOT NULL DEFAULT 0,
              avatar_ready INTEGER NOT NULL DEFAULT 0,
              accepted_for_graph INTEGER NOT NULL DEFAULT 0,
              source_raw_db_write_executed INTEGER NOT NULL DEFAULT 0,
              serving_rebuild_allowed INTEGER NOT NULL DEFAULT 0,
              public_serving_field_allowed INTEGER NOT NULL DEFAULT 0,
              payload_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX atlas_dj_social_links_entity_kind_url_platform
            ON atlas_dj_social_links(entity_id, candidate_kind, canonical_url_key, platform)
            """
        )
        conn.execute(
            """
            CREATE TABLE atlas_dj_social_entity_rollups (
              entity_id TEXT PRIMARY KEY,
              candidate_rows INTEGER NOT NULL,
              profile_rows INTEGER NOT NULL,
              outlink_rows INTEGER NOT NULL,
              platforms_json TEXT NOT NULL,
              hosts_json TEXT NOT NULL,
              serving_entity_present INTEGER NOT NULL,
              merge_status TEXT NOT NULL,
              payload_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            )
            """
        )

        metadata = {
            "schema_version": SCHEMA_VERSION + ".sqlite",
            "generated_at": generated_at,
            "source_raw_target_db": schema_snapshot["target_db"],
            "source_raw_target_schema_hash": schema_snapshot["target_schema_hash"],
            "input_contract_decision": contract.get("decision"),
            "source_raw_db_write_executed": False,
            "serving_rebuild_executed": False,
            "graph_vector_public_write_executed": False,
            "huaidj_club_upload_executed": False,
        }
        for key, value in metadata.items():
            conn.execute("INSERT INTO atlas_overlay_metadata VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False, sort_keys=True)))

        conn.executemany(
            """
            INSERT INTO atlas_dj_social_links (
              candidate_id, entity_id, candidate_kind, platform, host,
              canonical_url_key, canonical_url_key_hash, validation_status,
              merge_status, source_context_verified, identity_review_required,
              avatar_ready, accepted_for_graph, source_raw_db_write_executed,
              serving_rebuild_allowed, public_serving_field_allowed, payload_hash, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            [
                (
                    row["candidate_id"],
                    row["entity_id"],
                    row["candidate_kind"],
                    row["platform"],
                    row["host"],
                    row["canonical_url_key"],
                    hashlib.sha256(str(row["canonical_url_key"]).encode("utf-8")).hexdigest(),
                    row.get("validation_status") or "merge_precheck_ready_report_only",
                    "overlay_ready_local_only",
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    stable_hash(row),
                    generated_at,
                )
                for row in rows
            ],
        )

        by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_entity[str(row["entity_id"])].append(row)
        rollup_map = {str(row.get("entity_id") or ""): row for row in entity_rollups}
        rollup_records = []
        for entity_id, entity_rows in sorted(by_entity.items()):
            kind_counts = Counter(str(row.get("candidate_kind") or "") for row in entity_rows)
            platforms = sorted({str(row.get("platform") or "") for row in entity_rows if row.get("platform")})
            hosts = sorted({str(row.get("host") or "") for row in entity_rows if row.get("host")})
            source_rollup = rollup_map.get(entity_id, {})
            payload = {
                "entity_id": entity_id,
                "candidate_rows": len(entity_rows),
                "kind_counts": dict(sorted(kind_counts.items())),
                "platforms": platforms,
                "hosts": hosts,
                "serving_entity_present": bool(source_rollup.get("serving_entity_present", True)),
            }
            rollup_records.append(
                (
                    entity_id,
                    len(entity_rows),
                    int(kind_counts.get("profile", 0)),
                    int(kind_counts.get("outlink", 0)),
                    json.dumps(platforms, ensure_ascii=False, sort_keys=True),
                    json.dumps(hosts, ensure_ascii=False, sort_keys=True),
                    1 if payload["serving_entity_present"] else 0,
                    "overlay_ready_local_only",
                    stable_hash(payload),
                    generated_at,
                )
            )
        conn.executemany(
            """
            INSERT INTO atlas_dj_social_entity_rollups (
              entity_id, candidate_rows, profile_rows, outlink_rows, platforms_json, hosts_json,
              serving_entity_present, merge_status, payload_hash, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            rollup_records,
        )
        conn.commit()

        readback = {
            "sqlite_quick_check": conn.execute("PRAGMA quick_check").fetchone()[0],
            "link_rows": conn.execute("SELECT COUNT(*) FROM atlas_dj_social_links").fetchone()[0],
            "rollup_rows": conn.execute("SELECT COUNT(*) FROM atlas_dj_social_entity_rollups").fetchone()[0],
            "profile_rows": conn.execute("SELECT COUNT(*) FROM atlas_dj_social_links WHERE candidate_kind='profile'").fetchone()[0],
            "outlink_rows": conn.execute("SELECT COUNT(*) FROM atlas_dj_social_links WHERE candidate_kind='outlink'").fetchone()[0],
            "unique_entity_ids": conn.execute("SELECT COUNT(DISTINCT entity_id) FROM atlas_dj_social_links").fetchone()[0],
            "duplicate_selector_rows": conn.execute(
                """
                SELECT COUNT(*) FROM (
                  SELECT entity_id, candidate_kind, canonical_url_key, platform, COUNT(*) AS c
                  FROM atlas_dj_social_links
                  GROUP BY entity_id, candidate_kind, canonical_url_key, platform
                  HAVING c > 1
                )
                """
            ).fetchone()[0],
            "write_guard_open_rows": conn.execute(
                """
                SELECT COUNT(*) FROM atlas_dj_social_links
                WHERE accepted_for_graph<>0 OR source_raw_db_write_executed<>0
                   OR serving_rebuild_allowed<>0 OR public_serving_field_allowed<>0
                """
            ).fetchone()[0],
        }
    finally:
        conn.close()
    readback["overlay_db_sha256"] = file_sha256(overlay_db)
    readback["overlay_db_size_bytes"] = overlay_db.stat().st_size
    return readback


def build_packet(validation_dir: Path, target_db: Path, out_dir: Path, report_path: Path) -> dict[str, Any]:
    generated_at = now_iso()
    reject_unbounded_d_root(validation_dir, "validation_dir")
    reject_unbounded_d_root(target_db, "target_db")
    reject_unbounded_d_root(out_dir, "out_dir")
    out_dir.mkdir(parents=True, exist_ok=True)

    contract = read_json(validation_dir / "merge_contract.json", "merge_contract")
    candidates = read_jsonl(validation_dir / "merge_precheck_ready_candidates.jsonl", "merge_precheck_ready_candidates")
    entity_rollups = read_jsonl(validation_dir / "entity_validation_rollups.jsonl", "entity_validation_rollups")

    leak_counts = {"public_url_hits": 0, "sensitive_key_hits": 0, "local_path_hits": 0}
    add_leak_counts(leak_counts, contract)
    add_leak_counts(leak_counts, candidates)
    add_leak_counts(leak_counts, entity_rollups)

    failed_checks = validate_contract(contract)
    candidate_failures, kind_counts, duplicate_rows, invalid_rows = validate_candidates(candidates)
    failed_checks.extend(candidate_failures)
    if any(leak_counts.values()):
        failed_checks.append("input_payload_leak_hits_present")

    schema_snapshot = target_schema_snapshot(target_db)
    if schema_snapshot.get("sqlite_quick_check") != "ok":
        failed_checks.append("target_db_quick_check_failed")
    schema_blockers: list[dict[str, Any]] = []
    if not schema_snapshot["native_social_tables"]:
        schema_blockers.append(
            {
                "blocker": "source_raw_target_lacks_native_social_link_tables",
                "impact": "inplace source/raw social merge is not safe without an explicit migration",
                "resolution": "use report-local overlay DB now, then create a separate schema migration/serving rebuild gate",
            }
        )

    overlay_db = out_dir / OVERLAY_DB_NAME
    postwrite_readback: dict[str, Any] = {}
    overlay_write_executed = False
    if not failed_checks:
        postwrite_readback = create_overlay_db(overlay_db, candidates, entity_rollups, schema_snapshot, contract, generated_at)
        overlay_write_executed = True
        if postwrite_readback["link_rows"] != len(candidates):
            failed_checks.append("overlay_link_row_count_mismatch")
        if postwrite_readback["duplicate_selector_rows"] != 0:
            failed_checks.append("overlay_duplicate_selector_rows_present")
        if postwrite_readback["write_guard_open_rows"] != 0:
            failed_checks.append("overlay_write_guards_open")
        if postwrite_readback["sqlite_quick_check"] != "ok":
            failed_checks.append("overlay_quick_check_failed")

    validation_blockers = []
    validation_blockers.extend(schema_blockers)
    validation_blockers.extend(invalid_rows[:1000])
    validation_blockers.extend(duplicate_rows[:1000])

    rollback_contract = {
        "schema_version": SCHEMA_VERSION + ".rollback_contract",
        "generated_at": generated_at,
        "rollback_scope": "report_local_overlay_only",
        "source_raw_db_rollback_required": False,
        "rollback_actions": [
            f"delete report-local overlay sqlite `{display_path(overlay_db)}`",
            "delete overlay summary/report artifacts if abandoning this candidate",
        ],
        "post_rollback_verification": [
            "overlay sqlite path absent or regenerated with a new SHA256",
            "source/raw target DB schema hash unchanged",
        ],
    }

    decision = (
        "atlas_t6_sidecar_new_atlas_overlay_db_built_local_only"
        if overlay_write_executed and not failed_checks
        else "atlas_t6_sidecar_new_atlas_overlay_db_blocked_report_only"
    )
    counts = {
        "input_merge_precheck_ready_rows": len(candidates),
        "input_entity_rollup_rows": len(entity_rollups),
        "unique_candidate_entity_ids": len({str(row.get("entity_id") or "") for row in candidates}),
        "profile_candidate_rows": int(kind_counts.get("profile", 0)),
        "outlink_candidate_rows": int(kind_counts.get("outlink", 0)),
        "invalid_candidate_rows": len(invalid_rows),
        "duplicate_candidate_or_selector_rows": len(duplicate_rows),
        "target_table_count": int(schema_snapshot["table_count"]),
        "native_social_table_count": int(schema_snapshot["native_social_table_count"]),
        "schema_blocker_rows": len(schema_blockers),
        "overlay_link_rows": int(postwrite_readback.get("link_rows", 0)),
        "overlay_rollup_rows": int(postwrite_readback.get("rollup_rows", 0)),
        "overlay_unique_entity_ids": int(postwrite_readback.get("unique_entity_ids", 0)),
        "overlay_duplicate_selector_rows": int(postwrite_readback.get("duplicate_selector_rows", 0)),
        "overlay_write_guard_open_rows": int(postwrite_readback.get("write_guard_open_rows", 0)),
    }
    write_guards = {
        "report_local_overlay_sqlite_write_executed": overlay_write_executed,
        "source_raw_db_write_executed": False,
        "serving_sqlite_write_executed": False,
        "serving_rebuild_executed": False,
        "neo4j_write_executed": False,
        "qdrant_write_executed": False,
        "public_pointer_updated": False,
        "huaidj_club_upload_executed": False,
        "mini_program_upload_or_review_executed": False,
        "memory_write_executed": False,
        "write_execution_allowed_now": False,
    }
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": sorted(set(failed_checks)),
        "counts": counts,
        "target_schema": {
            "target_db": schema_snapshot["target_db"],
            "target_db_opened_read_only": schema_snapshot["target_db_opened_read_only"],
            "target_db_size_bytes": schema_snapshot["target_db_size_bytes"],
            "sqlite_quick_check": schema_snapshot["sqlite_quick_check"],
            "target_schema_hash": schema_snapshot["target_schema_hash"],
            "native_social_tables": schema_snapshot["native_social_tables"],
            "inplace_social_merge_allowed": schema_snapshot["inplace_social_merge_allowed"],
        },
        "postwrite_readback": postwrite_readback,
        "leak_scan": leak_counts,
        "write_guards": write_guards,
        "rollback_contract": rollback_contract,
        "paths": {
            "overlay_db": display_path(overlay_db),
            "prewrite_schema_snapshot": display_path(out_dir / "prewrite_schema_snapshot.json"),
            "postwrite_readback": display_path(out_dir / "postwrite_readback.json"),
            "rollback_contract": display_path(out_dir / "rollback_contract.json"),
            "validation_blockers": display_path(out_dir / "validation_blockers.jsonl"),
            "summary": display_path(out_dir / "sidecar_new_db_overlay_summary.json"),
            "report": display_path(report_path),
        },
        "next_resume_pointer": display_path(overlay_db if overlay_write_executed else out_dir / "validation_blockers.jsonl"),
    }

    write_json(out_dir / "prewrite_schema_snapshot.json", schema_snapshot)
    write_json(out_dir / "postwrite_readback.json", postwrite_readback)
    write_json(out_dir / "rollback_contract.json", rollback_contract)
    write_jsonl(out_dir / "validation_blockers.jsonl", validation_blockers)
    write_json(out_dir / "sidecar_new_db_overlay_summary.json", summary)
    write_text(report_path, render_report(summary))
    return summary


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    target = summary["target_schema"]
    readback = summary.get("postwrite_readback") or {}
    failed = summary["failed_checks"]
    leak = summary["leak_scan"]
    lines = [
        "# Atlas T5/T6 Sidecar New DB Overlay",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- failed_checks: `{json.dumps(failed, ensure_ascii=False)}`",
        f"- target_schema_hash: `{target['target_schema_hash']}`",
        "",
        "## Source/Raw Target Provenance",
        "",
        f"- target DB opened read-only: `{target['target_db_opened_read_only']}`",
        f"- target DB size bytes: `{target['target_db_size_bytes']}`",
        f"- SQLite quick_check: `{target['sqlite_quick_check']}`",
        f"- native social tables: `{json.dumps(target['native_social_tables'], ensure_ascii=False)}`",
        f"- in-place social merge allowed now: `{target['inplace_social_merge_allowed']}`",
        "",
        "## Overlay Write",
        "",
        f"- input merge-precheck-ready rows: `{counts['input_merge_precheck_ready_rows']}`",
        f"- input entity rollups: `{counts['input_entity_rollup_rows']}`",
        f"- profile/outlink rows: `{counts['profile_candidate_rows']}/{counts['outlink_candidate_rows']}`",
        f"- unique candidate entity ids: `{counts['unique_candidate_entity_ids']}`",
        f"- overlay DB: `{summary['paths']['overlay_db']}`",
        f"- overlay link/rollup/entity rows: `{counts['overlay_link_rows']}/{counts['overlay_rollup_rows']}/{counts['overlay_unique_entity_ids']}`",
        f"- overlay duplicate selector rows: `{counts['overlay_duplicate_selector_rows']}`",
        f"- overlay write-guard-open rows: `{counts['overlay_write_guard_open_rows']}`",
        f"- overlay DB SHA256: `{readback.get('overlay_db_sha256', '')}`",
        "",
        "## Rollback And Boundary",
        "",
        "- rollback scope: `report_local_overlay_only`; deleting the overlay DB rolls back this slice.",
        "- source/raw Atlas DB writes: `False`",
        "- serving rebuild/write: `False`",
        "- Neo4j/Qdrant/production SQLite/public pointer/huaidj.club/mini-program/memory writes: `False`",
        f"- leak counts public_url/sensitive/local_path: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`",
        "",
        "## Next",
        "",
        f"- next resume pointer: `{summary['next_resume_pointer']}`",
        "- Next gate: attach this overlay to a serving rebuild/new Atlas read-model builder, prove DJ social-link counts/search/graph API behavior, and keep public upload disabled until re-enabled.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validation-dir", type=Path, default=DEFAULT_VALIDATION_DIR)
    parser.add_argument("--target-db", type=Path, default=DEFAULT_TARGET_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    summary = build_packet(args.validation_dir, args.target_db, args.out_dir, args.report)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "failed_checks": summary["failed_checks"],
                "summary": summary["paths"]["summary"],
                "report": summary["paths"]["report"],
                "next_resume_pointer": summary["next_resume_pointer"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if not summary["failed_checks"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
