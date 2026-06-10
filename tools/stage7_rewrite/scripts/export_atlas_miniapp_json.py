#!/usr/bin/env python3
"""Export atlas_miniapp DB → compressed JSON for in-memory serving.
v4: source_ref lineage for mini-program venue source articles."""
import sqlite3, json, gzip, re
from pathlib import Path

DB = Path("/mnt/c/code/githubstar/wechathtmldownload/services/weekly_activity_cloudrun/data/atlas_miniapp.sqlite")
OUT = DB.parent / "atlas_index.json.gz"

def norm(s):
    return re.sub(r'[^a-z0-9一-鿿]', '', str(s).lower())

# ── Full venue normalization (synced with normalize_venue_names.py) ──
ALIAS_MAP = {
    "oil油": "OIL", "oil club": "OIL", "oilclub": "OIL",
    "oil油 mainroom": "OIL", "oil油 main room": "OIL",
    "room 2 (oil油)": "OIL", "main room (oil油)": "OIL",
    "oil油 mainroom.": "OIL", "@oil club": "OIL", "(oil油?)": "OIL",
    "oil油俱乐部": "OIL", "room2 at oil油": "OIL", "mainroom, oil油": "OIL",
    "room2, oil油": "OIL", "oil油(mainroom)": "OIL", "oil油 mainroom +": "OIL",
    "oil油 (mainroom)": "OIL", "mainroom (oil油)": "OIL",
    "oil油 3 rooms event": "OIL", "oil soundsystem及公众号名oil油": "OIL",
    "油田(oil油)": "OIL", "oil油厅": "OIL", "oil油?": "OIL",
    "车公庙oil油": "OIL",
    "jar这儿": "JAR", "all俱乐部": "ALL", "/\\||": "ALL",
    "foundation俱乐部": "FOUNDATION",
    "elevator上海": "Elevator", "elevator shanghai": "Elevator",
    "heim shanghai": "Heim",
    "vervo国际独立电音俱乐部": "VERVO",
    "vervo国际独立电音俱乐部(云南)": "VERVO",
    "(vervo国际独立电音俱乐部)": "VERVO",
    "vervo国际独立电音俱乐部, 昆明": "VERVO",
    "vervo国际独立电音俱乐部一楼": "VERVO",
    "昆明 vervo国际独立电音俱乐部": "VERVO",
    "dada bar beijing": "Dada Beijing",
    "dada bar shanghai": "Dada Shanghai",
    "dada shanghai / dada beijing": "Dada Shanghai",
    "dada bar kunming": "Dada Kunming",
    "dada bar": "Dada Beijing",
    "dada, beijing": "Dada Beijing",
    "dada, shanghai": "Dada Shanghai",
    "dada, 115 xingfu lu, shanghai": "Dada Shanghai",
    "tagchengdu": "TAG", ".tagchengdu": "TAG",
    "tagchengdu hidden bar": "TAG",
    "tagchengdu (保利中心a座2118)": "TAG",
    "tag (tagchengdu)": "TAG", "mic (tagchengdu)": "TAG",
    "bo live(福田店)": "BO LIVE",
    "potent club": "POTENT", "potent俱乐部": "POTENT",
    "cs bar": "C's Bar", "echo bay": "EchoBay",
    "play house": "Play House", "hum club": "Hum Club",
    "solo beijing": "SOLO Beijing", "exit shanghai": "EXIT Shanghai",
    "canto club": "Canto Club", "院吧 hakka bar": "院吧 Hakka Bar",
    "the window club": "THE WINDOW CLUB",
    "wuhanprison": "WuhanPrison", "zhaodai": "ZhaoDai",
    "招待所": "ZhaoDai", "招待": "ZhaoDai",
    "44kw": "44KW", "axis": "AXIS",
    "wigwam": "wigwam", "club between": "club between",
    "hakka bar院吧": "院吧 Hakka Bar",
    "reactor shanghai": "REACTOR Shanghai",
    "illum shanghai": "ILLUM Shanghai",
    "boiler room": "Boiler Room",
    "pillbox beijing": "PILLBOX Beijing", "plur皮樂": "PLUR皮樂",
    "dada bar北京": "Dada Beijing", "dada bar beijing 北京": "Dada Beijing",
    "the black room(vervo国际独立电音俱乐部)": "VERVO",
    "vervo国际独立电音俱乐部一楼bar": "VERVO",
    "vervo国际独立电音俱乐部(推断)": "VERVO",
    "vervo国际独立电音俱乐部或正义坊北馆·钱王街71号": "VERVO",
    "club (vervo国际独立电音俱乐部)": "VERVO",
    "vervo国际独立电音俱乐部 black": "VERVO",
    "vervo国际独立电音俱乐部(正义坊)": "VERVO",
    "vervo国际独立电音俱乐部(昆明站)": "VERVO",
    "vervo国际独立电音俱乐部(昆明正义坊)": "VERVO",
    "vervo国际独立电音俱乐部二楼club": "VERVO",
    "正义坊北馆·钱王街71号 (vervo国际独立电音俱乐部)": "VERVO",
    "中国6家最热门的club(含vervo国际独立电音俱乐部)": "VERVO",
}
ANNOTATION_WORDS = ["推测", "未明确", "未定", "待定", "待确认", "可能", "推测为", "tbc", "tbd", "未确认", "未公布", "推断", "具体场馆未知", "未提及"]
CITY_NAMES = ["上海","北京","深圳","广州","成都","杭州","南京","武汉","重庆","西安","长沙","昆明","贵阳","厦门","福州","青岛","大连","天津","苏州","宁波","沈阳","郑州"]

def norm_venue(raw: str) -> str:
    if not raw or not raw.strip():
        return ""
    text = raw.strip()
    text = re.sub(r'^[@.]\s*', '', text)
    key = text.lower().strip()
    if key in ALIAS_MAP:
        return ALIAS_MAP[key]

    paren_extractions = {}
    def strip_paren(m):
        inner = m.group(1).strip()
        il = inner.lower()
        for w in ANNOTATION_WORDS:
            if w in il:
                em = re.search(r'(?:推测为|可能是|推断为|提及|公众号)\s*(.+?)(?:所?在地|场地|所属|或\s+\S|的|$)', inner)
                if em:
                    candidate = em.group(1).strip().rstrip('。，,)）')
                    if len(candidate) >= 2:
                        paren_extractions[m.span()] = candidate
                return ''
        for c in CITY_NAMES:
            if inner == c:
                return ''
        return m.group(0)

    text = re.sub(r'[（(]([^）)]*)[）)]', strip_paren, text)
    if paren_extractions and (not text or len(text.strip()) < 3):
        text = list(paren_extractions.values())[0]

    for city in sorted(CITY_NAMES, key=len, reverse=True):
        text = re.sub(rf'^{re.escape(city)}\s*[,，]?\s*', '', text)

    parts = re.split(r'\s*/\s*|\s+或\s+', text)
    if len(parts) > 1:
        for p in parts:
            p = p.strip()
            if p and p.lower() not in {c.lower() for c in CITY_NAMES}:
                text = p
                break

    text = re.sub(r'[:：]\s*[\u4e00-\u9fff\d\s,，.号路街巷弄层楼广场大道]+$', '', text)
    m = re.match(r'^.*\bat\s+(.+)$', text, re.IGNORECASE)
    if m: text = m.group(1).strip()
    text = re.sub(r'\s+(ROOM\s+\d+|MAIN\s*ROOM|MAINROOM\.?|大厅舞池|舞池)\s*$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip().rstrip(',，')

    key2 = text.lower().strip()
    if key2 in ALIAS_MAP:
        return ALIAS_MAP[key2]

    for ann in ANNOTATION_WORDS:
        if ann in text.lower():
            m = re.search(r'(?:为|是|即)\s*(.+?)(?:所?在地|所属场地|或|场地|$)', text)
            if m:
                extracted = m.group(1).strip().rstrip('。，,)）')
                if len(extracted) >= 2 and extracted != text:
                    return norm_venue(extracted)
            break

    # Final pass: if text contains any known alias, extract it
    for alias_key, alias_val in ALIAS_MAP.items():
        kl = alias_key.lower()
        tl = text.lower()
        if kl in tl and kl != tl:
            # Check if the alias appears as a clean substring
            if tl.startswith(kl + ',') or tl.startswith(kl + ' ') or tl.startswith(kl + '(') or tl.startswith(kl + '（'):
                return alias_val
            if tl.endswith(',' + kl) or tl.endswith(' ' + kl) or tl.endswith(')' + kl) or tl.endswith('）' + kl):
                return alias_val
            if tl.endswith(kl):  # "车公庙OIL油" ends with "oil油"
                return alias_val
            if (' ' + kl + ' ') in (' ' + tl + ' ') or ('(' + kl + ')') in tl or ('（' + kl + '）') in tl:
                return alias_val

    return text if len(text) >= 2 else raw.strip()

conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
conn.row_factory = sqlite3.Row

def table_exists(name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

def column_exists(table: str, column: str) -> bool:
    if not table_exists(table):
        return False
    return any(row[1] == column for row in conn.execute(f"PRAGMA table_info({table})"))

DJ_EVENT_HAS_SOURCE_REF = column_exists("dj_event", "source_ref_id")

# Export subjects
subjects = []
for row in conn.execute("SELECT subject_id, subject_type, display_name, normalized_name, aliases_json, city_primary, event_count FROM subject"):
    is_venue_like = row[1] in ('venue', 'org', 'radio')
    n = norm_venue(row[2]) if is_venue_like else row[2]
    nn = norm_venue(row[3]) if is_venue_like else row[3]
    aliases = json.loads(row[4]) if row[4] else []
    if is_venue_like:
        aliases = [norm_venue(a) for a in aliases]
        aliases = list(set(aliases))
    subjects.append({"i": row[0], "t": row[1], "n": n, "nn": nn, "a": aliases, "c": row[5] or "", "ec": row[6] or 0})
print(f"Subjects: {len(subjects):,d}")

# DJ profiles with bios
profiles = {}
profile_columns = {row[1] for row in conn.execute("PRAGMA table_info(dj_profile)")}
for row in conn.execute("SELECT * FROM dj_profile"):
    bio = row['bio'] if 'bio' in profile_columns else ""
    bio_source = row['bio_source'] if 'bio_source' in profile_columns else ""
    profiles[row['dj_id']] = {"n": row['display_name'], "c": row['city_primary'] or "", "ec": row['event_count'] or 0, "vc": row['venue_count'] or 0, "cc": row['collaborator_count'] or 0, "fs": row['first_seen_at'] or "", "ls": row['last_seen_at'] or "", "b": bio or "", "bs": bio_source or ""}
print(f"Profiles: {len(profiles):,d}")

# Compact source refs — only refs present in the miniapp DB.
source_refs = {}
if table_exists("source_ref"):
    for row in conn.execute("SELECT source_ref_id, source_hash, source_account, source_title, post_date, source_kind FROM source_ref"):
        rid = row["source_ref_id"] or ""
        if not rid:
            continue
        source_refs[rid] = {
            "h": row["source_hash"] or "",
            "a": row["source_account"] or "",
            "t": row["source_title"] or "",
            "p": row["post_date"] or "",
            "k": row["source_kind"] or "",
        }
print(f"Source refs: {len(source_refs):,d}")

# DJ events — DEDUPED per-DJ (not cross-DJ, so multi-DJ events show for all artists)
events = {}
for row in conn.execute("SELECT * FROM dj_event ORDER BY starts_at DESC"):
    dj = row['dj_id']
    if dj not in events: events[dj] = []
    if len(events[dj]) < 100:
        dk = (row['event_title'] or '', row['starts_at'] or '', row['venue_id'] or '')
        if dk not in events.setdefault('_seen', {}).setdefault(dj, set()):
            events.setdefault('_seen', {})[dj].add(dk)
            event = {"eid": row['event_id'], "t": row['event_title'], "d": row['starts_at'] or "", "v": norm_venue(row['venue_name'] or ""), "vi": row['venue_id'] or "", "ci": row['city'] or ""}
            if DJ_EVENT_HAS_SOURCE_REF and row['source_ref_id']:
                event["sr"] = row['source_ref_id']
            events[dj].append(event)
total_dj_events = sum(len(v) for k, v in events.items() if k != '_seen')
print(f"DJ events: {len([k for k in events if k != '_seen']):,d} DJs, {total_dj_events:,d} deduped events")

# DJ venues — already deduped in rollup table
dj_venues = {}
for row in conn.execute("SELECT * FROM dj_venue ORDER BY event_count DESC"):
    dj = row['dj_id']
    if dj not in dj_venues: dj_venues[dj] = []
    if len(dj_venues[dj]) < 20: dj_venues[dj].append({"vn": norm_venue(row['venue_name']), "ec": row['event_count'] or 0, "vi": row['venue_id']})
print(f"DJ venues: {len(dj_venues):,d} DJs")

# Venue events — deduped
venue_events = {}
venue_by_name = {}
vseen = set()
source_ref_select = ", de.source_ref_id" if DJ_EVENT_HAS_SOURCE_REF else ""
for row in conn.execute(f"SELECT de.venue_id, de.event_id, de.event_title, de.starts_at, de.venue_name, de.city, de.dj_id{source_ref_select} FROM dj_event de WHERE de.venue_id IS NOT NULL ORDER BY de.starts_at DESC"):
    vid = row['venue_id']
    if vid not in venue_events: venue_events[vid] = []
    if len(venue_events[vid]) < 200:
        dk = (row['event_title'] or '', row['starts_at'] or '', vid)
        if dk not in vseen:
            vseen.add(dk)
            event = {"eid": row['event_id'], "t": row['event_title'], "d": row['starts_at'] or "", "di": row['dj_id'], "ci": row['city'] or ""}
            if DJ_EVENT_HAS_SOURCE_REF and row['source_ref_id']:
                event["sr"] = row['source_ref_id']
            venue_events[vid].append(event)
    vn = norm_venue(row['venue_name'] or '').lower()
    if vn:
        if vn not in venue_by_name: venue_by_name[vn] = set()
        venue_by_name[vn].add(vid)
venue_by_name = {k: list(v) for k, v in venue_by_name.items()}

# ── Cross-reference: map normalized venue names → subject_ids so direct lookups work ──
venue_name_to_subject_ids = {}
for s in subjects:
    if s["t"] in ("venue", "org", "radio") and s["n"]:
        sn = norm_venue(s["n"]).lower()
        if sn not in venue_name_to_subject_ids:
            venue_name_to_subject_ids[sn] = set()
        venue_name_to_subject_ids[sn].add(s["i"])
# Populate venue_events also keyed by subject_id (via name match)
for vn, sids in venue_name_to_subject_ids.items():
    for vid in venue_by_name.get(vn, []):
        for sid in sids:
            if sid not in venue_events:
                venue_events[sid] = venue_events.get(vid, [])
    # Add subject_ids to venue_by_name entries (values are already lists)
    for sid in sids:
        if vn in venue_by_name and sid not in venue_by_name[vn]:
            venue_by_name[vn].append(sid)
print(f"Venues: {len(venue_events):,d}")

# Collabs — use rollup count (already deduped), resolve names
collabs = {}
for row in conn.execute("SELECT dc.*, s.display_name as cn FROM dj_collaborator dc JOIN subject s ON s.subject_id = dc.dst_dj_id ORDER BY dc.same_event_count DESC"):
    dj = row['src_dj_id']
    if dj not in collabs: collabs[dj] = []
    if len(collabs[dj]) < 30:
        # Dedupe by dst_dj_id
        if not any(c['di'] == row['dst_dj_id'] for c in collabs[dj]):
            collabs[dj].append({"di": row['dst_dj_id'], "n": row['cn'] or row['dst_dj_id'], "ec": row['same_event_count'] or 0})
print(f"Collabs: {len(collabs):,d} DJs")

# Strip internal _seen key before JSON serialization
events_out = {k: v for k, v in events.items() if k != '_seen'}

# Build payload
payload = {"v": 4, "subjects": subjects, "profiles": profiles, "events": events_out, "dj_venues": dj_venues, "venue_events": venue_events, "venue_by_name": venue_by_name, "collabs": collabs, "source_refs": source_refs}

# ── Final clean: post-process JSON string to catch anything norm_venue missed ──
print("Final cleaning pass ...")
raw_json = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))

# Exact string replacements for known dirty patterns
CLEANUP = {
    "推测OIL油场地": "推测OIL场地",
    "推测oil油场地": "推测oil场地",
    "车公庙OIL油": "车公庙OIL",
    "车公庙oil油": "车公庙oil",
    '"OIL油': '"OIL', 'OIL油"': 'OIL"', 'OIL油,': 'OIL,',
    '"oil油': '"oil', 'oil油"': 'oil"', 'oil油,': 'oil,',
    'JAR这儿': 'JAR',
    'jar这儿': 'jar',
    'VERVO国际独立电音俱乐部': 'VERVO',
    'vervo国际独立电音俱乐部': 'vervo',
    'Dada Bar Beijing': 'Dada Beijing',
    'dada bar beijing': 'dada beijing',
    'Dada Bar Shanghai': 'Dada Shanghai',
    'dada bar shanghai': 'dada shanghai',
    'TAGChengdu': 'TAG',
    'tagchengdu': 'tag',
    'POTENT CLUB': 'POTENT',
    'Potent Club': 'POTENT',
    'potent club': 'potent',
}
for old, new in CLEANUP.items():
    if old in raw_json:
        raw_json = raw_json.replace(old, new)

# Write cleaned JSON
with gzip.open(OUT, 'wt', encoding='utf-8', compresslevel=9) as f:
    f.write(raw_json)
print(f"Output: {OUT} ({OUT.stat().st_size/1024/1024:.1f} MB)")
conn.close()
