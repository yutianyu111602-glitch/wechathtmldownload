#!/usr/bin/env python3
"""ATLAS serving v2 — Phase 1: promote ALL entity types to first-class subjects.

The Stage4 serving (atlas_serving_candidate.sqlite) is DJ-centric: venues/orgs
exist only denormalized inside DJ rollups and series isn't served at all. But
Stage3 `entities_resolved.sqlite` already holds the unified `canonical_entity`
(dj / venue / org / series, with rich `attrs_json`) plus `resolved_event` (FK to
venue/series/organizer) and `event_participant`.

This builds `atlas_serving_v2.sqlite` with a unified `subject` table + per-type
profiles (dj/venue/org/series), with computed event counts, activity spans, and
roster/resident counts. Additive: leaves v1 untouched. Phase 2 (unified typed
relation table) and the star-map v2 lenses build on top of this.

See docs/ATLAS_NEXTGEN_DESIGN_20260620.md. Read-only on the source DB.
Runnable check: `python build_atlas_serving_v2.py --selftest`.
"""
from __future__ import annotations
import argparse, hashlib, json, sqlite3, time
from pathlib import Path

SCHEMA_VERSION = "atlas_serving.v2"
DDL = """
CREATE TABLE subject (
  subject_id TEXT PRIMARY KEY, subject_type TEXT, display_name TEXT,
  normalized_name TEXT, name_en TEXT, aliases_json TEXT, city_primary TEXT,
  event_count INTEGER DEFAULT 0, relation_count INTEGER DEFAULT 0,
  source_count INTEGER DEFAULT 0, confidence REAL,
  first_seen_at TEXT, last_seen_at TEXT, taxon_path TEXT, public_state TEXT DEFAULT 'public_rollup');
CREATE INDEX ix_subject_type ON subject(subject_type);
CREATE INDEX ix_subject_norm ON subject(normalized_name);
CREATE TABLE dj_profile (
  subject_id TEXT PRIMARY KEY, name_en TEXT, nationality TEXT, origin_city TEXT,
  roles_json TEXT, styles_json TEXT, genre TEXT, social_json TEXT, gear TEXT,
  bio_snippet TEXT, affiliations_json TEXT, venue_count INTEGER DEFAULT 0,
  org_count INTEGER DEFAULT 0);
CREATE TABLE venue_profile (
  subject_id TEXT PRIMARY KEY, name_en TEXT, city TEXT, district TEXT, address TEXT,
  geo_lat REAL, geo_lng REAL, venue_type TEXT, rooms TEXT, capacity TEXT,
  booth_gear_json TEXT, sound_brand_json TEXT, social_json TEXT,
  resident_dj_count INTEGER DEFAULT 0, event_count INTEGER DEFAULT 0);
CREATE TABLE org_profile (
  subject_id TEXT PRIMARY KEY, org_type TEXT, city TEXT, social_json TEXT,
  roster_count INTEGER DEFAULT 0, event_count INTEGER DEFAULT 0);
CREATE TABLE series_profile (
  subject_id TEXT PRIMARY KEY, venue_subject_id TEXT, organizer_subject_id TEXT,
  concept TEXT, edition_count INTEGER DEFAULT 0);
CREATE TABLE relation (
  relation_id TEXT PRIMARY KEY, src_subject_id TEXT, dst_subject_id TEXT, relation_type TEXT,
  weight REAL, same_event_count INTEGER, b2b_count INTEGER, label_zh TEXT,
  first_seen_at TEXT, last_seen_at TEXT, public_state TEXT DEFAULT 'public_rollup', sample_evidence_json TEXT);
CREATE INDEX ix_relation_src ON relation(src_subject_id);
CREATE INDEX ix_relation_dst ON relation(dst_subject_id);
CREATE INDEX ix_relation_type ON relation(relation_type);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _j(v):
    return json.dumps(v, ensure_ascii=False) if v not in (None, "", [], {}) else None


def _norm(s):
    return (s or "").strip().lower()


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _count_span(cur, sql):
    """-> {key: (count, min_date, max_date)} for a GROUP BY key query."""
    out = {}
    for k, n, mn, mx in cur.execute(sql):
        if k:
            out[k] = (n, mn, mx)
    return out


def _distinct(cur, sql):
    return {k: n for k, n in cur.execute(sql) if k}


def _build_relations(out, serving_path):
    """Unify Stage4 DJ rollups + series FKs into one typed `relation` table. Returns degree dict.
    IDs are already aligned (rollup ids == v2 subject_ids), so endpoints link directly."""
    o = out.cursor()
    subj = set(r[0] for r in o.execute("SELECT subject_id FROM subject"))
    deg, seen = {}, set()

    def emit(src, dst, rtype, weight, same_ev, b2b, label, first, last, evidence):
        if not src or not dst or src == dst or src not in subj or dst not in subj:
            return
        if rtype in ("b2b", "collab") and src > dst:  # undirected -> canonical order
            src, dst = dst, src
        rid = hashlib.sha1(f"{src}|{rtype}|{dst}".encode("utf-8")).hexdigest()[:16]
        if rid in seen:
            return
        seen.add(rid)
        o.execute("INSERT OR IGNORE INTO relation (relation_id, src_subject_id, dst_subject_id, "
                  "relation_type, weight, same_event_count, b2b_count, label_zh, first_seen_at, "
                  "last_seen_at, sample_evidence_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (rid, src, dst, rtype, weight, same_ev, b2b, label, first, last, evidence))
        deg[src] = deg.get(src, 0) + 1
        deg[dst] = deg.get(dst, 0) + 1

    s = sqlite3.connect(f"file:{serving_path}?mode=ro", uri=True)
    s.row_factory = sqlite3.Row
    try:
        for r in s.execute("SELECT src_dj_id,dst_dj_id,relation_score,b2b_count,same_event_count,"
                           "relation_label_zh,sample_evidence_json,first_seen_at,last_seen_at FROM dj_relation_rollup"):
            b = int(r["b2b_count"] or 0)
            emit(r["src_dj_id"], r["dst_dj_id"], "b2b" if b > 0 else "collab", float(r["relation_score"] or 0),
                 int(r["same_event_count"] or 0), b, r["relation_label_zh"], r["first_seen_at"], r["last_seen_at"],
                 r["sample_evidence_json"])
    except Exception:
        pass
    try:
        for r in s.execute("SELECT dj_id,venue_id,score,event_count,first_seen_at,last_seen_at FROM dj_venue_rollup"):
            emit(r["dj_id"], r["venue_id"], "resident_at", float(r["score"] or 0), int(r["event_count"] or 0), 0,
                 "驻场/常演", r["first_seen_at"], r["last_seen_at"], None)
    except Exception:
        pass
    try:
        for r in s.execute("SELECT dj_id,org_id,org_type,score,sample_evidence_json FROM dj_org_rollup"):
            emit(r["dj_id"], r["org_id"], "signed_to", float(r["score"] or 0), 0, 0,
                 f"厂牌/{r['org_type']}" if r["org_type"] else "厂牌/主办", None, None, r["sample_evidence_json"])
    except Exception:
        pass
    s.close()

    for sid, vid, oid, ed in o.execute("SELECT subject_id,venue_subject_id,organizer_subject_id,edition_count "
                                       "FROM series_profile").fetchall():
        if vid:
            emit(sid, vid, "held_at", float(ed or 0), 0, 0, "系列场地", None, None, None)
        if oid:
            emit(sid, oid, "presented_by", float(ed or 0), 0, 0, "系列主办", None, None, None)

    o.executemany("UPDATE subject SET relation_count=? WHERE subject_id=?", [(n, sid) for sid, n in deg.items()])
    return deg


def build(stage3_path, out_path, serving_path=None):
    s = sqlite3.connect(f"file:{stage3_path}?mode=ro", uri=True)
    s.row_factory = sqlite3.Row
    c = s.cursor()

    EV = "resolved_event"
    EP = "event_participant"
    dj_ev = _count_span(c, f"SELECT ep.dj_id, COUNT(DISTINCT ep.event_id), MIN(re.date_start), MAX(re.date_start) "
                           f"FROM {EP} ep JOIN {EV} re ON re.event_id=ep.event_id GROUP BY ep.dj_id")
    ven_ev = _count_span(c, f"SELECT venue_id, COUNT(*), MIN(date_start), MAX(date_start) FROM {EV} "
                            f"WHERE venue_id IS NOT NULL AND venue_id!='' GROUP BY venue_id")
    org_ev = _count_span(c, f"SELECT organizer_id, COUNT(*), MIN(date_start), MAX(date_start) FROM {EV} "
                            f"WHERE organizer_id IS NOT NULL AND organizer_id!='' GROUP BY organizer_id")
    ser_ev = _count_span(c, f"SELECT series_id, COUNT(*), MIN(date_start), MAX(date_start) FROM {EV} "
                            f"WHERE series_id IS NOT NULL AND series_id!='' GROUP BY series_id")
    ven_dj = _distinct(c, f"SELECT re.venue_id, COUNT(DISTINCT ep.dj_id) FROM {EV} re JOIN {EP} ep "
                          f"ON ep.event_id=re.event_id WHERE re.venue_id IS NOT NULL AND re.venue_id!='' GROUP BY re.venue_id")
    org_dj = _distinct(c, f"SELECT re.organizer_id, COUNT(DISTINCT ep.dj_id) FROM {EV} re JOIN {EP} ep "
                          f"ON ep.event_id=re.event_id WHERE re.organizer_id IS NOT NULL AND re.organizer_id!='' GROUP BY re.organizer_id")
    dj_ven = _distinct(c, f"SELECT ep.dj_id, COUNT(DISTINCT re.venue_id) FROM {EP} ep JOIN {EV} re "
                          f"ON re.event_id=ep.event_id WHERE re.venue_id IS NOT NULL AND re.venue_id!='' GROUP BY ep.dj_id")
    dj_org = _distinct(c, f"SELECT ep.dj_id, COUNT(DISTINCT re.organizer_id) FROM {EP} ep JOIN {EV} re "
                          f"ON re.event_id=ep.event_id WHERE re.organizer_id IS NOT NULL AND re.organizer_id!='' GROUP BY ep.dj_id")

    # series -> dominant venue / organizer (single pass over events)
    ser_v, ser_o = {}, {}
    for r in c.execute(f"SELECT series_id, venue_id, organizer_id FROM {EV} WHERE series_id IS NOT NULL AND series_id!=''"):
        if r["venue_id"]:
            ser_v.setdefault(r["series_id"], {}).update()
            ser_v[r["series_id"]][r["venue_id"]] = ser_v[r["series_id"]].get(r["venue_id"], 0) + 1
        if r["organizer_id"]:
            ser_o.setdefault(r["series_id"], {})
            ser_o[r["series_id"]][r["organizer_id"]] = ser_o[r["series_id"]].get(r["organizer_id"], 0) + 1
    dom = lambda d: max(d.items(), key=lambda kv: kv[1])[0] if d else None

    aliases = {}
    try:
        for r in c.execute("SELECT * FROM alias"):
            d = dict(r)
            eid = d.get("entity_id") or d.get("canonical_entity_id") or d.get("canonical_id")
            al = d.get("alias") or d.get("alias_text") or d.get("name") or d.get("surface")
            if eid and al:
                aliases.setdefault(eid, set()).add(al)
    except Exception:
        pass

    ents = c.execute("SELECT entity_id, type, canonical_name, name_en, city, attrs_json, "
                     "status, source_article_count, max_confidence FROM canonical_entity").fetchall()
    s.close()

    Path(out_path).unlink(missing_ok=True)
    out = sqlite3.connect(out_path)
    o = out.cursor()
    o.executescript(DDL)
    counts = {"dj": 0, "venue": 0, "org": 0, "series": 0, "other": 0}

    for e in ents:
        t = e["type"]
        eid = e["entity_id"]
        attrs = {}
        if e["attrs_json"]:
            try:
                attrs = json.loads(e["attrs_json"]) or {}
            except Exception:
                attrs = {}
        span = {"dj": dj_ev, "venue": ven_ev, "org": org_ev, "series": ser_ev}.get(t, {}).get(eid)
        ec = span[0] if span else 0
        first_seen = span[1] if span else None
        last_seen = span[2] if span else None
        al = sorted(aliases.get(eid, []))
        o.execute(
            "INSERT INTO subject (subject_id, subject_type, display_name, normalized_name, name_en, "
            "aliases_json, city_primary, event_count, relation_count, source_count, confidence, "
            "first_seen_at, last_seen_at, taxon_path) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (eid, t, e["canonical_name"], _norm(e["canonical_name"]), e["name_en"], _j(al), e["city"],
             ec, 0, e["source_article_count"], e["max_confidence"], first_seen, last_seen, f"atlas/{t}"))

        if t == "dj":
            o.execute(
                "INSERT INTO dj_profile (subject_id, name_en, nationality, origin_city, roles_json, "
                "styles_json, genre, social_json, gear, bio_snippet, affiliations_json, venue_count, org_count) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, e["name_en"], attrs.get("nationality"), attrs.get("origin_city"),
                 _j(attrs.get("roles")), _j(attrs.get("styles")), attrs.get("genre"),
                 _j(attrs.get("social")), attrs.get("gear"), attrs.get("bio_snippet"),
                 _j(attrs.get("affiliations")), dj_ven.get(eid, 0), dj_org.get(eid, 0)))
            counts["dj"] += 1
        elif t == "venue":
            geo = attrs.get("geo") if isinstance(attrs.get("geo"), dict) else {}
            o.execute(
                "INSERT INTO venue_profile (subject_id, name_en, city, district, address, geo_lat, geo_lng, "
                "venue_type, rooms, capacity, booth_gear_json, sound_brand_json, social_json, "
                "resident_dj_count, event_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, e["name_en"], e["city"], attrs.get("district"), attrs.get("address"),
                 _num(geo.get("lat")), _num(geo.get("lng")), attrs.get("venue_type"),
                 attrs.get("rooms"), attrs.get("capacity"), _j(attrs.get("booth_gear")),
                 _j(attrs.get("sound_brand")), _j(attrs.get("social")), ven_dj.get(eid, 0), ec))
            counts["venue"] += 1
        elif t == "org":
            o.execute(
                "INSERT INTO org_profile (subject_id, org_type, city, social_json, roster_count, event_count) "
                "VALUES (?,?,?,?,?,?)",
                (eid, attrs.get("org_type"), e["city"], _j(attrs.get("social")), org_dj.get(eid, 0), ec))
            counts["org"] += 1
        elif t == "series":
            o.execute(
                "INSERT INTO series_profile (subject_id, venue_subject_id, organizer_subject_id, concept, edition_count) "
                "VALUES (?,?,?,?,?)",
                (eid, dom(ser_v.get(eid, {})), dom(ser_o.get(eid, {})), attrs.get("concept"), ec))
            counts["series"] += 1
        else:
            counts["other"] += 1

    rel_total = 0
    if serving_path:
        _build_relations(out, serving_path)
        rel_total = out.execute("SELECT COUNT(*) FROM relation").fetchone()[0]

    meta = {"schema_version": SCHEMA_VERSION, "source": str(stage3_path),
            "serving_source": str(serving_path or ""), "relation_count": str(rel_total),
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "counts": json.dumps(counts, ensure_ascii=False)}
    for k, v in meta.items():
        o.execute("INSERT INTO meta VALUES (?,?)", (k, str(v)))
    out.commit()
    _validate(out)
    out.close()
    return counts


def _validate(conn):
    c = conn.cursor()
    subj = c.execute("SELECT COUNT(*) FROM subject").fetchone()[0]
    assert subj > 0, "no subjects"
    by_type = dict(c.execute("SELECT subject_type, COUNT(*) FROM subject GROUP BY subject_type").fetchall())
    # every profile row must point at a subject of the right type
    for tbl, typ in [("dj_profile", "dj"), ("venue_profile", "venue"), ("org_profile", "org"), ("series_profile", "series")]:
        prof = c.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
        assert prof == by_type.get(typ, 0), f"{tbl} ({prof}) != subject {typ} ({by_type.get(typ, 0)})"
        orphan = c.execute(f"SELECT COUNT(*) FROM {tbl} p LEFT JOIN subject s ON s.subject_id=p.subject_id "
                           f"WHERE s.subject_id IS NULL").fetchone()[0]
        assert orphan == 0, f"{tbl} has {orphan} orphan rows"
    # series FKs (when set) must resolve to a subject
    bad = c.execute("SELECT COUNT(*) FROM series_profile sp WHERE sp.venue_subject_id IS NOT NULL "
                    "AND sp.venue_subject_id NOT IN (SELECT subject_id FROM subject)").fetchone()[0]
    assert bad == 0, f"{bad} series venue FKs dangling"
    rels = c.execute("SELECT COUNT(*) FROM relation").fetchone()[0]
    if rels:
        bad_rel = c.execute("SELECT COUNT(*) FROM relation r WHERE r.src_subject_id NOT IN "
                            "(SELECT subject_id FROM subject) OR r.dst_subject_id NOT IN "
                            "(SELECT subject_id FROM subject)").fetchone()[0]
        assert bad_rel == 0, f"{bad_rel} relation endpoints not in subject"
        assert c.execute("SELECT COUNT(*) FROM relation WHERE src_subject_id=dst_subject_id").fetchone()[0] == 0, "self-relation"
    return by_type


def _selftest():
    import tempfile, os
    fd, p = tempfile.mkstemp(suffix=".sqlite"); os.close(fd)
    s = sqlite3.connect(p); c = s.cursor()
    c.execute("CREATE TABLE canonical_entity(entity_id TEXT,type TEXT,canonical_name TEXT,name_en TEXT,city TEXT,attrs_json TEXT,status TEXT,source_article_count INT,max_confidence REAL)")
    c.execute("CREATE TABLE resolved_event(event_id TEXT,source_token TEXT,title TEXT,date_start TEXT,date_end TEXT,time_text TEXT,city TEXT,venue_id TEXT,series_id TEXT,organizer_id TEXT,confidence REAL,json TEXT,genre TEXT)")
    c.execute("CREATE TABLE event_participant(event_id TEXT,dj_id TEXT,role TEXT,performance_type TEXT)")
    c.execute("CREATE TABLE alias(entity_id TEXT,alias TEXT)")
    rows = [
        ("dj:1", "dj", "NORA", "NORA", "上海", '{"roles":["dj"],"styles":["techno"],"social":{"instagram":"nora"}}', "active", 5, 1.0),
        ("ven:1", "venue", "ALL Club", "ALL", "上海", '{"district":"黄浦","venue_type":"club","geo":{"lat":31.2,"lng":121.4},"capacity":"300"}', "active", 8, 1.0),
        ("org:1", "org", "FLAT", None, "上海", '{"org_type":"label"}', "active", 3, 1.0),
        ("ser:1", "series", "DEEP", None, "上海", '{"concept":"deep nights"}', "active", 2, 1.0),
    ]
    c.executemany("INSERT INTO canonical_entity VALUES(?,?,?,?,?,?,?,?,?)", rows)
    c.execute("INSERT INTO resolved_event VALUES('e1','t','Night','2025-03-01','','','上海','ven:1','ser:1','org:1',1.0,'{}','techno')")
    c.execute("INSERT INTO resolved_event VALUES('e2','t','Night2','2025-06-01','','','上海','ven:1','ser:1','org:1',1.0,'{}','techno')")
    c.execute("INSERT INTO event_participant VALUES('e1','dj:1','headliner','dj_set')")
    c.execute("INSERT INTO event_participant VALUES('e2','dj:1','headliner','dj_set')")
    c.execute("INSERT INTO alias VALUES('ven:1','ALL 俱乐部')")
    s.commit(); s.close()
    outp = p + ".v2.sqlite"
    counts = build(p, outp)
    v = sqlite3.connect(outp); vc = v.cursor()
    assert counts == {"dj": 1, "venue": 1, "org": 1, "series": 1, "other": 0}, counts
    assert vc.execute("SELECT event_count FROM venue_profile WHERE subject_id='ven:1'").fetchone()[0] == 2
    assert vc.execute("SELECT resident_dj_count FROM venue_profile WHERE subject_id='ven:1'").fetchone()[0] == 1
    assert vc.execute("SELECT geo_lat FROM venue_profile WHERE subject_id='ven:1'").fetchone()[0] == 31.2
    assert vc.execute("SELECT venue_subject_id FROM series_profile WHERE subject_id='ser:1'").fetchone()[0] == "ven:1"
    assert vc.execute("SELECT edition_count FROM series_profile WHERE subject_id='ser:1'").fetchone()[0] == 2
    assert vc.execute("SELECT first_seen_at,last_seen_at FROM subject WHERE subject_id='dj:1'").fetchone() == ("2025-03-01", "2025-06-01")
    assert "ALL 俱乐部" in (vc.execute("SELECT aliases_json FROM subject WHERE subject_id='ven:1'").fetchone()[0] or "")
    v.close(); os.remove(p); os.remove(outp)
    print("selftest OK:", counts)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage3", default="_fleet_14w_g5_80k_increment_20260620/merged/entities_resolved.sqlite")
    ap.add_argument("--out", default="_fleet_14w_g5_80k_increment_20260620/merged/atlas_serving_v2.sqlite")
    ap.add_argument("--serving", default="_fleet_14w_g5_80k_increment_20260620/merged/atlas_serving_candidate.sqlite",
                    help="Stage4 candidate for relation unification; pass '' to skip (subjects only)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        _selftest(); return
    counts = build(a.stage3, a.out, serving_path=a.serving or None)
    print(f"wrote {a.out}")
    print("  subjects by type:", counts)
    conn = sqlite3.connect(f"file:{a.out}?mode=ro", uri=True)
    rels = conn.execute("SELECT relation_type, COUNT(*) FROM relation GROUP BY relation_type ORDER BY 2 DESC").fetchall()
    print("  relations by type:", dict(rels), "total", sum(n for _, n in rels))
    conn.close()


if __name__ == "__main__":
    main()
