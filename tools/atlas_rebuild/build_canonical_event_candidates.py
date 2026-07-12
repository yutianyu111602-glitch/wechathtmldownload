#!/usr/bin/env python3
"""Build report-only canonical-event candidates from the current Atlas serving DB.

Phase 1 of the Atlas v2 dedupe/freshness design
(`C:\\code\\mavelpoint-cn-v2\\docs\\site-clone\\ATLAS_V2_DEDUP_SANJI_AUTOMATION_DEEP_DESIGN_2026-07-06.md`).

Problem: `performance_event` / `dj_event` in the serving DB count every *mention* of an
event (one row per source article that reports it) rather than the real-world event once.
A single roundup article often lists several distinct parties, so merging by
`source_ref_id` is wrong. This script instead groups by a strong identity key
(`event_date, city_norm, venue_id, title_norm`) and only when both a date and a venue are present and
the date is not an obvious sentinel/garbage value (e.g. `2046-12-25`). Rows missing a date
or venue, or carrying a suspect date, pass through unmerged as their own canonical event —
Phase 2 (date/venue repair) closes that gap later, not here.

This script only ever opens the source serving DB read-only. It never mutates it, never
touches Sanji or Hermes, makes no network or LLM calls, and refuses to write its output to
the source DB path (or anything that looks like a Sanji/Hermes path).

Phase 3 addition (`--repair-db`): when pointed at the Phase 2 output
(`build_date_venue_repair_candidates.py`'s `date_venue_repair_candidates.sqlite`), a
missing `starts_at`/`venue_id` is filled in from that DB's `auto_accepted` rows before
grouping — this is what actually lets rows that were singletons in Phase 1 (missing date or
venue) join a strong-key group. Omit `--repair-db` and behavior is identical to Phase 1
(nothing here changes for that path). `needs_review` repair rows are never used — only
`auto_accepted` ones cross into the merge.

Also computes `dj_profile_recount`: each DJ's event_count recomputed as
`COUNT(DISTINCT canonical_event_id)` from `canonical_dj_event`, next to the raw `dj_event`
row count, so the effect on individual DJ profiles (e.g. the known JOE LI 5,336-row /
224-real-event case) is directly inspectable rather than only visible in an aggregate ratio.

Two more merge tiers, added alongside the strong key (never replacing it — the strong key's
exact-title requirement stays; these only add more ways to safely collapse duplicates):

- **Medium key** (auto-merged): `event_date + city_norm + normalize_venue_name(venue_name) +
  title_norm`, applied only to rows that still have NO resolved `venue_id` (not even via a
  Phase 2 repair) but do carry a raw `venue_name` + `city`. Two or more independent rows
  agreeing on this key is treated the same way the strong key treats agreement — real
  corroboration, not a guess.
- **Weak key** (review-only, NEVER auto-merged): among canonical events that already share
  the same `(event_date, venue_id)`, any two with `title_norm` similarity (`difflib`,
  stdlib) >= `--weak-title-similarity` (default 0.85) are written to
  `canonical_event_merge_review_candidate` — a human/future-review signal, not a count
  change. Buckets larger than `--weak-key-max-bucket` (default 200) are skipped and counted
  rather than doing an unbounded pairwise scan.

Usage:
  python build_canonical_event_candidates.py
  python build_canonical_event_candidates.py --repair-db reports/.../date_venue_repair_candidates.sqlite
  python build_canonical_event_candidates.py --identity-db reports/.../identity_redirects.sqlite --venue-redirect-db reports/.../venue_redirects.sqlite
  python build_canonical_event_candidates.py --limit-events 5000 --out-dir reports/scratch
  python build_canonical_event_candidates.py --self-check
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE7_SCRIPTS = REPO_ROOT / "tools" / "stage7_rewrite" / "scripts"
if str(STAGE7_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(STAGE7_SCRIPTS))

from build_atlas_dj_first_canary import (  # noqa: E402
    confidence,
    connect_readonly,
    norm_key,
    norm_text,
    normalize_venue_name,
    now_iso,
    stable_id,
    write_json,
)

DEFAULT_SOURCE_DB = (
    REPO_ROOT
    / "reports"
    / "atlas_serving_activity_current_time_dedupe_strict_20260525-1625"
    / "atlas_serving.sqlite"
)
SCHEMA_VERSION = "atlas_v2_canonical_event_candidate.phase3_identity.v2"
FORBIDDEN_OUTPUT_MARKERS = (
    "appdata\\roaming\\sanji",
    "appdata/roaming/sanji",
    "appdata\\local\\hermes",
    "appdata/local/hermes",
)
UNKNOWN_CITY_KEYS = {"", "未知", "不详", "unknown", "none", "null"}


def parse_starts_at(value: Any) -> datetime | None:
    text = norm_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return None


def is_suspect_year(dt: datetime, now: datetime) -> bool:
    return dt.year > now.year + 2


def load_repair_candidates(repair_db: Path | None) -> tuple[dict[str, str], dict[str, str]]:
    """Load Phase 2's auto_accepted repair candidates. Returns
    (event_id -> repaired_date_iso, event_id -> repaired_venue_id). Empty dicts (Phase 1
    behavior, unaffected) if `repair_db` is None or the tables aren't there.
    """
    if repair_db is None or not repair_db.exists():
        return {}, {}
    conn = connect_readonly(repair_db)
    date_repairs: dict[str, str] = {}
    venue_repairs: dict[str, str] = {}
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='date_repair_candidate'").fetchone():
        for row in conn.execute(
            "SELECT event_id, candidate_date FROM date_repair_candidate WHERE review_state = 'auto_accepted'"
        ):
            date_repairs[row["event_id"]] = row["candidate_date"]
    if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='venue_repair_candidate'").fetchone():
        for row in conn.execute(
            "SELECT event_id, candidate_venue_id FROM venue_repair_candidate WHERE review_state = 'auto_accepted'"
        ):
            venue_repairs[row["event_id"]] = row["candidate_venue_id"]
    conn.close()
    return date_repairs, venue_repairs


def city_scope_key(value: Any) -> str:
    city = re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value or "")).strip().casefold())
    return "" if city in UNKNOWN_CITY_KEYS else city


def id_text(value: Any) -> str:
    return str(value or "").strip()


def _resolve_redirect_mapping(mapping: dict[str, str], label: str) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for source in mapping:
        current = source
        seen: set[str] = set()
        while current in mapping:
            if current in seen:
                chain = " -> ".join([*sorted(seen), current])
                raise ValueError(f"{label} redirect cycle detected: {chain}")
            seen.add(current)
            current = mapping[current]
        if current == source:
            raise ValueError(f"{label} redirect self-cycle detected: {source}")
        resolved[source] = current
    return resolved


def load_dj_redirects(identity_db: Path | None) -> dict[str, str]:
    if identity_db is None:
        return {}
    if not identity_db.is_file():
        raise FileNotFoundError(identity_db)
    conn = connect_readonly(identity_db)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dj_identity_redirect'"
        ).fetchone()
        if not exists:
            raise ValueError(f"identity DB has no dj_identity_redirect table: {identity_db}")
        mapping = {
            id_text(row["source_dj_id"]): id_text(row["canonical_dj_id"])
            for row in conn.execute(
                "SELECT source_dj_id,canonical_dj_id FROM dj_identity_redirect ORDER BY source_dj_id"
            )
        }
    finally:
        conn.close()
    if any(not source or not target for source, target in mapping.items()):
        raise ValueError("DJ redirect contains an empty source or target")
    return _resolve_redirect_mapping(mapping, "DJ")


def load_venue_redirects(venue_redirect_db: Path | None) -> dict[str, tuple[str, str]]:
    if venue_redirect_db is None:
        return {}
    if not venue_redirect_db.is_file():
        raise FileNotFoundError(venue_redirect_db)
    conn = connect_readonly(venue_redirect_db)
    try:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(venue_identity_redirect)")
        }
        required = {"source_venue_id", "source_city_key", "canonical_venue_id"}
        if not required.issubset(columns):
            raise ValueError(
                f"venue redirect DB is missing city-scoped columns: {sorted(required - columns)}"
            )
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT source_venue_id,source_city_key,canonical_venue_id "
                "FROM venue_identity_redirect ORDER BY source_venue_id"
            )
        ]
    finally:
        conn.close()
    raw_mapping = {
        id_text(row["source_venue_id"]): id_text(row["canonical_venue_id"])
        for row in rows
    }
    if any(not source or not target for source, target in raw_mapping.items()):
        raise ValueError("venue redirect contains an empty source or target")
    resolved = _resolve_redirect_mapping(raw_mapping, "venue")
    return {
        id_text(row["source_venue_id"]): (
            city_scope_key(row["source_city_key"]),
            resolved[id_text(row["source_venue_id"])],
        )
        for row in rows
    }


def effective_starts_at(row: sqlite3.Row, date_repairs: dict[str, str]) -> str:
    own = norm_text(row["starts_at"])
    return own or date_repairs.get(row["event_id"], "")


def effective_venue_id(
    row: sqlite3.Row,
    venue_repairs: dict[str, str],
    venue_redirects: dict[str, tuple[str, str]] | None = None,
) -> str:
    own = id_text(row["venue_id"])
    venue_id = own or venue_repairs.get(row["event_id"], "")
    redirect = (venue_redirects or {}).get(venue_id)
    if redirect and city_scope_key(row["city"]) == redirect[0]:
        return redirect[1]
    return venue_id


def classify_event_row(
    row: sqlite3.Row,
    now: datetime,
    date_repairs: dict[str, str] | None = None,
    venue_repairs: dict[str, str] | None = None,
    venue_redirects: dict[str, tuple[str, str]] | None = None,
) -> tuple[str, str, datetime | None]:
    """Return (eligibility, date_iso_or_reason, parsed_datetime).

    eligibility is one of: "eligible", "missing_date", "missing_venue", "suspect_date".
    A row's own starts_at/venue_id always wins; a Phase 2 repair only fills in what the row
    itself left blank.
    """
    date_repairs = date_repairs or {}
    venue_repairs = venue_repairs or {}
    venue_id = effective_venue_id(row, venue_repairs, venue_redirects)
    parsed = parse_starts_at(effective_starts_at(row, date_repairs))
    if parsed is None:
        return "missing_date", "", None
    if is_suspect_year(parsed, now):
        return "suspect_date", parsed.date().isoformat(), parsed
    if not venue_id:
        return "missing_venue", parsed.date().isoformat(), parsed
    return "eligible", parsed.date().isoformat(), parsed


def build_canonical_events(
    performance_rows: list[sqlite3.Row],
    now: datetime,
    date_repairs: dict[str, str] | None = None,
    venue_repairs: dict[str, str] | None = None,
    venue_redirects: dict[str, tuple[str, str]] | None = None,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], dict[str, str], Counter[str]]:
    """Group performance_event rows into canonical events.

    Returns (canonical_events_by_id, canonical_event_member_rows, event_id_to_canonical_id, reason_counts).
    """
    date_repairs = date_repairs or {}
    venue_repairs = venue_repairs or {}
    venue_redirects = venue_redirects or {}
    groups: dict[tuple[str, str, str, str], list[sqlite3.Row]] = defaultdict(list)
    singleton_rows: list[tuple[sqlite3.Row, str, str]] = []  # (row, eligibility, date_iso)
    reason_counts: Counter[str] = Counter()

    for row in performance_rows:
        eligibility, date_iso, _parsed = classify_event_row(
            row, now, date_repairs, venue_repairs, venue_redirects
        )
        reason_counts[eligibility] += 1
        if eligibility == "eligible":
            if not norm_text(row["starts_at"]):
                reason_counts["eligible_via_date_repair"] += 1
            if not id_text(row["venue_id"]):
                reason_counts["eligible_via_venue_repair"] += 1
            title_norm = norm_key(row["event_title"])
            raw_venue_id = effective_venue_id(row, venue_repairs)
            venue_id = effective_venue_id(row, venue_repairs, venue_redirects)
            if raw_venue_id != venue_id:
                reason_counts["eligible_via_venue_redirect"] += 1
            groups[(date_iso, city_scope_key(row["city"]), venue_id, title_norm)].append(row)
        else:
            singleton_rows.append((row, eligibility, date_iso))

    # Medium key: rows with a valid, non-suspect date but no resolved venue_id (not even via
    # Phase 2 repair) still often carry a raw venue_name. Two or more independent rows
    # agreeing on (date, city, normalized venue_name, title) is real corroboration, same
    # principle as the strong key -- just without a resolved venue_id backing it.
    medium_groups: dict[tuple[str, str, str, str], list[sqlite3.Row]] = defaultdict(list)
    remaining_singletons: list[tuple[sqlite3.Row, str, str]] = []
    for row, eligibility, date_iso in singleton_rows:
        if eligibility != "missing_venue":
            remaining_singletons.append((row, eligibility, date_iso))
            continue
        venue_name_norm = norm_key(normalize_venue_name(row["venue_name"]))
        if not venue_name_norm:
            remaining_singletons.append((row, eligibility, date_iso))
            continue
        city_norm = norm_key(row["city"])
        title_norm = norm_key(row["event_title"])
        medium_groups[(date_iso, city_norm, venue_name_norm, title_norm)].append(row)

    medium_only_groups: dict[tuple, list[sqlite3.Row]] = {}
    for key, members in medium_groups.items():
        if len(members) > 1:
            medium_only_groups[key] = members
        else:
            remaining_singletons.append((members[0], "missing_venue", key[0]))
    singleton_rows = remaining_singletons

    canonical_events: dict[str, dict[str, Any]] = {}
    event_id_to_canonical: dict[str, str] = {}
    member_rows: list[dict[str, Any]] = []

    def add_members(canonical_id: str, members: list[sqlite3.Row], match_rule: str) -> None:
        ranked = sorted(members, key=lambda r: (-confidence(r["confidence"]), id_text(r["event_id"])))
        for rank, row in enumerate(ranked, start=1):
            event_id_to_canonical[row["event_id"]] = canonical_id
            member_rows.append(
                {
                    "canonical_event_id": canonical_id,
                    "mention_id": row["event_id"],
                    "legacy_event_id": row["event_id"],
                    "source_article_id": id_text(row["source_ref_id"]),
                    "match_rule": match_rule,
                    "match_confidence": confidence(row["confidence"]),
                    "is_primary": 1 if rank == 1 else 0,
                    "provenance_rank": rank,
                }
            )

    for (date_iso, city_key, venue_id, title_norm), members in groups.items():
        canonical_id = stable_id("canonical_event", date_iso, city_key, venue_id, title_norm)
        titles = Counter(norm_text(r["event_title"]) for r in members if norm_text(r["event_title"]))
        venue_names = Counter(norm_text(r["venue_name"]) for r in members if norm_text(r["venue_name"]))
        cities = Counter(norm_text(r["city"]) for r in members if norm_text(r["city"]))
        canonical_events[canonical_id] = {
            "canonical_event_id": canonical_id,
            "event_date": date_iso,
            "start_time": "",
            "venue_id": venue_id,
            "venue_name": venue_names.most_common(1)[0][0] if venue_names else "",
            "city_norm": cities.most_common(1)[0][0] if cities else "",
            "title_norm": title_norm,
            "title_display": titles.most_common(1)[0][0] if titles else "",
            "merge_key_strong": f"{date_iso}|{city_key}|{venue_id}|{title_norm}",
            "confidence": max((confidence(r["confidence"]) for r in members), default=0.0),
            "status": "active",
            "member_count": len(members),
            "created_at": now_iso(),
            "merge_version": SCHEMA_VERSION,
        }
        add_members(canonical_id, members, "strong_key")

    for (date_iso, city_norm, venue_name_norm, title_norm), members in medium_only_groups.items():
        canonical_id = stable_id("canonical_event_medium", date_iso, city_norm, venue_name_norm, title_norm)
        titles = Counter(norm_text(r["event_title"]) for r in members if norm_text(r["event_title"]))
        venue_names = Counter(norm_text(r["venue_name"]) for r in members if norm_text(r["venue_name"]))
        canonical_events[canonical_id] = {
            "canonical_event_id": canonical_id,
            "event_date": date_iso,
            "start_time": "",
            "venue_id": "",
            "venue_name": venue_names.most_common(1)[0][0] if venue_names else "",
            "city_norm": city_norm,
            "title_norm": title_norm,
            "title_display": titles.most_common(1)[0][0] if titles else "",
            "merge_key_strong": "",
            "merge_key_medium": f"{date_iso}|{city_norm}|{venue_name_norm}|{title_norm}",
            "confidence": max((confidence(r["confidence"]) for r in members), default=0.0),
            "status": "active",
            "member_count": len(members),
            "created_at": now_iso(),
            "merge_version": SCHEMA_VERSION,
        }
        add_members(canonical_id, members, "medium_key")

    for row, eligibility, date_iso in singleton_rows:
        canonical_id = stable_id("canonical_event_singleton", row["event_id"])
        parsed_effective = parse_starts_at(effective_starts_at(row, date_repairs))
        canonical_events[canonical_id] = {
            "canonical_event_id": canonical_id,
            "event_date": parsed_effective.date().isoformat() if parsed_effective else "",
            "start_time": "",
            "venue_id": effective_venue_id(row, venue_repairs, venue_redirects),
            "venue_name": norm_text(row["venue_name"]),
            "city_norm": norm_text(row["city"]),
            "title_norm": norm_key(row["event_title"]),
            "title_display": norm_text(row["event_title"]),
            "merge_key_strong": "",
            "confidence": confidence(row["confidence"]),
            "status": "review" if eligibility == "suspect_date" else "active",
            "member_count": 1,
            "created_at": now_iso(),
            "merge_version": SCHEMA_VERSION,
        }
        add_members(canonical_id, [row], f"singleton_{eligibility}")

    reason_counts["medium_key_merged_rows"] = sum(len(m) for m in medium_only_groups.values())
    reason_counts["medium_key_group_count"] = len(medium_only_groups)
    return canonical_events, member_rows, event_id_to_canonical, reason_counts


def build_canonical_dj_events(
    conn: sqlite3.Connection,
    event_id_to_canonical: dict[str, str],
    limit: int,
    dj_redirects: dict[str, str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    # role defaults to "dj": the source dj_event table has no role column, and it already
    # only holds rows the upstream extraction attributed as a DJ appearance. Phase 2/3 can
    # refine this with a real role signal if one becomes available.
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    raw_count = 0
    orphan_count = 0
    redirect_count = 0
    dj_redirects = dj_redirects or {}
    query = "SELECT dj_id, event_id, starts_at, source_ref_id, confidence FROM dj_event"
    if limit:
        query += f" LIMIT {int(limit)}"
    cur = conn.execute(query)
    while True:
        batch = cur.fetchmany(20000)
        if not batch:
            break
        for row in batch:
            raw_count += 1
            raw_dj_id = id_text(row["dj_id"])
            dj_id = dj_redirects.get(raw_dj_id, raw_dj_id)
            redirect_count += int(dj_id != raw_dj_id)
            canonical_id = event_id_to_canonical.get(row["event_id"])
            if canonical_id is None:
                orphan_count += 1
                continue
            key = (dj_id, canonical_id, "dj")
            entry = groups.get(key)
            starts_at = norm_text(row["starts_at"])
            source_ref = id_text(row["source_ref_id"])
            conf = confidence(row["confidence"])
            if entry is None:
                groups[key] = {
                    "dj_id": dj_id,
                    "canonical_event_id": canonical_id,
                    "role": "dj",
                    "role_confidence": conf,
                    "source_refs": {source_ref} if source_ref else set(),
                    "last_seen_at": starts_at,
                }
            else:
                entry["role_confidence"] = max(entry["role_confidence"], conf)
                if source_ref:
                    entry["source_refs"].add(source_ref)
                if starts_at > entry["last_seen_at"]:
                    entry["last_seen_at"] = starts_at

    rows_out = []
    for entry in groups.values():
        source_refs = sorted(entry.pop("source_refs"))
        entry["source_count"] = len(source_refs)
        entry["first_source_article_id"] = source_refs[0] if source_refs else ""
        rows_out.append(entry)

    return rows_out, {
        "raw_dj_event_rows": raw_count,
        "orphan_dj_event_rows": orphan_count,
        "dj_identity_redirect_applied_rows": redirect_count,
    }


WEAK_KEY_CLUSTER_CAP = 30


def apply_weak_key_merges(
    canonical_events: dict[str, dict[str, Any]],
    member_rows: list[dict[str, Any]],
    event_id_to_canonical: dict[str, str],
    merge_decisions_db: Path,
    cluster_cap: int = WEAK_KEY_CLUSTER_CAP,
) -> dict[str, int]:
    """W4: fold APPROVED weak-key merge decisions into the canonical event set.

    Decisions come from adjudicate_weak_key_candidates.py's store; only rows with
    decision='merge' contribute edges (keep_separate / needs_human / pending_llm never do).
    Union-find runs over approved edges only; clusters larger than `cluster_cap` are left
    unmerged in full (anti-snowball). Events with status='review' (suspect dates) never
    participate. The store's pair identity is (event_date, venue_id, title_norms), which is
    stable across runs when unambiguous. If the same legacy venue/date/title appears in
    multiple cities, the city-less legacy decision is skipped rather than applied across cities.
    """
    stats = {
        "approved_pairs_total": 0,
        "approved_pairs_resolved_in_this_run": 0,
        "clusters_merged": 0,
        "events_absorbed": 0,
        "clusters_skipped_over_cap": 0,
        "pairs_skipped_review_status": 0,
        "pairs_skipped_ambiguous_city": 0,
        "pairs_skipped_cross_city": 0,
    }
    if not merge_decisions_db or not merge_decisions_db.exists():
        return stats

    # (event_date, venue_id, title_norm) -> canonical_event_id for mergeable events
    lookup: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for cid, event in canonical_events.items():
        if event["event_date"] and event["venue_id"] and event["status"] == "active":
            lookup[(event["event_date"], event["venue_id"], event["title_norm"])].append(cid)

    dconn = connect_readonly(merge_decisions_db)
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: str, y: str) -> None:
        parent[find(x)] = find(y)

    for row in dconn.execute(
        "SELECT event_date, venue_id, title_norm_a, title_norm_b FROM weak_key_merge_decision WHERE decision = 'merge'"
    ):
        stats["approved_pairs_total"] += 1
        matches_a = lookup.get((row["event_date"], row["venue_id"], row["title_norm_a"]), [])
        matches_b = lookup.get((row["event_date"], row["venue_id"], row["title_norm_b"]), [])
        if len(matches_a) > 1 or len(matches_b) > 1:
            stats["pairs_skipped_ambiguous_city"] += 1
            continue
        cid_a = matches_a[0] if len(matches_a) == 1 else None
        cid_b = matches_b[0] if len(matches_b) == 1 else None
        if cid_a is None or cid_b is None or cid_a == cid_b:
            # endpoint missing here usually means the event carries status='review' or the
            # titles merged already via strong key in this run
            if cid_a is None or cid_b is None:
                stats["pairs_skipped_review_status"] += 1
            continue
        if city_scope_key(canonical_events[cid_a]["city_norm"]) != city_scope_key(
            canonical_events[cid_b]["city_norm"]
        ):
            stats["pairs_skipped_cross_city"] += 1
            continue
        stats["approved_pairs_resolved_in_this_run"] += 1
        union(cid_a, cid_b)
    dconn.close()

    clusters: dict[str, list[str]] = defaultdict(list)
    for cid in list(parent):
        clusters[find(cid)].append(cid)

    remap: dict[str, str] = {}
    for members in clusters.values():
        if len(members) < 2:
            continue
        if len(members) > cluster_cap:
            stats["clusters_skipped_over_cap"] += 1
            continue
        primary = max(
            members,
            key=lambda c: (canonical_events[c]["member_count"], canonical_events[c]["created_at"] == "", c),
        )
        stats["clusters_merged"] += 1
        for cid in members:
            if cid == primary:
                continue
            remap[cid] = primary
            absorbed = canonical_events.pop(cid)
            canonical_events[primary]["member_count"] += absorbed["member_count"]
            canonical_events[primary]["confidence"] = max(
                canonical_events[primary]["confidence"], absorbed["confidence"]
            )
            stats["events_absorbed"] += 1

    if remap:
        for event_id, cid in list(event_id_to_canonical.items()):
            if cid in remap:
                event_id_to_canonical[event_id] = remap[cid]
        for member in member_rows:
            if member["canonical_event_id"] in remap:
                member["canonical_event_id"] = remap[member["canonical_event_id"]]
                member["match_rule"] = f"{member['match_rule']}+weak_key_approved"
                member["is_primary"] = 0

    return stats


def build_weak_key_review_candidates(
    canonical_events: dict[str, dict[str, Any]],
    max_bucket: int,
    similarity_threshold: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Never merges anything. Flags pairs of DISTINCT canonical events that already share
    (event_date, city_norm, venue_id) but have suspiciously similar titles -- a human/future-review
    signal that they might be the same real event under two slightly different titles.
    """
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in canonical_events.values():
        if event["event_date"] and event["venue_id"]:
            buckets[(event["event_date"], event["city_norm"], event["venue_id"])].append(event)

    candidates: list[dict[str, Any]] = []
    skipped_large_buckets = 0
    compared_pairs = 0
    for members in buckets.values():
        if len(members) < 2:
            continue
        if len(members) > max_bucket:
            skipped_large_buckets += 1
            continue
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                a, b = members[i], members[j]
                compared_pairs += 1
                if a["title_norm"] == b["title_norm"]:
                    continue  # already the same title_norm would have strong-key-merged already
                ratio = difflib.SequenceMatcher(None, a["title_norm"], b["title_norm"]).ratio()
                if ratio >= similarity_threshold:
                    candidates.append(
                        {
                            "canonical_event_id_a": a["canonical_event_id"],
                            "canonical_event_id_b": b["canonical_event_id"],
                            "event_date": a["event_date"],
                            "venue_id": a["venue_id"],
                            "title_display_a": a["title_display"],
                            "title_display_b": b["title_display"],
                            "title_similarity": round(ratio, 4),
                            "review_state": "needs_review",
                        }
                    )
    return candidates, {
        "weak_key_review_candidate_count": len(candidates),
        "weak_key_compared_pairs": compared_pairs,
        "weak_key_skipped_large_buckets": skipped_large_buckets,
    }


def write_candidate_db(
    out_db: Path,
    canonical_events: dict[str, dict[str, Any]],
    member_rows: list[dict[str, Any]],
    dj_event_rows: list[dict[str, Any]],
    review_candidates: list[dict[str, Any]],
    metadata: dict[str, str],
) -> None:
    if out_db.exists():
        out_db.unlink()
    out_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(out_db))
    conn.executescript(
        """
        CREATE TABLE canonical_event (
          canonical_event_id TEXT PRIMARY KEY,
          event_date TEXT,
          start_time TEXT,
          venue_id TEXT,
          venue_name TEXT,
          city_norm TEXT,
          title_norm TEXT,
          title_display TEXT,
          merge_key_strong TEXT,
          merge_key_medium TEXT,
          confidence REAL,
          status TEXT,
          member_count INTEGER,
          created_at TEXT,
          merge_version TEXT
        );
        CREATE TABLE canonical_event_member (
          canonical_event_id TEXT,
          mention_id TEXT,
          legacy_event_id TEXT,
          source_article_id TEXT,
          match_rule TEXT,
          match_confidence REAL,
          is_primary INTEGER,
          provenance_rank INTEGER
        );
        CREATE TABLE canonical_dj_event (
          dj_id TEXT,
          canonical_event_id TEXT,
          role TEXT,
          role_confidence REAL,
          source_count INTEGER,
          first_source_article_id TEXT,
          last_seen_at TEXT
        );
        CREATE TABLE canonical_event_merge_review_candidate (
          canonical_event_id_a TEXT,
          canonical_event_id_b TEXT,
          event_date TEXT,
          venue_id TEXT,
          title_display_a TEXT,
          title_display_b TEXT,
          title_similarity REAL,
          review_state TEXT
        );
        CREATE TABLE build_metadata (key TEXT PRIMARY KEY, value TEXT);
        CREATE INDEX idx_cem_event ON canonical_event_member(canonical_event_id);
        CREATE INDEX idx_cem_legacy ON canonical_event_member(legacy_event_id);
        CREATE INDEX idx_cde_dj ON canonical_dj_event(dj_id);
        CREATE INDEX idx_cde_event ON canonical_dj_event(canonical_event_id);
        """
    )
    for event in canonical_events.values():
        event.setdefault("merge_key_medium", "")
    conn.executemany(
        "INSERT INTO canonical_event VALUES (:canonical_event_id,:event_date,:start_time,:venue_id,"
        ":venue_name,:city_norm,:title_norm,:title_display,:merge_key_strong,:merge_key_medium,:confidence,:status,"
        ":member_count,:created_at,:merge_version)",
        canonical_events.values(),
    )
    conn.executemany(
        "INSERT INTO canonical_event_member VALUES (:canonical_event_id,:mention_id,:legacy_event_id,"
        ":source_article_id,:match_rule,:match_confidence,:is_primary,:provenance_rank)",
        member_rows,
    )
    conn.executemany(
        "INSERT INTO canonical_dj_event VALUES (:dj_id,:canonical_event_id,:role,:role_confidence,"
        ":source_count,:first_source_article_id,:last_seen_at)",
        dj_event_rows,
    )
    conn.executemany(
        "INSERT INTO canonical_event_merge_review_candidate VALUES (:canonical_event_id_a,:canonical_event_id_b,"
        ":event_date,:venue_id,:title_display_a,:title_display_b,:title_similarity,:review_state)",
        review_candidates,
    )
    conn.executemany("INSERT INTO build_metadata VALUES (?, ?)", metadata.items())
    conn.commit()
    conn.close()


def build_multi_event_source_refs(
    member_rows: list[dict[str, Any]],
    canonical_events: dict[str, dict[str, Any]],
    conn: sqlite3.Connection,
    sample_size: int,
) -> dict[str, Any]:
    by_source: dict[str, set[str]] = defaultdict(set)
    for member in member_rows:
        source_ref = member["source_article_id"]
        if source_ref:
            by_source[source_ref].add(member["canonical_event_id"])
    multi = {src: sorted(ids) for src, ids in by_source.items() if len(ids) > 1}

    sample = []
    for source_ref in list(multi.keys())[:sample_size]:
        evidence = conn.execute(
            "SELECT source_title, source_account, post_date FROM evidence_ref WHERE source_ref_id = ?",
            (source_ref,),
        ).fetchone()
        sample.append(
            {
                "source_ref_id": source_ref,
                "source_title": evidence["source_title"] if evidence else "",
                "source_account": evidence["source_account"] if evidence else "",
                "post_date": evidence["post_date"] if evidence else "",
                "canonical_events": [
                    {
                        "canonical_event_id": cid,
                        "event_date": canonical_events[cid]["event_date"],
                        "venue_name": canonical_events[cid]["venue_name"],
                        "title_display": canonical_events[cid]["title_display"],
                    }
                    for cid in multi[source_ref]
                ],
            }
        )
    return {"count": len(multi), "sample": sample}


def build_dj_profile_recount(
    conn: sqlite3.Connection,
    dj_event_rows: list[dict[str, Any]],
    limit: int,
    top_n: int,
    dj_redirects: dict[str, str] | None = None,
) -> dict[str, Any]:
    raw_counts: Counter[str] = Counter()
    dj_redirects = dj_redirects or {}
    query = "SELECT dj_id FROM dj_event"
    if limit:
        query += f" LIMIT {int(limit)}"
    for row in conn.execute(query):
        raw_dj_id = id_text(row["dj_id"])
        raw_counts[dj_redirects.get(raw_dj_id, raw_dj_id)] += 1

    canonical_counts: Counter[str] = Counter(r["dj_id"] for r in dj_event_rows)
    dj_ids = set(raw_counts) | set(canonical_counts)
    names = {}
    has_dj_profile = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dj_profile'"
    ).fetchone()
    if dj_ids and has_dj_profile:
        for chunk_start in range(0, len(dj_ids), 400):
            chunk = list(dj_ids)[chunk_start : chunk_start + 400]
            placeholders = ",".join("?" for _ in chunk)
            for row in conn.execute(f"SELECT dj_id, display_name FROM dj_profile WHERE dj_id IN ({placeholders})", chunk):
                names[row["dj_id"]] = row["display_name"]

    deltas = []
    for dj_id in dj_ids:
        raw = raw_counts.get(dj_id, 0)
        canon = canonical_counts.get(dj_id, 0)
        deltas.append(
            {
                "dj_id": dj_id,
                "display_name": names.get(dj_id, ""),
                "raw_event_count": raw,
                "canonical_event_count": canon,
                "delta": raw - canon,
            }
        )
    deltas.sort(key=lambda d: -d["delta"])
    return {
        "dj_count": len(dj_ids),
        "top_inflated_djs": deltas[:top_n],
    }


def build_report(
    source_db: Path,
    source_generated_at: str | None,
    performance_rows: list[sqlite3.Row],
    canonical_events: dict[str, dict[str, Any]],
    member_rows: list[dict[str, Any]],
    dj_event_rows: list[dict[str, Any]],
    dj_event_counts: dict[str, int],
    reason_counts: Counter[str],
    conn: sqlite3.Connection,
    top_groups: int,
    sample_multi_event: int,
    repair_db_used: str | None,
    review_candidates: list[dict[str, Any]],
    weak_key_counts: dict[str, int],
    limit_events: int = 0,
    dj_redirects: dict[str, str] | None = None,
) -> dict[str, Any]:
    raw_pe = len(performance_rows)
    canonical_count = len(canonical_events)
    merge_groups = [e for e in canonical_events.values() if e["member_count"] > 1]
    strong_merge_groups = [e for e in merge_groups if e.get("merge_key_strong")]
    medium_merge_groups = [e for e in merge_groups if e.get("merge_key_medium")]
    top = sorted(merge_groups, key=lambda e: -e["member_count"])[:top_groups]
    top_report = []
    for group in top:
        source_refs = sorted(
            {m["source_article_id"] for m in member_rows if m["canonical_event_id"] == group["canonical_event_id"] and m["source_article_id"]}
        )[:10]
        top_report.append(
            {
                "canonical_event_id": group["canonical_event_id"],
                "member_count": group["member_count"],
                "event_date": group["event_date"],
                "venue_id": group["venue_id"],
                "venue_name": group["venue_name"],
                "title_display": group["title_display"],
                "sample_source_ref_ids": source_refs,
            }
        )

    raw_dj = dj_event_counts["raw_dj_event_rows"]
    canonical_dj = len(dj_event_rows)
    pe_ratio = round(raw_pe / canonical_count, 4) if canonical_count else None
    dj_ratio = round(raw_dj / canonical_dj, 4) if canonical_dj else None

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "source_serving_db": str(source_db),
        "source_generated_at": source_generated_at,
        "repair_db_used": repair_db_used,
        "boundaries": {
            "source_opened_read_only": True,
            "source_db_mutated": False,
            "sanji_touched": False,
            "hermes_touched": False,
            "network_call_executed": False,
            "llm_call_executed": False,
        },
        "counts": {
            "raw_performance_event_rows": raw_pe,
            "eligible_for_strong_merge_rows": reason_counts["eligible"],
            "eligible_via_date_repair": reason_counts["eligible_via_date_repair"],
            "eligible_via_venue_repair": reason_counts["eligible_via_venue_repair"],
            "singleton_missing_date_rows": reason_counts["missing_date"],
            "singleton_missing_venue_rows": reason_counts["missing_venue"],
            "singleton_suspect_date_rows": reason_counts["suspect_date"],
            "canonical_event_count": canonical_count,
            "canonical_event_count_from_merge_groups": len(merge_groups),
            "canonical_event_count_from_strong_key": len(strong_merge_groups),
            "canonical_event_count_from_medium_key": len(medium_merge_groups),
            "medium_key_merged_rows": reason_counts["medium_key_merged_rows"],
            "canonical_event_count_singleton": canonical_count - len(merge_groups),
            "performance_event_inflation_ratio": pe_ratio,
            "raw_dj_event_rows": raw_dj,
            "orphan_dj_event_rows": dj_event_counts["orphan_dj_event_rows"],
            "dj_identity_redirect_applied_rows": dj_event_counts.get(
                "dj_identity_redirect_applied_rows", 0
            ),
            "venue_identity_redirect_applied_rows": reason_counts[
                "eligible_via_venue_redirect"
            ],
            "canonical_dj_event_count": canonical_dj,
            "dj_event_inflation_ratio": dj_ratio,
        },
        # Gate semantics revised per ATLAS_V2_WEAK_KEY_AND_COUNT_CONVERGENCE_PLAN_2026-07-08 §6:
        # the raw/canonical inflation threshold was measured to move the WRONG way as dedup
        # improves (evidence rows are kept by design while the canonical denominator shrinks),
        # so it is reported as information only and no longer passes/fails anything.
        "gate": {
            "suspect_quarantine_gate_pass": not any(
                e["status"] == "review" and e["member_count"] > 1 for e in canonical_events.values()
            ),
            "date_suspect_rows_excluded_from_strong_merge": reason_counts["suspect_date"],
            "inflation_ratios_informational": {"performance_event": pe_ratio, "dj_event": dj_ratio},
        },
        "top_collapsed_groups": top_report,
        "multi_event_source_refs": build_multi_event_source_refs(member_rows, canonical_events, conn, sample_multi_event),
        "dj_profile_recount": build_dj_profile_recount(
            conn, dj_event_rows, limit_events, 20, dj_redirects
        ),
        "weak_key_review": {**weak_key_counts, "sample": review_candidates[:20]},
    }


def assert_output_boundaries(source_db: Path, out_db: Path) -> None:
    if source_db.resolve() == out_db.resolve():
        raise SystemExit("refusing to run: --out candidate db path equals the source serving DB path")
    out_str = str(out_db.resolve()).lower()
    for marker in FORBIDDEN_OUTPUT_MARKERS:
        if marker in out_str:
            raise SystemExit(f"refusing to run: output path looks like a Sanji/Hermes path ({marker})")


def run(
    source_db: Path,
    out_dir: Path,
    limit_events: int,
    top_groups: int,
    sample_multi_event: int,
    repair_db: Path | None = None,
    weak_title_similarity: float = 0.85,
    weak_key_max_bucket: int = 200,
    merge_decisions_db: Path | None = None,
    identity_db: Path | None = None,
    venue_redirect_db: Path | None = None,
) -> dict[str, Any]:
    out_db = out_dir / "canonical_event_candidates.sqlite"
    report_path = out_dir / "collapse_report.json"
    assert_output_boundaries(source_db, out_db)

    conn = connect_readonly(source_db)
    source_meta = conn.execute("SELECT value FROM build_metadata WHERE key = 'generated_at'").fetchone()
    source_generated_at = source_meta["value"] if source_meta else None

    date_repairs, venue_repairs = load_repair_candidates(repair_db)
    dj_redirects = load_dj_redirects(identity_db)
    venue_redirects = load_venue_redirects(venue_redirect_db)

    query = "SELECT event_id, event_title, starts_at, venue_id, venue_name, city, source_ref_id, confidence FROM performance_event"
    if limit_events:
        query += f" LIMIT {int(limit_events)}"
    performance_rows = conn.execute(query).fetchall()

    now = datetime.now()
    canonical_events, member_rows, event_id_to_canonical, reason_counts = build_canonical_events(
        performance_rows, now, date_repairs, venue_repairs, venue_redirects
    )
    weak_key_application = apply_weak_key_merges(
        canonical_events, member_rows, event_id_to_canonical, merge_decisions_db
    ) if merge_decisions_db else {}
    dj_event_rows, dj_event_counts = build_canonical_dj_events(
        conn, event_id_to_canonical, limit_events, dj_redirects
    )
    review_candidates, weak_key_counts = build_weak_key_review_candidates(
        canonical_events, weak_key_max_bucket, weak_title_similarity
    )

    report = build_report(
        source_db,
        source_generated_at,
        performance_rows,
        canonical_events,
        member_rows,
        dj_event_rows,
        dj_event_counts,
        reason_counts,
        conn,
        top_groups,
        sample_multi_event,
        str(repair_db) if repair_db else None,
        review_candidates,
        weak_key_counts,
        limit_events,
        dj_redirects,
    )
    report["weak_key_application"] = weak_key_application
    report["identity_db_used"] = str(identity_db) if identity_db else None
    report["venue_redirect_db_used"] = str(venue_redirect_db) if venue_redirect_db else None

    # weak_key_block gate: no keep_separate decision may end up with both titles inside the
    # same canonical event (plan 2026-07-08 §6 indicator 3)
    if merge_decisions_db and merge_decisions_db.exists():
        post_lookup: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        for cid, event in canonical_events.items():
            post_lookup[(event["event_date"], event["venue_id"], event["title_norm"])].append(cid)
        block_violations = 0
        dconn = connect_readonly(merge_decisions_db)
        for row in dconn.execute(
            "SELECT event_date, venue_id, title_norm_a, title_norm_b FROM weak_key_merge_decision "
            "WHERE decision = 'keep_separate'"
        ):
            matches_a = post_lookup.get(
                (row["event_date"], row["venue_id"], row["title_norm_a"]), []
            )
            matches_b = post_lookup.get(
                (row["event_date"], row["venue_id"], row["title_norm_b"]), []
            )
            cid_a = matches_a[0] if len(matches_a) == 1 else None
            cid_b = matches_b[0] if len(matches_b) == 1 else None
            if cid_a is not None and cid_a == cid_b:
                block_violations += 1
        dconn.close()
        report["gate"]["weak_key_block_gate_pass"] = block_violations == 0
        report["gate"]["weak_key_block_violations"] = block_violations

    write_candidate_db(
        out_db,
        canonical_events,
        member_rows,
        dj_event_rows,
        review_candidates,
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": report["generated_at"],
            "source_serving_db": str(source_db),
            "source_generated_at": source_generated_at or "",
            "identity_db": str(identity_db) if identity_db else "",
            "venue_redirect_db": str(venue_redirect_db) if venue_redirect_db else "",
        },
    )
    write_json(report_path, report)
    conn.close()
    return report


def _self_check() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source_db = tmp_path / "fixture_serving.sqlite"
        conn = sqlite3.connect(str(source_db))
        conn.executescript(
            """
            CREATE TABLE performance_event (
              event_id TEXT, event_title TEXT, starts_at TEXT, time_text TEXT,
              venue_id TEXT, venue_name TEXT, city TEXT, source_ref_id TEXT,
              participant_count INTEGER, organizer_count INTEGER, confidence REAL
            );
            CREATE TABLE dj_event (
              dj_id TEXT, event_id TEXT, starts_at TEXT, time_text TEXT, event_title TEXT,
              venue_id TEXT, venue_name TEXT, city TEXT, source_ref_id TEXT, confidence REAL
            );
            CREATE TABLE evidence_ref (
              source_ref_id TEXT, source_hash TEXT, source_account TEXT, source_title TEXT,
              post_date TEXT, public_snippet TEXT, source_kind TEXT, public_url_allowed INTEGER
            );
            CREATE TABLE build_metadata (key TEXT, value TEXT);
            """
        )
        conn.executemany(
            "INSERT INTO performance_event VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                # evt1 + evt2: same real party, reposted by two different articles -> must collapse
                ("evt1", "Party A", "2026-06-05", "22:00", "venue1", "Venue One", "Shanghai", "src1", 3, 1, 0.9),
                ("evt2", "Party A", "2026-06-05", "22:00", "venue1", "Venue One", "Shanghai", "src2", 3, 1, 0.85),
                # evt3: a *different* party, but reported in the SAME article as evt2 (src2) ->
                # must NOT collapse into evt2's group just because they share a source_ref
                ("evt3", "Party B", "2026-06-05", "23:00", "venue1", "Venue One", "Shanghai", "src2", 2, 0, 0.8),
                # evt4 + evt5: identical (date, venue, title) but the date is a sentinel/garbage
                # value far in the future -> must NOT collapse despite matching the strong key
                ("evt4", "Mystery Fest", "2046-12-25", "20:00", "venue2", "Venue Two", "Beijing", "src3", 5, 1, 0.7),
                ("evt5", "Mystery Fest", "2046-12-25", "20:00", "venue2", "Venue Two", "Beijing", "src4", 5, 1, 0.75),
                # evt6: missing date -> singleton passthrough
                ("evt6", "No Date Show", "", "", "venue3", "Venue Three", "Guangzhou", "src5", 1, 0, 0.6),
                # evt7: missing venue -> singleton passthrough
                ("evt7", "No Venue Show", "2026-06-10", "21:00", "", "", "Chengdu", "src6", 1, 0, 0.6),
            ],
        )
        conn.executemany(
            "INSERT INTO dj_event VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                ("dj_alice", "evt1", "2026-06-05", "22:00", "Party A", "venue1", "Venue One", "Shanghai", "src1", 0.9),
                ("dj_alice", "evt2", "2026-06-05", "22:00", "Party A", "venue1", "Venue One", "Shanghai", "src2", 0.85),
                ("dj_bob", "evt3", "2026-06-05", "23:00", "Party B", "venue1", "Venue One", "Shanghai", "src2", 0.8),
            ],
        )
        conn.executemany(
            "INSERT INTO evidence_ref VALUES (?,?,?,?,?,?,?,?)",
            [
                ("src1", "h1", "acct1", "Party A tonight", "2026-06-05", "", "article", 0),
                ("src2", "h2", "acct2", "Weekend roundup: Party A + Party B", "2026-06-04", "", "article", 0),
                ("src3", "h3", "acct3", "Mystery Fest", "2026-06-01", "", "article", 0),
                ("src4", "h4", "acct4", "Mystery Fest repost", "2026-06-02", "", "article", 0),
                ("src5", "h5", "acct5", "No Date Show", "2026-06-01", "", "article", 0),
                ("src6", "h6", "acct6", "No Venue Show", "2026-06-01", "", "article", 0),
            ],
        )
        conn.executemany(
            "INSERT INTO build_metadata VALUES (?, ?)",
            [("schema_version", "atlas_serving_read_model.v1"), ("generated_at", "2026-06-05T00:00:00")],
        )
        conn.commit()
        conn.close()

        out_dir = tmp_path / "candidate"
        report = run(source_db, out_dir, limit_events=0, top_groups=20, sample_multi_event=10)

        assert report["counts"]["raw_performance_event_rows"] == 7, report["counts"]
        assert report["counts"]["canonical_event_count"] == 6, report["counts"]
        assert report["counts"]["singleton_suspect_date_rows"] == 2, report["counts"]
        assert report["counts"]["singleton_missing_date_rows"] == 1, report["counts"]
        assert report["counts"]["singleton_missing_venue_rows"] == 1, report["counts"]

        candidate_db = sqlite3.connect(str(out_dir / "canonical_event_candidates.sqlite"))
        candidate_db.row_factory = sqlite3.Row
        member_by_legacy = {
            r["legacy_event_id"]: r["canonical_event_id"]
            for r in candidate_db.execute("SELECT legacy_event_id, canonical_event_id FROM canonical_event_member")
        }
        assert member_by_legacy["evt1"] == member_by_legacy["evt2"], "evt1/evt2 should collapse to one canonical event"
        assert member_by_legacy["evt3"] != member_by_legacy["evt2"], "evt3 must not merge just because it shares a source_ref with evt2"
        assert member_by_legacy["evt4"] != member_by_legacy["evt5"], "suspect-date rows must not merge even with a matching key"

        dj_rows = candidate_db.execute(
            "SELECT dj_id, canonical_event_id, source_count FROM canonical_dj_event WHERE dj_id = 'dj_alice'"
        ).fetchall()
        assert len(dj_rows) == 1, "dj_alice's two mentions of the same collapsed event must be one canonical_dj_event row"
        assert dj_rows[0]["source_count"] == 2

        multi = report["multi_event_source_refs"]
        assert multi["count"] == 1, multi
        assert multi["sample"][0]["source_ref_id"] == "src2"
        assert len(multi["sample"][0]["canonical_events"]) == 2

        candidate_db.close()

        # --- Phase 3 addition: --repair-db should let previously-singleton rows (evt6
        # missing date, evt7 missing venue) join a strong-key group once repaired ---
        repair_db = tmp_path / "fixture_repair.sqlite"
        rconn = sqlite3.connect(str(repair_db))
        rconn.executescript(
            """
            CREATE TABLE date_repair_candidate (
              event_id TEXT, candidate_date TEXT, candidate_end_date TEXT, date_kind TEXT,
              anchor_published_at TEXT, anchor_source TEXT, source_field TEXT, confidence REAL,
              reason_code TEXT, review_state TEXT
            );
            CREATE TABLE venue_repair_candidate (
              event_id TEXT, candidate_venue_id TEXT, venue_name_norm TEXT, city_norm TEXT,
              confidence REAL, match_kind TEXT, review_state TEXT
            );
            """
        )
        rconn.execute(
            # evt6's repaired date matches evt1/evt2's group exactly (same venue1 + "party a"
            # title_norm) -> once repaired it must join that SAME canonical event, not just
            # become its own new singleton.
            "INSERT INTO date_repair_candidate VALUES ('evt6','2026-06-05','','exact','','sanji_publish_time_recovered','time_text',0.95,'exact_date_parsed','auto_accepted')"
        )
        rconn.execute(
            "INSERT INTO venue_repair_candidate VALUES ('evt7','venue1','venue three','Chengdu',0.90,'unique_name',?)",
            ("needs_review",),  # ambiguous/low-confidence repair must NOT be used
        )
        rconn.commit()
        rconn.close()
        conn2 = sqlite3.connect(str(source_db))
        # evt6 already has its own (non-empty) venue3/"No Date Show" — only its date was
        # missing. Retarget title+venue to exactly match evt1/evt2's group so the repaired
        # date is the ONLY thing standing between it and joining that existing group.
        conn2.execute(
            "UPDATE performance_event SET event_title='Party A', venue_id='venue1', venue_name='Venue One', "
            "city='Shanghai' WHERE event_id='evt6'"
        )
        conn2.commit()
        conn2.close()

        repair_out_dir = tmp_path / "candidate_repaired"
        repaired_report = run(source_db, repair_out_dir, limit_events=0, top_groups=20, sample_multi_event=10, repair_db=repair_db)
        assert repaired_report["counts"]["eligible_via_date_repair"] == 1, repaired_report["counts"]
        assert repaired_report["counts"]["eligible_via_venue_repair"] == 0, "needs_review venue repair must not be used"
        assert repaired_report["counts"]["singleton_missing_venue_rows"] == 1, "evt7 stays a singleton: its only repair candidate is needs_review"

        repaired_db = sqlite3.connect(str(repair_out_dir / "canonical_event_candidates.sqlite"))
        repaired_db.row_factory = sqlite3.Row
        repaired_member_by_legacy = {
            r["legacy_event_id"]: r["canonical_event_id"]
            for r in repaired_db.execute("SELECT legacy_event_id, canonical_event_id FROM canonical_event_member")
        }
        repaired_db.close()
        assert repaired_member_by_legacy["evt6"] == repaired_member_by_legacy["evt1"], "repaired date must join the existing evt1/evt2 group, not a new one"

        # --- isolated fixture for medium-key auto-merge and weak-key review-only flagging ---
        mk_db = tmp_path / "fixture_medium_weak.sqlite"
        mconn2 = sqlite3.connect(str(mk_db))
        mconn2.executescript(
            """
            CREATE TABLE performance_event (
              event_id TEXT, event_title TEXT, starts_at TEXT, time_text TEXT,
              venue_id TEXT, venue_name TEXT, city TEXT, source_ref_id TEXT,
              participant_count INTEGER, organizer_count INTEGER, confidence REAL
            );
            CREATE TABLE dj_event (
              dj_id TEXT, event_id TEXT, starts_at TEXT, time_text TEXT, event_title TEXT,
              venue_id TEXT, venue_name TEXT, city TEXT, source_ref_id TEXT, confidence REAL
            );
            CREATE TABLE evidence_ref (
              source_ref_id TEXT, source_hash TEXT, source_account TEXT, source_title TEXT,
              post_date TEXT, public_snippet TEXT, source_kind TEXT, public_url_allowed INTEGER
            );
            CREATE TABLE build_metadata (key TEXT, value TEXT);
            """
        )
        mconn2.executemany(
            "INSERT INTO performance_event VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                # medA + medB: no venue_id at all, but two INDEPENDENT articles agree on the
                # same date+city+venue_name+title -> must auto-merge via medium key.
                ("medA", "Warehouse Night", "2026-08-01", "", "", "The Warehouse", "Chengdu", "srcMedA", 1, 0, 0.8),
                ("medB", "Warehouse Night", "2026-08-01", "", "", "The Warehouse", "Chengdu", "srcMedB", 1, 0, 0.8),
                # medC: same date+city+venue_name but a DIFFERENT title -> must NOT join medA/medB
                ("medC", "Rooftop Session", "2026-08-01", "", "", "The Warehouse", "Chengdu", "srcMedC", 1, 0, 0.8),
                # weakA/weakB: both have a real resolved venue_id (so each is its own strong-key
                # singleton canonical event), same date+venue, near-duplicate titles -> must be
                # flagged as a weak-key REVIEW candidate, but stay two DISTINCT canonical events.
                ("weakA", "Techno Night Vol 3", "2026-08-05", "", "venueW", "Venue W", "Beijing", "srcWeakA", 1, 0, 0.8),
                ("weakB", "Techno Night Vol. 3", "2026-08-05", "", "venueW", "Venue W", "Beijing", "srcWeakB", 1, 0, 0.8),
            ],
        )
        mconn2.executemany(
            "INSERT INTO evidence_ref VALUES (?,?,?,?,?,?,?,?)",
            [
                ("srcMedA", "h", "acct", "Warehouse Night", "2026-07-30", "", "article", 0),
                ("srcMedB", "h", "acct", "Warehouse Night repost", "2026-07-31", "", "article", 0),
                ("srcMedC", "h", "acct", "Rooftop Session", "2026-07-30", "", "article", 0),
                ("srcWeakA", "h", "acct", "Techno Night Vol 3", "2026-08-01", "", "article", 0),
                ("srcWeakB", "h", "acct", "Techno Night Vol. 3", "2026-08-02", "", "article", 0),
            ],
        )
        mconn2.executemany(
            "INSERT INTO build_metadata VALUES (?, ?)",
            [("schema_version", "atlas_serving_read_model.v1"), ("generated_at", "2026-08-01T00:00:00")],
        )
        mconn2.commit()
        mconn2.close()

        mk_out_dir = tmp_path / "candidate_medium_weak"
        mk_report = run(mk_db, mk_out_dir, limit_events=0, top_groups=20, sample_multi_event=10)

        assert mk_report["counts"]["medium_key_merged_rows"] == 2, mk_report["counts"]
        assert mk_report["counts"]["canonical_event_count_from_medium_key"] == 1, mk_report["counts"]

        mk_candidate_db = sqlite3.connect(str(mk_out_dir / "canonical_event_candidates.sqlite"))
        mk_candidate_db.row_factory = sqlite3.Row
        mk_member_by_legacy = {
            r["legacy_event_id"]: r["canonical_event_id"]
            for r in mk_candidate_db.execute("SELECT legacy_event_id, canonical_event_id FROM canonical_event_member")
        }
        assert mk_member_by_legacy["medA"] == mk_member_by_legacy["medB"], "medA/medB must merge via medium key"
        assert mk_member_by_legacy["medC"] != mk_member_by_legacy["medA"], "medC has a different title -> must not join the medium-key group"
        assert mk_member_by_legacy["weakA"] != mk_member_by_legacy["weakB"], "weak-key matches must NEVER be auto-merged"

        review_rows = mk_candidate_db.execute("SELECT * FROM canonical_event_merge_review_candidate").fetchall()
        mk_candidate_db.close()
        review_pairs = {(r["canonical_event_id_a"], r["canonical_event_id_b"]) for r in review_rows}
        weak_ids = {mk_member_by_legacy["weakA"], mk_member_by_legacy["weakB"]}
        assert any(set(pair) == weak_ids for pair in review_pairs), "weakA/weakB must appear as a weak-key review candidate"

        # --- W4 fixture: applying approved weak-key merge decisions ---
        wk_db = tmp_path / "fixture_weak_apply.sqlite"
        wconn = sqlite3.connect(str(wk_db))
        wconn.executescript(
            """
            CREATE TABLE performance_event (
              event_id TEXT, event_title TEXT, starts_at TEXT, time_text TEXT,
              venue_id TEXT, venue_name TEXT, city TEXT, source_ref_id TEXT,
              participant_count INTEGER, organizer_count INTEGER, confidence REAL
            );
            CREATE TABLE dj_event (
              dj_id TEXT, event_id TEXT, starts_at TEXT, time_text TEXT, event_title TEXT,
              venue_id TEXT, venue_name TEXT, city TEXT, source_ref_id TEXT, confidence REAL
            );
            CREATE TABLE evidence_ref (
              source_ref_id TEXT, source_hash TEXT, source_account TEXT, source_title TEXT,
              post_date TEXT, public_snippet TEXT, source_kind TEXT, public_url_allowed INTEGER
            );
            CREATE TABLE build_metadata (key TEXT, value TEXT);
            """
        )
        wconn.executemany(
            "INSERT INTO performance_event VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                # wkA/wkB: approved merge pair (same date+venue, title variants)
                ("wkA", "Techno Night Vol 3", "2026-09-01", "", "vW", "Venue W", "BJ", "sA", 1, 0, 0.9),
                ("wkB", "Techno Night Vol.3 感谢", "2026-09-01", "", "vW", "Venue W", "BJ", "sB", 1, 0, 0.8),
                # wkC: pair with wkA exists in candidates but decision=keep_separate -> must NOT merge
                ("wkC", "Techno Day Vol 3", "2026-09-01", "", "vW", "Venue W", "BJ", "sC", 1, 0, 0.8),
                # wkD: no decision at all -> must NOT merge
                ("wkD", "Techno Nite Vol 3", "2026-09-01", "", "vW", "Venue W", "BJ", "sD", 1, 0, 0.8),
            ],
        )
        wconn.executemany(
            "INSERT INTO dj_event VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                ("dj_w", "wkA", "2026-09-01", "", "Techno Night Vol 3", "vW", "Venue W", "BJ", "sA", 0.9),
                ("dj_w", "wkB", "2026-09-01", "", "Techno Night Vol.3 感谢", "vW", "Venue W", "BJ", "sB", 0.8),
            ],
        )
        wconn.executemany(
            "INSERT INTO build_metadata VALUES (?, ?)",
            [("schema_version", "atlas_serving_read_model.v1"), ("generated_at", "2026-09-01T00:00:00")],
        )
        wconn.commit()
        wconn.close()

        decisions_db = tmp_path / "fixture_decisions.sqlite"
        dconn = sqlite3.connect(str(decisions_db))
        dconn.executescript(
            """
            CREATE TABLE weak_key_merge_decision (
              pair_key TEXT PRIMARY KEY, event_date TEXT, venue_id TEXT,
              title_norm_a TEXT, title_norm_b TEXT, title_display_a TEXT, title_display_b TEXT,
              title_similarity REAL, tier TEXT, decision TEXT, method TEXT, confidence REAL,
              reason TEXT, llm_verdict_raw TEXT, decided_at TEXT
            );
            """
        )
        tn = norm_key  # alias
        dconn.execute(
            "INSERT INTO weak_key_merge_decision VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("k1", "2026-09-01", "vW", tn("Techno Night Vol 3"), tn("Techno Night Vol.3 感谢"),
             "Techno Night Vol 3", "Techno Night Vol.3 感谢", 0.9, "c_high_sim", "merge", "llm", 0.85, "", "same", ""),
        )
        dconn.execute(
            "INSERT INTO weak_key_merge_decision VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("k2", "2026-09-01", "vW", tn("Techno Night Vol 3"), tn("Techno Day Vol 3"),
             "Techno Night Vol 3", "Techno Day Vol 3", 0.9, "c_high_sim", "keep_separate", "llm", 0.85, "", "diff", ""),
        )
        dconn.commit()
        dconn.close()

        wk_out = tmp_path / "candidate_weak_apply"
        wk_report = run(wk_db, wk_out, limit_events=0, top_groups=20, sample_multi_event=10, merge_decisions_db=decisions_db)
        app = wk_report["weak_key_application"]
        assert app["approved_pairs_resolved_in_this_run"] == 1, app
        assert app["clusters_merged"] == 1 and app["events_absorbed"] == 1, app

        wdb = sqlite3.connect(str(wk_out / "canonical_event_candidates.sqlite"))
        wdb.row_factory = sqlite3.Row
        wk_map = {
            r["legacy_event_id"]: r["canonical_event_id"]
            for r in wdb.execute("SELECT legacy_event_id, canonical_event_id FROM canonical_event_member")
        }
        assert wk_map["wkA"] == wk_map["wkB"], "approved pair must merge"
        assert wk_map["wkC"] != wk_map["wkA"], "keep_separate decision must never merge"
        assert wk_map["wkD"] != wk_map["wkA"], "undecided candidate must never merge"
        dj_w = wdb.execute("SELECT COUNT(*) FROM canonical_dj_event WHERE dj_id='dj_w'").fetchone()[0]
        assert dj_w == 1, "dj rows across a weak-key-merged pair must collapse to one canonical_dj_event"
        wdb.close()

        # over-cap cluster: chain 40 approved pairs -> cluster of 41 > cap 30 -> nothing merges
        big_decisions = tmp_path / "fixture_decisions_big.sqlite"
        bconn = sqlite3.connect(str(big_decisions))
        bconn.executescript(
            """
            CREATE TABLE weak_key_merge_decision (
              pair_key TEXT PRIMARY KEY, event_date TEXT, venue_id TEXT,
              title_norm_a TEXT, title_norm_b TEXT, title_display_a TEXT, title_display_b TEXT,
              title_similarity REAL, tier TEXT, decision TEXT, method TEXT, confidence REAL,
              reason TEXT, llm_verdict_raw TEXT, decided_at TEXT
            );
            """
        )
        chain_db = tmp_path / "fixture_chain.sqlite"
        cconn2 = sqlite3.connect(str(chain_db))
        cconn2.executescript(
            """
            CREATE TABLE performance_event (
              event_id TEXT, event_title TEXT, starts_at TEXT, time_text TEXT,
              venue_id TEXT, venue_name TEXT, city TEXT, source_ref_id TEXT,
              participant_count INTEGER, organizer_count INTEGER, confidence REAL
            );
            CREATE TABLE dj_event (
              dj_id TEXT, event_id TEXT, starts_at TEXT, time_text TEXT, event_title TEXT,
              venue_id TEXT, venue_name TEXT, city TEXT, source_ref_id TEXT, confidence REAL
            );
            CREATE TABLE evidence_ref (
              source_ref_id TEXT, source_hash TEXT, source_account TEXT, source_title TEXT,
              post_date TEXT, public_snippet TEXT, source_kind TEXT, public_url_allowed INTEGER
            );
            CREATE TABLE build_metadata (key TEXT, value TEXT);
            """
        )
        for i in range(41):
            cconn2.execute(
                "INSERT INTO performance_event VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (f"ch{i}", f"Chain Party {i}", "2026-09-02", "", "vC", "Venue C", "BJ", f"s{i}", 1, 0, 0.9),
            )
            if i > 0:
                bconn.execute(
                    "INSERT INTO weak_key_merge_decision VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"ck{i}", "2026-09-02", "vC", norm_key(f"Chain Party {i-1}"), norm_key(f"Chain Party {i}"),
                     f"Chain Party {i-1}", f"Chain Party {i}", 0.9, "c_high_sim", "merge", "llm", 0.85, "", "same", ""),
                )
        cconn2.execute("INSERT INTO build_metadata VALUES ('generated_at', '2026-09-02T00:00:00')")
        cconn2.commit(); cconn2.close()
        bconn.commit(); bconn.close()

        chain_out = tmp_path / "candidate_chain"
        chain_report = run(chain_db, chain_out, limit_events=0, top_groups=20, sample_multi_event=10, merge_decisions_db=big_decisions)
        capp = chain_report["weak_key_application"]
        assert capp["clusters_skipped_over_cap"] == 1, capp
        assert capp["events_absorbed"] == 0, "over-cap cluster must merge nothing"

        print(
            "self-check OK: canonical-event collapse, multi-event-article safety, suspect-date quarantine, "
            "repair-db-driven merge expansion, medium-key auto-merge, weak-key review-only flagging, "
            "approved-merge application, keep-separate/undecided isolation, and over-cap cluster skip all verified"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-serving-db", type=Path, default=DEFAULT_SOURCE_DB)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--limit-events", type=int, default=0, help="0 = all performance_event rows")
    ap.add_argument("--top-groups", type=int, default=20)
    ap.add_argument("--sample-multi-event", type=int, default=10)
    ap.add_argument(
        "--repair-db",
        type=Path,
        default=None,
        help="Phase 2 output (date_venue_repair_candidates.sqlite); omit for pure Phase 1 behavior",
    )
    ap.add_argument("--weak-title-similarity", type=float, default=0.85)
    ap.add_argument("--weak-key-max-bucket", type=int, default=200)
    ap.add_argument(
        "--merge-decisions-db",
        type=Path,
        default=None,
        help="weak-key decision store (adjudicate_weak_key_candidates.py); only decision='merge' rows are applied",
    )
    ap.add_argument(
        "--identity-db",
        type=Path,
        default=None,
        help="DJ identity redirect sidecar from build_serving_identity_redirects.py",
    )
    ap.add_argument(
        "--venue-redirect-db",
        type=Path,
        default=None,
        help="city-scoped venue redirect sidecar from build_serving_venue_redirects.py",
    )
    ap.add_argument("--self-check", action="store_true")
    args = ap.parse_args()

    if args.self_check:
        _self_check()
        return 0

    if not args.source_serving_db.exists():
        raise SystemExit(f"source serving DB not found: {args.source_serving_db}")

    out_dir = args.out_dir or (
        REPO_ROOT / "reports" / f"atlas_canonical_event_candidates_{datetime.now():%Y%m%d_%H%M%S}"
    )
    report = run(
        args.source_serving_db,
        out_dir,
        args.limit_events,
        args.top_groups,
        args.sample_multi_event,
        args.repair_db,
        args.weak_title_similarity,
        args.weak_key_max_bucket,
        args.merge_decisions_db,
        args.identity_db,
        args.venue_redirect_db,
    )
    if report.get("weak_key_application"):
        print("weak_key_application:", json.dumps(report["weak_key_application"], ensure_ascii=False))
    print(json.dumps({k: v for k, v in report.items() if k in ("counts", "gate")}, indent=2, ensure_ascii=False))
    print(f"\ncandidate db: {out_dir / 'canonical_event_candidates.sqlite'}")
    print(f"report:       {out_dir / 'collapse_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
