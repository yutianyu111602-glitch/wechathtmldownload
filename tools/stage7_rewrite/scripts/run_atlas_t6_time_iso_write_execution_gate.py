#!/usr/bin/env python3
"""Run the confirmed Atlas T6 source/raw time_iso writer with rollback evidence.

Consumes readback-ready rows from three T6 time-title readback gate tracks:
  - Track A (exact date)
  - Track B (year/span)
  - Track C (span split)

Maps each readback row to source/raw events via normalized title + venue-family
+ date-token matching, then writes only `events.time_iso` for validated rows.

Default mode is a dry-run. Mutation mode requires an explicit confirm token and
only updates `events.time_iso` for rows whose prewrite snapshots pass validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# ---------------------------------------------------------------------------
# Track definitions
# ---------------------------------------------------------------------------

TRACK_A_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_title_readback_gate_20260527"
TRACK_B_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_title_year_span_readback_gate_20260527"
TRACK_C_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_title_span_split_readback_gate_20260527"

DEFAULT_TRACK_DIRS = [TRACK_A_DIR, TRACK_B_DIR, TRACK_C_DIR]

DEFAULT_TARGET_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_TARGET_DB_PROVENANCE = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_source_raw_mapping_probe_q6_20260526"
    / "source_raw_mapping_target_db_provenance_summary.json"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t6_time_iso_write_execution_gate_20260527"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_TIME_ISO_WRITE_EXECUTION_GATE_20260527.md"
CONFIRM_TOKEN = "ENABLE_ATLAS_T6_TIME_ISO_EVENTS_TIME_ISO_WRITE"
SCHEMA_VERSION = "stage7_atlas_t6_time_iso_write_execution_gate.v1"

DATE_RE = re.compile(r"^(20\d{2})-(\d{2})-(\d{2})$")
YEAR_RE = re.compile(r"20\d{2}")

# ---------------------------------------------------------------------------
# URL / secret / path detection (for leak scanning)
# ---------------------------------------------------------------------------

URL_RE_PAT = re.compile(r"https?://|www\.", re.I)
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

# ---------------------------------------------------------------------------
# Utility functions (self-contained, same semantics as the base module)
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 500) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = URL_RE_PAT.sub("[redacted_url]", text)
    text = LOCAL_PATH_RE.sub("[redacted_path]", text)
    return text[:limit].strip()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def short_hash(value: str, length: int = 16) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:length]


def row_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8", errors="replace")).hexdigest()


def normalize_text(value: Any) -> str:
    return re.sub(r"[^0-9a-z一-鿿]+", "", compact(value, 2000).casefold())


def venue_family(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    oil_tokens = (
        "oil油", "oilclub", "oil俱乐部", "oilmainroom", "oilroom",
        "深圳oil", "shenzhenoil", "车公庙泰然", "l111a",
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


def scan_payload(payload: Any) -> dict[str, int]:
    text = canonical_json(payload)
    return {
        "public_url_hits": len(URL_RE_PAT.findall(text)),
        "sensitive_key_hits": len(SECRET_KEY_RE.findall(text)) + len(SECRET_VALUE_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def merge_scan(*scans: dict[str, int]) -> dict[str, int]:
    keys = {"public_url_hits", "sensitive_key_hits", "local_path_hits"}
    return {key: sum(int(scan.get(key, 0)) for scan in scans) for key in keys}


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def open_readonly(path: Path) -> sqlite3.Connection:
    reject_d_root(path, "target_db")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def open_rw(path: Path) -> sqlite3.Connection:
    reject_d_root(path, "target_db")
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=rw", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in conn.execute(f'PRAGMA table_info("{table}")')}


def schema_hash(conn: sqlite3.Connection) -> str:
    rows = conn.execute(
        "SELECT type, name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type, name"
    ).fetchall()
    payload = "\n".join(f"{row['type']}|{row['name']}|{row['sql']}" for row in rows)
    return hashlib.sha256(payload.encode("utf-8", errors="replace")).hexdigest()


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------


def parsed_date(value: Any) -> tuple[str, str, str] | None:
    match = DATE_RE.fullmatch(compact(value, 40))
    if not match:
        return None
    return match.group(1), str(int(match.group(2))), str(int(match.group(3)))


def date_variant_groups(value: Any) -> tuple[set[str], set[str]]:
    parsed = parsed_date(value)
    if not parsed:
        return set(), set()
    year, month, day = parsed
    mm = f"{int(month):02d}"
    dd = f"{int(day):02d}"
    full = {
        f"{year}{mm}{dd}",
        f"{year}-{mm}-{dd}",
        f"{year}-{int(month)}-{int(day)}",
        f"{year}.{mm}.{dd}",
        f"{year}.{int(month)}.{int(day)}",
        f"{year}/{mm}/{dd}",
        f"{year}/{int(month)}/{int(day)}",
        f"{year}年{month}月{day}日",
        f"{year}年{month}月{dd}日",
        f"{year}年{mm}月{day}日",
        f"{year}年{mm}月{dd}日",
    }
    partial = {
        f"{int(month)}/{int(day)}",
        f"{mm}/{dd}",
        f"{int(month)}.{int(day)}",
        f"{mm}.{dd}",
        f"{month}月{day}日",
        f"{month}月{dd}日",
        f"{mm}月{day}日",
        f"{mm}月{dd}日",
    }
    return full, partial


def date_matches(candidate_date: str, *texts: Any) -> bool:
    full_variants, partial_variants = date_variant_groups(candidate_date)
    if not full_variants and not partial_variants:
        return False
    haystacks = [compact(text, 500) for text in texts if compact(text, 500)]
    for haystack in haystacks:
        normalized_haystack = normalize_text(haystack)
        if any(variant in haystack or normalize_text(variant) in normalized_haystack for variant in full_variants):
            return True
        if YEAR_RE.search(haystack):
            continue
        if any(variant in haystack or normalize_text(variant) in normalized_haystack for variant in partial_variants):
            return True
    return False


# ---------------------------------------------------------------------------
# Raw event helpers
# ---------------------------------------------------------------------------


def raw_event_projection(row: sqlite3.Row) -> dict[str, Any]:
    """Project a raw events row into the prewrite snapshot format."""
    raw_json = row["raw_json"] if "raw_json" in row.keys() else ""
    return {
        "row_pk": int(row["row_pk"]),
        "evid": compact(row["evid"], 120),
        "name": compact(row["name"], 240),
        "place": compact(row["place"], 240),
        "city": compact(row["city"], 120),
        "time_iso": compact(row["time_iso"], 120),
        "time_text": compact(row["time_text"], 180),
        "source_article_uid_hash": short_hash(compact(row["source_article_uid"], 500), 16),
        "raw_json_hash": hashlib.sha256(str(raw_json or "").encode("utf-8", errors="replace")).hexdigest(),
    }


def raw_event_by_pk(conn: sqlite3.Connection, row_pk: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT row_pk, evid, name, place, city, time_iso, time_text, source_article_uid, raw_json
        FROM events
        WHERE row_pk = ?
        """,
        (row_pk,),
    ).fetchone()
    if row is None:
        return None
    item = raw_event_projection(row)
    item["prewrite_row_hash"] = row_hash(item)
    return item


def build_raw_index(conn: sqlite3.Connection) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Build an index of raw events with empty time_iso for title+venue matching."""
    sql = """
    SELECT row_pk, evid, name, place, city, time_iso, time_text, source_article_uid, raw_json
    FROM events
    WHERE coalesce(time_iso, '') = ''
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


# ---------------------------------------------------------------------------
# Readback row helpers (extracting mapping evidence)
# ---------------------------------------------------------------------------


def source_titles(row: dict[str, Any]) -> list[str]:
    values = [
        compact(row.get("source_title"), 240),
        compact((row.get("evidence_ref_readback") or {}).get("source_title"), 240)
        if isinstance(row.get("evidence_ref_readback"), dict)
        else "",
    ]
    for key in ("performance_event_samples", "dj_event_samples"):
        for item in row.get(key) or []:
            if isinstance(item, dict):
                values.append(compact(item.get("event_title"), 240))
    return sorted({item for item in values if item})


def source_venues(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("performance_event_samples", "dj_event_samples"):
        for item in row.get(key) or []:
            if isinstance(item, dict):
                values.append(compact(item.get("venue_name"), 240))
    return sorted({item for item in values if item})


def sample_event_ids(row: dict[str, Any], limit: int = 24) -> list[str]:
    ids = [compact(item, 160) for item in row.get("performance_event_ids") or [] if compact(item, 160)]
    for pair in row.get("dj_event_pairs") or []:
        text = compact(pair, 240)
        if "::" in text:
            ids.append(text.split("::", 1)[0])
    return sorted(set(ids))[:limit]


def sample_dj_ids(row: dict[str, Any], limit: int = 24) -> list[str]:
    ids: list[str] = []
    for pair in row.get("dj_event_pairs") or []:
        text = compact(pair, 240)
        if "::" in text:
            ids.append(text.split("::", 1)[1])
    return sorted(set(ids))[:limit]


def validate_readback_row(row: dict[str, Any], track_label: str) -> list[str]:
    """Validate a single readback-ready row."""
    blockers: list[str] = []
    if row.get("schema_version") != "stage7_atlas_t6_time_title_readback_gate.v1.row":
        blockers.append("readback_row_schema_unexpected")
    if row.get("readback_status") != "time_title_date_readback_ready_report_only":
        blockers.append("readback_status_not_ready")
    if row.get("readback_failures") not in ([], None):
        blockers.append("readback_failures_present")
    candidate_date = compact(row.get("candidate_event_date"), 40)
    if not parsed_date(candidate_date):
        blockers.append("candidate_event_date_invalid_or_missing")
    accepted = row.get("accepted_date_candidate")
    if not accepted:
        blockers.append("accepted_date_candidate_missing")
    elif isinstance(accepted, dict):
        accepted_value = compact(accepted.get("value"), 40)
        if accepted_value and accepted_value != candidate_date:
            blockers.append("accepted_date_candidate_value_mismatch")
    if row.get("source_raw_db_write_allowed") is not False:
        blockers.append("source_raw_db_write_allowed_not_false")
    if row.get("serving_rebuild_allowed") is not False:
        blockers.append("serving_rebuild_allowed_not_false")
    if row.get("public_serving_field_allowed") is not False:
        blockers.append("public_serving_field_allowed_not_false")
    if row.get("write_gate_allowed_now") is not False:
        blockers.append("write_gate_allowed_now_not_false")
    if not source_titles(row):
        blockers.append("event_title_evidence_missing")
    if not source_venues(row):
        blockers.append("venue_evidence_missing")
    return sorted(set(blockers))


def validate_readback_summary(summary: dict[str, Any], ready_rows: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    if summary.get("decision") != "atlas_t6_time_title_readback_gate_ready_report_only":
        failures.append("readback_summary_not_ready")
    if summary.get("failed_checks") not in ([], None):
        failures.append("readback_summary_failed_checks_present")
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    if counts.get("ready_rows") != len(ready_rows):
        failures.append("ready_row_count_mismatch_against_readback_summary")
    if (summary.get("boundary_truth") or {}).get("source_raw_db_opened") is not False:
        failures.append("readback_summary_source_raw_boundary_drift")
    if (summary.get("boundary_truth") or {}).get("serving_sqlite_opened_read_only") is not True:
        failures.append("readback_summary_serving_readonly_missing")
    return failures


def validate_readback_contract(contract: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if contract.get("write_execution_allowed_now") is not False:
        failures.append("readback_contract_write_execution_not_false")
    required = set(contract.get("later_gate_requires") or [])
    expected = {
        "explicit source/raw target DB provenance",
        "source/raw prewrite snapshots for every target row",
        "inverse rollback mapping",
        "postwrite source/raw readback",
        "serving rebuild candidate with no time/participant regression",
    }
    if not expected.issubset(required):
        failures.append("readback_contract_later_gate_requirements_missing")
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
    decision = compact(provenance.get("decision"))
    if decision not in {
        "atlas_social_manual_participant_source_raw_target_db_mapping_ready_report_only",
        "atlas_social_manual_participant_source_raw_mapping_probe_ready_report_only",
    }:
        blockers.append("target_db_provenance_decision_not_ready")
    return not blockers, blockers, compact(target.get("target_db_sha256"), 128)


# ---------------------------------------------------------------------------
# Mapping: readback row -> raw event rows
# ---------------------------------------------------------------------------


def map_readback_to_raw(
    row: dict[str, Any],
    raw_index: dict[tuple[str, str], list[dict[str, Any]]],
    candidate_date: str,
    max_raw_matches: int,
) -> list[dict[str, Any]]:
    """Map a readback row to raw event rows by title+venue+date match."""
    raw_matches: dict[int, dict[str, Any]] = {}
    for title in source_titles(row):
        for venue in source_venues(row):
            key = (normalize_text(title), venue_family(venue))
            for raw_row in raw_index.get(key, []):
                if date_matches(candidate_date, raw_row.get("time_text"), raw_row.get("name")):
                    raw_matches[int(raw_row["row_pk"])] = raw_row
    matched = [raw_matches[key] for key in sorted(raw_matches)]
    if len(matched) > max_raw_matches:
        return []  # too broad, treated as blocked
    return matched


# ---------------------------------------------------------------------------
# Ready raw row builders
# ---------------------------------------------------------------------------


def build_ready_raw_row(
    raw_row: dict[str, Any],
    proposed_time_iso: str,
    refs: list[dict[str, Any]],
    target_db_display: str,
    generated_at: str,
) -> dict[str, Any]:
    row = {
        "schema_version": SCHEMA_VERSION + ".ready_raw_event_time_iso_row",
        "generated_at": generated_at,
        "target_db": target_db_display,
        "target_table": "events",
        "target_column": "time_iso",
        "raw_event_row_pk": raw_row["row_pk"],
        "raw_event_evid": raw_row["evid"],
        "raw_event_name": raw_row["name"],
        "raw_event_place": raw_row["place"],
        "raw_event_city": raw_row["city"],
        "raw_event_current_time_iso": raw_row["time_iso"],
        "raw_event_time_text": raw_row["time_text"],
        "source_article_uid_hash": raw_row["source_article_uid_hash"],
        "raw_json_hash": raw_row["raw_json_hash"],
        "prewrite_row_hash": raw_row["prewrite_row_hash"],
        "proposed_time_iso": proposed_time_iso,
        "candidate_event_date": proposed_time_iso,
        "candidate_refs": refs[:20],
        "candidate_ref_count": len(refs),
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
        "rollback_required": True,
        "postwrite_readback_required": True,
        "serving_rebuild_required_after_future_write": True,
    }
    row["prewrite_contract_hash"] = row_hash(row)
    return row


def build_mapped_readback_row(
    row: dict[str, Any],
    raw_rows: list[dict[str, Any]],
    generated_at: str,
    track_label: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".readback_mapping",
        "generated_at": generated_at,
        "track": track_label,
        "time_title_readback_selector_id": compact(row.get("time_title_readback_selector_id"), 160),
        "source_ref_id": compact(row.get("source_ref_id"), 160),
        "source_hash_prefix": compact(row.get("source_hash_prefix"), 80),
        "candidate_event_date": compact(row.get("candidate_event_date"), 40),
        "accepted_date_policy": compact((row.get("accepted_date_candidate") or {}).get("evidence_policy"), 160)
        if isinstance(row.get("accepted_date_candidate"), dict)
        else "",
        "title_sample": source_titles(row)[:8],
        "venue_sample": source_venues(row)[:8],
        "serving_event_ids_sample": sample_event_ids(row),
        "serving_dj_ids_sample": sample_dj_ids(row),
        "raw_event_row_pks_report_only": [item["row_pk"] for item in raw_rows],
        "raw_event_match_count": len(raw_rows),
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
    }


def build_blocked_row(
    row: dict[str, Any],
    blockers: list[str],
    generated_at: str,
    track_label: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + ".blocked_readback_row",
        "generated_at": generated_at,
        "track": track_label,
        "time_title_readback_selector_id": compact(row.get("time_title_readback_selector_id"), 160),
        "source_ref_id": compact(row.get("source_ref_id"), 160),
        "source_hash_prefix": compact(row.get("source_hash_prefix"), 80),
        "candidate_event_date": compact(row.get("candidate_event_date"), 40),
        "blockers": sorted(set(blockers)),
        "title_sample": source_titles(row)[:8],
        "venue_sample": source_venues(row)[:8],
        "serving_event_ids_sample": sample_event_ids(row, limit=12),
        "source_raw_db_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
    }


# ---------------------------------------------------------------------------
# Preflight: map all 3 tracks to ready raw rows
# ---------------------------------------------------------------------------


def run_preflight(
    track_dirs: list[Path],
    target_db: Path,
    provenance_path: Path,
    generated_at: str,
    max_raw_matches: int,
) -> tuple[
    list[dict[str, Any]],  # ready raw rows
    list[dict[str, Any]],  # mapped readback rows
    list[dict[str, Any]],  # blocked readback rows
    list[dict[str, Any]],  # conflict groups
    list[dict[str, Any]],  # duplicate selector groups
    list[str],             # critical blockers
    str,                   # target_schema_hash
    int,                   # raw_index_keys
]:
    track_labels = ["A_exact_date", "B_year_span", "C_span_split"]
    target_db_display = display_path(target_db)

    all_ready_inputs: list[tuple[str, dict[str, Any]]] = []
    all_summary_failures: list[str] = []
    all_contract_failures: list[str] = []

    for track_dir, track_label in zip(track_dirs, track_labels):
        ready_path = track_dir / "time_title_readback_ready_report_only.jsonl"
        summary_path = track_dir / "time_title_readback_summary.json"
        contract_path = track_dir / "time_title_readback_contract.json"

        if not ready_path.exists():
            continue

        ready_rows = read_jsonl(ready_path, f"ready_rows_{track_label}")
        summary = read_json(summary_path, f"summary_{track_label}")
        contract = read_json(contract_path, f"contract_{track_label}")

        all_summary_failures.extend(
            f"{track_label}:" + f for f in validate_readback_summary(summary, ready_rows)
        )
        all_contract_failures.extend(
            f"{track_label}:" + f for f in validate_readback_contract(contract)
        )

        for row in ready_rows:
            all_ready_inputs.append((track_label, row))

    provenance_ready, provenance_blockers, provenance_sha = validate_provenance(
        read_json(provenance_path, "provenance"), target_db
    )
    target_db_present = target_db.exists()

    critical_blockers: list[str] = []
    critical_blockers.extend(all_summary_failures)
    critical_blockers.extend(all_contract_failures)
    critical_blockers.extend(provenance_blockers)

    target_schema_hash = ""
    raw_index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    column_failures: list[str] = []
    db_opened = False

    if target_db_present and provenance_ready:
        conn = open_readonly(target_db)
        try:
            db_opened = True
            target_schema_hash = schema_hash(conn)
            if not table_exists(conn, "events"):
                column_failures.append("events_table_missing")
            else:
                required_cols = {"row_pk", "evid", "name", "place", "city", "time_iso", "time_text", "source_article_uid", "raw_json"}
                missing_cols = sorted(required_cols - table_columns(conn, "events"))
                if missing_cols:
                    column_failures.append("events_required_columns_missing:" + ",".join(missing_cols))
            if not column_failures:
                raw_index = build_raw_index(conn)
        finally:
            conn.close()

    critical_blockers.extend(column_failures)

    mapped_rows: list[dict[str, Any]] = []
    blocked_rows: list[dict[str, Any]] = []
    raw_refs: dict[int, dict[str, Any]] = {}
    raw_dates: dict[int, set[str]] = defaultdict(set)
    raw_candidate_refs: dict[int, list[dict[str, Any]]] = defaultdict(list)

    if critical_blockers:
        for track_label, row in all_ready_inputs:
            blocked_rows.append(build_blocked_row(row, critical_blockers, generated_at, track_label))
    else:
        for track_label, row in all_ready_inputs:
            blockers = validate_readback_row(row, track_label)
            candidate_date = compact(row.get("candidate_event_date"), 40)

            raw_matches: list[dict[str, Any]] = []
            if "accepted_date_candidate_value_mismatch" not in blockers and "candidate_event_date_invalid_or_missing" not in blockers:
                raw_matches = map_readback_to_raw(row, raw_index, candidate_date, max_raw_matches)

            if not raw_matches:
                blockers.append("source_raw_exact_title_venue_date_mapping_missing")
            if len(raw_matches) > max_raw_matches:
                blockers.append("source_raw_exact_title_venue_date_mapping_too_broad")

            if blockers:
                blocked_rows.append(build_blocked_row(row, blockers, generated_at, track_label))
                continue

            mapped_rows.append(build_mapped_readback_row(row, raw_matches, generated_at, track_label))
            ref = {
                "track": track_label,
                "time_title_readback_selector_id": compact(row.get("time_title_readback_selector_id"), 160),
                "source_ref_id": compact(row.get("source_ref_id"), 160),
                "source_hash_prefix": compact(row.get("source_hash_prefix"), 80),
                "candidate_event_date": candidate_date,
                "serving_event_ids_sample": sample_event_ids(row, limit=12),
            }
            for raw_row in raw_matches:
                raw_pk = int(raw_row["row_pk"])
                raw_refs[raw_pk] = raw_row
                raw_dates[raw_pk].add(candidate_date)
                raw_candidate_refs[raw_pk].append(ref)

    # Resolve conflicts and duplicates
    conflict_groups: list[dict[str, Any]] = []
    duplicate_groups: list[dict[str, Any]] = []
    ready_rows: list[dict[str, Any]] = []

    for raw_pk, raw_row in sorted(raw_refs.items()):
        dates = sorted(raw_dates[raw_pk])
        refs = raw_candidate_refs[raw_pk]
        if len(dates) != 1:
            conflict_groups.append({
                "schema_version": SCHEMA_VERSION + ".conflict_group",
                "generated_at": generated_at,
                "raw_event_row_pk": raw_pk,
                "candidate_event_dates": dates,
                "candidate_refs": refs[:20],
                "blocker": "conflicting_candidate_event_dates_for_raw_event",
            })
            continue
        if len(refs) > 1:
            duplicate_groups.append({
                "schema_version": SCHEMA_VERSION + ".duplicate_selector_group",
                "generated_at": generated_at,
                "raw_event_row_pk": raw_pk,
                "candidate_event_date": dates[0],
                "candidate_ref_count": len(refs),
                "candidate_refs": refs[:20],
                "collapse_policy": "same raw row and same proposed time_iso collapse to one source/raw update target",
            })
        ready_rows.append(build_ready_raw_row(raw_row, dates[0], refs, target_db_display, generated_at))

    return (
        ready_rows,
        mapped_rows,
        blocked_rows,
        conflict_groups,
        duplicate_groups,
        critical_blockers,
        target_schema_hash,
        len(raw_index),
    )


# ---------------------------------------------------------------------------
# Write execution gate (from validated ready rows)
# ---------------------------------------------------------------------------


def contract_hash_matches(row: dict[str, Any]) -> bool:
    expected = str(row.get("prewrite_contract_hash") or "")
    if not expected:
        return False
    payload = dict(row)
    payload.pop("prewrite_contract_hash", None)
    return row_hash(payload) == expected


def non_time_iso_mismatches(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    fields = [
        ("raw_event_evid", "evid"),
        ("raw_event_name", "name"),
        ("raw_event_place", "place"),
        ("raw_event_city", "city"),
        ("raw_event_time_text", "time_text"),
        ("source_article_uid_hash", "source_article_uid_hash"),
        ("raw_json_hash", "raw_json_hash"),
    ]
    mismatches = []
    for left, right in fields:
        if str(expected.get(left) or "") != str(actual.get(right) or ""):
            mismatches.append(left)
    return mismatches


def validate_ready_rows(
    ready_rows: list[dict[str, Any]],
    target_db: Path,
    conn: sqlite3.Connection,
    generated_at: str,
    target_schema_hash: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Validate ready rows against the current state of the target DB."""
    ready: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    prewrite_snapshots: list[dict[str, Any]] = []

    db_failures: list[str] = []
    if not table_exists(conn, "events"):
        db_failures.append("events_table_missing")
    current_schema_hash = schema_hash(conn) if table_exists(conn, "events") else ""
    if current_schema_hash and target_schema_hash and current_schema_hash != target_schema_hash:
        db_failures.append("target_db_schema_hash_drift")
    required_cols = {"row_pk", "evid", "name", "place", "city", "time_iso", "time_text", "source_article_uid", "raw_json"}
    if table_exists(conn, "events"):
        missing_cols = sorted(required_cols - table_columns(conn, "events"))
        if missing_cols:
            db_failures.append("events_required_columns_missing:" + ",".join(missing_cols))

    seen: set[int] = set()
    for row in ready_rows:
        blockers = list(db_failures)
        row_pk = int(row.get("raw_event_row_pk") or -1)
        proposed_time_iso = compact(row.get("proposed_time_iso"), 40)

        if row.get("schema_version") != SCHEMA_VERSION + ".ready_raw_event_time_iso_row":
            blockers.append("ready_row_schema_version_unexpected")
        if row.get("target_table") != "events" or row.get("target_column") != "time_iso":
            blockers.append("ready_row_target_not_events_time_iso")
        if row.get("target_db") != display_path(target_db):
            blockers.append("ready_row_target_db_mismatch")
        if row_pk <= 0:
            blockers.append("raw_event_row_pk_missing")
        if row_pk in seen:
            blockers.append("duplicate_raw_event_row_pk_in_ready_rows")
        seen.add(row_pk)
        if not parsed_date(proposed_time_iso):
            blockers.append("proposed_time_iso_invalid")
        if row.get("raw_event_current_time_iso") not in ("", None):
            blockers.append("ready_row_current_time_iso_not_empty")
        if row.get("rollback_required") is not True:
            blockers.append("rollback_not_required")
        if row.get("postwrite_readback_required") is not True:
            blockers.append("postwrite_readback_not_required")
        for gate in [
            "source_raw_db_write_allowed",
            "serving_rebuild_allowed",
            "graph_write_allowed",
            "public_serving_field_allowed",
            "memory_write_allowed",
            "write_execution_allowed_now",
        ]:
            if row.get(gate) is not False:
                blockers.append(f"{gate}_not_false_in_ready_row")
        if not contract_hash_matches(row):
            blockers.append("prewrite_contract_hash_mismatch")

        actual = raw_event_by_pk(conn, row_pk) if row_pk > 0 and table_exists(conn, "events") else None
        if actual is None:
            blockers.append("target_row_missing")
            actual_for_output = {}
        else:
            actual_for_output = actual
            if str(actual.get("prewrite_row_hash") or "") != str(row.get("prewrite_row_hash") or ""):
                blockers.append("prewrite_row_hash_drift")
            if compact(actual.get("time_iso"), 120) != "":
                blockers.append("target_time_iso_not_empty")
            mismatches = non_time_iso_mismatches(row, actual)
            if mismatches:
                blockers.append("non_time_iso_field_drift:" + ",".join(mismatches))

        snapshot = {
            "schema_version": SCHEMA_VERSION + ".prewrite_snapshot",
            "generated_at": generated_at,
            "raw_event_row_pk": row_pk,
            "expected_prewrite_row_hash": compact(row.get("prewrite_row_hash"), 128),
            "actual_prewrite_row_hash": compact(actual_for_output.get("prewrite_row_hash"), 128),
            "current_time_iso": compact(actual_for_output.get("time_iso"), 120),
            "proposed_time_iso": proposed_time_iso,
            "hash_match": (
                not any(b.startswith("prewrite_row_hash_drift") for b in blockers)
                and actual is not None
            ),
            "non_time_iso_mismatches": [b for b in blockers if b.startswith("non_time_iso_field_drift:")],
        }
        prewrite_snapshots.append(snapshot)

        if blockers:
            blocked.append({
                "schema_version": SCHEMA_VERSION + ".blocked_row",
                "generated_at": generated_at,
                "raw_event_row_pk": row_pk,
                "proposed_time_iso": proposed_time_iso,
                "blockers": sorted(set(blockers)),
                "write_executed": False,
            })
        else:
            ready.append(row)

    return ready, blocked, prewrite_snapshots


def execute_time_iso_write(
    conn: sqlite3.Connection,
    rows: list[dict[str, Any]],
    generated_at: str,
    *,
    execute: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], bool]:
    write_rows: list[dict[str, Any]] = []
    postwrite_rows: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    committed = False

    try:
        if execute:
            conn.execute("BEGIN IMMEDIATE")
        for row in rows:
            row_pk = int(row["raw_event_row_pk"])
            proposed_time_iso = compact(row.get("proposed_time_iso"), 40)
            before = raw_event_by_pk(conn, row_pk)
            blockers: list[str] = []
            if before is None:
                blockers.append("target_row_missing_at_write_time")
            elif str(before.get("prewrite_row_hash") or "") != str(row.get("prewrite_row_hash") or ""):
                blockers.append("prewrite_row_hash_drift_at_write_time")
            elif compact(before.get("time_iso"), 120) != "":
                blockers.append("target_time_iso_not_empty_at_write_time")

            if blockers:
                blocked.append({
                    "schema_version": SCHEMA_VERSION + ".write_blocked_row",
                    "generated_at": generated_at,
                    "raw_event_row_pk": row_pk,
                    "proposed_time_iso": proposed_time_iso,
                    "blockers": blockers,
                    "write_executed": False,
                })
                continue

            if execute:
                cursor = conn.execute(
                    "UPDATE events SET time_iso = ? WHERE row_pk = ? AND coalesce(time_iso, '') = ''",
                    (proposed_time_iso, row_pk),
                )
                if cursor.rowcount != 1:
                    blocked.append({
                        "schema_version": SCHEMA_VERSION + ".write_blocked_row",
                        "generated_at": generated_at,
                        "raw_event_row_pk": row_pk,
                        "proposed_time_iso": proposed_time_iso,
                        "blockers": ["sqlite_update_rowcount_not_one"],
                        "sqlite_rowcount": cursor.rowcount,
                        "write_executed": False,
                    })
                    continue

            after = raw_event_by_pk(conn, row_pk)
            time_iso_matches = after is not None and compact(after.get("time_iso"), 120) == proposed_time_iso
            non_time_iso_drift = non_time_iso_mismatches(row, after or {}) if after else ["target_row_missing_after_write"]
            postwrite = {
                "schema_version": SCHEMA_VERSION + ".postwrite_readback",
                "generated_at": generated_at,
                "raw_event_row_pk": row_pk,
                "expected_time_iso": proposed_time_iso,
                "actual_time_iso": compact((after or {}).get("time_iso"), 120),
                "time_iso_matches": time_iso_matches if execute else False,
                "non_time_iso_drift_fields": non_time_iso_drift,
                "postwrite_row_hash": compact((after or {}).get("prewrite_row_hash"), 128),
                "write_executed": execute,
            }
            postwrite_rows.append(postwrite)
            if execute and (not time_iso_matches or non_time_iso_drift):
                blocked.append({
                    "schema_version": SCHEMA_VERSION + ".write_blocked_row",
                    "generated_at": generated_at,
                    "raw_event_row_pk": row_pk,
                    "proposed_time_iso": proposed_time_iso,
                    "blockers": ["postwrite_readback_failed"],
                    "postwrite": postwrite,
                    "write_executed": True,
                })
            write_rows.append({
                "schema_version": SCHEMA_VERSION + ".write_row",
                "generated_at": generated_at,
                "raw_event_row_pk": row_pk,
                "restore_time_iso": row.get("raw_event_current_time_iso") or "",
                "proposed_time_iso": proposed_time_iso,
                "prewrite_row_hash": row["prewrite_row_hash"],
                "postwrite_row_hash": postwrite["postwrite_row_hash"],
                "write_executed": execute,
            })
        if execute:
            if blocked:
                conn.rollback()
            else:
                conn.commit()
                committed = True
    except Exception:
        if execute:
            conn.rollback()
        raise

    if execute and not committed:
        postwrite_rows = []
        for row in rows:
            after = raw_event_by_pk(conn, int(row["raw_event_row_pk"]))
            postwrite_rows.append({
                "schema_version": SCHEMA_VERSION + ".postwrite_readback",
                "generated_at": generated_at,
                "raw_event_row_pk": int(row["raw_event_row_pk"]),
                "expected_time_iso": compact(row.get("proposed_time_iso"), 40),
                "actual_time_iso": compact((after or {}).get("time_iso"), 120),
                "time_iso_matches": False,
                "non_time_iso_drift_fields": [],
                "postwrite_row_hash": compact((after or {}).get("prewrite_row_hash"), 128),
                "write_executed": False,
                "transaction_committed": False,
            })
    return write_rows, postwrite_rows, blocked, committed


def rollback_rows(rows: list[dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": SCHEMA_VERSION + ".rollback_contract",
            "generated_at": generated_at,
            "target_table": "events",
            "target_column": "time_iso",
            "raw_event_row_pk": int(row["raw_event_row_pk"]),
            "restore_value": row.get("raw_event_current_time_iso") or "",
            "written_value": compact(row.get("proposed_time_iso"), 40),
            "prewrite_row_hash": row["prewrite_row_hash"],
            "rollback_required_if_write_committed": True,
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Summary / report rendering
# ---------------------------------------------------------------------------


def render_summary(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    return "\n".join([
        "# Atlas T6 Time ISO Write Execution Summary",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Failed checks: `{summary['failed_checks']}`",
        f"- Execute requested: `{str(summary['execute_requested']).lower()}`",
        f"- Input readback rows (A/B/C): `{counts['input_readback_rows_a']}/{counts['input_readback_rows_b']}/{counts['input_readback_rows_c']}`",
        f"- Mapped / blocked readback rows: `{counts['mapped_readback_rows']}/{counts['blocked_readback_rows']}`",
        f"- Conflict / duplicate groups: `{counts['conflict_groups']}/{counts['duplicate_selector_groups']}`",
        f"- Ready raw event rows / validated / blocked: `{counts['ready_raw_event_rows']}/{counts['validated_ready_rows']}/{counts['execution_blocked_rows']}`",
        f"- Write committed rows: `{counts['write_committed_rows']}`",
        f"- Postwrite readback / time_iso match rows: `{counts['postwrite_readback_rows']}/{counts['postwrite_time_iso_match_rows']}`",
        f"- Leak hits: `{summary['leak_scan']['public_url_hits']}/{summary['leak_scan']['sensitive_key_hits']}/{summary['leak_scan']['local_path_hits']}`",
        f"- Next resume pointer: `{summary['next_resume_pointer']}`",
        "",
    ])


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    boundary = summary["boundary_truth"]
    return "\n".join([
        "# ATLAS T6 Time ISO Write Execution Gate - 2026-05-27",
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
            "This writer consumes readback-ready rows from three T6 time-title readback "
            "gate tracks (A: exact date, B: year/span, C: span split), maps each to "
            "source/raw events via normalized title + venue-family + date-token matching, "
            "then updates only `events.time_iso`. It rechecks prewrite row hashes before "
            "every write and produces rollback contracts and postwrite readbacks. No "
            "serving, graph, vector, or public-surface mutation is performed."
        ),
        "",
        "## Counts",
        "",
        f"- Input readback rows: A={counts['input_readback_rows_a']} B={counts['input_readback_rows_b']} C={counts['input_readback_rows_c']}",
        f"- Mapped / blocked readback rows: `{counts['mapped_readback_rows']}` / `{counts['blocked_readback_rows']}`",
        f"- Conflict / duplicate groups: `{counts['conflict_groups']}` / `{counts['duplicate_selector_groups']}`",
        f"- Ready raw event rows: `{counts['ready_raw_event_rows']}`",
        f"- Validated ready / execution blocked rows: `{counts['validated_ready_rows']}` / `{counts['execution_blocked_rows']}`",
        f"- Prewrite snapshots / hash matches: `{counts['prewrite_snapshot_rows']}` / `{counts['prewrite_hash_match_rows']}`",
        f"- Write committed rows: `{counts['write_committed_rows']}`",
        f"- Postwrite readback / time_iso matches: `{counts['postwrite_readback_rows']}` / `{counts['postwrite_time_iso_match_rows']}`",
        f"- Rollback contracts: `{counts['rollback_contract_rows']}`",
        f"- Leak hits public URL / sensitive key / local path: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
        "",
        "## Outputs",
        "",
        f"- Summary: `{outputs['summary_json']}`",
        f"- Prewrite snapshots: `{outputs['prewrite_snapshots']}`",
        f"- Write rows: `{outputs['write_rows']}`",
        f"- Postwrite readback: `{outputs['postwrite_readback']}`",
        f"- Rollback contracts: `{outputs['rollback_contracts']}`",
        f"- Execution blocked rows: `{outputs['execution_blocked_rows']}`",
        f"- Preflight blocked rows: `{outputs['preflight_blocked_rows']}`",
        "",
        "## Boundary Truth",
        "",
        f"- Source/raw DB opened read-write: `{str(boundary['source_raw_db_opened_read_write']).lower()}`",
        f"- Source/raw DB write executed: `{str(boundary['source_raw_db_write_executed']).lower()}`",
        f"- Source/raw DB write scope: `{boundary['source_raw_db_write_scope']}`",
        f"- Serving write/rebuild executed: `{str(boundary['serving_sqlite_write_or_rebuild_executed']).lower()}`",
        f"- Graph/vector/public mutation executed: `{str(boundary['neo4j_write_executed'] or boundary['qdrant_write_executed'] or boundary['public_pointer_updated']).lower()}`",
        f"- OCR/network/model/memory executed: `{str(boundary['ocr_executed'] or boundary['network_fetch_executed'] or boundary['model_call_executed'] or boundary['memory_write_executed']).lower()}`",
        "",
        "## Next",
        "",
        (
            f"Next resume pointer: `{summary['next_resume_pointer']}`. If the write is verified, "
            "the next bounded lane is a serving rebuild or read-model gap delta validation from "
            "the updated source/raw DB. If blocked, repair the blocked readback rows or continue "
            "the source/OCR time-title queues."
        ),
        "",
    ])


# ---------------------------------------------------------------------------
# Main build function
# ---------------------------------------------------------------------------


def build_gate(
    track_dirs: list[Path],
    target_db: Path,
    provenance_path: Path,
    out_dir: Path,
    report_path: Path,
    *,
    execute: bool,
    confirm_token: str,
    max_raw_matches: int,
) -> dict[str, Any]:
    generated_at = now_iso()
    out_dir.mkdir(parents=True, exist_ok=True)

    confirm_ok = (not execute) or confirm_token == CONFIRM_TOKEN
    initial_blockers = [] if confirm_ok else ["confirm_token_invalid_or_missing"]

    # Phase 1: Preflight -- map readback rows to raw events
    (
        ready_raw_rows,
        mapped_readback_rows,
        blocked_readback_rows,
        conflict_groups,
        duplicate_groups,
        critical_blockers,
        target_schema_hash,
        raw_index_keys,
    ) = run_preflight(track_dirs, target_db, provenance_path, generated_at, max_raw_matches)

    # Count inputs per track
    track_labels = ["A_exact_date", "B_year_span", "C_span_split"]
    track_input_counts = {label: 0 for label in track_labels}
    for track_dir, label in zip(track_dirs, track_labels):
        ready_path = track_dir / "time_title_readback_ready_report_only.jsonl"
        if ready_path.exists():
            track_input_counts[label] = len(read_jsonl(ready_path, f"count_{label}"))

    # Phase 2: Write execution gate
    ready_rows_for_write: list[dict[str, Any]] = []
    validated_blocked: list[dict[str, Any]] = []
    prewrite_snapshots: list[dict[str, Any]] = []
    write_rows: list[dict[str, Any]] = []
    postwrite_rows: list[dict[str, Any]] = []
    execution_blocked: list[dict[str, Any]] = []
    committed = False

    if not critical_blockers and ready_raw_rows:
        conn = open_rw(target_db)
        try:
            ready_rows_for_write, validated_blocked, prewrite_snapshots = validate_ready_rows(
                ready_raw_rows, target_db, conn, generated_at, target_schema_hash
            )
            if initial_blockers:
                for row in ready_rows_for_write:
                    validated_blocked.append({
                        "schema_version": SCHEMA_VERSION + ".blocked_row",
                        "generated_at": generated_at,
                        "raw_event_row_pk": int(row.get("raw_event_row_pk") or -1),
                        "proposed_time_iso": compact(row.get("proposed_time_iso"), 40),
                        "blockers": initial_blockers,
                        "write_executed": False,
                    })
                ready_rows_for_write = []

            write_rows, postwrite_rows, execution_blocked, committed = execute_time_iso_write(
                conn,
                ready_rows_for_write,
                generated_at,
                execute=execute and not validated_blocked,
            )
            validated_blocked.extend(execution_blocked)
        finally:
            conn.close()
    elif critical_blockers:
        validated_blocked = [
            {
                "schema_version": SCHEMA_VERSION + ".blocked_row",
                "generated_at": generated_at,
                "raw_event_row_pk": -1,
                "proposed_time_iso": "",
                "blockers": critical_blockers,
                "write_executed": False,
            }
        ]

    rollback = rollback_rows(ready_rows_for_write, generated_at)

    # Leak scan
    output_scan = merge_scan(
        scan_payload(prewrite_snapshots),
        scan_payload(write_rows),
        scan_payload(postwrite_rows),
        scan_payload(rollback),
        scan_payload(validated_blocked),
        scan_payload(mapped_readback_rows),
        scan_payload(blocked_readback_rows),
        scan_payload(conflict_groups),
        scan_payload(duplicate_groups),
    )

    failed_checks: list[str] = []
    if critical_blockers:
        failed_checks.append("critical_preflight_blockers_present")
    if validated_blocked:
        failed_checks.append("blocked_rows_present")
    if execute and not committed:
        failed_checks.append("write_not_committed")
    if any(output_scan.values()):
        failed_checks.append("leak_scan_hits_present")

    decision = (
        "atlas_t6_time_iso_write_execution_gate_source_raw_time_iso_write_verified"
        if execute and committed and not failed_checks
        else "atlas_t6_time_iso_write_execution_gate_dry_run_ready"
        if not execute and ready_rows_for_write and not failed_checks
        else "atlas_t6_time_iso_write_execution_gate_blocked"
    )

    counts = {
        "input_readback_rows_a": track_input_counts.get("A_exact_date", 0),
        "input_readback_rows_b": track_input_counts.get("B_year_span", 0),
        "input_readback_rows_c": track_input_counts.get("C_span_split", 0),
        "input_readback_rows_total": sum(track_input_counts.values()),
        "mapped_readback_rows": len(mapped_readback_rows),
        "blocked_readback_rows": len(blocked_readback_rows),
        "conflict_groups": len(conflict_groups),
        "duplicate_selector_groups": len(duplicate_groups),
        "ready_raw_event_rows": len(ready_raw_rows),
        "validated_ready_rows": len(ready_rows_for_write),
        "execution_blocked_rows": len(validated_blocked),
        "prewrite_snapshot_rows": len(prewrite_snapshots),
        "prewrite_hash_match_rows": sum(1 for row in prewrite_snapshots if row.get("hash_match") is True),
        "dry_run_rows": len(write_rows) if not execute else 0,
        "write_attempt_rows": len(write_rows) if execute else 0,
        "write_committed_rows": len(write_rows) if committed else 0,
        "postwrite_readback_rows": len(postwrite_rows),
        "postwrite_time_iso_match_rows": sum(1 for row in postwrite_rows if row.get("time_iso_matches") is True),
        "rollback_contract_rows": len(rollback),
        "transaction_committed": int(committed),
        "source_raw_db_write_executed_rows": len(write_rows) if committed else 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
        "raw_index_keys": raw_index_keys,
    }

    outputs = {
        "summary_json": display_path(out_dir / "time_iso_write_execution_summary.json"),
        "summary_md": display_path(out_dir / "time_iso_write_execution_summary.md"),
        "prewrite_snapshots": display_path(out_dir / "time_iso_write_execution_prewrite_snapshots.jsonl"),
        "write_rows": display_path(out_dir / "time_iso_write_execution_write_rows.jsonl"),
        "postwrite_readback": display_path(out_dir / "time_iso_write_execution_postwrite_readback.jsonl"),
        "rollback_contracts": display_path(out_dir / "time_iso_write_execution_rollback_contracts.jsonl"),
        "execution_blocked_rows": display_path(out_dir / "time_iso_write_execution_blocked_rows.jsonl"),
        "mapped_readback_rows": display_path(out_dir / "time_iso_write_execution_mapped_readback_rows.jsonl"),
        "preflight_blocked_rows": display_path(out_dir / "time_iso_write_execution_preflight_blocked_rows.jsonl"),
        "conflict_groups": display_path(out_dir / "time_iso_write_execution_conflict_groups.jsonl"),
        "duplicate_groups": display_path(out_dir / "time_iso_write_execution_duplicate_groups.jsonl"),
        "report": display_path(report_path),
    }

    boundary_truth = {
        "report_only": not committed,
        "source_raw_db_opened_read_write": True,
        "source_raw_db_write_executed": committed,
        "source_raw_db_write_scope": "events.time_iso only" if committed else "none",
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
    }

    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": generated_at,
        "decision": decision,
        "failed_checks": failed_checks,
        "execute_requested": execute,
        "confirm_token_sha256": sha256_text(confirm_token) if confirm_token else "",
        "counts": counts,
        "inputs": {
            "track_a_dir": display_path(track_dirs[0]) if len(track_dirs) > 0 else "",
            "track_b_dir": display_path(track_dirs[1]) if len(track_dirs) > 1 else "",
            "track_c_dir": display_path(track_dirs[2]) if len(track_dirs) > 2 else "",
            "target_db": display_path(target_db),
            "provenance_path": display_path(provenance_path),
        },
        "target_db": {
            "display": display_path(target_db),
            "schema_sha256": target_schema_hash,
            "written": committed,
        },
        "leak_scan": output_scan,
        "outputs": outputs,
        "boundary_truth": boundary_truth,
        "next_resume_pointer": (
            display_path(out_dir / "time_iso_write_execution_postwrite_readback.jsonl")
            if committed
            else display_path(out_dir / "time_iso_write_execution_blocked_rows.jsonl")
            if validated_blocked
            else display_path(out_dir / "time_iso_write_execution_write_rows.jsonl")
        ),
        "next_if_blocked": display_path(out_dir / "time_iso_write_execution_preflight_blocked_rows.jsonl"),
    }

    # Write all outputs
    write_jsonl(out_dir / "time_iso_write_execution_prewrite_snapshots.jsonl", prewrite_snapshots)
    write_jsonl(out_dir / "time_iso_write_execution_write_rows.jsonl", write_rows)
    write_jsonl(out_dir / "time_iso_write_execution_postwrite_readback.jsonl", postwrite_rows)
    write_jsonl(out_dir / "time_iso_write_execution_rollback_contracts.jsonl", rollback)
    write_jsonl(out_dir / "time_iso_write_execution_blocked_rows.jsonl", validated_blocked)
    write_jsonl(out_dir / "time_iso_write_execution_mapped_readback_rows.jsonl", mapped_readback_rows)
    write_jsonl(out_dir / "time_iso_write_execution_preflight_blocked_rows.jsonl", blocked_readback_rows)
    write_jsonl(out_dir / "time_iso_write_execution_conflict_groups.jsonl", conflict_groups)
    write_jsonl(out_dir / "time_iso_write_execution_duplicate_groups.jsonl", duplicate_groups)
    write_json(out_dir / "time_iso_write_execution_summary.json", summary)
    write_text(out_dir / "time_iso_write_execution_summary.md", render_summary(summary))
    write_text(report_path, render_report(summary))
    return summary


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--track-a-dir", type=Path, default=TRACK_A_DIR,
                        help="Track A (exact date) readback gate directory")
    parser.add_argument("--track-b-dir", type=Path, default=TRACK_B_DIR,
                        help="Track B (year/span) readback gate directory")
    parser.add_argument("--track-c-dir", type=Path, default=TRACK_C_DIR,
                        help="Track C (span split) readback gate directory")
    parser.add_argument("--target-db", type=Path, default=DEFAULT_TARGET_DB)
    parser.add_argument("--provenance", type=Path, default=DEFAULT_TARGET_DB_PROVENANCE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--max-raw-matches", type=int, default=80,
                        help="Max raw event matches per readback row (default 80)")
    parser.add_argument("--execute", action="store_true",
                        help="Actually write to source/raw DB (default: dry-run only)")
    parser.add_argument("--confirm-token", default="",
                        help=f"Required for --execute; must equal '{CONFIRM_TOKEN}'")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    track_dirs = [
        d for d in [args.track_a_dir, args.track_b_dir, args.track_c_dir]
        if d is not None and d.exists()
    ]
    if not track_dirs:
        print("No valid track directories found.", file=sys.stderr)
        sys.exit(1)

    summary = build_gate(
        track_dirs=track_dirs,
        target_db=args.target_db,
        provenance_path=args.provenance,
        out_dir=args.out_dir,
        report_path=args.report,
        execute=args.execute,
        confirm_token=args.confirm_token,
        max_raw_matches=args.max_raw_matches,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
