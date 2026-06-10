#!/usr/bin/env python3
"""Map manual participant/date candidates back to source/raw Atlas SQLite rows.

This probe is intentionally read-only. It binds selected serving-layer event
identity/date candidates to the source/raw article and event rows that can carry
the later write contract.
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
SCHEMA_VERSION = "stage7_atlas_social_manual_participant_source_raw_mapping_probe.v1"

DEFAULT_TARGET_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_incremental_wechat_refresh_20260522_1438"
    / "atlas_local_sqlite_db_139123_activity_candidate_current_20260525_1435"
    / "atlas.sqlite"
)
DEFAULT_REMAINING_READY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_remaining_identity_readback_gate_q6_20260526"
    / "event_identity_readback_ready_report_only.jsonl"
)
DEFAULT_MIDNIGHT_READY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_overnight_midnight_readback_gate_q6_20260526"
    / "overnight_midnight_readback_ready_report_only.jsonl"
)
DEFAULT_SOURCE_DATE_READY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_manual_participant_source_date_readback_gate_q6_20260526"
    / "source_date_readback_ready_report_only.jsonl"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_manual_participant_source_raw_mapping_probe_q6_20260526"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_MANUAL_PARTICIPANT_SOURCE_RAW_MAPPING_PROBE_20260526.md"

URL_RE = re.compile(r"https?://", re.I)
SECRET_RE = re.compile(r"\b(secret|token|cookie|password|api[_-]?key|authorization|bearer)\b", re.I)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.I,
)
DATE_RE = re.compile(r"(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})")


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_id(prefix: str, parts: Iterable[Any]) -> str:
    raw = "|".join(compact(part, 1000) for part in parts)
    return f"{prefix}:{sha256_text(raw)[:16]}"


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for source/raw mapping probe: {path}")


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return path.name


def sanitize_report_text(value: Any, limit: int = 1000) -> str:
    text = compact(value, limit).replace("\\", "/")
    text = URL_RE.sub("[url-redacted]", text)
    text = LOCAL_PATH_RE.sub("[local-path-redacted]", text)
    text = re.sub(r"token", "marker", text, flags=re.I)
    text = SECRET_RE.sub("[sensitive-label-redacted]", text)
    return text


def normalize_text(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 2000).casefold())


def normalize_name(value: Any) -> str:
    text = compact(value, 300).casefold()
    text = re.sub(r"\([^)]*\)", "", text)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def venue_family(value: Any) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    if "oil" in text or "车公庙泰然" in text or "l111a" in text or "l111a" in text.replace("一", "1"):
        return "oil"
    if "clubme" in text:
        return "clubme"
    if "coolwave" in text or "酷浪" in text:
        return "coolwaveclub"
    if "thebox" in text or "年轻力中心" in text:
        return "the_box"
    if "dada" in text and ("kunming" in text or "昆明" in text):
        return "dada_kunming"
    if "dada" in text and ("beijing" in text or "北京" in text):
        return "dada_beijing"
    return text


def grams(value: str) -> set[str]:
    text = normalize_text(value)
    if not text:
        return set()
    if len(text) <= 2:
        return {text}
    return {text[index : index + 2] for index in range(len(text) - 1)}


def title_similarity(raw_title: str, target_titles: Iterable[str]) -> float:
    raw_norm = normalize_text(raw_title)
    raw_grams = grams(raw_title)
    best = 0.0
    for title in target_titles:
        target_norm = normalize_text(title)
        if not raw_norm or not target_norm:
            continue
        if raw_norm in target_norm or target_norm in raw_norm:
            best = max(best, 1.0)
            continue
        target_grams = grams(title)
        if not raw_grams or not target_grams:
            continue
        overlap = len(raw_grams & target_grams)
        best = max(best, overlap / max(len(raw_grams), len(target_grams), 1))
    return round(best, 4)


def parse_date(value: Any) -> tuple[str, str, str] | None:
    match = DATE_RE.fullmatch(compact(value, 40))
    if not match:
        return None
    return match.group("year"), str(int(match.group("month"))), str(int(match.group("day")))


def date_variants(date_value: str) -> set[str]:
    parsed = parse_date(date_value)
    if not parsed:
        return set()
    year, month, day = parsed
    mm = f"{int(month):02d}"
    dd = f"{int(day):02d}"
    return {
        f"{year}{mm}{dd}",
        f"{year}年{month}月{day}日",
        f"{year}-{mm}-{dd}",
        f"{month}月{day}日",
        f"{int(month)}/{int(day)}",
        f"{mm}/{dd}",
    }


def date_matches(raw_time_text: str, raw_title: str, dates: Iterable[str]) -> list[str]:
    haystacks = [
        compact(raw_time_text, 200),
        compact(raw_title, 300),
        normalize_text(raw_time_text),
        normalize_text(raw_title),
    ]
    matched: list[str] = []
    for date_value in sorted({compact(item, 40) for item in dates if compact(item, 40)}):
        for variant in date_variants(date_value):
            normalized_variant = normalize_text(variant)
            if any(variant in haystack or normalized_variant in normalize_text(haystack) for haystack in haystacks):
                matched.append(date_value)
                break
    return sorted(set(matched))


def read_jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    reject_d_path(path, label)
    if not path.exists():
        return []
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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
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


def dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def list_values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def list_strings(value: Any, limit: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    return [compact(item, limit) for item in value if compact(item, limit)]


def parse_json_array(value: Any) -> list[str]:
    if isinstance(value, list):
        return [compact(item, 240) for item in value if compact(item, 240)]
    text = compact(value, 5000)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, list):
        return [compact(item, 240) for item in parsed if compact(item, 240)]
    return []


def row_hash(row: sqlite3.Row, columns: Iterable[str]) -> str:
    payload = {column: row[column] for column in columns if column in row.keys()}
    return sha256_text(canonical_json(payload))


def connect_readonly(path: Path) -> sqlite3.Connection:
    reject_d_path(path, "target_db")
    if not path.exists():
        raise FileNotFoundError(f"target DB does not exist: {path}")
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def lane_for(row: dict[str, Any]) -> str:
    db_readback = dict_value(row.get("db_readback"))
    if (
        row.get("overnight_midnight_acceptance_gate_id")
        or row.get("overnight_midnight_readback_selector_id")
        or row.get("midnight_boundary_date_report_only")
        or row.get("normalized_boundary_report_only")
        or db_readback.get("boundary_dates_required")
    ):
        return "overnight_midnight_boundary"
    if row.get("source_date_acceptance_gate_id") or row.get("selected_date_report_only"):
        return "manual_date_context"
    return "remaining_event_identity"


def selected_event_ids(row: dict[str, Any]) -> list[str]:
    target_selector = dict_value(row.get("target_selector"))
    rollback = dict_value(row.get("rollback_contract"))
    return (
        list_strings(row.get("selected_event_ids_review_only"), 180)
        or list_strings(row.get("selected_event_ids_report_only"), 180)
        or list_strings(target_selector.get("selected_event_ids"), 180)
        or list_strings(rollback.get("selected_event_ids_report_only"), 180)
    )


def representative_event_id(row: dict[str, Any], ids: list[str]) -> str:
    target_selector = dict_value(row.get("target_selector"))
    return compact(row.get("representative_event_id_review_only"), 180) or compact(
        target_selector.get("representative_event_id"), 180
    ) or (ids[0] if ids else "")


def source_ref_ids(row: dict[str, Any]) -> list[str]:
    target_selector = dict_value(row.get("target_selector"))
    refs = list_strings(row.get("source_ref_ids"), 180) or list_strings(target_selector.get("source_ref_ids"), 180)
    evidence_refs = [
        compact(item.get("source_ref_id"), 180)
        for item in list_values(row.get("source_evidence_sample"))
        if isinstance(item, dict) and compact(item.get("source_ref_id"), 180)
    ]
    db_refs = [
        compact(item.get("source_ref_id"), 180)
        for item in list_values(dict_value(row.get("db_readback")).get("evidence_ref_rows"))
        if isinstance(item, dict) and compact(item.get("source_ref_id"), 180)
    ]
    return sorted(set(refs + evidence_refs + db_refs))


def target_dates(row: dict[str, Any]) -> list[str]:
    target_selector = dict_value(row.get("target_selector"))
    normalized_boundary = dict_value(row.get("normalized_boundary_report_only"))
    candidates: set[str] = set()
    for key in (
        "selected_date_report_only",
        "boundary_start_date_report_only",
        "midnight_boundary_date_report_only",
        "boundary_start_date",
        "midnight_boundary_date",
    ):
        value = row.get(key) or target_selector.get(key)
        if parse_date(value):
            candidates.add(compact(value, 40))
    for key in ("start_date_report_only", "midnight_boundary_date_report_only"):
        value = normalized_boundary.get(key)
        if parse_date(value):
            candidates.add(compact(value, 40))
    for item in list_values(row.get("candidate_date_values")):
        if parse_date(item):
            candidates.add(compact(item, 40))
    for item in dict_value(row.get("boundary_date_counts")).keys():
        if parse_date(item):
            candidates.add(compact(item, 40))
    for cluster in list_values(row.get("selected_semantic_event_clusters")):
        if isinstance(cluster, dict) and parse_date(cluster.get("starts_at")):
            candidates.add(compact(cluster.get("starts_at"), 40))
    for cluster in list_values(row.get("semantic_event_clusters_for_review")):
        if isinstance(cluster, dict) and parse_date(cluster.get("starts_at")):
            candidates.add(compact(cluster.get("starts_at"), 40))
    return sorted(candidates)


def target_titles(row: dict[str, Any]) -> list[str]:
    values = [compact(row.get("title"), 500), compact(row.get("name"), 500)]
    db_readback = dict_value(row.get("db_readback"))
    perf = dict_value(db_readback.get("performance_event_rows"))
    values.extend(list_strings(perf.get("title_sample"), 500))
    for cluster in list_values(row.get("selected_semantic_event_clusters")):
        if isinstance(cluster, dict):
            values.append(compact(cluster.get("event_title_sample"), 500))
    return sorted({sanitize_report_text(item, 500) for item in values if compact(item, 500)})


def target_venues(row: dict[str, Any]) -> list[str]:
    values: list[str] = []
    db_readback = dict_value(row.get("db_readback"))
    perf = dict_value(db_readback.get("performance_event_rows"))
    values.extend(list_strings(perf.get("venue_values"), 300))
    values.extend(list_strings(perf.get("venue_normalized_values"), 300))
    for cluster in list_values(row.get("selected_semantic_event_clusters")):
        if isinstance(cluster, dict):
            values.append(compact(cluster.get("canonical_venue"), 300))
            values.append(compact(cluster.get("venue_name_sample"), 300))
            values.append(compact(cluster.get("venue_family"), 300))
    return sorted({sanitize_report_text(item, 300) for item in values if compact(item, 300)})


def target_participants(row: dict[str, Any]) -> list[str]:
    sample = list_values(dict_value(row.get("db_readback")).get("participant_evidence_sample"))
    names = [
        compact(item.get("display_name"), 240)
        for item in sample
        if isinstance(item, dict) and compact(item.get("display_name"), 240)
    ]
    return sorted(set(names))


def fetch_article(conn: sqlite3.Connection, article_uid: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT row_pk, article_id, article_uid, title, source_account, publish_time,
                   publish_time_status, publish_time_index_status, city_label, local_image_count,
                   source_archived_at, raw_json
            FROM articles
            WHERE article_uid = ?
            ORDER BY row_pk
            """,
            (article_uid,),
        )
    )


def fetch_events(conn: sqlite3.Connection, article_uid: str) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            """
            SELECT row_pk, evid, name, place, city, time_iso, time_text, source_kind,
                   source_article_uid, confidence, participants_json, organizers_json, raw_json
            FROM events
            WHERE source_article_uid = ?
            ORDER BY row_pk
            """,
            (article_uid,),
        )
    )


def article_snapshot(row: sqlite3.Row) -> dict[str, Any]:
    raw_json = compact(row["raw_json"], 500000)
    return {
        "row_pk": row["row_pk"],
        "article_id": sanitize_report_text(row["article_id"], 260),
        "article_uid": sanitize_report_text(row["article_uid"], 320),
        "title": sanitize_report_text(row["title"], 500),
        "source_account": sanitize_report_text(row["source_account"], 260),
        "publish_time": sanitize_report_text(row["publish_time"], 120),
        "publish_time_status": sanitize_report_text(row["publish_time_status"], 120),
        "publish_time_index_status": sanitize_report_text(row["publish_time_index_status"], 120),
        "city_label": sanitize_report_text(row["city_label"], 120),
        "local_image_count": row["local_image_count"],
        "source_archived_at": sanitize_report_text(row["source_archived_at"], 120),
        "row_hash": row_hash(row, row.keys()),
        "raw_json_hash": sha256_text(raw_json) if raw_json else "",
    }


def score_raw_event(raw: sqlite3.Row, context: dict[str, Any]) -> dict[str, Any]:
    raw_participants = parse_json_array(raw["participants_json"])
    normalized_raw_participants = {normalize_name(item): item for item in raw_participants if normalize_name(item)}
    normalized_target_participants = {
        normalize_name(item): item for item in context["target_participants"] if normalize_name(item)
    }
    participant_overlap = sorted(
        {
            normalized_target_participants[name]
            for name in normalized_raw_participants.keys() & normalized_target_participants.keys()
        }
    )
    matched_dates = date_matches(compact(raw["time_text"], 300), compact(raw["name"], 300), context["target_dates"])
    raw_venue_family = venue_family(raw["place"])
    target_venue_families = {venue_family(item) for item in context["target_venues"] if venue_family(item)}
    venue_match = bool(raw_venue_family and raw_venue_family in target_venue_families)
    sim = title_similarity(compact(raw["name"], 300), context["target_titles"])

    score = 0.0
    score += 5.0 + min(len(participant_overlap), 5) if participant_overlap else 0.0
    score += 3.0 if matched_dates else 0.0
    score += 2.0 if venue_match else 0.0
    if sim >= 0.55:
        score += 3.0
    elif sim >= 0.25:
        score += 2.0
    elif sim >= 0.12:
        score += 1.0

    reasons: list[str] = []
    if participant_overlap:
        reasons.append("participant_overlap")
    if matched_dates:
        reasons.append("date_match")
    if venue_match:
        reasons.append("venue_match")
    if sim >= 0.25:
        reasons.append("title_similarity")
    elif sim >= 0.12:
        reasons.append("weak_title_similarity")

    return {
        "raw_event_row_pk": raw["row_pk"],
        "raw_event_evid": sanitize_report_text(raw["evid"], 160),
        "raw_event_name": sanitize_report_text(raw["name"], 300),
        "raw_event_place": sanitize_report_text(raw["place"], 300),
        "raw_event_city": sanitize_report_text(raw["city"], 120),
        "raw_event_time_iso": sanitize_report_text(raw["time_iso"], 120),
        "raw_event_time_text": sanitize_report_text(raw["time_text"], 200),
        "raw_participant_count": len(raw_participants),
        "raw_participant_sample": [sanitize_report_text(item, 160) for item in raw_participants[:8]],
        "participant_overlap": [sanitize_report_text(item, 160) for item in participant_overlap],
        "matched_dates": matched_dates,
        "venue_family": raw_venue_family,
        "venue_match": venue_match,
        "title_similarity": sim,
        "score": round(score, 3),
        "score_reasons": reasons,
        "row_hash": row_hash(raw, raw.keys()),
        "raw_json_hash": sha256_text(compact(raw["raw_json"], 500000)) if compact(raw["raw_json"], 100) else "",
    }


def selected_raw_event_score(score_row: dict[str, Any]) -> bool:
    reasons = set(score_row.get("score_reasons") or [])
    if "participant_overlap" in reasons and (reasons & {"date_match", "venue_match", "title_similarity"}):
        return True
    if "title_similarity" in reasons and "venue_match" in reasons:
        return True
    if "date_match" in reasons and (reasons & {"venue_match", "title_similarity"}):
        return True
    return False


def build_context(row: dict[str, Any], source_label: str) -> dict[str, Any]:
    ids = selected_event_ids(row)
    return {
        "input_source": source_label,
        "candidate_lane": lane_for(row),
        "article_uid": compact(row.get("article_uid"), 320),
        "source_account": sanitize_report_text(row.get("source_account"), 260),
        "source_ref_ids": source_ref_ids(row),
        "source_hash": compact(row.get("source_hash") or dict_value(row.get("target_selector")).get("source_hash"), 120),
        "selected_event_ids": ids,
        "selected_event_id_count": len(ids),
        "representative_event_id": representative_event_id(row, ids),
        "target_dates": target_dates(row),
        "target_titles": target_titles(row),
        "target_venues": target_venues(row),
        "target_participants": target_participants(row),
        "upstream_id": compact(
            row.get("resolution_id")
            or row.get("source_date_acceptance_gate_id")
            or row.get("overnight_midnight_acceptance_gate_id")
            or row.get("work_item_id"),
            180,
        ),
    }


def map_candidate(conn: sqlite3.Connection, row: dict[str, Any], source_label: str) -> dict[str, Any]:
    context = build_context(row, source_label)
    article_uid = context["article_uid"]
    blockers: list[str] = []
    if not article_uid:
        blockers.append("missing_article_uid")

    article_rows = fetch_article(conn, article_uid) if article_uid else []
    event_rows = fetch_events(conn, article_uid) if article_uid else []
    if len(article_rows) != 1:
        blockers.append("source_raw_article_uid_not_unique")
    if not event_rows:
        blockers.append("source_raw_article_events_missing")

    scored = [score_raw_event(raw, context) for raw in event_rows]
    scored.sort(key=lambda item: (-item["score"], item["raw_event_row_pk"]))
    best = scored[0] if scored else {}
    strong_best = bool(best and best.get("score", 0) >= 4.0 and best.get("score_reasons"))
    if event_rows and not strong_best:
        blockers.append("source_raw_event_selector_weak")

    ready = not blockers
    selected_raw_event_row_pks = [item["raw_event_row_pk"] for item in scored if selected_raw_event_score(item)][:12]
    if ready and not selected_raw_event_row_pks and best:
        blockers.append("source_raw_event_selector_context_incomplete")
        ready = False

    return {
        "schema_version": SCHEMA_VERSION + ".row",
        "mapping_probe_id": stable_id(
            "sourcerawmapping",
            [source_label, article_uid, context["selected_event_ids"], context["target_dates"]],
        ),
        "generated_at": now_iso(),
        "input_source": source_label,
        "candidate_lane": context["candidate_lane"],
        "article_uid": sanitize_report_text(article_uid, 320),
        "source_account": context["source_account"],
        "upstream_id": context["upstream_id"],
        "source_ref_ids": context["source_ref_ids"],
        "source_hash": sanitize_report_text(context["source_hash"], 120),
        "selected_event_ids_report_only": context["selected_event_ids"],
        "representative_event_id_report_only": context["representative_event_id"],
        "target_dates": context["target_dates"],
        "target_title_sample": context["target_titles"][:5],
        "target_venue_sample": context["target_venues"][:5],
        "target_participant_sample": [sanitize_report_text(item, 160) for item in context["target_participants"][:12]],
        "source_raw_article_rows": [article_snapshot(item) for item in article_rows],
        "source_raw_article_row_count": len(article_rows),
        "source_raw_event_candidate_count": len(event_rows),
        "source_raw_event_score_rows": scored[:12],
        "selected_raw_event_row_pks_report_only": selected_raw_event_row_pks,
        "source_raw_mapping_ready_report_only": ready,
        "source_raw_mapping_blockers": blockers,
        "source_raw_db_opened_read_only": True,
        "prewrite_snapshot_contract": {
            "required": True,
            "read_only_snapshot_first": True,
            "source_raw_target_db_required": True,
            "must_capture_article_row_hashes": True,
            "must_capture_event_row_hashes": True,
            "must_capture_selected_raw_event_row_pks": True,
            "write_execution_allowed_now": False,
        },
        "rollback_contract": {
            "required": True,
            "inverse_mapping_required": True,
            "article_uid": sanitize_report_text(article_uid, 320),
            "selected_raw_event_row_pks_report_only": selected_raw_event_row_pks,
            "selected_serving_event_ids_report_only": context["selected_event_ids"],
            "postwrite_readback_required": True,
            "write_execution_allowed_now": False,
        },
        "postwrite_readback_contract": {
            "required": True,
            "must_verify": [
                "source/raw article row hash drift is limited to declared selectors",
                "source/raw event rows read back with the declared article_uid and selected raw row_pk set",
                "participant/date/venue evidence remains recoverable",
                "serving rebuild diff preserves selected serving event identity lineage",
                "Neo4j/Qdrant/public pointer are verified separately after serving rebuild",
            ],
            "write_execution_allowed_now": False,
        },
        "accepted_for_graph": False,
        "source_sqlite_write_allowed": False,
        "serving_rebuild_allowed": False,
        "graph_write_allowed": False,
        "public_serving_field_allowed": False,
        "memory_write_allowed": False,
        "write_execution_allowed_now": False,
        "write_status": "report_only",
    }


def scan_payload(payload: Any) -> dict[str, int]:
    text = canonical_json(payload)
    return {
        "public_url_hits": len(URL_RE.findall(text)),
        "sensitive_key_hits": len(SECRET_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
    }


def source_group_batches(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[compact(row.get("source_account"), 260)].append(row)
    batches: list[dict[str, Any]] = []
    for source_account, group in sorted(grouped.items()):
        ready = [row for row in group if row["source_raw_mapping_ready_report_only"]]
        batches.append(
            {
                "schema_version": SCHEMA_VERSION + ".source_account_batch",
                "source_account": sanitize_report_text(source_account, 260),
                "row_count": len(group),
                "ready_rows": len(ready),
                "blocked_rows": len(group) - len(ready),
                "article_uids": sorted({row["article_uid"] for row in group}),
                "candidate_lanes": dict(Counter(row["candidate_lane"] for row in group)),
                "write_execution_allowed_now": False,
            }
        )
    return batches


def render_summary_md(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    leak = summary["leak_counts"]
    return f"""# Atlas Manual Participant Source/Raw Mapping Probe

- Generated at: `{summary['generated_at']}`
- Decision: `{summary['decision']}`
- Failed checks: `{summary['failed_checks']}`
- Target DB: `{summary['target_db']['target_db_display_path']}`
- Target DB opened read-only: `{summary['safety']['source_sqlite_opened_read_only']}`
- Input / ready / blocked rows: `{counts['input_target_rows']}/{counts['ready_rows']}/{counts['blocked_rows']}`
- Lane split: `{counts['lane_rows']}`
- Unique articles / selected serving events / selected raw event rows: `{counts['unique_article_uids']}/{counts['unique_selected_serving_event_ids']}/{counts['unique_selected_raw_event_row_pks']}`
- Direct explicit source/raw target DB paths: `{counts['direct_existing_explicit_source_raw_target_db_paths']}`
- Write execution allowed rows: `{counts['write_execution_allowed_rows']}`
- Accepted/source-sqlite/serving/graph/public/memory rows: `0/0/0/0/0/0`
- Leak hits public/sensitive/local: `{leak['public_url_hits']}/{leak['sensitive_key_hits']}/{leak['local_path_hits']}`

## Boundary

Report-only source/raw mapping probe. It opens the explicit target `atlas.sqlite` read-only and does not write source/raw DB, serving SQLite, Neo4j, Qdrant, production SQLite, public pointers, CloudRun/VPS, mini-program state, or memory.

## Next Resume Pointer

`{summary['next_resume_pointer']}`
"""


def render_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    outputs = summary["outputs"]
    return f"""# Atlas T6 Manual Participant Source/Raw Mapping Probe - 2026-05-26

## Decision

`{summary['decision']}`

## Evidence

- Target DB: `{summary['target_db']['target_db_display_path']}`
- Target DB hash: `{summary['target_db']['target_db_sha256']}`
- Input / ready / blocked rows: `{counts['input_target_rows']}/{counts['ready_rows']}/{counts['blocked_rows']}`
- Lane split: `{counts['lane_rows']}`
- Unique articles / selected serving events / selected raw event rows: `{counts['unique_article_uids']}/{counts['unique_selected_serving_event_ids']}/{counts['unique_selected_raw_event_row_pks']}`
- Source-account batches: `{counts['source_account_batches']}`
- Leak hits public/sensitive/local: `{summary['leak_counts']['public_url_hits']}/{summary['leak_counts']['sensitive_key_hits']}/{summary['leak_counts']['local_path_hits']}`

## Outputs

- Summary JSON: `{outputs['summary_json']}`
- Provenance summary JSON: `{outputs['target_db_provenance_summary']}`
- Mapping ready rows: `{outputs['source_raw_mapping_ready_rows']}`
- Mapping blocked rows: `{outputs['source_raw_mapping_blocked_rows']}`
- All mapping rows: `{outputs['source_raw_mapping_rows']}`
- Source-account batches: `{outputs['source_account_batches']}`

## Boundary Truth

This packet opens the explicit source/raw candidate DB in read-only mode only. It does not write source/raw Atlas DB, rebuild/write serving SQLite, accept graph facts, write Neo4j/Qdrant/production SQLite, update public pointers, deploy CloudRun/VPS, upload/review mini-program, execute network/OCR/model calls, or write memory.

## Next

Use `{outputs['target_db_provenance_summary']}` as the provenance summary for the remaining identity, midnight-boundary, and source-date acceptance/write-gate contracts. The next write-capable packet must still capture prewrite row hashes, inverse rollback, minimal mutation scope, and postwrite readback before any production/public promotion.
"""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_packet(
    target_db: Path,
    remaining_ready: Path,
    midnight_ready: Path,
    source_date_ready: Path,
    out_dir: Path,
    report: Path,
) -> dict[str, Any]:
    reject_d_path(target_db, "target_db")
    reject_d_path(out_dir, "out_dir")
    reject_d_path(report, "report")
    inputs = [
        ("remaining_event_identity", remaining_ready),
        ("overnight_midnight_boundary", midnight_ready),
        ("manual_date_context", source_date_ready),
    ]
    input_rows: list[tuple[str, dict[str, Any]]] = []
    for source_label, path in inputs:
        for row in read_jsonl(path, source_label):
            input_rows.append((source_label, row))

    mapped_pairs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    with connect_readonly(target_db) as conn:
        for source_label, original_row in input_rows:
            mapped_pairs.append((source_label, original_row, map_candidate(conn, original_row, source_label)))
    rows = [mapped_row for _, _, mapped_row in mapped_pairs]

    ready_rows = [row for row in rows if row["source_raw_mapping_ready_report_only"]]
    blocked_rows = [row for row in rows if not row["source_raw_mapping_ready_report_only"]]
    batches = source_group_batches(rows)
    leak_counts = scan_payload(rows + batches)
    failed_checks = [key for key, value in leak_counts.items() if value]
    if blocked_rows:
        failed_checks.append("source_raw_mapping_blocked_rows_present")

    target_db_hash = file_sha256(target_db)
    outputs = {
        "summary_json": display_path(out_dir / "source_raw_mapping_probe_summary.json"),
        "summary_md": display_path(out_dir / "source_raw_mapping_probe_summary.md"),
        "target_db_provenance_summary": display_path(out_dir / "source_raw_mapping_target_db_provenance_summary.json"),
        "source_raw_mapping_rows": display_path(out_dir / "source_raw_mapping_rows.jsonl"),
        "source_raw_mapping_ready_rows": display_path(out_dir / "source_raw_mapping_ready_report_only.jsonl"),
        "source_raw_mapping_blocked_rows": display_path(out_dir / "source_raw_mapping_blocked_rows.jsonl"),
        "source_account_batches": display_path(out_dir / "source_account_source_raw_mapping_batches.jsonl"),
        "remaining_identity_gate_ready_rows": display_path(out_dir / "remaining_identity_gate_ready_input_rows.jsonl"),
        "remaining_identity_target_db_provenance_summary": display_path(
            out_dir / "remaining_identity_target_db_provenance_summary.json"
        ),
        "overnight_midnight_gate_ready_rows": display_path(out_dir / "overnight_midnight_gate_ready_input_rows.jsonl"),
        "overnight_midnight_target_db_provenance_summary": display_path(
            out_dir / "overnight_midnight_target_db_provenance_summary.json"
        ),
        "manual_date_context_gate_ready_rows": display_path(out_dir / "manual_date_context_gate_ready_input_rows.jsonl"),
        "manual_date_context_target_db_provenance_summary": display_path(
            out_dir / "manual_date_context_target_db_provenance_summary.json"
        ),
        "manual_date_context_mapping_blocked_original_rows": display_path(
            out_dir / "manual_date_context_mapping_blocked_original_rows.jsonl"
        ),
    }
    counts = {
        "input_target_rows": len(input_rows),
        "mapping_rows": len(rows),
        "ready_rows": len(ready_rows),
        "blocked_rows": len(blocked_rows),
        "source_raw_mapping_ready_rows": len(ready_rows),
        "source_raw_mapping_blocked_rows": len(blocked_rows),
        "direct_existing_explicit_source_raw_target_db_paths": 1 if target_db.exists() else 0,
        "unique_article_uids": len({row["article_uid"] for row in rows if row["article_uid"]}),
        "unique_selected_serving_event_ids": len(
            {event_id for row in rows for event_id in row["selected_event_ids_report_only"]}
        ),
        "unique_selected_raw_event_row_pks": len(
            {row_pk for row in rows for row_pk in row["selected_raw_event_row_pks_report_only"]}
        ),
        "source_account_batches": len(batches),
        "lane_rows": dict(Counter(row["candidate_lane"] for row in rows)),
        "lane_ready_rows": dict(Counter(row["candidate_lane"] for row in ready_rows)),
        "lane_blocked_rows": dict(Counter(row["candidate_lane"] for row in blocked_rows)),
        "write_execution_allowed_rows": 0,
        "accepted_for_graph_rows": 0,
        "source_sqlite_write_allowed_rows": 0,
        "serving_rebuild_allowed_rows": 0,
        "graph_write_allowed_rows": 0,
        "public_serving_field_allowed_rows": 0,
        "memory_write_allowed_rows": 0,
    }
    decision = (
        "atlas_social_manual_participant_source_raw_mapping_probe_ready_report_only"
        if not failed_checks
        else "atlas_social_manual_participant_source_raw_mapping_probe_blocked_report_only"
    )
    summary = {
        "schema_version": SCHEMA_VERSION + ".summary",
        "generated_at": now_iso(),
        "decision": decision,
        "failed_checks": failed_checks,
        "counts": counts,
        "inputs": {
            "remaining_ready": display_path(remaining_ready),
            "midnight_ready": display_path(midnight_ready),
            "source_date_ready": display_path(source_date_ready),
        },
        "target_db": {
            "target_db_display_path": display_path(target_db),
            "target_db_sha256": target_db_hash,
            "target_db_exists": target_db.exists(),
            "source_raw_target_db_ready": not failed_checks,
        },
        "outputs": outputs,
        "leak_counts": leak_counts,
        "safety": {
            "report_only": True,
            "source_sqlite_opened_read_only": True,
            "source_sqlite_write_executed": False,
            "serving_sqlite_opened": False,
            "serving_sqlite_rebuild_executed": False,
            "network_call_executed": False,
            "ocr_executed": False,
            "model_call_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "production_write_executed": False,
            "memory_write_executed": False,
            "credential_read": False,
            "d_root_scan": False,
        },
        "write_guards": {
            "write_execution_allowed_now": False,
            "accepted_for_graph": False,
            "source_sqlite_write_allowed": False,
            "serving_rebuild_allowed": False,
            "graph_write_allowed": False,
            "public_serving_field_allowed": False,
            "memory_write_allowed": False,
        },
        "next_resume_pointer": outputs["target_db_provenance_summary"],
        "stop_reason": "" if not failed_checks else ",".join(failed_checks),
    }
    provenance_summary = {
        "schema_version": SCHEMA_VERSION + ".target_db_provenance_summary",
        "generated_at": summary["generated_at"],
        "decision": "atlas_social_manual_participant_source_raw_target_db_mapping_ready_report_only"
        if not failed_checks
        else "atlas_social_manual_participant_source_raw_target_db_mapping_blocked_report_only",
        "failed_checks": failed_checks,
        "counts": counts,
        "target_db": summary["target_db"],
        "mapping_probe_summary": outputs["summary_json"],
        "source_raw_target_db_ready": not failed_checks,
        "write_execution_allowed_rows": 0,
        "write_execution_allowed_now": False,
        "report_only": True,
    }
    gate_ready_inputs: dict[str, list[dict[str, Any]]] = {
        "remaining_event_identity": [],
        "overnight_midnight_boundary": [],
        "manual_date_context": [],
    }
    gate_blocked_inputs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for _, original_row, mapped_row in mapped_pairs:
        lane = mapped_row["candidate_lane"]
        if mapped_row["source_raw_mapping_ready_report_only"]:
            gate_ready_inputs[lane].append(original_row)
        else:
            gate_blocked_inputs[lane].append(original_row)

    lane_provenance: dict[str, dict[str, Any]] = {}
    for lane, gate_rows in gate_ready_inputs.items():
        mapped_for_lane = [row for row in ready_rows if row["candidate_lane"] == lane]
        blocked_for_lane = [row for row in blocked_rows if row["candidate_lane"] == lane]
        lane_counts = dict(counts)
        lane_counts.update(
            {
                "input_target_rows": len(gate_rows),
                "mapping_rows": len(mapped_for_lane),
                "ready_rows": len(mapped_for_lane),
                "blocked_rows": 0,
                "source_raw_mapping_ready_rows": len(mapped_for_lane),
                "source_raw_mapping_blocked_rows": 0,
                "unique_article_uids": len({row["article_uid"] for row in mapped_for_lane if row["article_uid"]}),
                "unique_selected_serving_event_ids": len(
                    {event_id for row in mapped_for_lane for event_id in row["selected_event_ids_report_only"]}
                ),
                "unique_selected_raw_event_row_pks": len(
                    {row_pk for row in mapped_for_lane for row_pk in row["selected_raw_event_row_pks_report_only"]}
                ),
                "lane_total_blocked_rows_excluded_from_this_gate": len(blocked_for_lane),
            }
        )
        lane_provenance[lane] = {
            "schema_version": SCHEMA_VERSION + ".lane_target_db_provenance_summary",
            "generated_at": summary["generated_at"],
            "decision": f"atlas_social_manual_participant_{lane}_source_raw_target_db_mapping_ready_report_only"
            if mapped_for_lane
            else f"atlas_social_manual_participant_{lane}_source_raw_target_db_mapping_empty_report_only",
            "failed_checks": [] if mapped_for_lane else ["no_lane_ready_rows"],
            "counts": lane_counts,
            "target_db": summary["target_db"] | {"source_raw_target_db_ready": bool(mapped_for_lane)},
            "mapping_probe_summary": outputs["summary_json"],
            "source_raw_target_db_ready": bool(mapped_for_lane),
            "write_execution_allowed_rows": 0,
            "write_execution_allowed_now": False,
            "report_only": True,
            "excluded_blocked_rows_for_same_lane": len(blocked_for_lane),
        }

    write_json(out_dir / "source_raw_mapping_probe_summary.json", summary)
    write_json(out_dir / "source_raw_mapping_target_db_provenance_summary.json", provenance_summary)
    write_json(out_dir / "remaining_identity_target_db_provenance_summary.json", lane_provenance["remaining_event_identity"])
    write_json(out_dir / "overnight_midnight_target_db_provenance_summary.json", lane_provenance["overnight_midnight_boundary"])
    write_json(out_dir / "manual_date_context_target_db_provenance_summary.json", lane_provenance["manual_date_context"])
    write_text(out_dir / "source_raw_mapping_probe_summary.md", render_summary_md(summary))
    write_jsonl(out_dir / "source_raw_mapping_rows.jsonl", rows)
    write_jsonl(out_dir / "source_raw_mapping_ready_report_only.jsonl", ready_rows)
    write_jsonl(out_dir / "source_raw_mapping_blocked_rows.jsonl", blocked_rows)
    write_jsonl(out_dir / "source_account_source_raw_mapping_batches.jsonl", batches)
    write_jsonl(out_dir / "remaining_identity_gate_ready_input_rows.jsonl", gate_ready_inputs["remaining_event_identity"])
    write_jsonl(out_dir / "overnight_midnight_gate_ready_input_rows.jsonl", gate_ready_inputs["overnight_midnight_boundary"])
    write_jsonl(out_dir / "manual_date_context_gate_ready_input_rows.jsonl", gate_ready_inputs["manual_date_context"])
    write_jsonl(
        out_dir / "manual_date_context_mapping_blocked_original_rows.jsonl",
        gate_blocked_inputs.get("manual_date_context", []),
    )
    write_text(report, render_report(summary))
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-db", type=Path, default=DEFAULT_TARGET_DB)
    parser.add_argument("--remaining-ready", type=Path, default=DEFAULT_REMAINING_READY)
    parser.add_argument("--midnight-ready", type=Path, default=DEFAULT_MIDNIGHT_READY)
    parser.add_argument("--source-date-ready", type=Path, default=DEFAULT_SOURCE_DATE_READY)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    summary = build_packet(
        args.target_db,
        args.remaining_ready,
        args.midnight_ready,
        args.source_date_ready,
        args.out_dir,
        args.report,
    )
    print(json.dumps({"decision": summary["decision"], "counts": summary["counts"]}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
