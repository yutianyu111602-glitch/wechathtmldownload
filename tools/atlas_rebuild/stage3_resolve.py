"""Stage 3 — Entity resolution / canonicalization.

Reads rich extractions (machine `extractions.sqlite` and/or `gold.sqlite`),
resolves DJ / venue / org / series surface forms to canonical type-scoped IDs
(dj:slug / venue:slug / org:slug / series:slug), keeps all rich attributes, and
links events to participants. Deterministic normalized-name merge; genuinely
ambiguous cases go to a merge_queue (no silent bad merges).

Writes entities_resolved.sqlite. Idempotent (re-run reloads existing aliases).

Usage:
  python stage3_resolve.py --source gold          # gold|extractions|both
"""
from __future__ import annotations
import argparse
import difflib
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
import genre_filter

DB = config.DB_RESOLVED
SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_entity (
  entity_id TEXT PRIMARY KEY, type TEXT, canonical_name TEXT, name_en TEXT,
  city TEXT, attrs_json TEXT,
  status TEXT DEFAULT 'candidate',
  source_article_count INTEGER DEFAULT 0,
  max_confidence REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS alias (
  surface_norm TEXT, type TEXT, entity_id TEXT, surface_raw TEXT,
  PRIMARY KEY (surface_norm, type));
CREATE TABLE IF NOT EXISTS resolved_event (
  event_id TEXT PRIMARY KEY, source_token TEXT, title TEXT,
  date_start TEXT, date_end TEXT, time_text TEXT, city TEXT, venue_id TEXT,
  series_id TEXT, organizer_id TEXT, confidence REAL, json TEXT,
  genre TEXT DEFAULT 'unknown');
CREATE TABLE IF NOT EXISTS event_source (
  event_id TEXT, source_token TEXT, event_index INTEGER, confidence REAL,
  PRIMARY KEY (event_id, source_token, event_index));
CREATE TABLE IF NOT EXISTS event_participant (
  event_id TEXT, dj_id TEXT, role TEXT, performance_type TEXT,
  PRIMARY KEY (event_id, dj_id));
CREATE TABLE IF NOT EXISTS dj_affiliation (
  dj_id TEXT, org_id TEXT, PRIMARY KEY (dj_id, org_id));
CREATE TABLE IF NOT EXISTS dj_b2b (
  dj_a TEXT, dj_b TEXT, event_id TEXT, PRIMARY KEY (dj_a, dj_b, event_id));
CREATE TABLE IF NOT EXISTS merge_queue (
  surface_norm TEXT, type TEXT, existing_id TEXT, new_name TEXT, reason TEXT);
"""

SCHEMA_MIGRATIONS = {
    "canonical_entity": (
        ("status", "TEXT DEFAULT 'candidate'"),
        ("source_article_count", "INTEGER DEFAULT 0"),
        ("max_confidence", "REAL DEFAULT 0"),
    ),
    "resolved_event": (
        ("genre", "TEXT DEFAULT 'unknown'"),
    ),
}

_PUNC = re.compile(
    r"[\s·・·.,!?\"'’“”（）()\[\]{}|/\\@#&*\-_:：，。！？、"
    r"\ufe0e\ufe0f\U0001f300-\U0001faff]+"
)


def norm(s):
    return _PUNC.sub("", (s or "").strip().lower())


def slug(s, n=40):
    return norm(s)[:n] or "x"


def _hash(value: str, n=16) -> str:
    import hashlib
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:n]


_SANITY_REJECT_KEYWORDS = re.compile(
    r"门票|票价|rmb|http|www|时间|地址|¥|￥|预售|购票|阵容",
    re.IGNORECASE,
)
_DATE_OR_TIME_RE = re.compile(
    r"(?<!\w)(?:19|20)\d{2}[-/.年]\d{1,2}(?:[-/.月]\d{1,2}日?)?(?!\w)"
    r"|(?<!\w)\d{1,2}[-/.月]\d{1,2}(?:日)?(?!\w)"
    r"|(?<!\w)\d{1,2}:\d{2}(?::\d{2})?(?!\w)"
    r"|周[一二三四五六日天]"
)
_PLACEHOLDER_NAME_NORMS = {
    "未明确", "未明确说明", "未知", "不详", "待定", "待公布", "敬请期待",
    # 旧库抽样 ~16% 噪声，占位「嘉宾」类是大头（exact-norm 匹配，不误伤真名）
    "神秘嘉宾", "神秘", "嘉宾", "特邀嘉宾", "神秘dj", "惊喜嘉宾", "神秘客人",
    "unknown", "unk", "na", "none", "null", "tbd", "tba",
    "guest", "specialguest", "surpriseguest", "mysteryguest", "secretguest", "surprise",
}
_B2B_MARKER_RE = re.compile(
    r"(^|[\s\-_/\\|:+（(])(?:b\s*2\s*b|back\s*[- ]?to\s*[- ]?back)(?=$|[\s\-_/\\|:+）).,!！?？])",
    re.IGNORECASE,
)


def _sanity_reject(name: str) -> bool:
    """Return True if the name should be rejected before any trust voting.

    Catches empty, single-char, pure-digit, pure-punctuation, known junk
    keywords, obvious date patterns, pure emoji, and garbage that normalises
    to nothing.
    """
    if not name:
        return True
    n = (name or "").strip()
    if len(n) == 0 or len(n) > 40:
        return True
    if len(n) == 1 and not n.isalnum():
        return True
    if n.isdigit():
        return True
    # Pure punctuation / symbols only
    clean = "".join(ch for ch in n if ch.isalnum())
    if not clean:
        return True
    if _SANITY_REJECT_KEYWORDS.search(n):
        return True
    if _DATE_OR_TIME_RE.search(n):
        return True
    # Normalise and check for usable characters
    normed = norm(n)
    if not normed:
        return True
    if normed in _PLACEHOLDER_NAME_NORMS:
        return True
    # A standalone b2b/back-to-back marker is a relation, not a person/venue/org/series.
    # Legitimate two-sided lineup cells are split before this fallback path.
    if _B2B_MARKER_RE.search(n):
        return True
    return False


def _usable_alias_surface(surface: str) -> bool:
    sn = norm(surface)
    return bool(sn) and sn not in _PLACEHOLDER_NAME_NORMS


_B2B_COMPOUND_RE = re.compile(
    r"\s+(?:b\s*2\s*b|back\s*[- ]?to\s*[- ]?back)\s+",
    re.IGNORECASE,
)


def _split_compound_b2b_name(name: str) -> list[str]:
    """Split a single lineup cell like "Alpha b2b Beta" into DJ endpoints.

    This is deliberately narrow: only a two-sided explicit b2b/back-to-back
    separator is split. Other compound-looking names stay intact for review.
    """
    raw = (name or "").strip()
    if not raw:
        return []
    if _B2B_MARKER_RE.search(raw) and any(ch in raw for ch in "()（）"):
        return []
    parts = [p.strip() for p in _B2B_COMPOUND_RE.split(raw) if p.strip()]
    if len(parts) == 2 and all(not _sanity_reject(p) for p in parts):
        return parts
    return [raw] if not _sanity_reject(raw) else []


def _lineup_member_names(member: dict) -> list[str]:
    if not isinstance(member, dict):
        return []
    return _split_compound_b2b_name(member.get("name") or "")


def ensure_schema_migrations(con):
    """Add columns introduced after early canary DBs were created."""
    for table, columns in SCHEMA_MIGRATIONS.items():
        existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns:
            if name not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _event_identity_key(ev, venue_id, series_id, organizer_id, token, index):
    """Stable event identity across reposts while avoiding unsafe no-date merges."""
    date_start = (ev.get("date_start") or "").strip()
    date_end = (ev.get("date_end") or "").strip()
    date = f"{date_start}|{date_end}" if date_start or date_end else ""
    title = norm(ev.get("title"))
    city = norm(ev.get("city"))
    venue = venue_id or norm(ev.get("venue"))
    org = organizer_id or series_id or norm(ev.get("organizer") or ev.get("series_name"))
    lineup = sorted({
        norm(member_name)
        for m in (ev.get("lineup") or [])
        for member_name in _lineup_member_names(m)
        if norm(member_name)
    })
    lineup_key = ",".join(lineup[:16])

    if date and venue and lineup_key:
        return "date_venue_lineup|" + "|".join([date, venue, _hash(lineup_key), org])
    if date and title and lineup_key:
        return "date_title_lineup|" + "|".join([date, title, _hash(lineup_key), city, org])
    if date and venue and title:
        return "date_venue_title|" + "|".join([date, venue, title, org])
    if date and title:
        return "date_title|" + "|".join([date, title, city, org])
    # Missing-date rows are too risky to merge automatically. They stay
    # source-scoped and remain visible for review rather than polluting stats.
    return f"source_scoped|{token}|{index}|{title}"


def _event_id_from_key(key):
    return f"event:{_hash(key, 20)}"


def _richness(ev):
    score = 0
    for k, v in (ev or {}).items():
        if v in (None, "", [], {}):
            continue
        if isinstance(v, list):
            score += len(v) * 3
        elif isinstance(v, dict):
            score += len([x for x in v.values() if x not in (None, "", [], {})]) * 2
        else:
            score += 1
    try:
        score += int(float(ev.get("confidence") or 0) * 10)
    except Exception:
        pass
    return score


def _merge_list(dst, src):
    seen = {json.dumps(x, ensure_ascii=False, sort_keys=True) for x in dst if x not in (None, "", [], {})}
    out = [x for x in dst if x not in (None, "", [], {})]
    for item in src:
        if item in (None, "", [], {}):
            continue
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _merge_event_json(old, new):
    merged = dict(old or {})
    for k, v in (new or {}).items():
        if v in (None, "", [], {}):
            continue
        cur = merged.get(k)
        if cur in (None, "", [], {}):
            merged[k] = v
        elif isinstance(cur, list) and isinstance(v, list):
            merged[k] = _merge_list(cur, v)
        elif isinstance(cur, dict) and isinstance(v, dict):
            m = dict(cur)
            for kk, vv in v.items():
                if vv not in (None, "", [], {}) and m.get(kk) in (None, "", [], {}):
                    m[kk] = vv
            merged[k] = m
        elif isinstance(cur, str) and isinstance(v, str) and len(v) > len(cur) * 1.4:
            merged[k] = v
    try:
        merged["confidence"] = max(float(old.get("confidence") or 0), float(new.get("confidence") or 0))
    except Exception:
        pass
    return merged


class Resolver:
    """Type-scoped canonical registry, persisted; idempotent across runs."""

    def __init__(self, con):
        self.con = con
        self.alias = {}      # (norm,type) -> entity_id
        self.ents = {}       # entity_id -> dict(attrs merged)
        self.merge_queue = []
        self.merge_queue_keys = set()
        for sn, t, eid in con.execute("SELECT surface_norm,type,entity_id FROM alias"):
            self.alias[(sn, t)] = eid
        for eid, t, cn, en, city, attrs in con.execute(
                "SELECT entity_id,type,canonical_name,name_en,city,attrs_json FROM canonical_entity"):
            self.ents[eid] = {"type": t, "canonical_name": cn, "name_en": en, "city": city,
                              "attrs": json.loads(attrs or "{}")}

    def resolve(self, name, etype, attrs=None, name_en=None, city=None):
        name = (name or "").strip()
        if not name or _sanity_reject(name):
            return None
        key = (norm(name), etype)
        eid = self.alias.get(key)
        if eid is None:
            eid = f"{etype}:{slug(name)}"
            if eid in self.ents and norm(self.ents[eid]["canonical_name"]) != key[0]:
                eid = f"{etype}:{slug(name)}-{abs(hash(name)) % 9973}"   # rare slug collision
            self.ents.setdefault(eid, {"type": etype, "canonical_name": name,
                                       "name_en": name_en, "city": city, "attrs": {}})
            self._register_alias(name, etype, eid, reason="canonical")
        ent = self.ents[eid]
        # enrich (don't overwrite good values with empty)
        if name_en and not ent.get("name_en"):
            ent["name_en"] = name_en
        if city and not ent.get("city"):
            ent["city"] = city
        if attrs:
            self._merge_attrs(ent["attrs"], attrs)
        self._register_declared_aliases(eid, etype, ent.get("attrs"), ent.get("name_en"))
        return eid

    def _queue_merge(self, surface_norm, etype, existing_id, new_name, reason):
        if not surface_norm or not etype or not existing_id or not new_name:
            return
        key = (surface_norm, etype, existing_id, new_name, reason)
        if key in self.merge_queue_keys:
            return
        self.merge_queue_keys.add(key)
        self.merge_queue.append(key)

    def _register_alias(self, surface, etype, eid, reason="alias"):
        sn = norm(surface)
        if not _usable_alias_surface(surface):
            return
        key = (sn, etype)
        existing = self.alias.get(key)
        if existing and existing != eid:
            self._queue_merge(sn, etype, existing, surface, f"{reason}_conflict:{eid}")
            return
        self.alias[key] = eid

    def _register_declared_aliases(self, eid, etype, attrs=None, name_en=None):
        ent = self.ents.get(eid, {})
        canonical_norm = norm(ent.get("canonical_name"))
        aliases = (attrs or {}).get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if isinstance(aliases, list):
            for alias in aliases:
                if alias:
                    self._register_alias(alias, etype, eid, reason="declared_alias")
        if name_en and norm(name_en) and norm(name_en) != canonical_norm:
            self._register_alias(name_en, etype, eid, reason="name_en")

    @staticmethod
    def _fuzzy_reason(a, b):
        a_name = norm(a.get("canonical_name"))
        b_name = norm(b.get("canonical_name"))
        if not a_name or not b_name or a_name == b_name:
            return None
        a_en = norm(a.get("name_en"))
        b_en = norm(b.get("name_en"))
        if (a_en and b_en and a_en == b_en and
                _usable_alias_surface(a.get("name_en")) and
                _usable_alias_surface(b.get("name_en"))):
            return "fuzzy:name_en_equal"
        ratio = difflib.SequenceMatcher(None, a_name, b_name).ratio()
        ratio_min = float(os.environ.get("ATLAS_STAGE3_FUZZY_RATIO_MIN", "0.90"))
        if ratio >= ratio_min:
            return f"fuzzy:ratio={ratio:.2f}"
        short, long = sorted((a_name, b_name), key=len)
        if len(short) >= 3 and short in long and (len(short) / len(long)) > 0.6:
            return f"fuzzy:substring={len(short)}/{len(long)}"
        return None

    @staticmethod
    def _fuzzy_bucket_keys(name_norm):
        """Cheap blocking keys for advisory merge_queue candidates."""
        if not name_norm:
            return ()
        keys = {f"p:{name_norm[:4]}", f"s:{name_norm[-4:]}"}
        if len(name_norm) <= 6:
            keys.add(f"w:{name_norm}")
        if len(name_norm) >= 3:
            if len(name_norm) <= 12:
                for i in range(len(name_norm) - 2):
                    keys.add(f"g:{name_norm[i:i + 3]}")
            else:
                step = max(1, (len(name_norm) - 3) // 6)
                for i in range(0, len(name_norm) - 2, step):
                    keys.add(f"g:{name_norm[i:i + 3]}")
                keys.add(f"g:{name_norm[-3:]}")
        return tuple(keys)

    def _queue_fuzzy_dups(self):
        by_type = defaultdict(list)
        for eid, ent in self.ents.items():
            by_type[ent.get("type")].append((eid, ent))
        for etype, rows in by_type.items():
            rows = sorted(rows, key=lambda item: (norm(item[1].get("canonical_name")), item[0]))
            if len(rows) < 2:
                continue

            # merge_queue is advisory; avoid the old O(n^2) full scan on 14w union.
            max_bucket = int(os.environ.get("ATLAS_STAGE3_FUZZY_BUCKET_MAX", "500"))
            max_pairs = int(os.environ.get("ATLAS_STAGE3_FUZZY_MAX_PAIRS", "3000000"))
            neighbor_window = int(os.environ.get("ATLAS_STAGE3_FUZZY_NEIGHBOR_WINDOW", "8"))
            candidates = set()
            budget_hit = False

            def add_pair(i, j):
                nonlocal budget_hit
                if i == j:
                    return
                if i > j:
                    i, j = j, i
                if len(candidates) >= max_pairs:
                    budget_hit = True
                    return
                candidates.add((i, j))

            for i in range(len(rows)):
                end = min(len(rows), i + 1 + neighbor_window)
                for j in range(i + 1, end):
                    add_pair(i, j)

            name_en_groups = defaultdict(list)
            buckets = defaultdict(list)
            for i, (_eid, ent) in enumerate(rows):
                name_raw = ent.get("canonical_name")
                name_norm = norm(name_raw)
                en_raw = ent.get("name_en")
                en_norm = norm(en_raw)
                if en_norm and _usable_alias_surface(en_raw):
                    name_en_groups[en_norm].append(i)
                for key in self._fuzzy_bucket_keys(name_norm):
                    buckets[key].append(i)

            skipped_big_buckets = 0
            for group in name_en_groups.values():
                if len(group) > max_bucket:
                    skipped_big_buckets += 1
                    continue
                for pos, i in enumerate(group):
                    for j in group[pos + 1:]:
                        add_pair(i, j)

            for group in buckets.values():
                if len(group) < 2:
                    continue
                if len(group) > max_bucket:
                    skipped_big_buckets += 1
                    continue
                for pos, i in enumerate(group):
                    for j in group[pos + 1:]:
                        add_pair(i, j)
                if budget_hit:
                    break

            print(
                "Stage3 fuzzy blocking:"
                f" type={etype} rows={len(rows)} candidates={len(candidates)}"
                f" skipped_big_buckets={skipped_big_buckets} budget_hit={int(budget_hit)}",
                file=sys.stderr,
            )
            for i, j in sorted(candidates):
                left_id, left = rows[i]
                right_id, right = rows[j]
                reason = self._fuzzy_reason(left, right)
                if not reason:
                    continue
                new_name = right.get("canonical_name") or right_id
                self._queue_merge(norm(new_name), etype, left_id, new_name, reason)

    @staticmethod
    def _merge_attrs(dst, src):
        for k, v in (src or {}).items():
            if v in (None, "", [], {}):
                continue
            if isinstance(v, list):
                cur = dst.setdefault(k, [])
                for it in v:
                    if it not in cur:
                        cur.append(it)
            elif isinstance(v, dict):
                self_merge = dst.setdefault(k, {})
                for kk, vv in v.items():
                    if vv not in (None, "", [], {}) and not self_merge.get(kk):
                        self_merge[kk] = vv
            else:
                dst.setdefault(k, v)

    def flush(self):
        c = self.con
        self._queue_fuzzy_dups()
        c.execute("DELETE FROM canonical_entity")
        c.execute("DELETE FROM alias")
        for eid, e in self.ents.items():
            c.execute("INSERT OR REPLACE INTO canonical_entity VALUES (?,?,?,?,?,?,?,?,?)",
                      (eid, e["type"], e["canonical_name"], e.get("name_en"), e.get("city"),
                       json.dumps(e["attrs"], ensure_ascii=False),
                       e.get("status", "candidate"),
                       e.get("source_article_count", 0),
                       e.get("max_confidence", 0.0)))
        for (sn, t), eid in self.alias.items():
            c.execute("INSERT OR REPLACE INTO alias VALUES (?,?,?,?)", (sn, t, eid, sn))
        for row in self.merge_queue:
            c.execute("INSERT INTO merge_queue VALUES (?,?,?,?,?)", row)
        c.commit()


def iter_payloads(source):
    seen = set()
    for which, path, col in (("gold", os.path.join(config.WORK_DIR, "gold.sqlite"), "payload"),
                             ("extractions", config.DB_EXTRACT, "payload")):
        if source not in (which, "both"):
            continue
        if not os.path.exists(path):
            continue
        c = sqlite3.connect(path)
        tbl = "gold" if which == "gold" else "extractions"
        where = "" if which == "gold" else " WHERE status='extracted' AND valid=1"
        for tok, payload in c.execute(f"SELECT token,{col} FROM {tbl}{where}"):
            if not payload or tok in seen:
                continue
            seen.add(tok)
            yield tok, json.loads(payload)
        c.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="gold", choices=["gold", "extractions", "both"])
    args = ap.parse_args()

    config.ensure_dirs()
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    ensure_schema_migrations(con)
    for table in ("resolved_event", "event_source", "event_participant", "dj_affiliation", "dj_b2b", "merge_queue"):
        con.execute(f"DELETE FROM {table}")
    R = Resolver(con)

    n_ev = n_part = n_b2b = 0
    event_cache = {}
    source_edges = 0
    for token, payload in iter_payloads(args.source):
        ents = payload.get("entities", {})
        # register rich entities first (best attributes)
        for d in ents.get("djs", []):
            R.resolve(d["surface"], "dj", attrs={k: d.get(k) for k in
                      ("aliases", "nationality", "origin_city", "roles", "affiliations",
                       "styles", "social", "gear", "bio_snippet")},
                      name_en=d.get("name_en"), city=d.get("origin_city"))
        for v in ents.get("venues", []):
            R.resolve(v["surface"], "venue", attrs={k: v.get(k) for k in
                      ("district", "address", "venue_type", "booth_gear", "sound_brand",
                       "resident_djs", "social")},
                      name_en=v.get("name_en"), city=v.get("city"))
        for o in ents.get("orgs", []):
            R.resolve(o["surface"], "org", attrs={k: o.get(k) for k in ("org_type", "roster", "social")},
                      city=o.get("city"))
        for s in ents.get("series", []):
            R.resolve(s["surface"], "series", attrs={k: s.get(k) for k in ("venue", "organizer", "concept")})
        # affiliations -> orgs + dj_affiliation edges
        for d in ents.get("djs", []):
            dj_id = R.resolve(d["surface"], "dj")
            if not dj_id:
                continue
            for aff in d.get("affiliations", []) or []:
                org_id = R.resolve(aff, "org", attrs={"org_type": "label"})
                if org_id:
                    con.execute("INSERT OR IGNORE INTO dj_affiliation VALUES (?,?)", (dj_id, org_id))

        for i, ev in enumerate(payload.get("events", [])):
            venue_id = R.resolve(ev.get("venue"), "venue", city=ev.get("city")) if ev.get("venue") else None
            series_id = R.resolve(ev.get("series_name"), "series") if ev.get("series_name") else None
            org_id = R.resolve(ev.get("organizer"), "org") if ev.get("organizer") else None
            identity_key = _event_identity_key(ev, venue_id, series_id, org_id, token, i)
            event_id = _event_id_from_key(identity_key)
            ev_json = dict(ev)
            ev_json["_dedup_key"] = identity_key
            prev = event_cache.get(event_id)
            if prev:
                merged_json = _merge_event_json(prev["json"], ev_json)
                if _richness(ev_json) > prev["richness"]:
                    source_token = token
                    base = ev
                    base_venue_id, base_series_id, base_org_id = venue_id, series_id, org_id
                else:
                    source_token = prev["source_token"]
                    base = prev["base"]
                    base_venue_id = prev["venue_id"]
                    base_series_id = prev["series_id"]
                    base_org_id = prev["org_id"]
                event_cache[event_id] = {
                    "json": merged_json,
                    "source_token": source_token,
                    "base": base,
                    "venue_id": base_venue_id,
                    "series_id": base_series_id,
                    "org_id": base_org_id,
                    "richness": max(prev["richness"], _richness(ev_json)),
                }
            else:
                merged_json = ev_json
                source_token = token
                base = ev
                base_venue_id, base_series_id, base_org_id = venue_id, series_id, org_id
                event_cache[event_id] = {
                    "json": merged_json,
                    "source_token": source_token,
                    "base": base,
                    "venue_id": base_venue_id,
                    "series_id": base_series_id,
                    "org_id": base_org_id,
                    "richness": _richness(ev_json),
                }
            # Compute genre from styles + title (卡 G)
            event_styles = [s for s in (base.get("styles") or []) if s]
            event_styles.append(base.get("genre") or "")
            lineup_styles = []
            for m in base.get("lineup", []) or []:
                if isinstance(m, dict):
                    ss = m.get("styles") or []
                    lineup_styles.extend(ss if isinstance(ss, list) else [])
            all_styles = [s for s in (event_styles + lineup_styles) if s and s.strip()]
            text_blob = base.get("title") or ""
            genre_val, genre_reason = genre_filter.genre_of(all_styles, text_blob)
            merged_json["genre"] = genre_val
            merged_json["genre_reason"] = genre_reason
            con.execute("INSERT OR REPLACE INTO resolved_event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (event_id, source_token, base.get("title"), base.get("date_start"), base.get("date_end"),
                         base.get("time_text"), base.get("city"), base_venue_id, base_series_id, base_org_id,
                         merged_json.get("confidence", 0.0), json.dumps(merged_json, ensure_ascii=False),
                         genre_val))
            con.execute("INSERT OR IGNORE INTO event_source VALUES (?,?,?,?)",
                        (event_id, token, i, ev.get("confidence", 0.0)))
            source_edges += 1
            if not prev:
                n_ev += 1
            name_to_djid = {}
            compound_b2b_pairs = set()
            for m in ev.get("lineup", []):
                if not isinstance(m, dict) or not m.get("name"):
                    continue
                member_names = _lineup_member_names(m)
                member_ids = []
                for member_name in member_names:
                    dj_id = R.resolve(member_name, "dj", name_en=m.get("name_en") if len(member_names) == 1 else None,
                                      attrs={"roles": ["dj"], "styles": m.get("styles")})
                    if not dj_id:
                        continue
                    name_to_djid[norm(member_name)] = dj_id
                    if len(member_names) == 1:
                        name_to_djid[norm(m.get("name"))] = dj_id
                        if m.get("name_en"):
                            name_to_djid[norm(m.get("name_en"))] = dj_id
                    cur = con.execute("INSERT OR IGNORE INTO event_participant VALUES (?,?,?,?)",
                                      (event_id, dj_id, m.get("role", "unknown"), m.get("performance_type", "unknown")))
                    n_part += int(cur.rowcount > 0)
                    member_ids.append(dj_id)
                if len(member_ids) >= 2:
                    for xi in range(len(member_ids)):
                        for yi in range(xi + 1, len(member_ids)):
                            if member_ids[xi] != member_ids[yi]:
                                compound_b2b_pairs.add(tuple(sorted((member_ids[xi], member_ids[yi]))))
            # b2b capture（★ DJ-DJ 最强边）：lineup.b2b_with + event.b2b_sets，只在已解析阵容内配对（不造新实体）
            b2b_pairs = set(compound_b2b_pairs)
            for m in ev.get("lineup", []) or []:
                if not isinstance(m, dict):
                    continue
                a_ids = [name_to_djid.get(norm(n)) for n in _lineup_member_names(m)]
                a_ids = [x for x in a_ids if x]
                for partner in (m.get("b2b_with") or []):
                    b_ids = [name_to_djid.get(norm(n)) for n in _split_compound_b2b_name(str(partner))]
                    b_ids = [x for x in b_ids if x]
                    for a in a_ids:
                        for b in b_ids:
                            if a and b and a != b:
                                b2b_pairs.add(tuple(sorted((a, b))))
            for grp in (ev.get("b2b_sets") or []):
                if not isinstance(grp, (list, tuple)):
                    continue
                ids = []
                for x in grp:
                    ids.extend(name_to_djid.get(norm(n)) for n in _split_compound_b2b_name(str(x)))
                ids = [x for x in ids if x]
                for xi in range(len(ids)):
                    for yi in range(xi + 1, len(ids)):
                        if ids[xi] != ids[yi]:
                            b2b_pairs.add(tuple(sorted((ids[xi], ids[yi]))))
            for a, b in b2b_pairs:
                cur = con.execute("INSERT OR IGNORE INTO dj_b2b VALUES (?,?,?)", (a, b, event_id))
                n_b2b += int(cur.rowcount > 0)

    # ---- three-state trust computation (卡 T) ---------------------------------
    # Count distinct source_articles per DJ via event_source + event_participant.
    dj_sources = defaultdict(set)   # dj_id -> set of source_token
    dj_confidences = defaultdict(list)  # dj_id -> list of confidences
    for source_token, conf, dj_id in con.execute(
        "SELECT es.source_token, es.confidence, ep.dj_id "
        "FROM event_source es "
        "JOIN event_participant ep ON ep.event_id = es.event_id"
    ):
        dj_sources[dj_id].add(source_token)
        try:
            dj_confidences[dj_id].append(float(conf or 0))
        except (TypeError, ValueError):
            pass
    # Also include DJs that appear in lineups but may have no event_source match
    # (synthetic tests with minimal data sometimes hit this path).
    for dj_id, _event_id in con.execute(
        "SELECT ep.dj_id, ep.event_id FROM event_participant ep"
    ):
        if dj_id not in dj_sources:
            dj_sources.setdefault(dj_id, set())

    for eid, ent in list(R.ents.items()):
        if ent.get("type") != "dj":
            # Non-DJ entities default to candidate for now
            ent.setdefault("status", "candidate")
            ent.setdefault("source_article_count", 0)
            ent.setdefault("max_confidence", 0.0)
            continue
        name = ent.get("canonical_name", "")
        if _sanity_reject(name):
            ent["status"] = "rejected"
            ent["source_article_count"] = 0
            ent["max_confidence"] = 0.0
            continue
        src_count = len(dj_sources.get(eid, set()))
        max_conf = max(dj_confidences.get(eid, [0.0]))
        ent["source_article_count"] = src_count
        ent["max_confidence"] = max_conf
        if src_count >= 2:
            ent["status"] = "confirmed"
        elif src_count == 1 and max_conf >= 0.8:
            ent["status"] = "confirmed"
        else:
            ent["status"] = "candidate"

    # ---- DJ genre derivation (卡 G) ------------------------------------------
    # Collect event genres per DJ from event_participant + resolved_event
    dj_event_genres = defaultdict(set)
    for dj_id, event_id in con.execute(
        "SELECT ep.dj_id, re.event_id FROM event_participant ep "
        "JOIN resolved_event re ON re.event_id = ep.event_id"
    ):
        genre = con.execute(
            "SELECT genre FROM resolved_event WHERE event_id=?", (event_id,)
        ).fetchone()
        if genre:
            dj_event_genres[dj_id].add(genre[0])
    for eid, ent in R.ents.items():
        if ent.get("type") != "dj":
            continue
        genres = dj_event_genres.get(eid, set())
        if "electronic" in genres:
            ent.setdefault("attrs", {})["genre"] = "electronic"
        elif genres and genres == {"non_electronic"}:
            ent.setdefault("attrs", {})["genre"] = "non_electronic"
        else:
            ent.setdefault("attrs", {})["genre"] = "unknown"

    R.flush()
    con.commit()
    counts = dict(con.execute("SELECT type, COUNT(*) FROM canonical_entity GROUP BY type").fetchall())
    con.close()
    print(f"Stage3 done: entities={counts} events={n_ev} participants={n_part} event_sources={source_edges} b2b_pairs={n_b2b}")
    print(f"  -> {DB}")


if __name__ == "__main__":
    main()
