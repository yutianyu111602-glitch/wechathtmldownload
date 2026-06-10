#!/usr/bin/env python3
"""Build a report-only DJ identity merge packet from the S61 split queue."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AUDIT_JSON = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_relation_identity_projection_s61_20260531"
    / "atlas_relation_field_integrity.json"
)
DEFAULT_DB3 = REPO_ROOT / "services" / "weekly_activity_cloudrun" / "data" / "atlas_miniapp.sqlite"
DEFAULT_OUT_DIR = REPO_ROOT / "tools" / "stage7_rewrite" / "reports" / "atlas_dj_identity_merge_packet_s62_20260531"


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return str(path)


def connect_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}


def fetch_profiles(conn: sqlite3.Connection, dj_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not dj_ids:
        return {}
    columns = table_columns(conn, "dj_profile")
    optional_fields = [
        field
        for field in [
            "dj_id",
            "display_name",
            "normalized_name",
            "aliases_json",
            "city_primary",
            "event_count",
            "venue_count",
            "collaborator_count",
            "source_article_count",
            "organization_count",
            "media_count",
            "first_seen_at",
            "last_seen_at",
            "bio",
            "bio_source",
            "avatar_url",
            "avatar_asset_id",
        ]
        if field in columns
    ]
    rows = conn.execute(
        f'''
        SELECT {", ".join(f'"{field}"' for field in optional_fields)}
        FROM dj_profile
        WHERE dj_id IN ({placeholders(dj_ids)})
        ''',
        tuple(dj_ids),
    ).fetchall()
    return {
        str(row[optional_fields.index("dj_id")]): {field: row[index] for index, field in enumerate(optional_fields)}
        for row in rows
    }


def grouped_count(conn: sqlite3.Connection, table: str, field: str, dj_ids: list[str]) -> dict[str, int]:
    if not dj_ids:
        return {}
    rows = conn.execute(
        f'''
        SELECT "{field}", COUNT(*)
        FROM "{table}"
        WHERE "{field}" IN ({placeholders(dj_ids)})
        GROUP BY "{field}"
        ''',
        tuple(dj_ids),
    ).fetchall()
    return {str(row[0]): int(row[1] or 0) for row in rows}


def collaborator_counts(conn: sqlite3.Connection, dj_ids: list[str]) -> dict[str, int]:
    counts = {dj_id: 0 for dj_id in dj_ids}
    for field in ["src_dj_id", "dst_dj_id"]:
        for dj_id, count in grouped_count(conn, "dj_collaborator", field, dj_ids).items():
            counts[dj_id] = counts.get(dj_id, 0) + count
    return counts


def int_field(profile: dict[str, Any], field: str) -> int:
    try:
        return int(profile.get(field) or 0)
    except (TypeError, ValueError):
        return 0


def non_empty_profile_fields(profile: dict[str, Any]) -> int:
    return sum(1 for value in profile.values() if value not in (None, "", [], {}))


def score_identity(
    dj_id: str,
    profile: dict[str, Any],
    event_rows: dict[str, int],
    venue_rows: dict[str, int],
    collaborator_rows: dict[str, int],
) -> dict[str, Any]:
    event_total = event_rows.get(dj_id, 0) + int_field(profile, "event_count")
    venue_total = venue_rows.get(dj_id, 0) + int_field(profile, "venue_count")
    collaborator_total = collaborator_rows.get(dj_id, 0) + int_field(profile, "collaborator_count")
    profile_field_count = non_empty_profile_fields(profile)
    return {
        "dj_id": dj_id,
        "display_name": str(profile.get("display_name") or ""),
        "normalized_name": str(profile.get("normalized_name") or ""),
        "city_primary": str(profile.get("city_primary") or ""),
        "event_rows": event_rows.get(dj_id, 0),
        "venue_rows": venue_rows.get(dj_id, 0),
        "collaborator_edges": collaborator_rows.get(dj_id, 0),
        "profile_event_count": int_field(profile, "event_count"),
        "profile_venue_count": int_field(profile, "venue_count"),
        "profile_collaborator_count": int_field(profile, "collaborator_count"),
        "profile_non_empty_fields": profile_field_count,
        "ranking_tuple": [event_total, collaborator_total, venue_total, profile_field_count],
    }


def canonical_sort_key(score: dict[str, Any]) -> tuple[int, int, int, int, str]:
    ranking = score["ranking_tuple"]
    return (-ranking[0], -ranking[1], -ranking[2], -ranking[3], score["dj_id"])


def build_candidate(conn: sqlite3.Connection, group: dict[str, Any]) -> dict[str, Any]:
    dj_ids = sorted({str(dj_id) for dj_id in group.get("dj_ids", []) if str(dj_id).strip()})
    profiles = fetch_profiles(conn, dj_ids)
    event_rows = grouped_count(conn, "dj_event", "dj_id", dj_ids)
    venue_rows = grouped_count(conn, "dj_venue", "dj_id", dj_ids)
    collaborator_rows = collaborator_counts(conn, dj_ids)
    scores = [
        score_identity(dj_id, profiles.get(dj_id, {"dj_id": dj_id}), event_rows, venue_rows, collaborator_rows)
        for dj_id in dj_ids
    ]
    ranked = sorted(scores, key=canonical_sort_key)
    canonical = ranked[0]["dj_id"] if ranked else ""
    return {
        "group_id": f"{group.get('city_key', '') or '_'}::{group.get('identity_token', '')}",
        "city_key": group.get("city_key", ""),
        "identity_token": group.get("identity_token", ""),
        "canonical_dj_id": canonical,
        "merge_dj_ids": [score["dj_id"] for score in ranked if score["dj_id"] != canonical],
        "all_dj_ids": [score["dj_id"] for score in ranked],
        "display_names": group.get("display_names", []),
        "normalized_names": group.get("normalized_names", []),
        "row_count": group.get("row_count", len(dj_ids)),
        "scores": ranked,
        "canonical_reason": "highest event, collaborator, venue, and profile-field coverage; lexicographic dj_id tie-break",
        "review_required": True,
        "safe_automerge": False,
        "database_write_allowed": False,
        "preserve_rules": [
            "Preserve all non-empty event, venue, relation, source_ref, mixtape, social, bio, avatar, and evidence fields.",
            "Never let an empty weekly/current overlay replace DB2/DB3 non-empty fields.",
            "Apply only after human review or an explicit write-gate packet with rollback evidence.",
        ],
    }


def build_packet(audit_payload: dict[str, Any], db3_path: Path) -> dict[str, Any]:
    review = audit_payload.get("db3_identity_dedupe_review", {})
    groups = review.get("same_normalized_multi_id_groups") or review.get("same_normalized_multi_id_sample") or []
    with connect_ro(db3_path) as conn:
        candidates = [build_candidate(conn, group) for group in groups]
    return {
        "schema_version": "atlas_dj_identity_merge_packet.v1",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "decision": "atlas_dj_identity_merge_packet_ready",
        "candidate_count": len(candidates),
        "merge_id_count": sum(len(candidate["merge_dj_ids"]) for candidate in candidates),
        "empty_normalized_profile_count": int(review.get("empty_normalized_profile_count") or 0),
        "empty_normalized_profile_sample": review.get("empty_normalized_profile_sample", []),
        "candidates": candidates,
        "rules": [
            "This packet is a repair input, not a write operation.",
            "All candidates are review_required and safe_automerge=false.",
            "Canonical dj_id is chosen by DB3 evidence coverage only; ambiguous artistic aliases still require review.",
            "Downstream write gates must update profile, subject, collaborator, venue, event, source, and external-link references together.",
        ],
        "safety": {
            "report_only": True,
            "database_mutations": False,
            "canonical_merge_executed": False,
            "provider_or_llm_calls": False,
            "secret_files_read": False,
            "deployment_executed": False,
            "upload_executed": False,
        },
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, candidates: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(candidate, ensure_ascii=False, sort_keys=True) for candidate in candidates) + "\n", encoding="utf-8")


def write_markdown(path: Path, packet: dict[str, Any], audit_json: Path, db3_path: Path) -> None:
    lines = [
        "# Atlas DJ Identity Merge Packet",
        "",
        f"- Decision: `{packet['decision']}`",
        f"- Candidate groups: `{packet['candidate_count']}`",
        f"- Merge ids: `{packet['merge_id_count']}`",
        f"- Empty normalized profiles: `{packet['empty_normalized_profile_count']}`",
        f"- Audit JSON: `{rel(audit_json)}`",
        f"- DB3: `{rel(db3_path)}`",
        "",
        "## Top Candidates",
    ]
    for candidate in packet["candidates"][:25]:
        lines.append(
            f"- `{candidate['identity_token']}` -> canonical `{candidate['canonical_dj_id']}`, merge `{len(candidate['merge_dj_ids'])}` ids, names `{', '.join(candidate['display_names'][:6])}`"
        )
    lines.extend(
        [
            "",
            "## Rules",
        ]
    )
    for rule in packet["rules"]:
        lines.append(f"- {rule}")
    lines.extend(
        [
            "",
            "## Safety",
            "- Report only: `true`",
            "- DB mutations: `false`",
            "- Canonical merge executed: `false`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_outputs(out_dir: Path, packet: dict[str, Any], audit_json: Path, db3_path: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "atlas_dj_identity_merge_packet.json", packet)
    write_jsonl(out_dir / "atlas_dj_identity_merge_candidates.jsonl", packet["candidates"])
    write_markdown(out_dir / "atlas_dj_identity_merge_packet.md", packet, audit_json, db3_path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build report-only DJ identity canonical merge candidates")
    parser.add_argument("--audit-json", type=Path, default=DEFAULT_AUDIT_JSON)
    parser.add_argument("--db3", type=Path, default=DEFAULT_DB3)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    audit_payload = read_json(args.audit_json)
    packet = build_packet(audit_payload, args.db3)
    write_outputs(args.out_dir, packet, args.audit_json, args.db3)
    print(
        json.dumps(
            {
                "decision": packet["decision"],
                "candidate_count": packet["candidate_count"],
                "merge_id_count": packet["merge_id_count"],
                "json": str(args.out_dir / "atlas_dj_identity_merge_packet.json"),
                "markdown": str(args.out_dir / "atlas_dj_identity_merge_packet.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
