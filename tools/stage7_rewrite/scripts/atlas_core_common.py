from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "atlas_core.v1"
COMPAT_SCHEMA_VERSION = "atlas_legacy_compat.v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def text(value: Any, limit: int | None = None) -> str:
    if value is None:
        return ""
    out = str(value)
    if limit is not None and len(out) > limit:
        return out[:limit]
    return out


def number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def integer(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_loads(value: Any, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json_dumps(row) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def write_gzip_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    with gzip.open(path, "wb") as fh:
        fh.write(raw)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=? LIMIT 1", (table,)).fetchone()
    return row is not None


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    if not table_exists(conn, table):
        return []
    return [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')]


def row_count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] or 0)


def connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def connect_rw(path: Path) -> sqlite3.Connection:
    ensure_parent(path)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def has_leak_value(value: Any) -> bool:
    raw = json_dumps(value) if isinstance(value, (dict, list)) else text(value)
    lowered = raw.casefold()
    tokens = [
        "http://",
        "https://",
        ".env",
        "cookie",
        "token=",
        "password",
        "secret",
        "c:\\users\\",
        "\\\\wsl",
        "/mnt/c/",
        "/home/",
    ]
    return any(token in lowered for token in tokens)


def leak_count_rows(rows: Iterable[Any]) -> int:
    return sum(1 for row in rows if has_leak_value(row))


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def default_reports_root() -> Path:
    return default_repo_root() / "reports"


def default_stage7_reports_root() -> Path:
    return Path(__file__).resolve().parents[1] / "reports"


def create_core_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = MEMORY;

        CREATE TABLE core_entity (
          entity_id TEXT PRIMARY KEY,
          entity_type TEXT NOT NULL,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL DEFAULT '[]',
          primary_city TEXT,
          country_code TEXT,
          public_state TEXT NOT NULL DEFAULT 'candidate',
          confidence REAL NOT NULL DEFAULT 0,
          first_seen_at TEXT,
          last_seen_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE entity_legacy_id (
          entity_id TEXT NOT NULL,
          canonical_entity_id TEXT NOT NULL,
          legacy_layer TEXT NOT NULL,
          legacy_table TEXT NOT NULL,
          legacy_id TEXT NOT NULL,
          legacy_name TEXT,
          source_report TEXT,
          is_primary INTEGER NOT NULL DEFAULT 0,
          valid_from TEXT,
          valid_to TEXT,
          PRIMARY KEY (legacy_layer, legacy_table, legacy_id)
        );

        CREATE TABLE core_source_ref (
          source_ref_id TEXT PRIMARY KEY,
          source_hash TEXT NOT NULL,
          source_account TEXT,
          source_title TEXT,
          post_date TEXT,
          source_kind TEXT,
          public_snippet TEXT,
          public_url_allowed INTEGER NOT NULL DEFAULT 0,
          source_url_hash TEXT,
          raw_url_redacted TEXT,
          evidence_level TEXT,
          credential_required INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE core_event (
          event_id TEXT PRIMARY KEY,
          event_title TEXT NOT NULL,
          starts_at TEXT,
          time_text TEXT,
          venue_entity_id TEXT,
          venue_legacy_id TEXT,
          venue_name TEXT,
          city TEXT,
          source_ref_id TEXT,
          confidence REAL NOT NULL DEFAULT 0,
          public_state TEXT NOT NULL DEFAULT 'candidate',
          raw_event_id TEXT
        );

        CREATE TABLE entity_event_edge (
          entity_id TEXT NOT NULL,
          event_id TEXT NOT NULL,
          role TEXT NOT NULL,
          confidence REAL NOT NULL DEFAULT 0,
          source_ref_id TEXT,
          first_seen_at TEXT,
          last_seen_at TEXT,
          PRIMARY KEY (entity_id, event_id, role, source_ref_id)
        );

        CREATE TABLE entity_relation_edge (
          src_entity_id TEXT NOT NULL,
          dst_entity_id TEXT NOT NULL,
          relation_type TEXT NOT NULL,
          same_event_count INTEGER NOT NULL DEFAULT 0,
          same_label_count INTEGER NOT NULL DEFAULT 0,
          same_venue_count INTEGER NOT NULL DEFAULT 0,
          same_source_context_count INTEGER NOT NULL DEFAULT 0,
          source_diversity INTEGER NOT NULL DEFAULT 0,
          relation_score REAL NOT NULL DEFAULT 0,
          relation_label_zh TEXT,
          sample_evidence_json TEXT NOT NULL DEFAULT '[]',
          public_state TEXT NOT NULL DEFAULT 'candidate',
          PRIMARY KEY (src_entity_id, dst_entity_id, relation_type)
        );

        CREATE TABLE external_link_evidence (
          link_id TEXT PRIMARY KEY,
          entity_id TEXT NOT NULL,
          platform TEXT,
          canonical_url_key_hash TEXT,
          url_hash TEXT,
          link_kind TEXT,
          public_category TEXT,
          confidence_score REAL NOT NULL DEFAULT 0,
          confidence_band TEXT,
          validation_status TEXT,
          merge_status TEXT NOT NULL,
          source_context_verified INTEGER NOT NULL DEFAULT 0,
          accepted_for_graph INTEGER NOT NULL DEFAULT 0,
          source_ref_id TEXT
        );

        CREATE TABLE identity_resolution_case (
          case_id TEXT PRIMARY KEY,
          group_id TEXT,
          normalized_name TEXT,
          candidate_entity_ids_json TEXT NOT NULL DEFAULT '[]',
          lane TEXT,
          approval_status TEXT,
          proposed_disposition TEXT,
          required_before_write_json TEXT NOT NULL DEFAULT '[]',
          approved_gate_id TEXT,
          reviewer TEXT,
          review_note TEXT
        );

        CREATE TABLE projection_event_log (
          projection_id TEXT PRIMARY KEY,
          from_layer TEXT NOT NULL,
          to_layer TEXT NOT NULL,
          source_dataset_id TEXT,
          action TEXT NOT NULL,
          gate_id TEXT,
          before_hash TEXT,
          after_hash TEXT,
          readback_status TEXT,
          rollback_ref TEXT
        );

        CREATE TABLE compat_activity_event_detail (
          event_id TEXT PRIMARY KEY,
          source_event_id TEXT,
          publish_package TEXT,
          title TEXT,
          event_date_start TEXT,
          event_date_end TEXT,
          event_time_text TEXT,
          time_start TEXT,
          time_end TEXT,
          venue_name TEXT,
          venue_id TEXT,
          address TEXT,
          city_name TEXT,
          lineup_artists_json TEXT,
          music_styles_json TEXT,
          genres_json TEXT,
          price_json TEXT,
          ticketing_text TEXT,
          source_ref_id TEXT,
          source_hash TEXT,
          source_account_name TEXT,
          source_published_at TEXT,
          generated_at TEXT
        );

        CREATE TABLE compat_activity_evidence_ref (
          evidence_ref_id TEXT PRIMARY KEY,
          event_id TEXT,
          field_path TEXT,
          field_value TEXT,
          support_type TEXT,
          source_kind TEXT,
          source_ref_id TEXT,
          source_hash TEXT,
          source_account_name TEXT,
          source_published_at TEXT,
          quote TEXT,
          quote_policy TEXT,
          ocr_span_id TEXT,
          ocr_span_status TEXT,
          confidence REAL,
          created_at TEXT
        );

        CREATE TABLE compat_graph_window_cache (
          window_key TEXT PRIMARY KEY,
          seed_subject_id TEXT NOT NULL,
          lens TEXT NOT NULL,
          depth INTEGER NOT NULL,
          node_count INTEGER NOT NULL DEFAULT 0,
          edge_count INTEGER NOT NULL DEFAULT 0,
          nodes_json TEXT NOT NULL,
          edges_json TEXT NOT NULL,
          generated_at TEXT NOT NULL
        );

        CREATE TABLE compat_canonical_subject (
          subject_id TEXT PRIMARY KEY,
          subject_type TEXT NOT NULL,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          taxon_path TEXT NOT NULL,
          aliases_json TEXT NOT NULL,
          city_primary TEXT,
          confidence REAL NOT NULL DEFAULT 0,
          source_count INTEGER NOT NULL DEFAULT 0,
          event_count INTEGER NOT NULL DEFAULT 0,
          relation_count INTEGER NOT NULL DEFAULT 0,
          first_seen_at TEXT,
          last_seen_at TEXT,
          public_state TEXT NOT NULL
        );

        CREATE TABLE compat_dj_profile (
          dj_id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          aliases_json TEXT NOT NULL,
          city_primary TEXT,
          avatar_asset_id TEXT,
          source_article_count INTEGER NOT NULL DEFAULT 0,
          event_count INTEGER NOT NULL DEFAULT 0,
          venue_count INTEGER NOT NULL DEFAULT 0,
          collaborator_count INTEGER NOT NULL DEFAULT 0,
          organization_count INTEGER NOT NULL DEFAULT 0,
          media_count INTEGER NOT NULL DEFAULT 0,
          first_seen_at TEXT,
          last_seen_at TEXT,
          confidence REAL NOT NULL DEFAULT 0
        );

        CREATE TABLE compat_search_document (
          doc_rowid INTEGER PRIMARY KEY,
          subject_id TEXT NOT NULL,
          subject_type TEXT NOT NULL,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          aliases_text TEXT,
          city_text TEXT,
          taxon_path TEXT NOT NULL,
          rank_score REAL NOT NULL DEFAULT 0,
          last_seen_at TEXT,
          public_state TEXT NOT NULL,
          search_text TEXT NOT NULL
        );

        CREATE TABLE compat_dj_org_rollup (
          dj_id TEXT NOT NULL,
          org_id TEXT NOT NULL,
          org_name TEXT NOT NULL,
          org_type TEXT NOT NULL,
          evidence_count INTEGER NOT NULL DEFAULT 0,
          score REAL NOT NULL DEFAULT 0,
          sample_evidence_json TEXT NOT NULL,
          PRIMARY KEY (dj_id, org_id)
        );

        CREATE TABLE dataset_manifest (
          dataset_id TEXT PRIMARY KEY,
          schema_version TEXT NOT NULL,
          compat_schema_version TEXT NOT NULL,
          source_snapshots_json TEXT NOT NULL,
          counts_json TEXT NOT NULL,
          sha256_json TEXT NOT NULL,
          decision TEXT NOT NULL,
          generated_at TEXT NOT NULL
        );

        CREATE INDEX idx_core_entity_type_name ON core_entity(entity_type, normalized_name);
        CREATE INDEX idx_entity_legacy_id_canonical ON entity_legacy_id(canonical_entity_id);
        CREATE INDEX idx_entity_legacy_id_lookup ON entity_legacy_id(legacy_layer, legacy_table, legacy_id);
        CREATE INDEX idx_core_event_venue ON core_event(venue_entity_id, starts_at);
        CREATE INDEX idx_entity_event_entity ON entity_event_edge(entity_id, event_id);
        CREATE INDEX idx_entity_relation_src_score ON entity_relation_edge(src_entity_id, relation_score DESC);
        CREATE INDEX idx_external_link_entity ON external_link_evidence(entity_id, platform);
        CREATE INDEX idx_identity_resolution_lane ON identity_resolution_case(lane, approval_status);
        CREATE INDEX idx_compat_activity_evidence_event ON compat_activity_evidence_ref(event_id);
        CREATE INDEX idx_compat_graph_window_seed ON compat_graph_window_cache(seed_subject_id, depth, node_count);
        CREATE INDEX idx_compat_canonical_subject_type ON compat_canonical_subject(subject_type, normalized_name);
        CREATE INDEX idx_compat_dj_profile_name ON compat_dj_profile(normalized_name);
        CREATE INDEX idx_compat_search_document_subject ON compat_search_document(subject_id, rank_score DESC);
        CREATE INDEX idx_compat_search_document_type ON compat_search_document(subject_type, rank_score DESC);
        CREATE INDEX idx_compat_dj_org_rollup_org ON compat_dj_org_rollup(org_id, score DESC);
        """
    )


def add_common_args(parser: argparse.ArgumentParser) -> None:
    reports_root = default_reports_root()
    stage7_reports_root = default_stage7_reports_root()
    repo_root = default_repo_root()
    parser.add_argument("--db1", type=Path, default=reports_root / "atlas_incremental_wechat_refresh_20260522_1438" / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435" / "atlas.sqlite")
    parser.add_argument("--db2", type=Path, default=reports_root / "atlas_serving_time_overlay_span_split_search_date_refresh_candidate_20260527_2018" / "atlas_serving.sqlite")
    parser.add_argument("--db3", type=Path, default=repo_root / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite")
    parser.add_argument("--external-link-sidecar", type=Path, default=stage7_reports_root / "external_link_db2_sidecar_contract_s119_20260601" / "external_link_db2_sidecar.sqlite")
    parser.add_argument("--s232d3b8-candidates", type=Path, default=stage7_reports_root / "atlas_relation_identity_s232d3b8_candidate_preflight_20260603" / "s232d3b8_candidate_rows.jsonl")
