"""Stage 4 — Build an Atlas serving SQLite candidate from resolved entities.

This writes a new candidate read model under the rebuild work dir. It does not
touch the existing production/candidate serving DBs elsewhere in the repo.

Input:
  _work/entities_resolved.sqlite  (Stage3)
  _work/clean.sqlite              (source snippets/accounts)

Output:
  _work/atlas_serving_candidate.sqlite

Usage:
  python stage4_rollup.py
  python stage4_rollup.py --limit-events 50
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


SCHEMA = """
CREATE TABLE search_document (
  doc_rowid INTEGER PRIMARY KEY,
  subject_id TEXT NOT NULL,
  subject_type TEXT NOT NULL,
  display_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  aliases_text TEXT,
  city_text TEXT,
  taxon_path TEXT NOT NULL,
  rank_score REAL NOT NULL DEFAULT 0,
  last_seen_at TEXT,
  public_state TEXT NOT NULL,
  search_text TEXT NOT NULL
);
CREATE TABLE canonical_subject (
  subject_id TEXT PRIMARY KEY,
  subject_type TEXT NOT NULL,
  display_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  taxon_path TEXT NOT NULL,
  aliases_json TEXT NOT NULL,
  city_primary TEXT,
  confidence REAL NOT NULL DEFAULT 0,
  source_count INTEGER NOT NULL DEFAULT 0,
  event_count INTEGER NOT NULL DEFAULT 0,
  relation_count INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT,
  last_seen_at TEXT,
  public_state TEXT NOT NULL
);
CREATE TABLE dj_profile (
  dj_id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  normalized_name TEXT NOT NULL,
  aliases_json TEXT NOT NULL,
  city_primary TEXT,
  avatar_asset_id TEXT,
  source_article_count INTEGER NOT NULL DEFAULT 0,
  event_count INTEGER NOT NULL DEFAULT 0,
  venue_count INTEGER NOT NULL DEFAULT 0,
  collaborator_count INTEGER NOT NULL DEFAULT 0,
  organization_count INTEGER NOT NULL DEFAULT 0,
  media_count INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT,
  last_seen_at TEXT,
  confidence REAL NOT NULL DEFAULT 0
);
CREATE TABLE performance_event (
  event_id TEXT PRIMARY KEY,
  event_title TEXT NOT NULL,
  starts_at TEXT,
  time_text TEXT,
  venue_id TEXT,
  venue_name TEXT,
  city TEXT,
  source_ref_id TEXT,
  participant_count INTEGER NOT NULL DEFAULT 0,
  organizer_count INTEGER NOT NULL DEFAULT 0,
  confidence REAL NOT NULL DEFAULT 0
);
CREATE TABLE dj_event (
  dj_id TEXT NOT NULL,
  event_id TEXT NOT NULL,
  starts_at TEXT,
  time_text TEXT,
  event_title TEXT NOT NULL,
  venue_id TEXT,
  venue_name TEXT,
  city TEXT,
  source_ref_id TEXT,
  confidence REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (dj_id, event_id, source_ref_id)
);
CREATE TABLE dj_relation_rollup (
  src_dj_id TEXT NOT NULL,
  dst_dj_id TEXT NOT NULL,
  same_event_count INTEGER NOT NULL DEFAULT 0,
  same_label_count INTEGER NOT NULL DEFAULT 0,
  same_venue_count INTEGER NOT NULL DEFAULT 0,
  same_source_context_count INTEGER NOT NULL DEFAULT 0,
  b2b_count INTEGER NOT NULL DEFAULT 0,
  source_diversity INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT,
  last_seen_at TEXT,
  relation_score REAL NOT NULL DEFAULT 0,
  relation_label_zh TEXT NOT NULL,
  sample_evidence_json TEXT NOT NULL,
  public_state TEXT NOT NULL,
  PRIMARY KEY (src_dj_id, dst_dj_id)
);
CREATE TABLE dj_venue_rollup (
  dj_id TEXT NOT NULL,
  venue_id TEXT NOT NULL,
  venue_name TEXT NOT NULL,
  city TEXT,
  event_count INTEGER NOT NULL DEFAULT 0,
  first_seen_at TEXT,
  last_seen_at TEXT,
  score REAL NOT NULL DEFAULT 0,
  PRIMARY KEY (dj_id, venue_id)
);
CREATE TABLE dj_org_rollup (
  dj_id TEXT NOT NULL,
  org_id TEXT NOT NULL,
  org_name TEXT NOT NULL,
  org_type TEXT NOT NULL,
  evidence_count INTEGER NOT NULL DEFAULT 0,
  score REAL NOT NULL DEFAULT 0,
  sample_evidence_json TEXT NOT NULL,
  PRIMARY KEY (dj_id, org_id)
);
CREATE TABLE evidence_ref (
  source_ref_id TEXT PRIMARY KEY,
  source_hash TEXT NOT NULL,
  source_account TEXT,
  source_title TEXT,
  post_date TEXT,
  public_snippet TEXT,
  source_kind TEXT,
  public_url_allowed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE activity_evidence_ref (
  evidence_ref_id TEXT PRIMARY KEY,
  source_ref_id TEXT,
  event_id TEXT,
  field_path TEXT,
  field_value TEXT,
  support_type TEXT,
  quote TEXT,
  quote_policy TEXT,
  confidence REAL
);
CREATE INDEX ix_search_document_subject ON search_document(subject_id);
CREATE INDEX ix_search_document_type ON search_document(subject_type);
CREATE INDEX ix_performance_event_source ON performance_event(source_ref_id);
CREATE INDEX ix_dj_event_event ON dj_event(event_id);
CREATE INDEX ix_dj_event_dj ON dj_event(dj_id);
CREATE INDEX ix_relation_src ON dj_relation_rollup(src_dj_id);
CREATE INDEX ix_relation_dst ON dj_relation_rollup(dst_dj_id);
CREATE INDEX ix_dj_venue_dj ON dj_venue_rollup(dj_id);
CREATE INDEX ix_dj_org_dj ON dj_org_rollup(dj_id);
"""

_NORM = re.compile(r"[\s·・·.,!?\"'’“”（）()\[\]{}|/\\@#&*\-_:：，。！？、]+")


def norm(value):
    return _NORM.sub("", (value or "").strip().lower())


def jdump(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def load_json(value, default=None):
    if not value:
        return default if default is not None else {}
    try:
        return json.loads(value)
    except Exception:
        return default if default is not None else {}


def first_text(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return str(value)
    return ""


def text_preview(value, limit=280):
    text = re.sub(r"\s+", " ", value or "").strip()
    return text[:limit]


def date_key(value):
    value = value or ""
    return value[:10] if len(value) >= 10 else value


def entity_subject_type(entity):
    etype = entity["type"]
    attrs = entity.get("attrs") or {}
    if etype == "dj":
        return "dj"
    if etype == "venue":
        return "venue"
    if etype == "org":
        org_type = attrs.get("org_type") or "organizer"
        return "radio" if org_type == "radio" else "organizer"
    if etype == "series":
        return "organizer"
    return etype


def taxon_path(entity):
    subject_type = entity_subject_type(entity)
    if entity["type"] == "org":
        return f"atlas/org/{(entity.get('attrs') or {}).get('org_type') or 'unknown'}"
    if entity["type"] == "series":
        return "atlas/series"
    return f"atlas/{subject_type}"


def safe_output_path(path):
    root = os.path.abspath(config.WORK_DIR)
    target = os.path.abspath(path)
    if os.path.commonpath([root, target]) != root:
        raise SystemExit(f"refuse to write outside ATLAS_WORK_DIR without a dedicated promotion step: {target}")
    return target


def load_source_meta():
    meta = {}
    clean_path = config.DB_CLEAN
    if not os.path.exists(clean_path):
        return meta
    con = sqlite3.connect(clean_path)
    cols = {row[1] for row in con.execute("PRAGMA table_info(clean)").fetchall()}
    select_cols = "token, account_key, title, clean_text"
    if {"token", "account_key", "title", "clean_text"}.issubset(cols):
        for token, account, title, clean_text in con.execute(f"SELECT {select_cols} FROM clean"):
            meta[token] = {
                "account": account or "",
                "title": title or "",
                "snippet": text_preview(clean_text or ""),
            }
    con.close()
    ingest_path = config.DB_INGEST
    if os.path.exists(ingest_path):
        con = sqlite3.connect(ingest_path)
        for token, account, title, _source_url, archived_at in con.execute("SELECT token, account_key, title, source_url, archived_at FROM ingest"):
            item = meta.setdefault(token, {})
            item.setdefault("account", account or "")
            item.setdefault("title", title or "")
            item["archived_at"] = archived_at or ""
        con.close()
    return meta


def load_resolved(limit_events=0):
    if not os.path.exists(config.DB_RESOLVED):
        raise SystemExit(f"resolved DB not found; run stage3_resolve.py first: {config.DB_RESOLVED}")
    con = sqlite3.connect(config.DB_RESOLVED)
    con.row_factory = sqlite3.Row
    entities = {}
    for row in con.execute("SELECT * FROM canonical_entity"):
        entities[row["entity_id"]] = {
            "id": row["entity_id"],
            "type": row["type"],
            "name": row["canonical_name"],
            "name_en": row["name_en"] or "",
            "city": row["city"] or "",
            "attrs": load_json(row["attrs_json"], {}),
            "status": row["status"] if "status" in row.keys() else "candidate",
        }
    q = "SELECT * FROM resolved_event ORDER BY event_id"
    if limit_events:
        q += f" LIMIT {int(limit_events)}"
    events = [dict(row) for row in con.execute(q)]
    event_sources = defaultdict(list)
    tables = {row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "event_source" in tables:
        for row in con.execute("SELECT event_id, source_token FROM event_source ORDER BY event_id, source_token"):
            if row["source_token"] not in event_sources[row["event_id"]]:
                event_sources[row["event_id"]].append(row["source_token"])
    participants = defaultdict(list)
    for row in con.execute("SELECT * FROM event_participant"):
        participants[row["event_id"]].append(dict(row))
    affiliations = defaultdict(set)
    for row in con.execute("SELECT * FROM dj_affiliation"):
        affiliations[row["dj_id"]].add(row["org_id"])
    b2b = defaultdict(set)  # (a,b) 双向 -> set(event_id)
    try:
        for row in con.execute("SELECT * FROM dj_b2b"):
            a, b, ev = row["dj_a"], row["dj_b"], row["event_id"]
            b2b[(a, b)].add(ev)
            b2b[(b, a)].add(ev)
    except sqlite3.OperationalError:
        pass  # 旧 entities_resolved 无 dj_b2b 表时优雅降级
    con.close()
    return entities, events, participants, affiliations, event_sources, b2b


def create_fts(db):
    try:
        db.execute("CREATE VIRTUAL TABLE search_document_fts USING fts5(search_text)")
        return True
    except sqlite3.OperationalError:
        return False


def insert_search_document(db, rowid, subject_id, subject_type, display_name, aliases, city, rank, last_seen, public_state="public_rollup"):
    """Insert into search_document + FTS table. public_state defaults to 'public_rollup'
    for confirmed entities; callers must pass 'candidate' for candidate-tier entities."""
    aliases_text = " ".join(a for a in aliases if a)
    # FTS bm25 is computed before rank_score in the service. Repeating high-value
    # primary names nudges exact DJ/venue searches above same-name org mentions.
    primary_terms = [display_name]
    if subject_type == "dj":
        primary_terms = [display_name, display_name, display_name]
    elif subject_type == "venue":
        primary_terms = [display_name, display_name]
    search_text = " ".join(x for x in [*primary_terms, aliases_text, city, subject_type] if x)
    db.execute(
        "INSERT INTO search_document VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (rowid, subject_id, subject_type, display_name, norm(display_name), aliases_text, city or "",
         f"atlas/{subject_type}", rank, last_seen or "", public_state, search_text),
    )
    try:
        db.execute("INSERT INTO search_document_fts(rowid, search_text) VALUES (?,?)", (rowid, search_text))
    except sqlite3.OperationalError:
        pass


def build(output, limit_events=0):
    output = safe_output_path(output)
    config.ensure_dirs()
    entities, events, participants, affiliations, event_sources, b2b = load_resolved(limit_events=limit_events)
    source_meta = load_source_meta()

    fd, tmp = tempfile.mkstemp(prefix="atlas_serving_candidate_", suffix=".sqlite", dir=config.WORK_DIR)
    os.close(fd)
    if os.path.exists(tmp):
        os.remove(tmp)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    create_fts(db)

    event_by_id = {}
    event_djs = defaultdict(list)
    dj_events = defaultdict(list)
    dj_venues = defaultdict(set)
    dj_sources = defaultdict(set)
    dj_conf = defaultdict(list)
    subject_events = defaultdict(set)
    subject_sources = defaultdict(set)
    subject_dates = defaultdict(list)
    org_edges = defaultdict(lambda: {"tokens": set(), "samples": []})

    for event in events:
        ev_json = load_json(event.get("json"), {})
        event_id = event["event_id"]
        venue_id = event.get("venue_id") or ""
        venue = entities.get(venue_id, {}) if venue_id else {}
        venue_name = first_text(ev_json.get("venue"), venue.get("name"), venue_id)
        starts_at = ev_json.get("date_start") or event.get("date_start") or ""
        source_ref_ids = event_sources.get(event_id) or ([event.get("source_token")] if event.get("source_token") else [])
        source_ref_id = event.get("source_token") or (source_ref_ids[0] if source_ref_ids else "")
        ev_parts = [p for p in participants.get(event_id, []) if p.get("dj_id")]
        event_genre = event.get("genre") or ev_json.get("genre") or "unknown"
        event_by_id[event_id] = {
            "event_id": event_id,
            "title": event.get("title") or ev_json.get("title") or event_id,
            "starts_at": starts_at,
            "time_text": event.get("time_text") or ev_json.get("time_text") or "",
            "venue_id": venue_id,
            "venue_name": venue_name,
            "city": event.get("city") or ev_json.get("city") or venue.get("city") or "",
            "source_ref_id": source_ref_id,
            "source_ref_ids": source_ref_ids,
            "participant_count": len(ev_parts),
            "organizer_count": int(bool(event.get("organizer_id"))) + int(bool(event.get("series_id"))),
            "confidence": float(event.get("confidence") or ev_json.get("confidence") or 0.0),
            "json": ev_json,
            "genre": event_genre,
        }
        for sid in (venue_id, event.get("organizer_id"), event.get("series_id")):
            if sid:
                subject_events[sid].add(event_id)
                subject_sources[sid].update(source_ref_ids)
                if starts_at:
                    subject_dates[sid].append(starts_at)
        for part in ev_parts:
            dj_id = part["dj_id"]
            event_djs[event_id].append(dj_id)
            dj_events[dj_id].append(event_id)
            dj_sources[dj_id].update(source_ref_ids)
            dj_conf[dj_id].append(event_by_id[event_id]["confidence"])
            if venue_id:
                dj_venues[dj_id].add(venue_id)
            subject_events[dj_id].add(event_id)
            subject_sources[dj_id].update(source_ref_ids)
            if starts_at:
                subject_dates[dj_id].append(starts_at)
            for org_id in (event.get("organizer_id"), event.get("series_id")):
                if org_id:
                    affiliations[dj_id].add(org_id)
                    org_edges[(dj_id, org_id)]["tokens"].update(source_ref_ids)
                    sample_source = source_ref_id or (source_ref_ids[0] if source_ref_ids else "")
                    org_edges[(dj_id, org_id)]["samples"].append({"source_ref_id": sample_source, "event_id": event_id})

    for dj_id, org_ids in affiliations.items():
        for org_id in org_ids:
            org_edges[(dj_id, org_id)]["tokens"].add("")

    # Only confirmed DJs enter serving relations and profiles (卡 T gate)
    confirmed_djs = {eid for eid, ent in entities.items()
                     if ent.get("type") == "dj" and ent.get("status") == "confirmed"}
    # Non-electronic DJs are excluded from serving heads (卡 G gate)
    non_electronic_djs = {eid for eid, ent in entities.items()
                          if ent.get("type") == "dj" and ent.get("attrs", {}).get("genre") == "non_electronic"}
    # DJs eligible for serving heads: confirmed AND not non_electronic
    serving_djs = confirmed_djs - non_electronic_djs
    non_electronic_event_ids = {eid for eid, ev in event_by_id.items()
                                if ev.get("genre") == "non_electronic"}

    for event in event_by_id.values():
        # Non-electronic events don't enter performance_event (卡 G)
        if event["genre"] == "non_electronic":
            continue
        db.execute(
            "INSERT INTO performance_event VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (event["event_id"], event["title"], event["starts_at"], event["time_text"], event["venue_id"],
             event["venue_name"], event["city"], event["source_ref_id"], event["participant_count"],
             event["organizer_count"], event["confidence"]),
        )
        for dj_id in event_djs.get(event["event_id"], []):
            if dj_id not in serving_djs:
                continue
            db.execute(
                "INSERT OR REPLACE INTO dj_event VALUES (?,?,?,?,?,?,?,?,?,?)",
                (dj_id, event["event_id"], event["starts_at"], event["time_text"], event["title"],
                 event["venue_id"], event["venue_name"], event["city"], event["source_ref_id"], event["confidence"]),
            )

    relation_acc = defaultdict(lambda: {"events": set(), "venues": set(), "sources": set(), "dates": [], "samples": []})
    for event_id, djs in event_djs.items():
        if len(djs) < 2:
            continue
        event = event_by_id[event_id]
        if event["genre"] == "non_electronic":
            continue
        unique_djs = sorted(set(djs))
        for src in unique_djs:
            if src not in serving_djs:
                continue
            for dst in unique_djs:
                if src == dst or dst not in serving_djs:
                    continue
                acc = relation_acc[(src, dst)]
                acc["events"].add(event_id)
                if event["venue_id"]:
                    acc["venues"].add(event["venue_id"])
                for source_ref in event.get("source_ref_ids") or []:
                    if source_ref:
                        acc["sources"].add(source_ref)
                if event["starts_at"]:
                    acc["dates"].append(event["starts_at"])
                if len(acc["samples"]) < 5:
                    acc["samples"].append({
                        "source_ref_id": event["source_ref_id"],
                        "source_ref_count": len(event.get("source_ref_ids") or []),
                        "event_id": event_id,
                        "event_title": event["title"],
                        "starts_at": event["starts_at"],
                    })

    for (src, dst), acc in relation_acc.items():
        same_event = len(acc["events"])
        same_venue = len(acc["venues"])
        diversity = len(acc["sources"])
        # 同厂牌边不做：国内厂牌组织松散，affiliation 噪声大、信号弱（用户拍板不要）。保留列=0。
        same_label = 0
        # b2b：深度合作，最强 DJ-DJ 边（真数据验证 VL 确实抽得到）
        b2b_count = len(b2b.get((src, dst), set()))
        score = same_event * 10 + same_venue * 2 + diversity + b2b_count * 30
        label = "b2b 深度合作" if b2b_count > 0 else ("高频同台" if same_event >= 3 else "同台")
        db.execute(
            "INSERT INTO dj_relation_rollup VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (src, dst, same_event, same_label, same_venue, same_event, b2b_count, diversity,
             min(acc["dates"]) if acc["dates"] else "", max(acc["dates"]) if acc["dates"] else "",
             score, label, jdump(acc["samples"]), "public_rollup"),
        )

    for dj_id, event_ids in dj_events.items():
        by_venue = defaultdict(list)
        for event_id in event_ids:
            event = event_by_id[event_id]
            if event["venue_id"]:
                by_venue[event["venue_id"]].append(event)
        for venue_id, rows in by_venue.items():
            venue = entities.get(venue_id, {})
            dates = [r["starts_at"] for r in rows if r["starts_at"]]
            db.execute(
                "INSERT INTO dj_venue_rollup VALUES (?,?,?,?,?,?,?,?)",
                (dj_id, venue_id, venue.get("name") or rows[0]["venue_name"] or venue_id,
                 rows[0]["city"] or venue.get("city") or "", len(rows),
                 min(dates) if dates else "", max(dates) if dates else "", len(rows) * 10),
            )

    for (dj_id, org_id), edge in org_edges.items():
        if dj_id not in entities or org_id not in entities:
            continue
        org = entities[org_id]
        org_type = (org.get("attrs") or {}).get("org_type") or ("series" if org["type"] == "series" else "unknown")
        evidence_count = max(1, len([t for t in edge["tokens"] if t]))
        db.execute(
            "INSERT OR REPLACE INTO dj_org_rollup VALUES (?,?,?,?,?,?,?)",
            (dj_id, org_id, org["name"], org_type, evidence_count, evidence_count * 10, jdump(edge["samples"][:5])),
        )

    relation_count_by_dj = defaultdict(int)
    for src, _dst in relation_acc:
        relation_count_by_dj[src] += 1

    rowid = 1
    for entity_id, entity in sorted(entities.items()):
        status = entity.get("status", "candidate")
        # rejected: never enters serving at all
        if status == "rejected":
            continue
        # non_electronic DJs: excluded from serving heads (卡 G)
        if entity.get("type") == "dj" and entity.get("attrs", {}).get("genre") == "non_electronic":
            continue

        attrs = entity.get("attrs") or {}
        aliases = []
        for value in attrs.get("aliases") or []:
            if value and value not in aliases:
                aliases.append(value)
        if entity.get("name_en") and entity["name_en"] not in aliases:
            aliases.append(entity["name_en"])
        dates = subject_dates.get(entity_id, [])
        source_count = len([s for s in subject_sources.get(entity_id, set()) if s])
        event_count = len(subject_events.get(entity_id, set()))
        subject_type = entity_subject_type(entity)
        city = first_text(entity.get("city"), attrs.get("origin_city"), attrs.get("city"))
        relation_count = relation_count_by_dj.get(entity_id, 0)
        confidence = 0.0
        if entity_id in dj_conf and dj_conf[entity_id]:
            confidence = round(max(dj_conf[entity_id]), 3)
        elif event_count:
            confidence = 0.7

        public_state = "public_rollup" if status == "confirmed" else "candidate"
        rank = event_count * 10 + relation_count * 3 + source_count

        if status == "confirmed":
            # Full serving entry: canonical_subject + dj_profile + search_document
            db.execute(
                "INSERT INTO canonical_subject VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (entity_id, subject_type, entity["name"], norm(entity["name"]), taxon_path(entity),
                 jdump(aliases), city, confidence, source_count, event_count, relation_count,
                 min(dates) if dates else "", max(dates) if dates else "", public_state),
            )
            if entity["type"] == "dj":
                db.execute(
                    "INSERT INTO dj_profile VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (entity_id, entity["name"], norm(entity["name"]), jdump(aliases), city, "",
                     len(dj_sources.get(entity_id, set())), len(dj_events.get(entity_id, [])), len(dj_venues.get(entity_id, set())),
                     relation_count_by_dj.get(entity_id, 0), len(affiliations.get(entity_id, set())), 0,
                     min(dates) if dates else "", max(dates) if dates else "", confidence),
                )
            insert_search_document(db, rowid, entity_id, subject_type, entity["name"], aliases, city, rank, max(dates) if dates else "", public_state)
            rowid += 1
        else:
            # candidate: search_document only, with public_state='candidate', no canonical_subject or dj_profile
            insert_search_document(db, rowid, entity_id, subject_type, entity["name"], aliases, city, rank, max(dates) if dates else "", "candidate")
            rowid += 1

    for event in event_by_id.values():
        if event["genre"] == "non_electronic":
            continue  # 卡 G: non-electronic events don't enter search
        aliases = [event["venue_name"], event["city"]]
        insert_search_document(db, rowid, event["event_id"], "event", event["title"], aliases, event["city"],
                               event["participant_count"] * 10 + event["confidence"] * 10, event["starts_at"])
        rowid += 1

    for token, meta in source_meta.items():
        # 推文日期 = 文章发布时间(publish_time，元数据 archived_at)，与演出日期(event.starts_at，VL 抽海报)
        # 严格区分。不再用 min(event_dates) 冒充——那把"演出日期"误当"推文日期"。元数据该走元数据，
        # 别让廉价多模态去判断"这是发布日还是活动日"(它分不清，也不该让它分)。
        post_date = (meta.get("archived_at") or "")[:10]
        source_title = meta.get("title") or token
        db.execute(
            "INSERT OR REPLACE INTO evidence_ref VALUES (?,?,?,?,?,?,?,?)",
            (token, hashlib.sha1(f"{token}|{source_title}".encode("utf-8")).hexdigest(), meta.get("account", ""),
             source_title, date_key(post_date), meta.get("snippet", ""), "wechat_raw_archive", 0),
        )

    for event in event_by_id.values():
        if event["genre"] == "non_electronic":
            continue  # 卡 G: non-electronic events don't enter evidence
        ev_json = event.get("json") or {}
        fields = {
            "title": event["title"],
            "date_start": event["starts_at"],
            "venue": event["venue_name"],
            "lineup": ", ".join(entities.get(dj, {}).get("name", dj) for dj in event_djs.get(event["event_id"], [])),
            "poster_asset_id": ev_json.get("poster_asset_id") or "",
        }
        for source_ref in event.get("source_ref_ids") or [event["source_ref_id"]]:
            for field, value in fields.items():
                if not value:
                    continue
                evid = f"{event['event_id']}:{source_ref}:{field}"
                db.execute(
                    "INSERT OR REPLACE INTO activity_evidence_ref VALUES (?,?,?,?,?,?,?,?,?)",
                    (evid, source_ref, event["event_id"], field, str(value), ev_json.get("evidence") or "unknown",
                     str(value)[:180], "short_excerpt", event["confidence"]),
                )

    db.commit()
    try:
        integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        counts = {}
        for table in ("search_document", "canonical_subject", "dj_profile", "performance_event", "dj_event",
                      "dj_relation_rollup", "dj_venue_rollup", "dj_org_rollup", "evidence_ref", "activity_evidence_ref"):
            counts[table] = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        db.close()

    os.replace(tmp, output)
    # Trust counts (卡 T)
    trust_counts = {"confirmed": 0, "candidate": 0, "rejected": 0}
    for ent in entities.values():
        s = ent.get("status", "")
        if s in trust_counts:
            trust_counts[s] += 1
    # Genre counts (卡 G)
    genre_counts = {"electronic": 0, "non_electronic": 0, "unknown": 0}
    for ev in event_by_id.values():
        g = ev.get("genre", "unknown")
        if g in genre_counts:
            genre_counts[g] += 1
    report = {
        "ok": integrity == "ok",
        "integrity_check": integrity,
        "output": output,
        "counts": counts,
        "trust_counts": trust_counts,
        "genre_counts": genre_counts,
        "source": {
            "resolved_db": config.DB_RESOLVED,
            "clean_db": config.DB_CLEAN,
            "limit_events": limit_events,
        },
        "dedupe": {
            "canonical_event_count": len(event_by_id),
            "event_source_count": sum(len(e.get("source_ref_ids") or []) for e in event_by_id.values()),
            "duplicate_source_count": max(0, sum(len(e.get("source_ref_ids") or []) for e in event_by_id.values()) - len(event_by_id)),
        },
        "boundary": "candidate_only_no_production_overwrite",
    }
    report_path = os.path.join(config.WORK_DIR, "atlas_serving_candidate_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report, report_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", default=config.DB_SERVING_CANDIDATE)
    ap.add_argument("--limit-events", type=int, default=0)
    args = ap.parse_args()
    report, report_path = build(args.output, limit_events=args.limit_events)
    print(f"Stage4 done: ok={report['ok']} integrity={report['integrity_check']}")
    print(f"  -> {report['output']}")
    print(f"  report -> {report_path}")
    print("  counts:", report["counts"])


if __name__ == "__main__":
    main()
