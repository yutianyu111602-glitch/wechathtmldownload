#!/usr/bin/env python3
"""Build report-only DJ historical performance and relationship rollups.

This is the DJ-first materialization seam for Atlas. It reads the local
``atlas.sqlite`` in read-only mode, aggregates complete event history for one
or more DJs, and writes sidecar reports only. It does not mutate the source
SQLite database, Neo4j, Qdrant, mem0, CloudRun, or production state.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from build_atlas_dj_first_canary import (  # noqa: E402
    DEFAULT_CURATED_RULES,
    DEFAULT_DB,
    classify_place_text,
    connect_readonly,
    load_curated_rules,
    norm_key,
    norm_text,
    normalize_venue_name,
    parse_json_list,
    source_scoped_id,
    stable_id,
    write_json,
    write_jsonl,
)


DEFAULT_OUT_DIR = Path(__file__).resolve().parents[3] / "reports" / "atlas_dj_history_rollup_20260522"


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def unique_names(values: Iterable[Any], limit: int = 0) -> list[str]:
    seen: set[str] = set()
    rows: list[str] = []
    for value in values:
        name = norm_text(value)
        key = norm_key(name)
        if not name or key in seen:
            continue
        seen.add(key)
        rows.append(name)
        if limit and len(rows) >= limit:
            break
    return rows


def add_sample(row: dict[str, Any], sample: dict[str, Any], limit: int = 8) -> None:
    rows = row.setdefault("sample_evidence", [])
    key = json.dumps(sample, ensure_ascii=False, sort_keys=True)
    seen = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in rows}
    if key not in seen and len(rows) < limit:
        rows.append(sample)


def curated_rule(value: Any, curated_rules: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    return curated_rules.get(norm_key(value))


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def event_public_id(row: dict[str, Any]) -> str:
    return source_scoped_id(row.get("source_article_uid"), row.get("evid"), stable_id("event", row.get("name")))


def event_time(row: dict[str, Any]) -> str:
    return norm_text(row.get("time_iso") or row.get("time_text") or row.get("publish_time"))


def event_sample(row: dict[str, Any], participants: list[str]) -> dict[str, Any]:
    return {
        "event_id": event_public_id(row),
        "event_name": norm_text(row.get("name")),
        "time": event_time(row),
        "place": norm_text(row.get("place")),
        "city": norm_text(row.get("city") or row.get("city_label")),
        "source_article_uid": norm_text(row.get("source_article_uid")),
        "source_title": norm_text(row.get("source_title")),
        "source_account": norm_text(row.get("source_account")),
        "participants_sample": participants[:16],
    }


def entity_profile_for_name(conn: sqlite3.Connection, name: str) -> dict[str, Any]:
    rows = [
        row_dict(row)
        for row in conn.execute(
            """
            SELECT name, type, city, source_article_uid, confidence
            FROM entities
            WHERE lower(name) = lower(?)
            ORDER BY confidence DESC, source_article_uid
            """,
            (name,),
        )
    ]
    display = rows[0]["name"] if rows else norm_text(name)
    source_articles = {norm_text(row.get("source_article_uid")) for row in rows if norm_text(row.get("source_article_uid"))}
    cities = Counter(norm_text(row.get("city")) for row in rows if norm_text(row.get("city")))
    avg_confidence = sum(confidence(row.get("confidence")) for row in rows) / max(len(rows), 1)
    return {
        "schema_version": "atlas_dj_history_rollup.profile.v1",
        "dj_id": stable_id("dj", norm_key(display)),
        "display_name": display,
        "normalized_name": norm_key(display),
        "entity_mention_count": len(rows),
        "entity_source_article_count": len(source_articles),
        "city": cities.most_common(1)[0][0] if cities else "",
        "avg_entity_confidence": round(avg_confidence, 4),
        "source_articles_sample": sorted(source_articles)[:20],
        "write_status": "report_only",
    }


def load_top_entity_djs(conn: sqlite3.Connection, limit: int) -> list[str]:
    sql = """
        SELECT name, COUNT(*) AS mention_count
        FROM entities
        WHERE lower(type) IN ('person', 'dj', 'artist')
          AND length(trim(name)) > 0
        GROUP BY lower(name)
        ORDER BY mention_count DESC, name
        LIMIT ?
    """
    return [row["name"] for row in conn.execute(sql, (limit,))]


def iter_events_for_targets(conn: sqlite3.Connection, target_names: list[str], all_events: bool = False) -> Iterable[dict[str, Any]]:
    base = """
        SELECT
          ev.evid,
          ev.name,
          ev.place,
          ev.city,
          ev.time_iso,
          ev.time_text,
          ev.source_article_uid,
          ev.confidence,
          ev.participants_json,
          ev.organizers_json,
          a.title AS source_title,
          a.source_account,
          a.publish_time,
          a.city_label
        FROM events ev
        LEFT JOIN articles a ON a.article_uid = ev.source_article_uid
    """
    if all_events:
        sql = base + " WHERE ev.participants_json IS NOT NULL ORDER BY COALESCE(ev.time_iso, a.publish_time, ev.time_text) DESC"
        yield from (row_dict(row) for row in conn.execute(sql))
        return
    clauses = []
    args: list[str] = []
    for name in unique_names(target_names):
        clauses.append("ev.participants_json LIKE ?")
        args.append(f"%{name}%")
    if not clauses:
        return
    sql = (
        base
        + " WHERE ev.participants_json IS NOT NULL AND ("
        + " OR ".join(clauses)
        + ") ORDER BY COALESCE(ev.time_iso, a.publish_time, ev.time_text) DESC"
    )
    yield from (row_dict(row) for row in conn.execute(sql, args))


def counter_rows(
    rows: dict[tuple[str, str], dict[str, Any]],
    count_field: str,
    score_field: str,
    multiplier: float,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows.values():
        row["source_article_count"] = len(row["source_articles"])
        row["source_articles"] = sorted(row["source_articles"])[:30]
        row[score_field] = round(multiplier * row[count_field] + min(row["source_article_count"], 10) * 0.2, 4)
        result.append(row)
    result.sort(key=lambda item: (-item[score_field], item.get("dj_name") or item.get("src_name") or "", item.get("venue_name") or item.get("dst_name") or ""))
    return result


def build_rows(
    profiles: list[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    curated_rules: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    profiles_by_key = {row["normalized_name"]: row for row in profiles}
    event_rows: list[dict[str, Any]] = []
    collaborators: dict[tuple[str, str], dict[str, Any]] = {}
    venues: dict[tuple[str, str], dict[str, Any]] = {}
    organizations: dict[tuple[str, str], dict[str, Any]] = {}
    media: dict[tuple[str, str], dict[str, Any]] = {}
    evidence_refs: list[dict[str, Any]] = []
    resolved_field_noise: dict[tuple[str, str], dict[str, Any]] = {}
    seen_dj_events: set[tuple[str, str]] = set()
    scanned_events = 0
    matched_events = 0

    for event in events:
        scanned_events += 1
        participants = unique_names(parse_json_list(event.get("participants_json")), limit=64)
        participant_by_key = {norm_key(name): name for name in participants}
        matched_keys = [key for key in profiles_by_key if key in participant_by_key]
        if not matched_keys:
            continue
        matched_events += 1
        organizers = unique_names(parse_json_list(event.get("organizers_json")), limit=32)
        place_raw = norm_text(event.get("place"))
        place_name = normalize_venue_name(place_raw)
        place_kind = classify_place_text(place_name, curated_rules)
        sample = event_sample(event, participants)
        for dj_key in matched_keys:
            profile = profiles_by_key[dj_key]
            dj_id = profile["dj_id"]
            source_article_uid = norm_text(event.get("source_article_uid"))
            event_id = event_public_id(event)
            dj_event_key = (dj_id, event_id)
            if dj_event_key in seen_dj_events:
                continue
            seen_dj_events.add(dj_event_key)
            event_rows.append(
                {
                    "schema_version": "atlas_dj_history_rollup.dj_event.v1",
                    "dj_id": dj_id,
                    "dj_name": profile["display_name"],
                    "event_id": event_id,
                    "event_name": norm_text(event.get("name")),
                    "event_time": event_time(event),
                    "event_time_sort": event_time(event),
                    "place_raw": place_raw,
                    "venue_name": place_name if place_kind == "venue" else "",
                    "place_kind": place_kind,
                    "city": norm_text(event.get("city") or event.get("city_label")),
                    "source_article_uid": source_article_uid,
                    "source_title": norm_text(event.get("source_title")),
                    "source_account": norm_text(event.get("source_account")),
                    "confidence": confidence(event.get("confidence")),
                    "participants": participants,
                    "organizers": organizers,
                    "participant_count": len(participants),
                    "write_status": "report_only",
                }
            )
            for other_key, other_name in participant_by_key.items():
                if other_key == dj_key:
                    continue
                row = collaborators.setdefault(
                    (dj_id, other_key),
                    {
                        "schema_version": "atlas_dj_history_rollup.dj_collaborator.v1",
                        "src_dj_id": dj_id,
                        "src_name": profile["display_name"],
                        "dst_dj_id": stable_id("dj", other_key),
                        "dst_name": other_name,
                        "same_event_count": 0,
                        "source_articles": set(),
                        "relation_score": 0.0,
                        "relation_label_zh": "同台演出",
                        "sample_evidence": [],
                        "write_status": "report_only",
                    },
                )
                row["same_event_count"] += 1
                if source_article_uid:
                    row["source_articles"].add(source_article_uid)
                add_sample(row, sample)
            if place_name and place_kind == "venue":
                row = venues.setdefault(
                    (dj_id, norm_key(place_name)),
                    {
                        "schema_version": "atlas_dj_history_rollup.dj_venue.v1",
                        "dj_id": dj_id,
                        "dj_name": profile["display_name"],
                        "venue_id": stable_id("venue", place_name),
                        "venue_name": place_name,
                        "played_event_count": 0,
                        "source_articles": set(),
                        "affinity_score": 0.0,
                        "sample_evidence": [],
                        "write_status": "report_only",
                    },
                )
                row["played_event_count"] += 1
                if source_article_uid:
                    row["source_articles"].add(source_article_uid)
                add_sample(row, sample)
            elif place_name:
                rule = curated_rule(place_name, curated_rules)
                if rule:
                    row = resolved_field_noise.setdefault(
                        ("event_place", norm_key(place_name)),
                        {
                            "schema_version": "atlas_dj_history_rollup.resolved_field_noise.v1",
                            "term_type": "event_place",
                            "term": place_name,
                            "normalized_term": norm_key(place_name),
                            "resolved_kind": norm_key(rule.get("kind")),
                            "resolution_basis": rule.get("basis", ""),
                            "confidence": rule.get("confidence", 0),
                            "public_sources": rule.get("sources", []),
                            "count": 0,
                            "sample_evidence": [],
                            "write_status": "report_only",
                        },
                    )
                    row["count"] += 1
                    add_sample(row, sample)
            for organizer in organizers:
                rule = curated_rule(organizer, curated_rules)
                org_kind = norm_key(rule.get("kind")) if rule else "label_org"
                bucket = media if org_kind == "radio" else organizations
                row = bucket.setdefault(
                    (dj_id, norm_key(organizer)),
                    {
                        "schema_version": "atlas_dj_history_rollup.dj_media.v1" if org_kind == "radio" else "atlas_dj_history_rollup.dj_organization.v1",
                        "dj_id": dj_id,
                        "dj_name": profile["display_name"],
                        "target_id": stable_id(org_kind, organizer),
                        "target_name": organizer,
                        "target_kind": org_kind,
                        "event_count": 0,
                        "source_articles": set(),
                        "relation_score": 0.0,
                        "sample_evidence": [],
                        "write_status": "report_only",
                    },
                )
                row["event_count"] += 1
                if source_article_uid:
                    row["source_articles"].add(source_article_uid)
                add_sample(row, sample)
            evidence_refs.append(
                {
                    "schema_version": "atlas_dj_history_rollup.evidence_ref.v1",
                    "evidence_id": stable_id("evidence", dj_id, event_id),
                    "fact_type": "dj_event_participation",
                    "fact_id": f"{dj_id}->{event_id}",
                    "source_article_uid": source_article_uid,
                    "source_title": sample["source_title"],
                    "source_account": sample["source_account"],
                    "visible_excerpt": sample["event_name"],
                    "evidence_strength": "same_event_participant",
                    "write_status": "report_only",
                }
            )

    event_rows.sort(key=lambda row: (row["event_time_sort"], row["source_article_uid"], row["event_id"]), reverse=True)
    collaborator_rows = counter_rows(collaborators, "same_event_count", "relation_score", 3.0)
    venue_rows = counter_rows(venues, "played_event_count", "affinity_score", 2.5)
    organization_rows = counter_rows(organizations, "event_count", "relation_score", 2.0)
    media_rows = counter_rows(media, "event_count", "relation_score", 2.0)
    resolved_rows = list(resolved_field_noise.values())
    resolved_rows.sort(key=lambda row: (-row["count"], row["term_type"], row["term"]))

    event_counts = Counter(row["dj_id"] for row in event_rows)
    source_counts: dict[str, set[str]] = {}
    venue_counts = Counter(row["dj_id"] for row in venue_rows)
    collab_counts = Counter(row["src_dj_id"] for row in collaborator_rows)
    for row in event_rows:
        source_counts.setdefault(row["dj_id"], set()).add(row["source_article_uid"])
    for profile in profiles:
        dj_id = profile["dj_id"]
        profile["event_count"] = int(event_counts.get(dj_id, 0))
        profile["source_article_count"] = len({item for item in source_counts.get(dj_id, set()) if item})
        profile["collaborator_count"] = int(collab_counts.get(dj_id, 0))
        profile["venue_count"] = int(venue_counts.get(dj_id, 0))

    return {
        "profiles": profiles,
        "events": event_rows,
        "collaborators": collaborator_rows,
        "venues": venue_rows,
        "organizations": organization_rows,
        "media": media_rows,
        "evidence_refs": evidence_refs,
        "resolved_field_noise": resolved_rows,
        "scanned_events": scanned_events,
        "matched_events": matched_events,
    }


def write_sidecar_sqlite(path: Path, result: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE dj_profile (dj_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
        CREATE TABLE dj_event (dj_id TEXT NOT NULL, event_id TEXT NOT NULL, event_time_sort TEXT, payload_json TEXT NOT NULL, PRIMARY KEY(dj_id, event_id));
        CREATE TABLE dj_collaborator (src_dj_id TEXT NOT NULL, dst_dj_id TEXT NOT NULL, relation_score REAL NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(src_dj_id, dst_dj_id));
        CREATE TABLE dj_venue (dj_id TEXT NOT NULL, venue_id TEXT NOT NULL, affinity_score REAL NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(dj_id, venue_id));
        CREATE TABLE dj_organization (dj_id TEXT NOT NULL, target_id TEXT NOT NULL, relation_score REAL NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(dj_id, target_id));
        CREATE TABLE dj_media (dj_id TEXT NOT NULL, target_id TEXT NOT NULL, relation_score REAL NOT NULL, payload_json TEXT NOT NULL, PRIMARY KEY(dj_id, target_id));
        CREATE TABLE evidence_ref (evidence_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL);
        CREATE INDEX idx_dj_event_dj_time ON dj_event(dj_id, event_time_sort DESC);
        CREATE INDEX idx_dj_collab_score ON dj_collaborator(src_dj_id, relation_score DESC);
        CREATE INDEX idx_dj_venue_score ON dj_venue(dj_id, affinity_score DESC);
        """
    )
    conn.executemany(
        "INSERT INTO dj_profile VALUES (?, ?)",
        [(row["dj_id"], json.dumps(row, ensure_ascii=False, sort_keys=True)) for row in result["profiles"]],
    )
    conn.executemany(
        "INSERT INTO dj_event VALUES (?, ?, ?, ?)",
        [(row["dj_id"], row["event_id"], row["event_time_sort"], json.dumps(row, ensure_ascii=False, sort_keys=True)) for row in result["events"]],
    )
    conn.executemany(
        "INSERT INTO dj_collaborator VALUES (?, ?, ?, ?)",
        [(row["src_dj_id"], row["dst_dj_id"], row["relation_score"], json.dumps(row, ensure_ascii=False, sort_keys=True)) for row in result["collaborators"]],
    )
    conn.executemany(
        "INSERT INTO dj_venue VALUES (?, ?, ?, ?)",
        [(row["dj_id"], row["venue_id"], row["affinity_score"], json.dumps(row, ensure_ascii=False, sort_keys=True)) for row in result["venues"]],
    )
    conn.executemany(
        "INSERT INTO dj_organization VALUES (?, ?, ?, ?)",
        [(row["dj_id"], row["target_id"], row["relation_score"], json.dumps(row, ensure_ascii=False, sort_keys=True)) for row in result["organizations"]],
    )
    conn.executemany(
        "INSERT INTO dj_media VALUES (?, ?, ?, ?)",
        [(row["dj_id"], row["target_id"], row["relation_score"], json.dumps(row, ensure_ascii=False, sort_keys=True)) for row in result["media"]],
    )
    conn.executemany(
        "INSERT INTO evidence_ref VALUES (?, ?)",
        [(row["evidence_id"], json.dumps(row, ensure_ascii=False, sort_keys=True)) for row in result["evidence_refs"]],
    )
    conn.commit()
    conn.close()


def write_markdown(path: Path, summary: dict[str, Any], result: dict[str, Any]) -> None:
    lines = [
        "# Atlas DJ History Rollup",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source_db: `{summary['source_db']}`",
        f"- sidecar_sqlite: `{summary['sidecar_sqlite']}`",
        f"- dj_count: `{summary['dj_count']}`",
        f"- dj_events: `{summary['relation_counts']['dj_events']}`",
        f"- dj_collaborators: `{summary['relation_counts']['dj_collaborators']}`",
        f"- dj_venues: `{summary['relation_counts']['dj_venues']}`",
        "",
        "## DJ Profiles",
        "",
        "| DJ | Events | Sources | Venues | Collaborators |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in result["profiles"][:50]:
        lines.append(f"| `{row['display_name']}` | {row['event_count']} | {row['source_article_count']} | {row['venue_count']} | {row['collaborator_count']} |")
    lines.extend(["", "## Top Collaborators", "", "| DJ | Related DJ | Same Events | Score |", "|---|---|---:|---:|"])
    for row in result["collaborators"][:30]:
        lines.append(f"| `{row['src_name']}` | `{row['dst_name']}` | {row['same_event_count']} | {row['relation_score']} |")
    lines.extend(["", "## Recent Events", "", "| DJ | Time | Event | Venue / Place | Source |", "|---|---|---|---|---|"])
    for row in result["events"][:30]:
        place = row["venue_name"] or row["place_raw"]
        lines.append(f"| `{row['dj_name']}` | `{row['event_time']}` | `{row['event_name']}` | `{place}` | `{row['source_title']}` |")
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only sidecar artifact.",
            "- Source SQLite opened read-only.",
            "- No Neo4j, Qdrant, mem0, CloudRun, paid API, model, or production writes.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_history_rollup(
    db_path: Path,
    out_dir: Path,
    dj_names: list[str] | None = None,
    all_djs: bool = False,
    max_djs: int = 100,
    curated_rules_path: Path | None = DEFAULT_CURATED_RULES,
) -> dict[str, Any]:
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    curated_rules = load_curated_rules(curated_rules_path)
    with connect_readonly(db_path) as conn:
        selected_names = unique_names(dj_names or [])
        if all_djs:
            selected_names = load_top_entity_djs(conn, max_djs)
        profiles = [entity_profile_for_name(conn, name) for name in selected_names]
        result = build_rows(profiles, iter_events_for_targets(conn, selected_names, all_events=False), curated_rules)

    sidecar_sqlite = out_dir / "atlas_dj_history_rollup.sqlite"
    write_sidecar_sqlite(sidecar_sqlite, result)
    summary = {
        "schema_version": "atlas_dj_history_rollup.summary.v1",
        "generated_at": now_iso(),
        "source_db": str(db_path),
        "out_dir": str(out_dir),
        "sidecar_sqlite": str(sidecar_sqlite),
        "curated_rules_path": str(curated_rules_path) if curated_rules_path else "",
        "curated_rules_loaded": len(curated_rules),
        "dj_count": len(profiles),
        "requested_djs": selected_names,
        "scanned_events": result["scanned_events"],
        "matched_events": result["matched_events"],
        "relation_counts": {
            "dj_events": len(result["events"]),
            "dj_collaborators": len(result["collaborators"]),
            "dj_venues": len(result["venues"]),
            "dj_organizations": len(result["organizations"]),
            "dj_media": len(result["media"]),
            "evidence_refs": len(result["evidence_refs"]),
            "resolved_field_noise": len(result["resolved_field_noise"]),
        },
        "safety": {
            "report_only": True,
            "source_sqlite_write_executed": False,
            "sidecar_sqlite_write_executed": True,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "cloudrun_deploy_executed": False,
            "paid_api_call_executed": False,
            "model_call_executed": False,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "dj_profiles.jsonl", result["profiles"])
    write_jsonl(out_dir / "dj_events.jsonl", result["events"])
    write_jsonl(out_dir / "dj_collaborators.jsonl", result["collaborators"])
    write_jsonl(out_dir / "dj_venues.jsonl", result["venues"])
    write_jsonl(out_dir / "dj_organizations.jsonl", result["organizations"])
    write_jsonl(out_dir / "dj_media.jsonl", result["media"])
    write_jsonl(out_dir / "evidence_refs.jsonl", result["evidence_refs"])
    write_jsonl(out_dir / "resolved_field_noise.jsonl", result["resolved_field_noise"])
    write_json(out_dir / "summary.json", summary)
    write_markdown(out_dir / "summary.md", summary, result)
    result["summary"] = summary
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--curated-rules", type=Path, default=DEFAULT_CURATED_RULES)
    parser.add_argument("--dj", action="append", default=[], help="Exact DJ display name to roll up. Repeatable.")
    parser.add_argument("--all-djs", action="store_true", help="Build top DJ profiles from person entities.")
    parser.add_argument("--max-djs", type=int, default=100, help="Top person-entity DJ count when --all-djs is used.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    if not args.dj and not args.all_djs:
        raise SystemExit("Provide at least one --dj or use --all-djs.")
    result = build_history_rollup(
        args.db,
        args.out_dir,
        dj_names=args.dj,
        all_djs=args.all_djs,
        max_djs=args.max_djs,
        curated_rules_path=args.curated_rules,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "dj_count": result["summary"]["dj_count"],
                "relation_counts": result["summary"]["relation_counts"],
                "sidecar_sqlite": result["summary"]["sidecar_sqlite"],
                "summary": str(Path(args.out_dir) / "summary.json"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
