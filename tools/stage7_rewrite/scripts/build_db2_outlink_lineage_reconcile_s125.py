from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEFAULT_LIVE_DB = Path("/db2-data/atlas_swarm_data.sqlite")
DEFAULT_S119_DB = Path(
    "tools/stage7_rewrite/reports/external_link_db2_sidecar_contract_s119_20260601/"
    "external_link_db2_sidecar.sqlite"
)
DEFAULT_T6_DB = Path(
    "tools/stage7_rewrite/reports/atlas_t6_sidecar_new_db_overlay_t5_t6_20260526/"
    "atlas_t6_sidecar_social_overlay.sqlite"
)
DEFAULT_COMPANION_DB = Path(
    "tools/stage7_rewrite/reports/atlas_dj_companion_20260522/atlas_dj_v2.sqlite"
)

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "igsh",
    "mc_cid",
    "mc_eid",
    "spm",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


def now_cst_date() -> str:
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d")


def canonicalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return "invalid-url:" + hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = (parts.path or "/").lower()
    if path != "/":
        path = path.rstrip("/") + "/"
    query_pairs = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(query_pairs, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def url_key_hash(url: str) -> str:
    canonical = canonicalize_url(url)
    if not canonical:
        return ""
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def connect_readonly(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def read_live_outlinks(live_db: Path, limit: int = 0) -> list[sqlite3.Row]:
    conn = connect_readonly(live_db)
    try:
        query = """
            SELECT outlink_id, eid, profile_id, outlink_url, outlink_platform,
                   entity_name, source_layer, source_profile_url,
                   profile_platform, discovered_at, source
            FROM dj_outlinks
            ORDER BY discovered_at DESC, outlink_id
        """
        if limit > 0:
            query += " LIMIT ?"
            return list(conn.execute(query, (limit,)).fetchall())
        return list(conn.execute(query).fetchall())
    finally:
        conn.close()


def row_value(row: sqlite3.Row | None, key: str, default=None):
    if row is None:
        return default
    return row[key] if key in row.keys() else default


def load_s119_by_hash(path: Path) -> dict[str, sqlite3.Row]:
    conn = connect_readonly(path)
    try:
        if not table_exists(conn, "external_link_candidates"):
            return {}
        rows = conn.execute("SELECT * FROM external_link_candidates").fetchall()
        by_hash: dict[str, sqlite3.Row] = {}
        for row in rows:
            hashed = url_key_hash(row_value(row, "url", ""))
            if hashed and hashed not in by_hash:
                by_hash[hashed] = row
        return by_hash
    finally:
        conn.close()


def load_t6_by_hash(path: Path) -> dict[str, sqlite3.Row]:
    conn = connect_readonly(path)
    try:
        if not table_exists(conn, "atlas_dj_social_links"):
            return {}
        rows = conn.execute("SELECT * FROM atlas_dj_social_links").fetchall()
        by_hash: dict[str, sqlite3.Row] = {}
        for row in rows:
            hashed = row_value(row, "canonical_url_key_hash", "")
            if not hashed:
                hashed = url_key_hash(row_value(row, "canonical_url_key", ""))
            if hashed and hashed not in by_hash:
                by_hash[hashed] = row
        return by_hash
    finally:
        conn.close()


def load_companion_by_hash(path: Path) -> dict[str, sqlite3.Row]:
    conn = connect_readonly(path)
    try:
        if not table_exists(conn, "dj_outlinks"):
            return {}
        rows = conn.execute("SELECT * FROM dj_outlinks").fetchall()
        by_hash: dict[str, sqlite3.Row] = {}
        for row in rows:
            hashed = url_key_hash(row_value(row, "outlink_url", ""))
            if hashed and hashed not in by_hash:
                by_hash[hashed] = row
        return by_hash
    finally:
        conn.close()


def is_searxng(row: sqlite3.Row) -> bool:
    markers = [
        row_value(row, "outlink_platform", ""),
        row_value(row, "source_layer", ""),
        row_value(row, "source", ""),
    ]
    return any("searx" in str(item).lower() for item in markers)


def projection_from_matches(s119: sqlite3.Row | None, t6: sqlite3.Row | None) -> bool:
    s119_allowed = bool(row_value(s119, "db2_projection_allowed", 0))
    t6_allowed = bool(row_value(t6, "public_serving_field_allowed", 0))
    return bool(s119_allowed and t6_allowed)


def classify_row(row: sqlite3.Row, s119: sqlite3.Row | None, t6: sqlite3.Row | None, hashed: str) -> tuple[str, str, bool]:
    projection_allowed = projection_from_matches(s119, t6)
    if not hashed:
        return "report_only", "missing_url_key_hash", False
    if is_searxng(row):
        return "blocked", "searxng_source_blocked", False
    copyright_safety = str(row_value(s119, "copyright_safety", "") or "").lower()
    if "blocked" in copyright_safety or "direct_media" in copyright_safety:
        return "blocked", "copyright_safety_blocked", False
    if row_value(t6, "source_raw_db_write_executed", 0):
        return "blocked", "source_raw_write_boundary_violation", False
    if not projection_allowed:
        return "candidate", "projection_gate_not_passed", False
    return "review_ready", "", True


def build_reconcile_rows(
    *,
    live_db: Path,
    s119_db: Path,
    t6_db: Path,
    companion_db: Path,
    lineage_run_id: str,
    limit: int = 0,
) -> list[dict]:
    s119_by_hash = load_s119_by_hash(s119_db)
    t6_by_hash = load_t6_by_hash(t6_db)
    companion_by_hash = load_companion_by_hash(companion_db)
    rows: list[dict] = []

    for live in read_live_outlinks(live_db, limit=limit):
        hashed = url_key_hash(row_value(live, "outlink_url", ""))
        s119 = s119_by_hash.get(hashed)
        t6 = t6_by_hash.get(hashed)
        companion = companion_by_hash.get(hashed)
        fact_state, block_reason, projection_allowed = classify_row(live, s119, t6, hashed)
        rows.append(
            {
                "lineage_run_id": lineage_run_id,
                "source_db_role": "live_swarm_external_link_db2",
                "source_table": "dj_outlinks",
                "source_row_key": "outlink_id",
                "entity_key": row_value(live, "eid", ""),
                "platform": row_value(live, "outlink_platform", ""),
                "url_key_hash": hashed,
                "candidate_id": row_value(live, "outlink_id", ""),
                "matched_s119_sidecar_id": row_value(s119, "sidecar_id"),
                "matched_t6_candidate_id": row_value(t6, "candidate_id"),
                "matched_companion_outlink_id": row_value(companion, "outlink_id"),
                "fact_state": fact_state,
                "projection_allowed": projection_allowed,
                "block_reason": block_reason,
                "source_layer": row_value(live, "source_layer", ""),
                "source_worker": row_value(live, "source", ""),
            }
        )
    return rows


def write_outputs(rows: list[dict], output_dir: Path, lineage_run_id: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / "db2_outlink_lineage_reconcile.jsonl"
    md_path = output_dir / "db2_outlink_lineage_reconcile.md"

    with jsonl_path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    fact_counts = Counter(row["fact_state"] for row in rows)
    platform_counts = Counter(row["platform"] for row in rows)
    matched_s119 = sum(1 for row in rows if row["matched_s119_sidecar_id"])
    matched_t6 = sum(1 for row in rows if row["matched_t6_candidate_id"])
    matched_companion = sum(1 for row in rows if row["matched_companion_outlink_id"])
    projection_allowed = sum(1 for row in rows if row["projection_allowed"])
    searxng_blocked = sum(1 for row in rows if row["block_reason"] == "searxng_source_blocked")

    lines = [
        "# DB2 Outlink Lineage Reconcile",
        "",
        f"- lineage_run_id: `{lineage_run_id}`",
        f"- rows: `{len(rows)}`",
        f"- matched_s119: `{matched_s119}`",
        f"- matched_t6: `{matched_t6}`",
        f"- matched_companion: `{matched_companion}`",
        f"- projection_allowed: `{projection_allowed}`",
        f"- searxng_blocked: `{searxng_blocked}`",
        "",
        "## Fact State Counts",
        "",
    ]
    for key, count in sorted(fact_counts.items()):
        lines.append(f"- `{key}`: `{count}`")
    lines.extend(["", "## Top Platforms", ""])
    for key, count in platform_counts.most_common(20):
        lines.append(f"- `{key}`: `{count}`")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- JSONL contains `url_key_hash`, not raw URL.",
            "- Rows remain candidate/report-only/blocked/review-ready unless a separate projection gate approves them.",
            "- This run does not write live DB, DB1, DB2 serving, DB3, graph, vector, memory, or public state.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return jsonl_path, md_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    today = now_cst_date()
    parser = argparse.ArgumentParser(description="Build DB2 outlink lineage reconcile report")
    parser.add_argument("--live-db", type=Path, default=DEFAULT_LIVE_DB)
    parser.add_argument("--s119-db", type=Path, default=DEFAULT_S119_DB)
    parser.add_argument("--t6-db", type=Path, default=DEFAULT_T6_DB)
    parser.add_argument("--companion-db", type=Path, default=DEFAULT_COMPANION_DB)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(f"tools/stage7_rewrite/reports/db2_outlink_lineage_reconcile_s125_{today}"),
    )
    parser.add_argument("--lineage-run-id", default=f"db2_outlink_lineage_reconcile_{today}")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    rows = build_reconcile_rows(
        live_db=args.live_db,
        s119_db=args.s119_db,
        t6_db=args.t6_db,
        companion_db=args.companion_db,
        lineage_run_id=args.lineage_run_id,
        limit=args.limit,
    )
    jsonl_path, md_path = write_outputs(rows, args.output_dir, args.lineage_run_id)
    print(json.dumps({"rows": len(rows), "jsonl": str(jsonl_path), "markdown": str(md_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
