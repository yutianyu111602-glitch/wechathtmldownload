#!/usr/bin/env python3
"""Build report-only venue candidates from the Atlas DJ venue work order.

This adapter consumes the 2026-05-25 DJ repair work-order packet and checks
whether missing-place events can be mapped to known public venue subjects from
the selected serving SQLite. It writes review evidence only; it does not mutate
source SQLite, serving SQLite, Neo4j, Qdrant, public pointers, or production
state.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_WORK_ORDER = (
    REPO_ROOT
    / "reports"
    / "atlas_dj_repair_queue_review_packet_activity_current_20260525_1537"
    / "venue_repair_review_work_order.jsonl"
)
DEFAULT_SERVING_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_activity_current_time_dedupe_strict_20260525-1625"
    / "atlas_serving.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_dj_venue_work_order_sidecar_20260525"

VENUE_HINTS = [
    "all",
    "axis",
    "bar",
    "bo live",
    "club",
    "cs bar",
    "dada",
    "dong",
    "dng",
    "elevator",
    "flat",
    "foundation",
    "heim",
    "hum",
    "live",
    "oil",
    "tag",
    "vervo",
    "window",
    "with bar",
    "zhaodai",
    "俱乐部",
    "招待",
    "院吧",
]
SECRET_WORD_RE = re.compile(r"\b(openid|fakeid|unionid|secret|token|cookie|password)\b", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"']+|/mnt/[A-Za-z][^\s\"']*|/home/[^\s\"']+|\\\\[A-Za-z0-9_.-]+[\\/][^\s\"']+",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://|mp\.weixin", re.IGNORECASE)
NON_WORD_RE = re.compile(r"[\s\-_/|·•.,，。:：;；!！?？()（）\[\]【】\"'“”‘’]+")


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def norm(value: Any) -> str:
    return NON_WORD_RE.sub("", text(value).casefold())


def has_venue_hint(value: str) -> bool:
    blob = value.casefold()
    return any(hint in blob for hint in VENUE_HINTS)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL row: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_no}: expected object row")
            rows.append(payload)
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
    tmp.replace(path)


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def load_venue_index(serving_db: Path) -> list[dict[str, Any]]:
    conn = connect_readonly(serving_db)
    try:
        rows: list[dict[str, Any]] = []
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dj_venue_rollup'").fetchone():
            for row in conn.execute(
                """
                SELECT venue_id, venue_name, city, SUM(event_count) AS event_count, MAX(score) AS score
                FROM dj_venue_rollup
                WHERE trim(COALESCE(venue_name, '')) != ''
                GROUP BY venue_id, venue_name, city
                """
            ):
                rows.append(
                    {
                        "venue_id": text(row["venue_id"]),
                        "venue_name": text(row["venue_name"]),
                        "city": text(row["city"]),
                        "event_count": int(row["event_count"] or 0),
                        "score": float(row["score"] or 0.0),
                        "source_table": "dj_venue_rollup",
                    }
                )
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='canonical_subject'").fetchone():
            for row in conn.execute(
                """
                SELECT subject_id, display_name, city_primary, event_count, confidence
                FROM canonical_subject
                WHERE lower(COALESCE(subject_type, '')) = 'venue'
                  AND trim(COALESCE(display_name, '')) != ''
                """
            ):
                rows.append(
                    {
                        "venue_id": text(row["subject_id"]),
                        "venue_name": text(row["display_name"]),
                        "city": text(row["city_primary"]),
                        "event_count": int(row["event_count"] or 0),
                        "score": float(row["confidence"] or 0.0),
                        "source_table": "canonical_subject",
                    }
                )
    finally:
        conn.close()

    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (text(row["venue_id"]), norm(row["venue_name"]))
        existing = deduped.get(key)
        if existing is None or (row["event_count"], row["score"]) > (existing["event_count"], existing["score"]):
            row["venue_name_norm"] = norm(row["venue_name"])
            deduped[key] = row
    return sorted(deduped.values(), key=lambda item: (-item["event_count"], -item["score"], item["venue_name"]))


def best_venue_match(source_account: str, venue_index: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, str, float]:
    source_norm = norm(source_account)
    if not source_norm:
        return None, "blank_source_account", 0.0
    source_blob = source_account.casefold()
    candidates: list[tuple[float, str, dict[str, Any]]] = []
    for venue in venue_index:
        venue_norm = text(venue.get("venue_name_norm"))
        venue_blob = text(venue.get("venue_name")).casefold()
        if not venue_norm:
            continue
        if source_norm == venue_norm:
            candidates.append((0.98, "exact_source_account_venue_name", venue))
        elif len(source_norm) >= 3 and source_norm in venue_norm:
            candidates.append((0.9, "source_account_contained_in_venue_name", venue))
        elif len(venue_norm) >= 3 and venue_norm in source_norm:
            candidates.append((0.86, "venue_name_contained_in_source_account", venue))
        else:
            for hint in VENUE_HINTS:
                if len(hint) >= 3 and hint in source_blob and hint in venue_blob:
                    candidates.append((0.82, "shared_source_account_venue_hint_token", venue))
                    break
    if not candidates:
        return None, "no_known_serving_venue_match", 0.0
    candidates.sort(key=lambda item: (-item[0], -int(item[2].get("event_count") or 0), -float(item[2].get("score") or 0.0)))
    confidence, match_kind, venue = candidates[0]
    return venue, match_kind, confidence


def normalize_row(row: dict[str, Any], venue_index: list[dict[str, Any]]) -> dict[str, Any]:
    source_account = text(row.get("source_account"))
    venue, match_kind, confidence = best_venue_match(source_account, venue_index)
    hint = has_venue_hint(source_account)
    if venue and hint:
        review_tier = "auto_candidate"
        decision = "venue_candidate_from_source_account_ready_for_acceptance_gate"
    elif venue:
        review_tier = "review_candidate"
        decision = "venue_candidate_from_source_account_needs_manual_hint_review"
        confidence = min(confidence, 0.74)
    elif hint:
        review_tier = "review_candidate"
        decision = "source_account_venue_hint_without_serving_match"
        confidence = 0.55
    else:
        review_tier = "unresolved"
        decision = "no_source_account_venue_candidate"
        confidence = 0.0

    return {
        "schema_version": "atlas_dj_venue_work_order_sidecar.row.v1",
        "work_item_id": text(row.get("work_item_id")),
        "article_uid": text(row.get("article_uid")),
        "event_id": text(row.get("event_id")),
        "source_account": source_account,
        "title": text(row.get("title")),
        "event_name": text(row.get("name")),
        "original_place": text(row.get("place")),
        "time_text": text(row.get("time_text")),
        "participants_json": text((row.get("evidence") or {}).get("participants_json")) if isinstance(row.get("evidence"), dict) else "",
        "candidate_venue_id": text(venue.get("venue_id")) if venue else "",
        "candidate_venue_name": text(venue.get("venue_name")) if venue else "",
        "candidate_city": text(venue.get("city")) if venue else "",
        "candidate_source_table": text(venue.get("source_table")) if venue else "",
        "candidate_event_count": int(venue.get("event_count") or 0) if venue else 0,
        "match_kind": match_kind,
        "confidence": round(confidence, 4),
        "review_tier": review_tier,
        "decision": decision,
        "serving_rebuild_candidate": review_tier == "auto_candidate",
        "serving_rebuild_executed": False,
        "write_status": "report_only",
    }


def public_leak_counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True)
        counts["url_hits"] += len(URL_RE.findall(payload))
        counts["secret_word_hits"] += len(SECRET_WORD_RE.findall(payload))
        counts["local_path_hits"] += len(LOCAL_PATH_RE.findall(payload))
    return dict(counts)


def build_summary_md(summary: dict[str, Any]) -> str:
    lines = [
        "# Atlas DJ Venue Work-Order Sidecar",
        "",
        f"- Generated at: `{summary['generated_at']}`",
        f"- Source work order: `{summary['source_work_order']}`",
        f"- Serving DB: `{summary['serving_db']}`",
        f"- Input rows: `{summary['counts']['input_rows']}`",
        f"- Auto candidates: `{summary['counts']['auto_candidates']}`",
        f"- Review candidates: `{summary['counts']['review_candidates']}`",
        f"- Unresolved rows: `{summary['counts']['unresolved_rows']}`",
        f"- Decision: `{summary['decision']['status']}`",
        "",
        "## Outputs",
    ]
    for name, path in sorted(summary["outputs"].items()):
        lines.append(f"- {name}: `{path}`")
    lines.extend(["", "## Safety"])
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Public Leak Scan"])
    for key, value in sorted(summary["public_leak_scan"].items()):
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    return "\n".join(lines)


def build_venue_work_order_sidecar(work_order_path: Path, serving_db: Path, out_dir: Path) -> dict[str, Any]:
    rows = read_jsonl(work_order_path)
    venue_index = load_venue_index(serving_db)
    normalized_rows = [normalize_row(row, venue_index) for row in rows]
    auto_rows = [row for row in normalized_rows if row["review_tier"] == "auto_candidate"]
    review_rows = [row for row in normalized_rows if row["review_tier"] == "review_candidate"]
    unresolved_rows = [row for row in normalized_rows if row["review_tier"] == "unresolved"]

    out_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "summary_json": str(out_dir / "summary.json"),
        "summary_md": str(out_dir / "summary.md"),
        "venue_candidates_jsonl": str(out_dir / "venue_candidates.jsonl"),
        "venue_auto_candidates_jsonl": str(out_dir / "venue_auto_candidates.jsonl"),
        "venue_review_candidates_jsonl": str(out_dir / "venue_review_candidates.jsonl"),
        "venue_unresolved_jsonl": str(out_dir / "venue_unresolved.jsonl"),
    }
    write_jsonl(out_dir / "venue_candidates.jsonl", normalized_rows)
    write_jsonl(out_dir / "venue_auto_candidates.jsonl", auto_rows)
    write_jsonl(out_dir / "venue_review_candidates.jsonl", review_rows)
    write_jsonl(out_dir / "venue_unresolved.jsonl", unresolved_rows)

    summary = {
        "schema_version": "atlas_dj_venue_work_order_sidecar.summary.v1",
        "generated_at": now_iso(),
        "source_work_order": str(work_order_path),
        "serving_db": str(serving_db),
        "out_dir": str(out_dir),
        "counts": {
            "input_rows": len(rows),
            "serving_venue_index_rows": len(venue_index),
            "auto_candidates": len(auto_rows),
            "review_candidates": len(review_rows),
            "unresolved_rows": len(unresolved_rows),
        },
        "review_tier_counts": dict(Counter(row["review_tier"] for row in normalized_rows)),
        "match_kind_counts": dict(Counter(row["match_kind"] for row in normalized_rows)),
        "top_candidate_venues": [
            {"candidate_venue_name": name, "count": count}
            for name, count in Counter(row["candidate_venue_name"] for row in auto_rows if row["candidate_venue_name"]).most_common(20)
        ],
        "decision": {
            "status": "atlas_dj_venue_work_order_sidecar_ready_report_only",
            "serving_rebuild_triggered": False,
            "reason": "Venue candidates were materialized for acceptance review only; no serving or production state was mutated.",
        },
        "outputs": outputs,
        "public_leak_scan": public_leak_counts(normalized_rows),
        "safety": {
            "llm_call_executed": False,
            "network_call_executed": False,
            "neo4j_write_executed": False,
            "paid_api_call_executed": False,
            "production_write_executed": False,
            "qdrant_write_executed": False,
            "report_only": True,
            "serving_sqlite_rebuild_executed": False,
            "serving_sqlite_write_executed": False,
            "source_sqlite_write_executed": False,
        },
    }
    write_json(out_dir / "summary.json", summary)
    (out_dir / "summary.md").write_text(build_summary_md(summary), encoding="utf-8")
    return {"summary": summary, "rows": normalized_rows}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-order", type=Path, default=DEFAULT_WORK_ORDER)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_venue_work_order_sidecar(args.work_order, args.serving_db, args.out_dir)
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
