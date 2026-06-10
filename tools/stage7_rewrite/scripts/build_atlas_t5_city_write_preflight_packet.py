#!/usr/bin/env python3
"""Build a report-only city write-preflight packet for Atlas event rows.

This packet consumes the deterministic venue->city serving candidates and maps
the safe subset back to the explicit source/raw Atlas SQLite target in read-only
mode. It materializes prewrite snapshots, rollback contracts, and postwrite
readback requirements, but it does not execute any mutation.
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
DEFAULT_GAP_DIR = STAGE7_ROOT / "reports" / "atlas_t5_time_city_venue_gap_closure_20260527"
DEFAULT_CANDIDATES = DEFAULT_GAP_DIR / "venue_city_deterministic_candidates.jsonl"
DEFAULT_GAP_SUMMARY = DEFAULT_GAP_DIR / "time_city_venue_gap_closure_summary.json"
DEFAULT_TARGET_DB_PROVENANCE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_source_raw_mapping_probe_q6_20260526"
    / "source_raw_mapping_target_db_provenance_summary.json"
)
DEFAULT_TARGET_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t5_city_write_preflight_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T5_CITY_WRITE_PREFLIGHT_PACKET_20260527.md"
SCHEMA_VERSION = "stage7_atlas_t5_city_write_preflight.v1"

URL_RE = re.compile(r"https?://|www\.", re.I)
SECRET_KEY_RE = re.compile(
    r"(?:\"|')?(?:secret|token|cookie|password|api[_-]?key|authorization|pass_ticket|openid)(?:\"|')?\s*[:=]",
    re.I,
)
SECRET_VALUE_RE = re.compile(
    r"api[_-]?key\s*[:=]|authorization\s*[:=]|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"pass_ticket=|openid=|token\s*[:=]|cookie\s*[:=]|password\s*[:=]",
    re.I,
)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|"
    r"/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = URL_RE.sub("[redacted_url]", text)
    text = LOCAL_PATH_RE.sub("[redacted_path]", text)
    return text[:limit].strip()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def short_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:length]


def row_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8", errors="replace")).hexdigest()


def stable_id(prefix: str, *parts: Any, length: int = 20) -> str:
    raw = "|".join(compact(part, 1000) for part in parts)
    return f"{prefix}:{short_hash(raw, length)}"


def reject_d_root(path: Path, label: str) -> None:
    raw = str(path).replace("\\", "/").casefold()
    if raw in {"d:", "d:/", "/mnt/d", "/mnt/d/"}:
        raise ValueError(f"{label} must not be an unbounded D: root: {path}")
    if raw.startswith("d:/ddownload") or raw.startswith("d:/aidata"):
        raise ValueError(f"{label} must not scan cold D: roots: {path}")
    if raw.startswith("/mnt/d/ddownload") or raw.startswith("/mnt/d/aidata"):
        raise ValueError(f"{label} must not scan cold D: roots: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except Exception:
        return path.name


def read_json(path: Path, label: str) -> dict[str, Any]:
    reject_d_root(path, label)
    value = json.loads(path.read_text(encoding="utf-8-sig", errors="replace"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_d_root(path, label)
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            value = json.loads(stripped)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(value)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(row))
            handle.write("\n")
            count += 1
        tmp = Path(handle.name)
    tmp.replace(path)
    return count


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as handle:
        handle.write(text)
        tmp = Path(handle.name)
    tmp.replace(path)


def normalize_text(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 2000).casefold())


def venue_family(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    oil_tokens = (
        "oil油",
        "oilclub",
        "oil俱乐部",
        "oilmainroom",
        "oilroom",
        "深圳oil",
        "shenzhenoil",
        "车公庙泰然",
        "l111a",
    )
    if text == "oil" or any(token in text for token in oil_tokens) or "l111a" in text.replace("一", "1"):
        return "oil"
    if "dada" in text and ("kunming" in text or "昆明" in text):
        return "dada_kunming"
    if "dada" in text and ("beijing" in text or "北京" in text):
        return "dada_beijing"
    if "zhaodai" in text or "招待" in text:
        return "zhaodai"
    if text in {"all", "allclub", "all俱乐部", "allshanghai"}:
        return "all_shanghai"
    if "abyss" in text:
        return "abyss"
    if "heim" in text:
        return "heim"
    if "system" in text and "shanghai" in text:
        return "system_shanghai"
    if "clubme" in text:
        return "clubme"
    if "coolwave" in text or "酷浪" in text:
        return "coolwaveclub"
    return text


def open_readonly(path: Path) -> sqlite3.Connection:
    reject_d_root(path, "target_db")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def schema_hash(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()
    payload = "\n".join(f"{row['type']}|{row['name']}|{row['sql']}" for row in rows)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f'PRAGMA table_info("{table}")')}


def scan_payload(payload: Any) -> dict[str, int]:
    text = canonical_json(payload)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_KEY_RE.findall(text)) + len(SECRET_VALUE_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def merge_scan(*scans: dict[str, int]) -> dict[str, int]:
    keys = {"public_url_hits", "sensitive_key_hits", "local_path_hits"}
    return {key: sum(int(scan.get(key, 0)) for scan in scans) for key in keys}


def validate_upstream(summary: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if compact(summary.get("decision")) != "atlas_t5_time_city_venue_gap_closure_packet_ready_report_only":
        failures.append("upstream_gap_packet_not_ready")
    if (summary.get("boundary_truth") or {}).get("source_raw_db_opened") is not False:
        failures.append("upstream_gap_packet_source_raw_boundary_drift")
    if (summary.get("counts") or {}).get("venue_city_deterministic_candidate_rows") is None:
        failures.append("upstream_candidate_count_missing")
    return failures


def validate_provenance(provenance: dict[str, Any], target_db: Path) -> tuple[bool, list[str], str]:
    blockers: list[str] = []
    target = provenance.get("target_db") if isinstance(provenance.get("target_db"), dict) else {}
    display = compact(target.get("target_db_display_path"), 500)
    if provenance.get("source_raw_target_db_ready") is not True:
        blockers.append("source_raw_target_db_not_ready_in_provenance_summary")
    if target.get("target_db_exists") is not True:
        blockers.append("target_db_not_existing_in_provenance_summary")
    if not display:
        blockers.append("target_db_display_path_missing")
    elif display_path(target_db) != display.replace("\\", "/"):
        blockers.append("target_db_path_mismatch_against_provenance_summary")
    if not compact(target.get("target_db_sha256"), 128):
        blockers.append("target_db_sha256_missing_in_provenance_summary")
    if compact(provenance.get("decision")) not in {
        "atlas_social_manual_participant_source_raw_target_db_mapping_ready_report_only",
        "atlas_social_manual_participant_source_raw_mapping_probe_ready_report_only",
    }:
        blockers.append("target_db_provenance_decision_not_ready")
    return not blockers, blockers, compact(target.get("target_db_sha256"), 128)


def raw_event_projection(row: sqlite3.Row) -> dict[str, Any]:
    raw_json = row["raw_json"] if "raw_json" in row.keys() else ""
    return {
        "row_pk": int(row["row_pk"]),
        "evid": compact(row["evid"], 120),
        "name": compact(row["name"], 240),
        "place": compact(row["place"], 240),
        "city": compact(row["city"], 120),
        "time_text": compact(row["time_text"], 180),
        "source_article_uid_hash": short_hash(compact(row["source_article_uid"], 500), 16),
        "raw_json_hash": hashlib.sha256(str(raw_json or "").encode("utf-8", errors="replace")).hexdigest(),
    }


def build_raw_index(conn: sqlite3.Connection) -> dict[tuple[str, str], list[dict[str, Any]]]:
    sql = """
    SELECT row_pk, evid, name, place, city, time_text, source_article_uid, raw_json
    FROM events
    WHERE coalesce(city, '') = ''
      AND coalesce(name, '') <> ''
      AND coalesce(place, '') <> ''
    ORDER BY row_pk
    """
    index: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in conn.execute(sql):
        key = (normalize_text(row["name"]), venue_family(row["place"]))
        if key[0] and key[1]:
            item = raw_event_projection(row)
            item["prewrite_row_hash"] = row_hash(item)
            index[key].append(item)
    return index


def candidate_blockers(row: dict[str, Any]) -> list[str]:
    blockers: list[str] = []
    if compact(row.get("target_field")) != "city":
        blockers.append("target_field_not_city")
    if compact(row.get("proposed_city"), 120) == "":
        blockers.append("proposed_city_missing")
    if compact(row.get("current_city"), 120) != "":
        blockers.append("current_city_not_empty")
    if compact(row.get("target_table")) not in {"performance_event", "dj_event"}:
        blockers.append("unsupported_target_table")
    for key in [
        "source_raw_db_write_allowed",
        "serving_rebuild_allowed",
        "public_serving_field_allowed",
        "write_gate_allowed_now",
    ]:
        if row.get(key) is not False:
            blockers.append(f"{key}_not_false")
    if row.get("rollback_required") is not True:
        blockers.append("rollback_required_not_true")
    if row.get("postwrite_readback_required") is not True:
        blockers.append("postwrite_readback_required_not_true")
    if not compact(row.get("event_title"), 240):
        blockers.append("event_title_missing")
    if not compact(row.get("venue_name"), 240):
        blockers.append("venue_name_missing")
    return sorted(set(blockers))


def mapped_candidate_row(row: dict[str, Any], raw_rows: list[dict[str, Any]], generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".serving_candidate_mapping",
        "generated_at": generated_at,
        "target_table": compact(row.get("target_table"), 60),
        "event_id": compact(row.get("event_id"), 160),
        "dj_id": compact(row.get("dj_id"), 160),
        "source_ref_id": compact(row.get("source_ref_id"), 160),
        "selector_hash": compact(row.get("selector_hash"), 120),
        "event_title": compact(row.get("event_title"), 260),
        "venue_name": compact(row.get("venue_name"), 220),
        "venue_family": venue_family(row.get("venue_name")),
        "proposed_city": compact(row.get("proposed_city"), 120),
        "raw_event_row_pks_report_only": [item["row_pk"] for item in raw_rows],
        "raw_event_match_count": len(raw_rows),
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
    }


def blocked_candidate_row(row: dict[str, Any], blockers: list[str], generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".blocked_candidate",
        "generated_at": generated_at,
        "target_table": compact(row.get("target_table"), 60),
        "event_id": compact(row.get("event_id"), 160),
        "dj_id": compact(row.get("dj_id"), 160),
        "source_ref_id": compact(row.get("source_ref_id"), 160),
        "selector_hash": compact(row.get("selector_hash"), 120),
        "event_title": compact(row.get("event_title"), 260),
        "venue_name": compact(row.get("venue_name"), 220),
        "venue_family": venue_family(row.get("venue_name")),
        "proposed_city": compact(row.get("proposed_city"), 120),
        "blockers": sorted(set(blockers)),
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
    }


def ready_raw_row(
    raw_row: dict[str, Any],
    proposed_city: str,
    candidate_refs: list[dict[str, Any]],
    target_db_display: str,
    generated_at: str,
) -> dict[str, Any]:
    selector = stable_id("citywrite", target_db_display, "events", raw_row["row_pk"], proposed_city)
    candidate_refs = sorted(candidate_refs, key=lambda item: (item["event_id"], item["target_table"], item["dj_id"]))[:24]
    payload = {
        "schema_version": SCHEMA_VERSION + ".ready_raw_event_city_row",
        "generated_at": generated_at,
        "selector_id": selector,
        "target_db": target_db_display,
        "target_table": "events",
        "target_column": "city",
        "raw_event_row_pk": raw_row["row_pk"],
        "raw_event_evid": raw_row["evid"],
        "raw_event_name": raw_row["name"],
        "raw_event_place": raw_row["place"],
        "raw_event_time_text": raw_row["time_text"],
        "source_article_uid_hash": raw_row["source_article_uid_hash"],
        "current_city": raw_row["city"],
        "proposed_city": proposed_city,
        "prewrite_row_hash": raw_row["prewrite_row_hash"],
        "raw_json_hash": raw_row["raw_json_hash"],
        "serving_candidate_ref_count": len(candidate_refs),
        "serving_candidate_refs_sample": candidate_refs,
        "prewrite_snapshot_required": True,
        "rollback_contract": {
            "required": True,
            "target_table": "events",
            "target_column": "city",
            "raw_event_row_pk": raw_row["row_pk"],
            "restore_value": raw_row["city"],
            "prewrite_row_hash": raw_row["prewrite_row_hash"],
        },
        "postwrite_readback_contract": {
            "required": True,
            "must_verify": [
                "events.row_pk remains present",
                "events.city equals proposed_city after the future confirmed write",
                "all non-city row fields remain stable or are explained in the write report",
                "serving rebuild and graph/vector/public surfaces are verified separately",
            ],
        },
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
    }
    payload["prewrite_contract_hash"] = row_hash(payload)
    return payload


def build_packet(
    candidates_path: Path,
    gap_summary_path: Path,
    target_db_provenance_path: Path,
    target_db: Path,
    out_dir: Path,
    report_path: Path,
    max_raw_matches_per_candidate: int,
) -> dict[str, Any]:
    generated_at = now_iso()
    out_dir.mkdir(parents=True, exist_ok=True)

    gap_summary = read_json(gap_summary_path, "gap_summary")
    provenance = read_json(target_db_provenance_path, "target_db_provenance")
    candidates = read_jsonl(candidates_path, "venue_city_candidates")

    upstream_failures = validate_upstream(gap_summary)
    provenance_ready, provenance_blockers, provenance_sha = validate_provenance(provenance, target_db)
    target_db_display = display_path(target_db)
    target_db_present = target_db.exists()

    required_table_failures: list[str] = []
    raw_index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    target_schema_hash = ""
    target_db_opened_read_only = False
    if target_db_present and provenance_ready:
        with open_readonly(target_db) as conn:
            target_db_opened_read_only = True
            target_schema_hash = schema_hash(conn)
            event_cols = table_columns(conn, "events") if conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone() else set()
            required_cols = {"row_pk", "evid", "name", "place", "city", "time_text", "source_article_uid", "raw_json"}
            missing_cols = sorted(required_cols - event_cols)
            if missing_cols:
                required_table_failures.append("events_required_columns_missing:" + ",".join(missing_cols))
            else:
                raw_index = build_raw_index(conn)

    mapped_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    raw_refs: dict[int, dict[str, Any]] = {}
    raw_proposed_cities: dict[int, set[str]] = defaultdict(set)
    raw_candidate_refs: dict[int, list[dict[str, Any]]] = defaultdict(list)

    critical_blockers = upstream_failures + provenance_blockers + required_table_failures
    if critical_blockers:
        for row in candidates:
            blocked_rows.append(blocked_candidate_row(row, critical_blockers, generated_at))
    else:
        for row in candidates:
            blockers = candidate_blockers(row)
            key = (normalize_text(row.get("event_title")), venue_family(row.get("venue_name")))
            raw_rows = raw_index.get(key, [])
            if not raw_rows:
                blockers.append("source_raw_exact_title_venue_mapping_missing")
            if len(raw_rows) > max_raw_matches_per_candidate:
                blockers.append("source_raw_exact_title_venue_mapping_too_broad")
            if blockers:
                blocked_rows.append(blocked_candidate_row(row, blockers, generated_at))
                continue

            mapped_rows.append(mapped_candidate_row(row, raw_rows, generated_at))
            ref = {
                "target_table": compact(row.get("target_table"), 60),
                "event_id": compact(row.get("event_id"), 160),
                "dj_id": compact(row.get("dj_id"), 160),
                "selector_hash": compact(row.get("selector_hash"), 120),
            }
            proposed_city = compact(row.get("proposed_city"), 120)
            for raw_row in raw_rows:
                raw_pk = int(raw_row["row_pk"])
                raw_refs[raw_pk] = raw_row
                raw_proposed_cities[raw_pk].add(proposed_city)
                raw_candidate_refs[raw_pk].append(ref)

    conflict_groups: list[dict[str, Any]] = []
    duplicate_groups: list[dict[str, Any]] = []
    ready_rows: list[dict[str, Any]] = []
    for raw_pk, raw_row in sorted(raw_refs.items()):
        proposed = sorted(raw_proposed_cities[raw_pk])
        refs = raw_candidate_refs[raw_pk]
        if len(proposed) != 1:
            conflict_groups.append(
                {
                    "schema_version": SCHEMA_VERSION + ".duplicate_or_conflict_group",
                    "generated_at": generated_at,
                    "raw_event_row_pk": raw_pk,
                    "proposed_city_values": proposed,
                    "serving_candidate_ref_count": len(refs),
                    "blocker": "raw_event_proposed_city_conflict",
                    "write_execution_allowed_now": False,
                }
            )
            continue
        if len(refs) > 1:
            duplicate_groups.append(
                {
                    "schema_version": SCHEMA_VERSION + ".duplicate_selector_group",
                    "generated_at": generated_at,
                    "raw_event_row_pk": raw_pk,
                    "proposed_city": proposed[0],
                    "serving_candidate_ref_count": len(refs),
                    "status": "duplicate_serving_candidates_collapsed_to_single_raw_city_write",
                    "write_execution_allowed_now": False,
                }
            )
        ready_rows.append(ready_raw_row(raw_row, proposed[0], refs, target_db_display, generated_at))

    rollback_rows = [
        {
            "schema_version": SCHEMA_VERSION + ".rollback_contract",
            "selector_id": row["selector_id"],
            "target_table": "events",
            "target_column": "city",
            "raw_event_row_pk": row["raw_event_row_pk"],
            "restore_value": row["current_city"],
            "prewrite_row_hash": row["prewrite_row_hash"],
            "write_execution_allowed_now": False,
        }
        for row in ready_rows
    ]
    postwrite_rows = [
        {
            "schema_version": SCHEMA_VERSION + ".postwrite_readback_contract",
            "selector_id": row["selector_id"],
            "target_table": "events",
            "target_column": "city",
            "raw_event_row_pk": row["raw_event_row_pk"],
            "expected_city": row["proposed_city"],
            "postwrite_readback_required": True,
            "serving_rebuild_required_after_source_write": True,
            "public_or_graph_promotion_allowed_by_this_packet": False,
        }
        for row in ready_rows
    ]

    write_jsonl(out_dir / "city_write_preflight_ready_raw_event_rows.jsonl", ready_rows)
    write_jsonl(out_dir / "city_write_preflight_serving_candidate_mapped_rows.jsonl", mapped_rows)
    write_jsonl(out_dir / "city_write_preflight_blocked_rows.jsonl", blocked_rows)
    write_jsonl(out_dir / "city_write_preflight_duplicate_selector_groups.jsonl", duplicate_groups)
    write_jsonl(out_dir / "city_write_preflight_conflict_groups.jsonl", conflict_groups)
    write_jsonl(out_dir / "city_write_preflight_rollback_contracts.jsonl", rollback_rows)
    write_jsonl(out_dir / "city_write_preflight_postwrite_readback_contracts.jsonl", postwrite_rows)

    output_scan = merge_scan(
        scan_payload(ready_rows),
        scan_payload(mapped_rows),
        scan_payload(blocked_rows),
        scan_payload(duplicate_groups),
        scan_payload(conflict_groups),
        scan_payload(rollback_rows),
        scan_payload(postwrite_rows),
    )
    failed_checks = []
    if upstream_failures:
        failed_checks.append("upstream_gap_packet_failed")
    if provenance_blockers:
        failed_checks.append("target_db_provenance_failed")
    if required_table_failures:
        failed_checks.append("target_db_schema_failed")
    if conflict_groups:
        failed_checks.append("raw_event_city_conflict_groups_present")
    if any(output_scan.values()):
        failed_checks.append("leak_scan_hits_present")

    decision = (
        "atlas_t5_city_write_preflight_partial_ready_report_only"
        if ready_rows and not failed_checks
        else "atlas_t5_city_write_preflight_blocked_report_only"
    )
    counts = {
        "input_candidate_rows": len(candidates),
        "serving_candidate_mapped_rows": len(mapped_rows),
        "serving_candidate_blocked_rows": len(blocked_rows),
        "raw_event_update_target_rows": len(ready_rows),
        "rollback_contract_rows": len(rollback_rows),
        "postwrite_readback_contract_rows": len(postwrite_rows),
        "duplicate_selector_groups": len(duplicate_groups),
        "conflict_groups": len(conflict_groups),
        "source_raw_target_db_present": int(target_db_present),
        "source_raw_target_db_opened_read_only": int(target_db_opened_read_only),
        "source_raw_target_db_provenance_ready": int(provenance_ready),
        "raw_index_keys": len(raw_index),
        "write_execution_allowed_rows": 0,
        "source_raw_db_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    outputs = {
        "summary_json": display_path(out_dir / "city_write_preflight_summary.json"),
        "summary_md": display_path(out_dir / "city_write_preflight_summary.md"),
        "contract_json": display_path(out_dir / "city_write_preflight_contract.json"),
        "ready_raw_event_rows": display_path(out_dir / "city_write_preflight_ready_raw_event_rows.jsonl"),
        "mapped_serving_candidate_rows": display_path(out_dir / "city_write_preflight_serving_candidate_mapped_rows.jsonl"),
        "blocked_rows": display_path(out_dir / "city_write_preflight_blocked_rows.jsonl"),
        "duplicate_selector_groups": display_path(out_dir / "city_write_preflight_duplicate_selector_groups.jsonl"),
        "conflict_groups": display_path(out_dir / "city_write_preflight_conflict_groups.jsonl"),
        "rollback_contracts": display_path(out_dir / "city_write_preflight_rollback_contracts.jsonl"),
        "postwrite_readback_contracts": display_path(out_dir / "city_write_preflight_postwrite_readback_contracts.jsonl"),
        "report": display_path(report_path),
    }
    boundary_truth = {
        "report_only": True,
        "source_raw_db_opened_read_only": target_db_opened_read_only,
        "source_raw_db_write_executed": False,
        "serving_sqlite_write_or_rebuild_executed": False,
        "neo4j_write_executed": False,
        "qdrant_write_executed": False,
        "production_sqlite_write_executed": False,
        "public_pointer_updated": False,
        "huaidj_club_upload_executed": False,
        "mini_program_upload_or_review_executed": False,
        "network_fetch_executed": False,
        "ocr_executed": False,
        "model_call_executed": False,
        "memory_write_executed": False,
        "write_execution_allowed_now": False,
    }
    contract = {
        "schema_version": SCHEMA_VERSION + ".contract",
        "generated_at": generated_at,
        "target_db": {
            "display": target_db_display,
            "exists": target_db_present,
            "opened_read_only": target_db_opened_read_only,
            "provenance_summary": display_path(target_db_provenance_path),
            "provenance_sha256": provenance_sha,
            "schema_sha256": target_schema_hash,
            "written": False,
        },
        "mapping_rule": {
            "rule": "serving city candidates map to raw events only by exact normalized event title and venue family, with current raw city empty",
            "max_raw_matches_per_candidate": max_raw_matches_per_candidate,
            "conflict_policy": "conflicting proposed city values block the raw row",
        },
        "prewrite_requirements": [
            "open source/raw target DB read-only and capture row hashes before any future write",
            "write only events.city for ready raw_event_row_pk selectors",
            "collapse duplicate serving candidates to one raw event city update when proposed city is identical",
            "do not modify starts_at, place, participants, source article, graph/vector/public state in this city writer",
        ],
        "rollback_requirements": [
            "restore each events.city value from city_write_preflight_rollback_contracts.jsonl",
            "verify row_pk and prewrite selector identity before rollback",
            "run post-rollback readback if any future write executes",
        ],
        "postwrite_requirements": [
            "read back every events.row_pk city after future confirmed write",
            "rebuild selected serving candidate separately and verify city gap deltas",
            "run graph/search/API smoke before any graph/vector/public promotion",
        ],
        "write_execution_allowed_now": False,
    }
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "inputs": {
            "venue_city_candidates": display_path(candidates_path),
            "gap_summary": display_path(gap_summary_path),
            "target_db_provenance_summary": display_path(target_db_provenance_path),
            "target_db": target_db_display,
        },
        "target_db": contract["target_db"],
        "leak_scan": output_scan,
        "outputs": outputs,
        "boundary_truth": boundary_truth,
        "next_resume_pointer": outputs["ready_raw_event_rows"] if ready_rows else outputs["blocked_rows"],
        "next_if_write_gate_closed": display_path(DEFAULT_GAP_DIR / "time_title_recovery_work_orders.jsonl"),
    }
    write_json(out_dir / "city_write_preflight_contract.json", contract)
    write_json(out_dir / "city_write_preflight_summary.json", summary)
    write_text(out_dir / "city_write_preflight_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    lines = [
        "# Atlas T5 City Write Preflight Summary",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Input / mapped / blocked serving candidates: `{counts['input_candidate_rows']}/{counts['serving_candidate_mapped_rows']}/{counts['serving_candidate_blocked_rows']}`",
        f"- Raw event update targets: `{counts['raw_event_update_target_rows']}`",
        f"- Duplicate selector groups / conflict groups: `{counts['duplicate_selector_groups']}/{counts['conflict_groups']}`",
        f"- Target DB present/opened read-only/provenance-ready: `{counts['source_raw_target_db_present']}/{counts['source_raw_target_db_opened_read_only']}/{counts['source_raw_target_db_provenance_ready']}`",
        f"- Leak hits: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
        f"- Next resume pointer: `{summary['next_resume_pointer']}`",
        "",
    ]
    return "\n".join(lines)


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    target = summary["target_db"]
    boundary = summary["boundary_truth"]
    lines = [
        "# ATLAS T5 City Write Preflight Packet - 2026-05-27",
        "",
        "## Decision",
        "",
        f"`{summary['decision']}`",
        "",
        f"Failed checks: `{summary['failed_checks']}`.",
        "",
        "## LLM Audit",
        "",
        (
            "The time/city/venue packet proved a high-volume city repair lane, but the serving-layer "
            "candidate rows cannot be written safely until they are rebound to an explicit source/raw "
            "target DB. This packet binds the existing source/raw target provenance, opens that DB "
            "read-only, and maps only the exact title + venue-family subset to raw `events.city` rows. "
            "Rows without a deterministic raw selector remain blocked for source/title/OCR recovery."
        ),
        "",
        "## Counts",
        "",
        f"- Input candidate rows: `{counts['input_candidate_rows']}`",
        f"- Serving candidate mapped / blocked rows: `{counts['serving_candidate_mapped_rows']}` / `{counts['serving_candidate_blocked_rows']}`",
        f"- Raw event city update targets: `{counts['raw_event_update_target_rows']}`",
        f"- Rollback / postwrite contracts: `{counts['rollback_contract_rows']}` / `{counts['postwrite_readback_contract_rows']}`",
        f"- Duplicate selector groups / conflict groups: `{counts['duplicate_selector_groups']}` / `{counts['conflict_groups']}`",
        f"- Target DB present / opened read-only / provenance ready: `{counts['source_raw_target_db_present']}` / `{counts['source_raw_target_db_opened_read_only']}` / `{counts['source_raw_target_db_provenance_ready']}`",
        f"- Leak hits public URL / sensitive key / local path: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Target DB",
        "",
        f"- Target DB: `{target['display']}`",
        f"- Provenance summary: `{target['provenance_summary']}`",
        f"- Provenance SHA256: `{target['provenance_sha256']}`",
        f"- Schema SHA256: `{target['schema_sha256']}`",
        "",
        "## Outputs",
        "",
        f"- Summary: `{outputs['summary_json']}`",
        f"- Contract: `{outputs['contract_json']}`",
        f"- Ready raw rows: `{outputs['ready_raw_event_rows']}`",
        f"- Mapped serving candidates: `{outputs['mapped_serving_candidate_rows']}`",
        f"- Blocked rows: `{outputs['blocked_rows']}`",
        f"- Rollback contracts: `{outputs['rollback_contracts']}`",
        f"- Postwrite readback contracts: `{outputs['postwrite_readback_contracts']}`",
        "",
        "## Boundary Truth",
        "",
        f"- Report-only: `{str(boundary['report_only']).lower()}`",
        f"- Source/raw DB opened read-only: `{str(boundary['source_raw_db_opened_read_only']).lower()}`",
        f"- Source/raw DB write executed: `{str(boundary['source_raw_db_write_executed']).lower()}`",
        f"- Serving write/rebuild executed: `{str(boundary['serving_sqlite_write_or_rebuild_executed']).lower()}`",
        f"- Graph/vector/public mutation executed: `{str(boundary['neo4j_write_executed'] or boundary['qdrant_write_executed'] or boundary['public_pointer_updated']).lower()}`",
        f"- huaidj.club upload executed: `{str(boundary['huaidj_club_upload_executed']).lower()}`",
        f"- OCR/network/model/memory executed: `{str(boundary['ocr_executed'] or boundary['network_fetch_executed'] or boundary['model_call_executed'] or boundary['memory_write_executed']).lower()}`",
        "",
        "## Next",
        "",
        (
            f"Next resume pointer: `{summary['next_resume_pointer']}`. A future confirmed writer must "
            "consume the ready raw rows, require an explicit confirm token, capture prewrite row hashes, "
            "apply only `events.city`, and run rollback plus postwrite readback before any serving rebuild."
        ),
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--gap-summary", type=Path, default=DEFAULT_GAP_SUMMARY)
    parser.add_argument("--target-db-provenance", type=Path, default=DEFAULT_TARGET_DB_PROVENANCE)
    parser.add_argument("--target-db", type=Path, default=DEFAULT_TARGET_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-raw-matches-per-candidate", type=int, default=25)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_packet(
        args.candidates,
        args.gap_summary,
        args.target_db_provenance,
        args.target_db,
        args.out_dir,
        args.report,
        args.max_raw_matches_per_candidate,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
