# GUARD: Audio system upload is BANNED. This script is read-only evidence gathering only.
#!/usr/bin/env python3
"""Build a report-only venue sound-system evidence sidecar from public Atlas serving data."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "atlas_venue_sound_system_evidence_sidecar.v1"
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_participant_delta_current_20260526_0016" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_venue_sound_system_evidence_current"

SOUND_PATTERNS = [
    ("Funktion-One", re.compile(r"\b(?:funktion[-\s]?one|f1)\b", re.IGNORECASE)),
    ("L-Acoustics", re.compile(r"\bL[-\s]?Acoustics\b", re.IGNORECASE)),
    ("d&b", re.compile(r"\bd\s*&\s*b\b|\bdnb\s+audiotechnik\b", re.IGNORECASE)),
    ("Void", re.compile(r"\bVoid(?:\s+Acoustics)?\b", re.IGNORECASE)),
    ("Martin Audio", re.compile(r"\bMartin\s+Audio\b", re.IGNORECASE)),
    ("KV2", re.compile(r"\bKV2\b", re.IGNORECASE)),
    ("Danley", re.compile(r"\bDanley\b", re.IGNORECASE)),
    ("sound system", re.compile(r"\b(?:sound\s*system|soundsystem|pa\s*system)\b|音响系统|音响|声场", re.IGNORECASE)),
]


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def text(value: Any) -> str:
    return str(value or "").strip()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
            count += 1
        tmp = Path(handle.name)
    tmp.replace(path)
    return count


def connect_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {name: row[name] for name in row.keys()}


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ? LIMIT 1", (table,)).fetchone())


def matched_terms(value: str) -> list[str]:
    out: list[str] = []
    for label, pattern in SOUND_PATTERNS:
        if pattern.search(value):
            out.append(label)
    return out


def compact_snippet(value: str, limit: int = 220) -> str:
    value = re.sub(r"\s+", " ", text(value))
    return value[:limit]


def load_sound_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not table_exists(conn, "performance_event") or not table_exists(conn, "evidence_ref"):
        return []
    rows = conn.execute(
        """
        SELECT p.venue_id, p.venue_name, p.city, p.event_id, p.event_title,
               e.source_ref_id, e.source_account, e.source_title, e.post_date, e.public_snippet
        FROM performance_event p
        JOIN evidence_ref e ON e.source_ref_id = p.source_ref_id
        WHERE p.venue_id <> ''
          AND (
            LOWER(e.public_snippet) LIKE '%sound%'
            OR LOWER(e.public_snippet) LIKE '%funktion%'
            OR LOWER(e.public_snippet) LIKE '%acoustics%'
            OR LOWER(e.public_snippet) LIKE '%martin audio%'
            OR LOWER(e.public_snippet) LIKE '%void%'
            OR LOWER(e.public_snippet) LIKE '%kv2%'
            OR LOWER(e.public_snippet) LIKE '%danley%'
            OR e.public_snippet LIKE '%音响%'
            OR LOWER(e.source_title) LIKE '%sound%'
            OR LOWER(e.source_title) LIKE '%funktion%'
            OR LOWER(e.source_title) LIKE '%acoustics%'
            OR e.source_title LIKE '%音响%'
          )
        """
    ).fetchall()
    out = []
    for row in rows:
        combined = " ".join([text(row["event_title"]), text(row["source_title"]), text(row["public_snippet"])])
        terms = matched_terms(combined)
        if not terms:
            continue
        out.append({**row_dict(row), "matched_terms": terms})
    return out


def build_sidecar(args: argparse.Namespace) -> dict[str, Any]:
    serving_db = Path(args.serving_db)
    out_dir = Path(args.out_dir)
    evidence_limit = max(1, int(args.evidence_limit))
    with connect_readonly(serving_db) as conn:
        rows = load_sound_rows(conn)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[text(row.get("venue_id"))].append(row)

    sidecar_rows: list[dict[str, Any]] = []
    for venue_id, items in grouped.items():
        term_counts = Counter(term for item in items for term in item.get("matched_terms") or [])
        city_counts = Counter(text(item.get("city")) for item in items if text(item.get("city")))
        venue_name = text(items[0].get("venue_name"))
        evidence = []
        seen_refs: set[str] = set()
        for item in sorted(items, key=lambda row: (text(row.get("post_date")), text(row.get("source_ref_id"))), reverse=True):
            source_ref_id = text(item.get("source_ref_id"))
            if source_ref_id in seen_refs:
                continue
            seen_refs.add(source_ref_id)
            evidence.append(
                {
                    "sourceRefId": source_ref_id,
                    "sourceAccount": text(item.get("source_account")),
                    "sourceTitle": text(item.get("source_title")),
                    "postDate": text(item.get("post_date")),
                    "eventId": text(item.get("event_id")),
                    "eventTitle": text(item.get("event_title")),
                    "matchedTerms": item.get("matched_terms") or [],
                    "publicSnippet": compact_snippet(item.get("public_snippet")),
                }
            )
            if len(evidence) >= evidence_limit:
                break
        sidecar_rows.append(
            {
                "schemaVersion": SCHEMA_VERSION + ".venue",
                "venueId": venue_id,
                "venueName": venue_name,
                "city": city_counts.most_common(1)[0][0] if city_counts else "",
                "evidenceCount": len(items),
                "sourceCount": len({text(item.get("source_ref_id")) for item in items if text(item.get("source_ref_id"))}),
                "terms": [term for term, _count in term_counts.most_common()],
                "confidence": min(0.95, 0.45 + 0.08 * len(items) + 0.05 * len(term_counts)),
                "evidence": evidence,
                "reportOnly": True,
            }
        )
    sidecar_rows.sort(key=lambda row: (row["evidenceCount"], row["venueName"]), reverse=True)

    out_dir.mkdir(parents=True, exist_ok=True)
    sidecar_path = out_dir / "venue_sound_system_evidence.jsonl"
    write_jsonl(sidecar_path, sidecar_rows)
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "decision": "atlas_venue_sound_system_evidence_sidecar_ready_report_only",
        "serving_db": str(serving_db),
        "out_dir": str(out_dir),
        "rows_scanned": len(rows),
        "venue_rows": len(sidecar_rows),
        "sidecar_path": str(sidecar_path),
        "term_counts": dict(Counter(term for row in sidecar_rows for term in row["terms"])),
        "safety": {
            "report_only": True,
            "sqlite_write_executed": False,
            "llm_call_executed": False,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "production_pointer_updated": False,
        },
    }
    write_json(out_dir / "venue_sound_system_evidence_summary.json", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serving-db", default=str(DEFAULT_SERVING_DB))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--evidence-limit", type=int, default=8)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    summary = build_sidecar(parse_args(argv))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
