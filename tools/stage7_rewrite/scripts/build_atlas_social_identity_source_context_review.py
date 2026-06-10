#!/usr/bin/env python3
"""Build report-only Atlas source-context review for Q6 social identity candidates.

This gate joins the Q6 SoundCloud metadata candidates to the selected local
Atlas serving read model. Local Atlas context can justify manual review
priority, but it is not identity proof for a public social profile.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


STAGE7_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STAGE7_ROOT.parents[1]
DEFAULT_CANDIDATES = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_identity_review_criteria_q6_20260524_0028"
    / "atlas_social_identity_review_candidates.jsonl"
)
DEFAULT_ROLLUPS = (
    STAGE7_ROOT
    / "reports"
    / "atlas_social_identity_review_criteria_q6_20260524_0028"
    / "atlas_social_identity_review_entity_rollups.jsonl"
)
DEFAULT_SERVING_DB = REPO_ROOT / "reports" / "atlas_serving_field_repair_fullcomplete_strict_20260523-1658" / "atlas_serving.sqlite"
DEFAULT_OUT_DIR = STAGE7_ROOT / "reports" / "atlas_social_identity_source_context_review_q6_20260524"
DEFAULT_REPORT = REPO_ROOT / "reports" / "ATLAS_T6_IDENTITY_SOURCE_CONTEXT_REVIEW_20260524.md"
SCHEMA_VERSION = "stage7_atlas_social_identity_source_context_review.v1"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def reject_d_path(path: Path, label: str) -> None:
    raw = str(path.resolve()).replace("\\", "/").casefold()
    if raw.startswith("d:/") or raw.startswith("/mnt/d/"):
        raise ValueError(f"{label} must not point to D: for Q6 identity source-context review: {path}")


def compact(value: Any, limit: int = 1000) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit].strip()


def normalize(value: Any) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact(value, 1000).casefold())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    reject_d_path(path, "jsonl")
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        tmp = Path(handle.name)
    tmp.replace(path)


def connect_serving_db(path: Path) -> sqlite3.Connection:
    reject_d_path(path, "serving_db")
    if not path.exists():
        raise FileNotFoundError(path)
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return row is not None


def rowdict(row: sqlite3.Row | None) -> dict[str, Any]:
    return dict(row) if row is not None else {}


def find_profile(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    if not table_exists(conn, "dj_profile"):
        return {}
    name_norm = normalize(name)
    rows = conn.execute(
        """
        SELECT dj_id, display_name, normalized_name, city_primary, source_article_count,
               event_count, venue_count, collaborator_count, organization_count,
               media_count, first_seen_at, last_seen_at, confidence
        FROM dj_profile
        WHERE lower(display_name) = lower(?) OR lower(normalized_name) = lower(?)
        ORDER BY event_count DESC, source_article_count DESC
        LIMIT 20
        """,
        (name, name),
    ).fetchall()
    for row in rows:
        if normalize(row["display_name"]) == name_norm or normalize(row["normalized_name"]) == name_norm:
            return rowdict(row)
    if rows:
        return rowdict(rows[0])
    return {}


def sample_events(conn: sqlite3.Connection, dj_id: str, limit: int = 3) -> list[dict[str, Any]]:
    if not dj_id or not table_exists(conn, "dj_event") or not table_exists(conn, "evidence_ref"):
        return []
    rows = conn.execute(
        """
        SELECT de.event_id, de.event_title, de.starts_at, de.time_text, de.venue_name, de.city,
               er.source_account, er.source_title, er.post_date, er.public_snippet, er.public_url_allowed
        FROM dj_event de
        LEFT JOIN evidence_ref er ON er.source_ref_id = de.source_ref_id
        WHERE de.dj_id = ?
        ORDER BY de.starts_at DESC, de.event_title
        LIMIT ?
        """,
        (dj_id, limit),
    ).fetchall()
    return [rowdict(row) for row in rows]


def role_counts_for_entity(candidates: list[dict[str, Any]], entity_search_id: str) -> dict[str, int]:
    return dict(Counter(row.get("evidence_role") or "unknown" for row in candidates if row.get("entity_search_id") == entity_search_id))


def review_entity(
    *,
    conn: sqlite3.Connection,
    rollup: dict[str, Any],
    candidates: list[dict[str, Any]],
    generated_at: str,
    rank: int,
) -> dict[str, Any]:
    name = compact(rollup.get("name"))
    profile = find_profile(conn, name)
    events = sample_events(conn, compact(profile.get("dj_id")), limit=3)
    role_counts = role_counts_for_entity(candidates, compact(rollup.get("entity_search_id")))
    atlas_profile_found = bool(profile)
    atlas_event_context_found = bool(events)
    public_evidence_refs = sum(1 for row in events if int(row.get("public_url_allowed") or 0) == 1)
    missing_requirements = [
        "independent public profile page body or rendered profile evidence",
        "profile/avatar hash from a supported public evidence runner",
        "cross-domain subject-matching external profile link",
        "explicit T5/T7 acceptance decision for the specific profile URL",
        "separate graph/write gate before any Neo4j/Qdrant/serving mutation",
    ]
    if not atlas_profile_found:
        review_status = "needs_atlas_source_context_before_identity_review"
    elif not atlas_event_context_found:
        review_status = "atlas_profile_found_needs_event_source_context"
    else:
        review_status = "atlas_source_context_found_manual_identity_review_needed"

    return {
        "schema_version": SCHEMA_VERSION + ".entity",
        "generated_at": generated_at,
        "review_rank": rank,
        "entity_search_id": compact(rollup.get("entity_search_id")),
        "name": name,
        "type": compact(rollup.get("type")),
        "candidate_rows": int(rollup.get("candidate_rows") or 0),
        "profile_identity_candidate_rows": int(rollup.get("profile_identity_candidate_rows") or 0),
        "supporting_music_artifact_rows": int(rollup.get("supporting_music_artifact_rows") or 0),
        "evidence_role_counts": role_counts,
        "atlas_profile_found": atlas_profile_found,
        "atlas_dj_id": compact(profile.get("dj_id")),
        "atlas_display_name": compact(profile.get("display_name")),
        "atlas_city_primary": compact(profile.get("city_primary")),
        "atlas_source_article_count": int(profile.get("source_article_count") or 0),
        "atlas_event_count": int(profile.get("event_count") or 0),
        "atlas_venue_count": int(profile.get("venue_count") or 0),
        "atlas_context_sample_events": events,
        "atlas_public_evidence_ref_samples": public_evidence_refs,
        "review_status": review_status,
        "missing_requirements_before_identity_proof": missing_requirements,
        "manual_review_required": True,
        "accepted_for_graph": False,
        "identity_proof": False,
        "graph_write_allowed": False,
        "next_gate": "Attach independent public profile/source context and run a separate T5/T7 acceptance gate.",
    }


def build_source_context_review(
    *,
    candidates_path: Path,
    rollups_path: Path,
    serving_db: Path,
    out_dir: Path,
    report_path: Path,
) -> dict[str, Any]:
    reject_d_path(out_dir, "out_dir")
    candidates = read_jsonl(candidates_path)
    rollups = read_jsonl(rollups_path)
    generated_at = now_iso()
    with connect_serving_db(serving_db) as conn:
        review_rows = [
            review_entity(conn=conn, rollup=row, candidates=candidates, generated_at=generated_at, rank=index)
            for index, row in enumerate(rollups, start=1)
        ]

    review_path = out_dir / "atlas_social_identity_source_context_review.jsonl"
    blocked_path = out_dir / "atlas_social_identity_source_context_blocked_for_graph.jsonl"
    summary_path = out_dir / "atlas_social_identity_source_context_review_summary.json"
    write_jsonl(review_path, review_rows)
    write_jsonl(blocked_path, review_rows)

    status_counts = Counter(row["review_status"] for row in review_rows)
    rows_with_context = sum(1 for row in review_rows if row["atlas_profile_found"] and row["atlas_context_sample_events"])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "ok": True,
        "decision": "atlas_social_identity_source_context_review_ready_report_only",
        "candidates_path": str(candidates_path),
        "rollups_path": str(rollups_path),
        "serving_db": str(serving_db),
        "out_dir": str(out_dir),
        "report_path": str(report_path),
        "review_path": str(review_path),
        "blocked_path": str(blocked_path),
        "entity_rows": len(review_rows),
        "entities_with_atlas_profile": sum(1 for row in review_rows if row["atlas_profile_found"]),
        "entities_with_atlas_event_context": rows_with_context,
        "status_counts": dict(sorted(status_counts.items())),
        "accepted_for_graph": 0,
        "identity_proof_promoted": 0,
        "graph_write_allowed": 0,
        "next_gate": "T5/T7 must attach independent profile/source evidence before any product truth, avatar display, public serving field, graph/vector/DB write, or memory action.",
        "safety": {
            "report_only": True,
            "serving_db_opened_read_only": True,
            "network_call_executed": False,
            "model_call_executed": False,
            "paid_api_used": False,
            "page_body_persisted": False,
            "graph_write_executed": False,
            "qdrant_write_executed": False,
            "neo4j_write_executed": False,
            "sqlite_write_executed": False,
            "mem0_write_executed": False,
            "secret_value_read_or_printed": False,
            "d_scan_executed": False,
        },
    }
    write_json(summary_path, summary)
    write_markdown(out_dir / "atlas_social_identity_source_context_review_summary.md", summary, review_rows)
    write_markdown(report_path, summary, review_rows, top_level=True)
    return summary


def write_markdown(path: Path, summary: dict[str, Any], review_rows: list[dict[str, Any]], top_level: bool = False) -> None:
    title = "Atlas T6 Identity Source Context Review Packet" if top_level else "Atlas Social Identity Source Context Review"
    lines = [
        f"# {title}",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- decision: `{summary['decision']}`",
        f"- entity_rows: `{summary['entity_rows']}`",
        f"- entities_with_atlas_profile: `{summary['entities_with_atlas_profile']}`",
        f"- entities_with_atlas_event_context: `{summary['entities_with_atlas_event_context']}`",
        f"- accepted_for_graph: `{summary['accepted_for_graph']}`",
        f"- identity_proof_promoted: `{summary['identity_proof_promoted']}`",
        f"- graph_write_allowed: `{summary['graph_write_allowed']}`",
        f"- review_path: `{summary['review_path']}`",
        f"- blocked_path: `{summary['blocked_path']}`",
        "",
        "## Status Counts",
        "",
    ]
    for key, value in summary["status_counts"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Entity Review Rows", ""])
    for row in review_rows:
        lines.append(
            "- `{name}` `{entity}`: status `{status}`, atlas_profile `{profile}`, events `{events}`, source_articles `{articles}`".format(
                name=row["name"],
                entity=row["entity_search_id"],
                status=row["review_status"],
                profile=row["atlas_profile_found"],
                events=row["atlas_event_count"],
                articles=row["atlas_source_article_count"],
            )
        )
    lines.extend(
        [
            "",
            "## Manual Gate",
            "",
            "- Atlas event/source context only proves the entity exists in the local atlas read model.",
            "- SoundCloud metadata remains a candidate signal, not identity proof.",
            "- Every row remains blocked for graph/product/memory use until independent profile evidence and a separate acceptance gate exist.",
            "",
            "## Safety",
            "",
        ]
    )
    for key, value in sorted(summary["safety"].items()):
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", f"- Next gate: {summary['next_gate']}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--rollups", type=Path, default=DEFAULT_ROLLUPS)
    parser.add_argument("--serving-db", type=Path, default=DEFAULT_SERVING_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = build_source_context_review(
        candidates_path=args.candidates,
        rollups_path=args.rollups,
        serving_db=args.serving_db,
        out_dir=args.out_dir,
        report_path=args.report_path,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "entity_rows": summary["entity_rows"],
                "entities_with_atlas_event_context": summary["entities_with_atlas_event_context"],
                "accepted_for_graph": summary["accepted_for_graph"],
                "summary": str(args.out_dir / "atlas_social_identity_source_context_review_summary.json"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
