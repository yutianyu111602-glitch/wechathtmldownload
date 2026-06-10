#!/usr/bin/env python3
"""Validate short Chinese city search for the T5 serving city overlay.

The 07:24 smoke proved direct search_document and graph readback for the city
overlay, but it also showed that FTS queries for two-character city names return
zero rows under the trigram tokenizer. This gate proves the candidate has the
city text needed by direct/LIKE fallback search and verifies that the service
code contains the guarded city fallback before any public-serving promotion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE7_ROOT = SCRIPT_DIR.parent

DEFAULT_SMOKE_SUMMARY = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t5_serving_city_overlay_search_graph_smoke_20260527"
    / "serving_city_overlay_search_graph_smoke_summary.json"
)
DEFAULT_OVERLAY_ROWS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_t5_serving_city_overlay_candidate_20260527"
    / "serving_city_overlay_search_document_rows.jsonl"
)
DEFAULT_SERVICE_STORE = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "src" / "stage7AtlasSqliteStore.mjs"
DEFAULT_SERVICE_TEST = (
    REPO_ROOT / "services" / "weekly_activity_cloudrun" / "tests" / "stage7SqliteLocal.test.mjs"
)
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_t5_serving_city_overlay_short_city_search_gate_20260527"
DEFAULT_REPORT_PATH = REPO_ROOT / "reports" / "ATLAS_T5_SERVING_CITY_OVERLAY_SHORT_CITY_SEARCH_GATE_20260527.md"

PUBLIC_URL_RE = re.compile(r"https?://|mp\.weixin\.qq\.com|wx\.qq\.com", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"(?:[A-Za-z]:\\|\\\\wsl|/mnt/|/home/)", re.IGNORECASE)
SENSITIVE_KEY_RE = re.compile(
    r"(?:api[_-]?key|secret|password|access[_-]?token|refresh[_-]?token|cookie|openid|unionid|fakeid)\s*[:=]",
    re.IGNORECASE,
)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def now_stamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT)).replace("/", "\\")
    except ValueError:
        return f"<external_path_hash:{hashlib.sha256(str(path).encode('utf-8')).hexdigest()[:16]}>"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            value = json.loads(text)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_no} is not a JSON object")
            rows.append(value)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def chunked(values: list[str], size: int = 500) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset : offset + size]


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def resolve_candidate_db(smoke_summary: dict[str, Any]) -> Path:
    raw = smoke_summary.get("inputs", {}).get("candidate_db") or ""
    if not raw:
        raise ValueError("smoke summary missing inputs.candidate_db")
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    return candidate


def city_is_short_cjk(city: str) -> bool:
    return bool(city and len(city) <= 2 and CJK_RE.search(city))


def fetch_event_docs(conn: sqlite3.Connection, event_ids: list[str]) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    for batch in chunked(event_ids):
        placeholders = ",".join("?" for _ in batch)
        for row in conn.execute(
            f"""
            SELECT doc_rowid, subject_id, city_text, search_text
            FROM search_document
            WHERE subject_type = 'event' AND subject_id IN ({placeholders})
            """,
            batch,
        ):
            docs[str(row["subject_id"])] = {
                "doc_rowid": int(row["doc_rowid"]),
                "city_text": row["city_text"] or "",
                "search_text": row["search_text"] or "",
            }
    return docs


def fts_match_count(conn: sqlite3.Connection, term: str) -> tuple[int, str]:
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM search_document_fts WHERE search_document_fts MATCH ?",
            (f'"{term}"',),
        ).fetchone()
        return int(row[0] or 0), ""
    except sqlite3.Error as exc:
        return 0, f"{exc.__class__.__name__}: {exc}"


def like_city_count(conn: sqlite3.Connection, term: str) -> int:
    like = f"%{term}%"
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM search_document
        WHERE subject_type = 'event'
          AND (city_text = ? OR search_text LIKE ?)
        """,
        (term, like),
    ).fetchone()
    return int(row[0] or 0)


def detect_service_fallback(service_store: Path, service_test: Path) -> dict[str, Any]:
    store_text = service_store.read_text(encoding="utf-8")
    test_text = service_test.read_text(encoding="utf-8")
    return {
        "service_store": rel(service_store),
        "service_test": rel(service_test),
        "like_fallback_function_present": "likeFallbackRows" in store_text,
        "city_exact_fallback_present": "cityFallbackRows" in store_text and "sd.city_text = ?" in store_text,
        "short_cjk_guard_present": "isShortCjkSearchLabel(query)" in store_text,
        "fts_empty_fallback_present": "if (rows.length) return rows;" in store_text,
        "short_city_regression_present": "shortCitySearch" in test_text and "深圳" in test_text,
        "short_cjk_regression_present": "shortCjkCitySearch" in test_text and "岜沙" in test_text,
    }


def leak_scan(value: Any) -> dict[str, int]:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return {
        "public_url_hits": len(PUBLIC_URL_RE.findall(text)),
        "local_path_hits": len(LOCAL_PATH_RE.findall(text)),
        "sensitive_key_hits": len(SENSITIVE_KEY_RE.findall(text)),
    }


def build_report(summary: dict[str, Any]) -> str:
    counts = summary["counts"]
    boundary = summary["boundary_truth"]
    return "\n".join(
        [
            "# Atlas T5 Serving City Overlay Short-City Search Gate",
            "",
            f"Generated: {summary['generated_at']}",
            "",
            "## Decision",
            "",
            f"`{summary['decision']}`",
            "",
            f"Failed checks: `{summary['failed_checks']}`",
            "",
            "## LLM Audit",
            "",
            "The city overlay rows are dominated by two-character Chinese city names. The selected FTS tokenizer is trigram, so a blind FTS delta refresh is not a sufficient public-serving gate for city search. The correct bounded fix is a guarded service fallback for known public city labels when FTS returns no rows, while keeping DB promotion/upload separate.",
            "",
            "## Counts",
            "",
            f"- overlay event search rows checked: `{counts['overlay_event_search_rows']}`",
            f"- unique city terms / short CJK city terms: `{counts['unique_city_terms']}` / `{counts['short_cjk_city_terms']}`",
            f"- direct city fallback match rows: `{counts['direct_city_fallback_match_rows']}`",
            f"- direct missing/mismatch/text-missing rows: `{counts['direct_missing_rows']}` / `{counts['direct_city_mismatch_rows']}` / `{counts['direct_search_text_missing_city_rows']}`",
            f"- FTS match rows across city terms: `{counts['fts_city_term_match_rows']}`",
            f"- FTS short-city refresh-insufficient rows: `{counts['fts_short_city_refresh_insufficient_rows']}`",
            f"- LIKE fallback available rows across city terms: `{counts['like_city_term_rows']}`",
            f"- service fallback markers passed: `{counts['service_fallback_markers_passed']}` / `{counts['service_fallback_markers_total']}`",
            f"- leak hits public URL / sensitive key / local path: `{summary['leak_scan']['public_url_hits']}` / `{summary['leak_scan']['sensitive_key_hits']}` / `{summary['leak_scan']['local_path_hits']}`",
            "",
            "## Boundary Truth",
            "",
            *[
                f"- {key}: `{str(value).lower() if isinstance(value, bool) else value}`"
                for key, value in boundary.items()
            ],
            "",
            "## Outputs",
            "",
            *[f"- {key}: `{value}`" for key, value in summary["outputs"].items()],
            "",
            "## Next Resume Pointer",
            "",
            summary["next_resume_pointer"],
            "",
        ]
    )


def build_gate(
    smoke_summary_path: Path,
    overlay_rows_path: Path,
    service_store: Path,
    service_test: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    smoke_summary = read_json(smoke_summary_path)
    overlay_rows = read_jsonl(overlay_rows_path)
    candidate_db = resolve_candidate_db(smoke_summary)
    service_markers = detect_service_fallback(service_store, service_test)

    event_ids = [str(row.get("event_id") or "") for row in overlay_rows if row.get("event_id")]
    city_by_event = {str(row.get("event_id") or ""): str(row.get("proposed_city") or "").strip() for row in overlay_rows}
    city_counts = Counter(city for city in city_by_event.values() if city)

    direct_samples: list[dict[str, Any]] = []
    failed_rows: list[dict[str, Any]] = []
    city_term_rows: list[dict[str, Any]] = []
    counts = Counter()
    conn = connect_readonly(candidate_db)
    try:
        docs = fetch_event_docs(conn, event_ids)
        for event_id in event_ids:
            city = city_by_event[event_id]
            doc = docs.get(event_id)
            if not doc:
                counts["direct_missing_rows"] += 1
                failed_rows.append({"event_id": event_id, "city": city, "reason": "missing_search_document"})
                continue
            city_matches = doc["city_text"].strip() == city
            text_has_city = city in doc["search_text"]
            if city_matches and text_has_city:
                counts["direct_city_fallback_match_rows"] += 1
            else:
                if not city_matches:
                    counts["direct_city_mismatch_rows"] += 1
                if not text_has_city:
                    counts["direct_search_text_missing_city_rows"] += 1
                failed_rows.append(
                    {
                        "event_id": event_id,
                        "city": city,
                        "doc_rowid": doc["doc_rowid"],
                        "city_text_hash": stable_hash(doc["city_text"]),
                        "reason": "direct_city_fallback_mismatch",
                    }
                )
            if len(direct_samples) < 200:
                direct_samples.append(
                    {
                        "event_id": event_id,
                        "doc_rowid": doc["doc_rowid"],
                        "city": city,
                        "city_matches": city_matches,
                        "search_text_has_city": text_has_city,
                        "sample_hash": stable_hash(
                            {
                                "event_id": event_id,
                                "doc_rowid": doc["doc_rowid"],
                                "city": city,
                                "city_matches": city_matches,
                                "search_text_has_city": text_has_city,
                            }
                        ),
                    }
                )
        for city, expected_rows in sorted(city_counts.items()):
            fts_hits, fts_error = fts_match_count(conn, city)
            like_hits = like_city_count(conn, city)
            short_cjk = city_is_short_cjk(city)
            if short_cjk and fts_hits < expected_rows:
                counts["fts_short_city_refresh_insufficient_rows"] += expected_rows
            counts["fts_city_term_match_rows"] += fts_hits
            counts["like_city_term_rows"] += like_hits
            city_term_rows.append(
                {
                    "city": city,
                    "overlay_event_rows": int(expected_rows),
                    "short_cjk_city_term": short_cjk,
                    "fts_match_rows": fts_hits,
                    "fts_error": fts_error,
                    "like_fallback_event_rows": like_hits,
                    "fallback_required": short_cjk and fts_hits < expected_rows,
                    "fallback_ready": like_hits >= expected_rows,
                }
            )
    finally:
        conn.close()

    marker_values = [
        bool(service_markers["like_fallback_function_present"]),
        bool(service_markers["city_exact_fallback_present"]),
        bool(service_markers["short_cjk_guard_present"]),
        bool(service_markers["fts_empty_fallback_present"]),
        bool(service_markers["short_city_regression_present"]),
        bool(service_markers["short_cjk_regression_present"]),
    ]
    failed_checks: list[str] = []
    if failed_rows:
        failed_checks.append("direct_city_fallback_rows_failed")
    if any(row["fallback_required"] and not row["fallback_ready"] for row in city_term_rows):
        failed_checks.append("like_city_fallback_rows_missing")
    if not all(marker_values):
        failed_checks.append("service_short_city_fallback_not_verified")

    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "serving_city_overlay_short_city_search_gate_summary.json"
    contract_path = out_dir / "serving_city_overlay_short_city_search_contract.json"
    direct_samples_path = out_dir / "short_city_direct_search_samples.jsonl"
    city_terms_path = out_dir / "short_city_term_fallback_status.jsonl"
    failed_rows_path = out_dir / "short_city_search_failed_rows.jsonl"
    outputs = {
        "summary_json": rel(summary_path),
        "contract": rel(contract_path),
        "direct_search_samples": rel(direct_samples_path),
        "city_term_status": rel(city_terms_path),
        "failed_rows": rel(failed_rows_path),
        "report": rel(report_path),
    }
    boundary_truth = {
        "candidate_serving_db_opened_read_only": True,
        "candidate_serving_db_mutated": False,
        "selected_serving_db_mutated": False,
        "source_raw_db_opened": False,
        "source_raw_db_write_executed": False,
        "serving_rebuild_executed": False,
        "graph_vector_public_mutation_executed": False,
        "public_pointer_updated": False,
        "huaidj_club_upload_executed": False,
        "cloudrun_or_vps_deploy_executed": False,
        "mini_program_upload_or_review_executed": False,
        "network_ocr_model_memory_executed": False,
        "deployable_public": False,
    }
    contract = {
        "schema_version": "stage7_atlas_t5_serving_city_overlay_short_city_search_contract.v1",
        "candidate_db": rel(candidate_db),
        "service_fallback": service_markers,
        "required_runtime_behavior": {
            "known_public_or_short_cjk_city_label_fts_empty": "fall_back_to_search_document_city_text_exact",
            "fts_errors": "fall_back_to_search_document_like",
            "non_city_fts_empty": "preserve_empty_fts_result",
        },
        "public_serving_approved": False,
    }
    summary: dict[str, Any] = {
        "schema_version": "stage7_atlas_t5_serving_city_overlay_short_city_search_gate.v1.summary",
        "generated_at": now_stamp(),
        "decision": (
            "atlas_t5_serving_city_overlay_short_city_search_gate_ready_report_only"
            if not failed_checks
            else "atlas_t5_serving_city_overlay_short_city_search_gate_blocked_report_only"
        ),
        "failed_checks": failed_checks,
        "inputs": {
            "smoke_summary": rel(smoke_summary_path),
            "overlay_rows": rel(overlay_rows_path),
            "candidate_db": rel(candidate_db),
            "service_store": rel(service_store),
            "service_test": rel(service_test),
        },
        "counts": {
            "overlay_event_search_rows": len(overlay_rows),
            "unique_city_terms": len(city_counts),
            "short_cjk_city_terms": sum(1 for city in city_counts if city_is_short_cjk(city)),
            "direct_city_fallback_match_rows": int(counts["direct_city_fallback_match_rows"]),
            "direct_missing_rows": int(counts["direct_missing_rows"]),
            "direct_city_mismatch_rows": int(counts["direct_city_mismatch_rows"]),
            "direct_search_text_missing_city_rows": int(counts["direct_search_text_missing_city_rows"]),
            "fts_city_term_match_rows": int(counts["fts_city_term_match_rows"]),
            "fts_short_city_refresh_insufficient_rows": int(counts["fts_short_city_refresh_insufficient_rows"]),
            "like_city_term_rows": int(counts["like_city_term_rows"]),
            "service_fallback_markers_passed": sum(1 for item in marker_values if item),
            "service_fallback_markers_total": len(marker_values),
            "source_sqlite_write_rows": 0,
            "serving_rebuild_rows": 0,
            "graph_write_rows": 0,
            "public_serving_field_rows": 0,
            "memory_write_rows": 0,
        },
        "service_fallback": service_markers,
        "leak_scan": {"public_url_hits": 0, "local_path_hits": 0, "sensitive_key_hits": 0},
        "boundary_truth": boundary_truth,
        "outputs": outputs,
        "next_resume_pointer": (
            "tools\\stage7_rewrite\\reports\\atlas_t5_serving_city_overlay_short_city_search_gate_20260527\\"
            "serving_city_overlay_short_city_search_gate_summary.json. Next: run a local service/API smoke against the "
            "city-overlay candidate with the short-city fallback, then package the candidate for promotion only while "
            "huaidj.club upload remains disabled."
        ),
    }
    scan_payload = {
        "summary": summary,
        "contract": contract,
        "direct_samples": direct_samples,
        "city_term_rows": city_term_rows,
        "failed_rows": failed_rows,
    }
    summary["leak_scan"] = leak_scan(scan_payload)
    if any(summary["leak_scan"].values()):
        summary["failed_checks"] = sorted(set(summary["failed_checks"] + ["leak_scan_hits_present"]))
        summary["decision"] = "atlas_t5_serving_city_overlay_short_city_search_gate_blocked_report_only"

    write_json(summary_path, summary)
    write_json(contract_path, contract)
    write_jsonl(direct_samples_path, direct_samples)
    write_jsonl(city_terms_path, city_term_rows)
    write_jsonl(failed_rows_path, failed_rows)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_report(summary), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke-summary", type=Path, default=DEFAULT_SMOKE_SUMMARY)
    parser.add_argument("--overlay-rows", type=Path, default=DEFAULT_OVERLAY_ROWS)
    parser.add_argument("--service-store", type=Path, default=DEFAULT_SERVICE_STORE)
    parser.add_argument("--service-test", type=Path, default=DEFAULT_SERVICE_TEST)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = build_gate(
        smoke_summary_path=args.smoke_summary,
        overlay_rows_path=args.overlay_rows,
        service_store=args.service_store,
        service_test=args.service_test,
        out_dir=args.out_dir,
        report_path=args.report_path,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "failed_checks": summary["failed_checks"],
                "summary_json": summary["outputs"]["summary_json"],
                "report": summary["outputs"]["report"],
                "direct_city_fallback_match_rows": summary["counts"]["direct_city_fallback_match_rows"],
                "fts_short_city_refresh_insufficient_rows": summary["counts"]["fts_short_city_refresh_insufficient_rows"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
