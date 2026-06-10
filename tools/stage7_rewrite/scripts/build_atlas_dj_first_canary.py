#!/usr/bin/env python3
"""Build a report-only DJ-first canonical Atlas canary.

Reads a local Atlas SQLite database, derives bounded canonical music identities
and relation rollups, and writes sidecar reports only. It never writes to the
source SQLite database, Neo4j, Qdrant, mem0, CloudRun, or production state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = (
    REPO_ROOT
    / "tools"
    / "stage7_rewrite"
    / "reports"
    / "atlas_local_sqlite_db_138102_20260521"
    / "atlas.sqlite"
)
DEFAULT_OUT_DIR = REPO_ROOT / "reports" / "atlas_dj_first_canary_20260522"
DEFAULT_CURATED_RULES = REPO_ROOT / "tools" / "stage7_rewrite" / "config" / "atlas_curated_entity_rules_20260522.json"
DEFAULT_SEEDS = ["MaFoL", "OIL", "DADA昆明", "BO LIVE", "TAG", "DONG 洞"]
LOCAL_PUBLIC_VERIFY_STACK = ["SearXNG", "OpenCLI", "Scrapling", "Lightpanda", "Maigret", "Camofox"]

NOISE_TERMS = {
    "葡萄酒",
    "红葡萄酒",
    "白葡萄酒",
    "酒单",
    "菜单",
    "咖啡",
    "餐厅",
    "招聘",
    "瑜伽",
    "酒店推荐",
    "课程表",
    "下午茶",
    "精酿",
    "啤酒",
    "威士忌",
    "cocktail",
    "wine",
}
VENUE_TERMS = {
    "club",
    "bar",
    "live",
    "venue",
    "俱乐部",
    "场地",
    "空间",
    "dada",
    "oil",
    "tag",
    "all",
    "bo live",
    "zhaodai",
    "招待",
    "dng",
    "dong",
    "dong 洞",
    "dirty house",
    "potent",
    "exit",
    "the box",
    "room mirror",
    "ins",
}
VENUE_ALIASES = {
    "/\\||": "ALL",
    "/||": "ALL",
    "/\\|| (all俱乐部)": "ALL",
}
LABEL_TERMS = {
    "厂牌",
    "crew",
    "records",
    "recordings",
    "collective",
    "label",
    "shcr",
    "svbkvlt",
    "do hits",
    "genome",
}
RADIO_TERMS = {
    "radio",
    "电台",
    "播客",
    "podcast",
    "shcr",
    "byyb",
    "baihui",
    "cdcr",
}
MUSIC_TERMS = {
    "dj",
    "producer",
    "live set",
    "mixtape",
    "club",
    "techno",
    "house",
    "bass",
    "rave",
    "电子",
    "电音",
    "派对",
    "演出",
    "阵容",
}


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\s+", " ", text.strip())


def norm_key(value: Any) -> str:
    return norm_text(value).casefold()


def stable_id(prefix: str, *parts: Any) -> str:
    body = "\x1f".join(norm_key(part) for part in parts if norm_text(part))
    digest = hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{digest}"


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


def parse_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [norm_text(item) for item in value if norm_text(item)]
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(parsed, list):
        return [norm_text(item) for item in parsed if norm_text(item)]
    return []


def source_scoped_id(source_article_uid: Any, local_id: Any, fallback: str) -> str:
    source = norm_text(source_article_uid)
    local = norm_text(local_id)
    if source and local:
        return f"{source}#{local}"
    if source:
        return f"{source}#{fallback}"
    return fallback


def confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def contains_any(haystack: str, terms: set[str]) -> bool:
    return any(term in haystack for term in terms)


def load_curated_rules(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records", [])
    rules: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = norm_key(row.get("normalized_term") or row.get("term"))
        kind = norm_key(row.get("kind"))
        if not key or kind not in {"dj", "venue", "label_org", "radio", "noise", "music_context", "context"}:
            continue
        rules[key] = row
    return rules


def curated_kind(value: Any, curated_rules: dict[str, dict[str, Any]] | None) -> str:
    if not curated_rules:
        return ""
    return norm_key(curated_rules.get(norm_key(value), {}).get("kind"))


def classify_entity(
    name: Any,
    raw_type: Any,
    source_account: Any = "",
    place_context: Any = "",
    curated_rules: dict[str, dict[str, Any]] | None = None,
) -> str:
    rule_kind = curated_kind(name, curated_rules)
    if rule_kind:
        return rule_kind
    raw = norm_key(raw_type)
    name_haystack = " ".join([norm_key(name), norm_key(place_context)])
    label_haystack = " ".join([norm_key(name), norm_key(source_account)])
    if raw == "product" or contains_any(name_haystack, NOISE_TERMS):
        return "noise"
    if raw == "person":
        return "dj"
    if contains_any(label_haystack, RADIO_TERMS):
        return "radio"
    if raw == "place" or contains_any(name_haystack, VENUE_TERMS):
        return "venue"
    if raw in {"organization", "brand"} or contains_any(label_haystack, LABEL_TERMS):
        return "label_org"
    if contains_any(label_haystack, MUSIC_TERMS):
        return "music_context"
    return "context"


def normalize_venue_name(value: Any) -> str:
    text = norm_text(value)
    key = norm_key(text)
    if key in VENUE_ALIASES:
        return VENUE_ALIASES[key]
    if "all俱乐部" in key:
        return "ALL"
    address_match = re.search(r"[（(]([^）)]*(?:路|街|巷|号|弄|层|楼|广场)[^）)]*)[）)]", text)
    if address_match:
        return norm_text(address_match.group(1))
    return text


def classify_place_text(value: Any, curated_rules: dict[str, dict[str, Any]] | None = None) -> str:
    text = normalize_venue_name(value)
    haystack = norm_key(text)
    if not haystack:
        return "context"
    rule_kind = curated_kind(text, curated_rules)
    if rule_kind:
        return rule_kind
    if contains_any(haystack, NOISE_TERMS):
        return "noise"
    if contains_any(haystack, RADIO_TERMS):
        return "radio"
    if contains_any(haystack, VENUE_TERMS):
        return "venue"
    if re.search(r"(路|街|巷|号|弄|层|楼|区|广场|address|street|road)", text, flags=re.IGNORECASE):
        return "venue"
    return "context"


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"{db_path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def load_seed_mentions(conn: sqlite3.Connection, seeds: list[str], max_sources: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    sql = """
        SELECT
          e.eid,
          e.name,
          e.type,
          e.city,
          e.source_article_uid,
          e.confidence,
          e.aliases_json,
          e.bio,
          e.evidence_quote,
          e.vector_text_preview,
          a.title AS source_title,
          a.source_account,
          a.publish_time,
          a.city_label
        FROM entities e
        LEFT JOIN articles a ON a.article_uid = e.source_article_uid
        WHERE lower(e.name) = lower(?)
        ORDER BY e.confidence DESC, e.source_article_uid
        LIMIT ?
    """
    for seed in seeds:
        for row in conn.execute(sql, (seed, max_sources)):
            item = row_dict(row)
            mid = source_scoped_id(item.get("source_article_uid"), item.get("eid"), f"seed:{len(rows)}")
            if mid in seen:
                continue
            seen.add(mid)
            item["mention_public_id"] = mid
            item["seed_query"] = seed
            rows.append(item)
    return rows


def load_events_for_sources(conn: sqlite3.Connection, source_ids: Iterable[str]) -> list[dict[str, Any]]:
    ids = sorted({source_id for source_id in source_ids if source_id})
    rows: list[dict[str, Any]] = []
    if not ids:
        return rows
    for offset in range(0, len(ids), 400):
        chunk = ids[offset : offset + 400]
        placeholders = ",".join("?" for _ in chunk)
        sql = f"""
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
            WHERE ev.source_article_uid IN ({placeholders})
            ORDER BY ev.time_iso DESC, ev.source_article_uid
        """
        rows.extend(row_dict(row) for row in conn.execute(sql, chunk))
    return rows


def group_identities(
    mentions: list[dict[str, Any]],
    curated_rules: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], Counter[str]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for mention in mentions:
        kind = classify_entity(
            mention.get("name"),
            mention.get("type"),
            mention.get("source_account"),
            curated_rules=curated_rules,
        )
        name_key = norm_key(mention.get("name"))
        if not name_key:
            continue
        group = groups.setdefault(
            (kind, name_key),
            {
                "kind": kind,
                "name_key": name_key,
                "display_names": Counter(),
                "source_articles": set(),
                "mention_ids": [],
                "confidence_sum": 0.0,
                "cities": Counter(),
                "source_accounts": Counter(),
                "aliases": Counter(),
            },
        )
        name = norm_text(mention.get("name"))
        group["display_names"][name] += 1
        group["confidence_sum"] += confidence(mention.get("confidence"))
        source_article_uid = norm_text(mention.get("source_article_uid"))
        if source_article_uid:
            group["source_articles"].add(source_article_uid)
        if len(group["mention_ids"]) < 30:
            group["mention_ids"].append(mention.get("mention_public_id"))
        city = norm_text(mention.get("city") or mention.get("city_label"))
        if city:
            group["cities"][city] += 1
        source_account = norm_text(mention.get("source_account"))
        if source_account:
            group["source_accounts"][source_account] += 1
        for alias in parse_json_list(mention.get("aliases_json")):
            group["aliases"][alias] += 1

    rows: list[dict[str, Any]] = []
    by_name: dict[str, dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    for (kind, name_key), group in sorted(groups.items(), key=lambda item: (item[0][0], item[0][1])):
        display_name = group["display_names"].most_common(1)[0][0]
        source_articles = sorted(group["source_articles"])
        mention_count = sum(group["display_names"].values())
        row = {
            "schema_version": "atlas_dj_first_canary.canonical_identity.v1",
            "canonical_id": stable_id(kind, name_key),
            "kind": kind,
            "display_name": display_name,
            "normalized_name": name_key,
            "aliases": [name for name, _count in group["aliases"].most_common(10)],
            "mention_count": mention_count,
            "source_article_count": len(source_articles),
            "source_articles_sample": source_articles[:20],
            "mention_ids_sample": group["mention_ids"],
            "city": group["cities"].most_common(1)[0][0] if group["cities"] else "",
            "source_accounts_sample": [name for name, _count in group["source_accounts"].most_common(10)],
            "avg_confidence": round(group["confidence_sum"] / max(mention_count, 1), 4),
            "write_status": "report_only",
        }
        rows.append(row)
        by_name[name_key] = row
        counts[kind] += 1
    return rows, by_name, counts


def event_sample(event: dict[str, Any], participants: list[str]) -> dict[str, Any]:
    return {
        "event_id": source_scoped_id(event.get("source_article_uid"), event.get("evid"), stable_id("event", event.get("name"))),
        "event_name": norm_text(event.get("name")),
        "place": norm_text(event.get("place")),
        "city": norm_text(event.get("city") or event.get("city_label")),
        "time": norm_text(event.get("time_iso") or event.get("time_text") or event.get("publish_time")),
        "source_article_uid": norm_text(event.get("source_article_uid")),
        "source_title": norm_text(event.get("source_title")),
        "source_account": norm_text(event.get("source_account")),
        "participants_sample": participants[:12],
    }


def add_sample(row: dict[str, Any], sample: dict[str, Any], limit: int = 8) -> None:
    samples = row.setdefault("sample_evidence", [])
    key = json.dumps(sample, ensure_ascii=False, sort_keys=True)
    existing = {json.dumps(item, ensure_ascii=False, sort_keys=True) for item in samples}
    if key not in existing and len(samples) < limit:
        samples.append(sample)


def add_uncertain_term(
    terms: dict[tuple[str, str, str], dict[str, Any]],
    term_type: str,
    term: str,
    reason: str,
    sample: dict[str, Any],
) -> None:
    key = (term_type, norm_key(term), reason)
    row = terms.setdefault(
        key,
        {
            "schema_version": "atlas_dj_first_canary.uncertain_term.v1",
            "term_type": term_type,
            "term": term,
            "normalized_term": norm_key(term),
            "reason": reason,
            "count": 0,
            "sample_evidence": [],
            "recommended_next_action": "public_web_verify_with_searxng_opencli_scrapling_lightpanda_maigret_camofox",
            "write_status": "report_only",
        },
    )
    row["count"] += 1
    add_sample(row, sample, limit=10)


def add_resolved_term(
    terms: dict[tuple[str, str], dict[str, Any]],
    term_type: str,
    term: str,
    sample: dict[str, Any],
    rule: dict[str, Any],
) -> None:
    key = (term_type, norm_key(term))
    row = terms.setdefault(
        key,
        {
            "schema_version": "atlas_dj_first_canary.resolved_field_noise.v1",
            "term_type": term_type,
            "term": term,
            "normalized_term": norm_key(term),
            "resolved_kind": norm_key(rule.get("kind")),
            "resolution_basis": rule.get("basis", ""),
            "confidence": rule.get("confidence", 0),
            "public_sources": rule.get("sources", []),
            "notes": rule.get("notes", ""),
            "count": 0,
            "sample_evidence": [],
            "write_status": "report_only",
        },
    )
    row["count"] += 1
    add_sample(row, sample, limit=10)


def build_relations(
    identities_by_name: dict[str, dict[str, Any]],
    events: list[dict[str, Any]],
    curated_rules: dict[str, dict[str, Any]] | None = None,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    seed_djs = {
        name_key: identity
        for name_key, identity in identities_by_name.items()
        if identity["kind"] == "dj"
    }
    collaborators: dict[tuple[str, str], dict[str, Any]] = {}
    venues: dict[tuple[str, str], dict[str, Any]] = {}
    label_edges: dict[tuple[str, str], dict[str, Any]] = {}
    evidence_refs: list[dict[str, Any]] = []
    evidence_seen: set[str] = set()
    uncertain_terms: dict[tuple[str, str, str], dict[str, Any]] = {}
    resolved_terms: dict[tuple[str, str], dict[str, Any]] = {}

    for event in events:
        participants = parse_json_list(event.get("participants_json"))
        organizers = parse_json_list(event.get("organizers_json"))
        participant_keys = {norm_key(name): name for name in participants}
        if not participant_keys:
            continue
        sample = event_sample(event, participants)
        place = normalize_venue_name(event.get("place"))
        source_article_uid = norm_text(event.get("source_article_uid"))
        for dj_key, dj in seed_djs.items():
            if dj_key not in participant_keys:
                continue
            src_id = dj["canonical_id"]
            for other_key, other_name in participant_keys.items():
                if other_key == dj_key:
                    continue
                dst_id = stable_id("dj_candidate", other_key)
                row = collaborators.setdefault(
                    (src_id, dst_id),
                    {
                        "schema_version": "atlas_dj_first_canary.dj_collaborator.v1",
                        "src_dj_id": src_id,
                        "src_name": dj["display_name"],
                        "dst_dj_id": dst_id,
                        "dst_name": other_name,
                        "same_event_count": 0,
                        "source_articles": set(),
                        "relation_score": 0.0,
                        "relation_label_zh": "经常同台候选",
                        "sample_evidence": [],
                        "write_status": "report_only",
                    },
                )
                row["same_event_count"] += 1
                if source_article_uid:
                    row["source_articles"].add(source_article_uid)
                add_sample(row, sample)
            place_kind = classify_place_text(place, curated_rules)
            if place and place_kind == "venue":
                venue_id = stable_id("venue_candidate", place)
                row = venues.setdefault(
                    (src_id, norm_key(place)),
                    {
                        "schema_version": "atlas_dj_first_canary.dj_venue.v1",
                        "dj_id": src_id,
                        "dj_name": dj["display_name"],
                        "venue_id": venue_id,
                        "venue_name": place,
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
            elif place:
                rule = curated_rules.get(norm_key(place)) if curated_rules else None
                if rule:
                    add_resolved_term(resolved_terms, "event_place", place, sample, rule)
                else:
                    add_uncertain_term(uncertain_terms, "event_place", place, f"place_classified_{place_kind}", sample)
            for organizer in organizers:
                org_key = norm_key(organizer)
                org_id = stable_id("label_org_candidate", org_key)
                row = label_edges.setdefault(
                    (src_id, org_id),
                    {
                        "schema_version": "atlas_dj_first_canary.dj_label_org.v1",
                        "dj_id": src_id,
                        "dj_name": dj["display_name"],
                        "org_id": org_id,
                        "org_name": organizer,
                        "organized_event_participation_count": 0,
                        "source_articles": set(),
                        "label_score": 0.0,
                        "public_state": "candidate",
                        "sample_evidence": [],
                        "write_status": "report_only",
                    },
                )
                row["organized_event_participation_count"] += 1
                if source_article_uid:
                    row["source_articles"].add(source_article_uid)
                add_sample(row, sample)
            evidence_id = stable_id("evidence", src_id, sample["event_id"])
            if evidence_id not in evidence_seen:
                evidence_seen.add(evidence_id)
                evidence_refs.append(
                    {
                        "schema_version": "atlas_dj_first_canary.evidence_ref.v1",
                        "evidence_id": evidence_id,
                        "fact_type": "dj_event_participation",
                        "fact_id": f"{src_id}->{sample['event_id']}",
                        "source_article_uid": source_article_uid,
                        "source_title": sample["source_title"],
                        "source_account": sample["source_account"],
                        "visible_excerpt": sample["event_name"],
                        "evidence_strength": "same_event_participant",
                        "write_status": "report_only",
                    }
                )

    collab_rows = []
    for row in collaborators.values():
        row["source_article_count"] = len(row["source_articles"])
        row["source_articles"] = sorted(row["source_articles"])[:20]
        row["relation_score"] = round(3.0 * row["same_event_count"] + min(row["source_article_count"], 5) * 0.2, 4)
        collab_rows.append(row)
    collab_rows.sort(key=lambda item: (-item["relation_score"], item["src_name"], item["dst_name"]))

    venue_rows = []
    for row in venues.values():
        row["source_article_count"] = len(row["source_articles"])
        row["source_articles"] = sorted(row["source_articles"])[:20]
        row["affinity_score"] = round(2.5 * row["played_event_count"] + min(row["source_article_count"], 5) * 0.2, 4)
        venue_rows.append(row)
    venue_rows.sort(key=lambda item: (-item["affinity_score"], item["dj_name"], item["venue_name"]))

    label_rows = []
    for row in label_edges.values():
        row["source_article_count"] = len(row["source_articles"])
        row["source_articles"] = sorted(row["source_articles"])[:20]
        row["label_score"] = round(2.0 * row["organized_event_participation_count"] + min(row["source_article_count"], 5) * 0.2, 4)
        label_rows.append(row)
    label_rows.sort(key=lambda item: (-item["label_score"], item["dj_name"], item["org_name"]))

    uncertain_rows = list(uncertain_terms.values())
    uncertain_rows.sort(key=lambda item: (-item["count"], item["term_type"], item["term"]))
    resolved_rows = list(resolved_terms.values())
    resolved_rows.sort(key=lambda item: (-item["count"], item["term_type"], item["term"]))

    return collab_rows, venue_rows, label_rows, evidence_refs, uncertain_rows, resolved_rows


def write_sidecar_sqlite(
    path: Path,
    identities: list[dict[str, Any]],
    collaborators: list[dict[str, Any]],
    venues: list[dict[str, Any]],
    label_edges: list[dict[str, Any]],
    evidence_refs: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE canonical_identity (
          canonical_id TEXT PRIMARY KEY,
          kind TEXT NOT NULL,
          display_name TEXT NOT NULL,
          normalized_name TEXT NOT NULL,
          mention_count INTEGER NOT NULL,
          source_article_count INTEGER NOT NULL,
          avg_confidence REAL NOT NULL,
          sample_json TEXT NOT NULL,
          write_status TEXT NOT NULL
        );
        CREATE TABLE dj_collaborator (
          src_dj_id TEXT NOT NULL,
          dst_dj_id TEXT NOT NULL,
          src_name TEXT NOT NULL,
          dst_name TEXT NOT NULL,
          same_event_count INTEGER NOT NULL,
          source_article_count INTEGER NOT NULL,
          relation_score REAL NOT NULL,
          sample_json TEXT NOT NULL,
          write_status TEXT NOT NULL,
          PRIMARY KEY(src_dj_id, dst_dj_id)
        );
        CREATE TABLE dj_venue (
          dj_id TEXT NOT NULL,
          venue_id TEXT NOT NULL,
          dj_name TEXT NOT NULL,
          venue_name TEXT NOT NULL,
          played_event_count INTEGER NOT NULL,
          source_article_count INTEGER NOT NULL,
          affinity_score REAL NOT NULL,
          sample_json TEXT NOT NULL,
          write_status TEXT NOT NULL,
          PRIMARY KEY(dj_id, venue_id)
        );
        CREATE TABLE dj_label_org (
          dj_id TEXT NOT NULL,
          org_id TEXT NOT NULL,
          dj_name TEXT NOT NULL,
          org_name TEXT NOT NULL,
          organized_event_participation_count INTEGER NOT NULL,
          source_article_count INTEGER NOT NULL,
          label_score REAL NOT NULL,
          sample_json TEXT NOT NULL,
          write_status TEXT NOT NULL,
          PRIMARY KEY(dj_id, org_id)
        );
        CREATE TABLE evidence_ref (
          evidence_id TEXT PRIMARY KEY,
          fact_type TEXT NOT NULL,
          fact_id TEXT NOT NULL,
          source_article_uid TEXT,
          source_title TEXT,
          source_account TEXT,
          visible_excerpt TEXT,
          evidence_strength TEXT NOT NULL,
          write_status TEXT NOT NULL
        );
        """
    )
    conn.executemany(
        """
        INSERT INTO canonical_identity VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["canonical_id"],
                row["kind"],
                row["display_name"],
                row["normalized_name"],
                row["mention_count"],
                row["source_article_count"],
                row["avg_confidence"],
                json.dumps(
                    {
                        "aliases": row["aliases"],
                        "source_articles_sample": row["source_articles_sample"],
                        "mention_ids_sample": row["mention_ids_sample"],
                        "source_accounts_sample": row["source_accounts_sample"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                row["write_status"],
            )
            for row in identities
        ],
    )
    conn.executemany(
        "INSERT INTO dj_collaborator VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["src_dj_id"],
                row["dst_dj_id"],
                row["src_name"],
                row["dst_name"],
                row["same_event_count"],
                row["source_article_count"],
                row["relation_score"],
                json.dumps(row["sample_evidence"], ensure_ascii=False, sort_keys=True),
                row["write_status"],
            )
            for row in collaborators
        ],
    )
    conn.executemany(
        "INSERT INTO dj_venue VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["dj_id"],
                row["venue_id"],
                row["dj_name"],
                row["venue_name"],
                row["played_event_count"],
                row["source_article_count"],
                row["affinity_score"],
                json.dumps(row["sample_evidence"], ensure_ascii=False, sort_keys=True),
                row["write_status"],
            )
            for row in venues
        ],
    )
    conn.executemany(
        "INSERT INTO dj_label_org VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["dj_id"],
                row["org_id"],
                row["dj_name"],
                row["org_name"],
                row["organized_event_participation_count"],
                row["source_article_count"],
                row["label_score"],
                json.dumps(row["sample_evidence"], ensure_ascii=False, sort_keys=True),
                row["write_status"],
            )
            for row in label_edges
        ],
    )
    conn.executemany(
        "INSERT INTO evidence_ref VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                row["evidence_id"],
                row["fact_type"],
                row["fact_id"],
                row["source_article_uid"],
                row["source_title"],
                row["source_account"],
                row["visible_excerpt"],
                row["evidence_strength"],
                row["write_status"],
            )
            for row in evidence_refs
        ],
    )
    conn.commit()
    conn.close()


def write_markdown(path: Path, summary: dict[str, Any], collaborators: list[dict[str, Any]], venues: list[dict[str, Any]]) -> None:
    lines = [
        "# Atlas DJ-First Canary Summary",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- source_db: `{summary['source_db']}`",
        f"- sidecar_sqlite: `{summary['sidecar_sqlite']}`",
        f"- seed_count: `{len(summary['seeds'])}`",
        f"- seed_entity_mentions: `{summary['seed_entity_mentions']}`",
        f"- source_articles_loaded: `{summary['source_articles_loaded']}`",
        f"- events_loaded: `{summary['events_loaded']}`",
        f"- canonical_counts: `{json.dumps(summary['canonical_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Top DJ Collaborators",
        "",
        "| DJ | Related DJ | Same Events | Source Articles | Score |",
        "|---|---|---:|---:|---:|",
    ]
    for row in collaborators[:20]:
        lines.append(
            f"| `{row['src_name']}` | `{row['dst_name']}` | {row['same_event_count']} | {row['source_article_count']} | {row['relation_score']} |"
        )
    lines.extend(["", "## Top DJ Venues", "", "| DJ | Venue | Events | Source Articles | Score |", "|---|---|---:|---:|---:|"])
    for row in venues[:20]:
        lines.append(
            f"| `{row['dj_name']}` | `{row['venue_name']}` | {row['played_event_count']} | {row['source_article_count']} | {row['affinity_score']} |"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- Report-only sidecar artifact.",
            "- Source SQLite opened read-only.",
            "- No Neo4j, Qdrant, mem0, CloudRun, model, paid API, or production writes.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_canary(
    db_path: Path,
    out_dir: Path,
    seeds: list[str] | None = None,
    max_sources: int = 2000,
    curated_rules_path: Path | None = DEFAULT_CURATED_RULES,
) -> dict[str, Any]:
    db_path = Path(db_path)
    out_dir = Path(out_dir)
    seed_values = [norm_text(seed) for seed in (seeds or DEFAULT_SEEDS) if norm_text(seed)]
    curated_rules = load_curated_rules(curated_rules_path)
    with connect_readonly(db_path) as conn:
        mentions = load_seed_mentions(conn, seed_values, max_sources=max_sources)
        source_articles = sorted({norm_text(row.get("source_article_uid")) for row in mentions if norm_text(row.get("source_article_uid"))})
        if max_sources:
            source_articles = source_articles[: max_sources * max(len(seed_values), 1)]
        events = load_events_for_sources(conn, source_articles)

    identities, identities_by_name, canonical_counts = group_identities(mentions, curated_rules)
    collaborators, venues, label_edges, evidence_refs, uncertain_terms, resolved_terms = build_relations(
        identities_by_name,
        events,
        curated_rules,
    )

    sidecar_sqlite = out_dir / "atlas_dj_first_canary.sqlite"
    write_sidecar_sqlite(sidecar_sqlite, identities, collaborators, venues, label_edges, evidence_refs)

    summary = {
        "schema_version": "atlas_dj_first_canary.summary.v1",
        "generated_at": now_iso(),
        "source_db": str(db_path),
        "out_dir": str(out_dir),
        "sidecar_sqlite": str(sidecar_sqlite),
        "seeds": seed_values,
        "seed_entity_mentions": len(mentions),
        "source_articles_loaded": len(source_articles),
        "events_loaded": len(events),
        "canonical_counts": {
            key: int(canonical_counts.get(key, 0))
            for key in ["dj", "venue", "label_org", "radio", "noise", "music_context", "context"]
        },
        "relation_counts": {
            "dj_collaborators": len(collaborators),
            "dj_venues": len(venues),
            "dj_label_org": len(label_edges),
            "evidence_refs": len(evidence_refs),
            "uncertain_terms": len(uncertain_terms),
            "resolved_terms": len(resolved_terms),
        },
        "curated_rules_path": str(curated_rules_path) if curated_rules_path else "",
        "curated_rules_loaded": len(curated_rules),
        "local_public_verify_stack": LOCAL_PUBLIC_VERIFY_STACK,
        "safety": {
            "report_only": True,
            "source_sqlite_write_executed": False,
            "sidecar_sqlite_write_executed": True,
            "neo4j_write_executed": False,
            "qdrant_write_executed": False,
            "mem0_write_executed": False,
            "cloudrun_deploy_executed": False,
            "model_call_executed": False,
            "paid_api_call_executed": False,
        },
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_dir / "canonical_identities.jsonl", identities)
    write_jsonl(out_dir / "dj_collaborators.jsonl", collaborators)
    write_jsonl(out_dir / "dj_venues.jsonl", venues)
    write_jsonl(out_dir / "dj_label_org.jsonl", label_edges)
    write_jsonl(out_dir / "evidence_refs.jsonl", evidence_refs)
    write_jsonl(out_dir / "uncertain_terms.jsonl", uncertain_terms)
    write_jsonl(out_dir / "resolved_field_noise.jsonl", resolved_terms)
    write_json(out_dir / "summary.json", summary)
    write_markdown(out_dir / "summary.md", summary, collaborators, venues)

    return {
        "summary": summary,
        "canonical_identities": identities,
        "relations": {
            "dj_collaborators": collaborators,
            "dj_venues": venues,
            "dj_label_org": label_edges,
        },
        "evidence_refs": evidence_refs,
        "uncertain_terms": uncertain_terms,
        "resolved_terms": resolved_terms,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--curated-rules", type=Path, default=DEFAULT_CURATED_RULES)
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument("--max-sources", type=int, default=2000)
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> int:
    result = build_canary(
        args.db,
        args.out_dir,
        seeds=args.seed or DEFAULT_SEEDS,
        max_sources=args.max_sources,
        curated_rules_path=args.curated_rules,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "summary": str(Path(args.out_dir) / "summary.json"),
                "sidecar_sqlite": result["summary"]["sidecar_sqlite"],
                "canonical_counts": result["summary"]["canonical_counts"],
                "relation_counts": result["summary"]["relation_counts"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
