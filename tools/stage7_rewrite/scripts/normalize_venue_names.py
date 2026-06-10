#!/usr/bin/env python3
"""Venue name normalization — TEMP TABLE approach for speed.
Single UPDATE via JOIN instead of row-by-row."""
import sqlite3, json, re
from pathlib import Path

MINIAPP_DB = Path("/mnt/c/code/githubstar/wechathtmldownload/services/weekly_activity_cloudrun/data/atlas_miniapp.sqlite")

ALIAS_MAP = {
    # OIL variants
    "oil油": "OIL", "oil club": "OIL", "oilclub": "OIL",
    "oil油 mainroom": "OIL", "oil油 main room": "OIL",
    "room 2 (oil油)": "OIL", "main room (oil油)": "OIL",
    "oil油 mainroom.": "OIL", "@oil club": "OIL",
    # JAR
    "jar这儿": "JAR",
    # ALL
    "all俱乐部": "ALL", "/\\||": "ALL",
    # FOUNDATION
    "foundation俱乐部": "FOUNDATION",
    # Elevator
    "elevator上海": "Elevator", "elevator shanghai": "Elevator",
    # Heim
    "heim shanghai": "Heim",
    # VERVO
    "vervo国际独立电音俱乐部": "VERVO",
    "vervo国际独立电音俱乐部(云南)": "VERVO",
    "(vervo国际独立电音俱乐部)": "VERVO",
    "vervo国际独立电音俱乐部, 昆明": "VERVO",
    "vervo国际独立电音俱乐部一楼": "VERVO",
    "昆明 vervo国际独立电音俱乐部": "VERVO",
    "昆明(vervo国际独立电音俱乐部)": "VERVO",
    # Dada
    "dada bar beijing": "Dada Beijing",
    "dada bar shanghai": "Dada Shanghai",
    "dada shanghai / dada beijing": "Dada Shanghai",
    "dada bar kunming": "Dada Kunming",
    "dada bar": "Dada Beijing",
    "dada, beijing": "Dada Beijing",
    "dada, shanghai": "Dada Shanghai",
    "dada, 115 xingfu lu, shanghai": "Dada Shanghai",
    "dada, 115 xingfu lu shanghai": "Dada Shanghai",
    # TAG
    "tagchengdu": "TAG", ".tagchengdu": "TAG",
    "tagchengdu hidden bar": "TAG",
    "tagchengdu (保利中心a座2118)": "TAG",
    "tag (tagchengdu)": "TAG",
    "mic (tagchengdu)": "TAG",
    # BO LIVE
    "bo live(福田店)": "BO LIVE",
    # POTENT
    "potent club": "POTENT",
    # Other venue aliases
    "cs bar": "C's Bar", "echo bay": "EchoBay",
    "play house": "Play House", "hum club": "Hum Club",
    "solo beijing": "SOLO Beijing",
    "exit shanghai": "EXIT Shanghai",
    "canto club": "Canto Club",
    "院吧 hakka bar": "院吧 Hakka Bar",
    "the window club": "THE WINDOW CLUB",
    "wuhanprison": "WuhanPrison", "zhaodai": "ZhaoDai",
    "招待所": "ZhaoDai", "招待": "ZhaoDai",
    "44kw": "44KW", "axis": "AXIS",
    "wigwam": "wigwam", "club between": "club between",
    "hakka bar院吧": "院吧 Hakka Bar",
    "reactor shanghai": "REACTOR Shanghai",
    "illum shanghai": "ILLUM Shanghai",
    "potent俱乐部": "POTENT", "pillbox beijing": "PILLBOX Beijing",
    "plur皮樂": "PLUR皮樂", "boiler room": "Boiler Room",
    "dada bar": "Dada Beijing", "dada bar.": "Dada Beijing",
    "aurora room": "AURORA ROOM", "aurora dark room": "AURORA DARK ROOM",
    "aurora red room": "AURORA RED ROOM", "aurora white room": "AURORA WHITE ROOM",
    # More dirty variants
    "oil油俱乐部": "OIL", "room2 at oil油": "OIL", "mainroom, oil油": "OIL",
    "room2, oil油": "OIL", "(oil油?)": "OIL",
    "dada bar北京": "Dada Beijing", "dada bar beijing 北京": "Dada Beijing",
    "potent club(上海tx淮海3f)": "POTENT",
    "tx淮海3f potent club": "POTENT",
    "dada bar beijing & temple": "Dada Beijing",
    "dada bar beijing 新地址": "Dada Beijing",
    "the black room(vervo国际独立电音俱乐部)": "VERVO",
    "vervo国际独立电音俱乐部一楼bar": "VERVO",
    "vervo国际独立电音俱乐部(推断)": "VERVO",
    "正义坊北馆·钱王街 71号 vervo国际独立电音俱乐部": "VERVO",
}

ANNOTATION_WORDS = ["推测", "未明确", "未定", "待定", "待确认", "可能", "推测为", "tbc", "tbd", "未确认", "未公布", "推断", "具体场馆未知", "未提及"]
CITY_NAMES = ["上海","北京","深圳","广州","成都","杭州","南京","武汉","重庆","西安","长沙","昆明","贵阳","厦门","福州","青岛","大连","天津","苏州","宁波","沈阳","郑州"]


def norm_key(s):
    return re.sub(r"\s+", " ", str(s or "").strip()).casefold()


def normalize_venue(raw: str) -> str:
    if not raw or not raw.strip():
        return ""
    text = raw.strip()
    text = re.sub(r'^[@.]\s*', '', text)
    key = text.lower().strip()
    if key in ALIAS_MAP:
        return ALIAS_MAP[key]

    # Track extracted venue names from annotation parens
    paren_extractions = {}  # span → extracted name

    def strip_paren(m):
        inner = m.group(1).strip()
        il = inner.lower()
        for w in ANNOTATION_WORDS:
            if w in il:
                # Try to extract venue name from annotation
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
        # Use the first extracted venue name
        text = list(paren_extractions.values())[0]

    for city in sorted(CITY_NAMES, key=len, reverse=True):
        text = re.sub(rf'^{re.escape(city)}\s*[,，]?\s*', '', text)

    parts = re.split(r'\s*/\s*|\s+或\s+', text)
    if len(parts) > 1:
        for p in parts:
            p = p.strip()
            if p and norm_key(p) not in {norm_key(c) for c in CITY_NAMES}:
                text = p
                break

    text = re.sub(r'[:：]\s*[\u4e00-\u9fff\d\s,，.号路街巷弄层楼广场大道]+$', '', text)
    # Strip "at VENUE" patterns: "ROOM2 at OIL油" → "OIL油"
    m = re.match(r'^.*\bat\s+(.+)$', text, re.IGNORECASE)
    if m:
        text = m.group(1).strip()
    # Room/floor suffix strip — only when followed by digit or clearly generic
    text = re.sub(r'\s+(ROOM\s+\d+|MAIN\s*ROOM|MAINROOM\.?|大厅舞池|舞池)\s*$', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+[（(]\s*(?:L\d|B\d|F\d|3F|大厅|小厅)\s*[）)]\s*$', '', text, flags=re.IGNORECASE)
    # "Room 2 (OIL油)" → extract venue from parens
    m = re.match(r'^(?:ROOM\s*\d+\s*|MAIN\s*ROOM\s*)[（(]([^）)]+)[）)]\s*$', text, flags=re.IGNORECASE)
    if m:
        text = m.group(1).strip()
    text = re.sub(r'\s+', ' ', text).strip().rstrip(',，')

    key2 = text.lower().strip()
    if key2 in ALIAS_MAP:
        return ALIAS_MAP[key2]

    # Final pass: if text still contains annotation keywords, try to extract actual venue name
    for ann in ANNOTATION_WORDS:
        if ann in text.lower():
            # Try common patterns: "...为VENUE" or "...为VENUE所在地"
            m = re.search(r'(?:为|是|即|at\s+)(.+?)(?:所?在地|所属场地|或|场地|$)', text)
            if m:
                extracted = m.group(1).strip().rstrip('。，,)）')
                if len(extracted) >= 2 and extracted != text:
                    return normalize_venue(extracted)  # recurse
            # "推断为公众号XXX所属场地" → try extracting XXX
            m = re.search(r'公众号\s*(\S+?)(?:\s*所属|\s*的|\s*场地|$)', text)
            if m:
                extracted = m.group(1).strip()
                if len(extracted) >= 2:
                    return normalize_venue(extracted)
            break

    return text if len(text) >= 2 else raw.strip()


def main():
    db = sqlite3.connect(str(MINIAPP_DB))
    db.row_factory = sqlite3.Row

    # ── Step 1: Collect distinct venue names from BOTH dj_event and dj_venue ──
    print("[1] Collecting distinct venue names ...")
    rows = db.execute("""
        SELECT DISTINCT venue_name FROM (
            SELECT DISTINCT venue_name FROM dj_event WHERE venue_name IS NOT NULL AND venue_name != ''
            UNION
            SELECT DISTINCT venue_name FROM dj_venue WHERE venue_name IS NOT NULL AND venue_name != ''
            UNION
            SELECT DISTINCT display_name FROM subject WHERE subject_type = 'venue' AND display_name IS NOT NULL AND display_name != ''
        )
    """).fetchall()
    print(f"  {len(rows):,d} unique names (from both dj_event + dj_venue)")

    # ── Step 2: Build normalization map (Python, fast) ──
    print("[2] Building normalization map ...")
    norm_map = {}  # old_name → new_name (venue_id preserved per contract §1.1)
    changed = 0
    for r in rows:
        orig = r["venue_name"]
        canon = normalize_venue(orig)
        norm_map[orig] = canon
        if canon != orig:
            changed += 1
    print(f"  {changed:,d} names to normalize")

    # Show samples
    shown = 0
    for orig, canon in sorted(norm_map.items(), key=lambda x: x[0].lower()):
        if orig != canon and shown < 25:
            print(f"    \"{orig[:55]}\" → \"{canon}\"")
            shown += 1

    # ── Step 3: Create temp table and bulk UPDATE ──
    print(f"\n[3] Creating temp table with {len(norm_map):,d} mappings ...")
    db.execute("CREATE TEMP TABLE _venue_norm (old_name TEXT PRIMARY KEY, new_name TEXT)")
    db.executemany(
        "INSERT INTO _venue_norm VALUES (?, ?)",
        [(old, new) for old, new in norm_map.items()]
    )

    print("[4] Bulk UPDATE dj_event via JOIN ...")
    # Per contract §1.1: NEVER change venue_id. Only normalize venue_name.
    db.execute("""
        UPDATE dj_event SET
            venue_name = (SELECT new_name FROM _venue_norm WHERE old_name = dj_event.venue_name)
        WHERE EXISTS (SELECT 1 FROM _venue_norm WHERE old_name = dj_event.venue_name)
    """)
    updated = db.execute("SELECT changes()").fetchone()[0]
    db.commit()
    print(f"  {updated:,d} dj_event rows updated")

    # ── Step 4: Update dj_venue — merge duplicates since venue_ids may collide ──
    print("[5] Merging dj_venue (consolidating duplicate venue_ids) ...")
    # Strategy: create merged table, swap
    # Use subquery so GROUP BY works on normalized venue_id, not original
    # Per contract §1.1: preserve venue_id, only normalize venue_name
    db.execute("""
        CREATE TEMP TABLE _dj_venue_merged AS
        SELECT dj_id, venue_id,
               COALESCE((SELECT new_name FROM _venue_norm WHERE old_name = dj_venue.venue_name), venue_name) as venue_name,
               MIN(city) as city, SUM(COALESCE(event_count, 0)) as event_count,
               MIN(first_seen_at) as first_seen_at, MAX(last_seen_at) as last_seen_at
        FROM dj_venue
        GROUP BY dj_id, venue_id
    """)
    db.execute("DELETE FROM dj_venue")
    db.execute("""
        INSERT INTO dj_venue (dj_id, venue_id, venue_name, city, event_count, first_seen_at, last_seen_at)
        SELECT dj_id, venue_id, venue_name, city, event_count, first_seen_at, last_seen_at
        FROM _dj_venue_merged
    """)
    v_updated = db.execute("SELECT changes()").fetchone()[0]
    db.execute("DROP TABLE _dj_venue_merged")
    db.commit()
    print(f"  {v_updated:,d} dj_venue rows after merge")

    # ── Step 5: Normalize ALL venue subject rows with normalize_venue() function ──
    print("[6] Normalizing venue names in subject table ...")
    subj_rows = db.execute("""
        SELECT subject_id, display_name, normalized_name, aliases_json FROM subject 
        WHERE subject_type = 'venue'
    """).fetchall()
    name_updated = 0
    alias_updated = 0
    for sr in subj_rows:
        new_dn = normalize_venue(sr['display_name'])
        new_nn = normalize_venue(sr['normalized_name'])
        if new_dn != sr['display_name'] or new_nn != sr['normalized_name']:
            db.execute("UPDATE subject SET display_name = ?, normalized_name = ? WHERE subject_id = ?",
                       (new_dn, new_nn, sr['subject_id']))
            name_updated += 1
        # Normalize aliases too
        try:
            aliases = json.loads(sr['aliases_json']) if sr['aliases_json'] else []
        except:
            aliases = []
        new_aliases = []
        for a in aliases:
            canon = normalize_venue(a)
            new_aliases.append(canon)
        new_aliases = list(set(new_aliases))
        if new_aliases != aliases:
            db.execute("UPDATE subject SET aliases_json = ? WHERE subject_id = ?",
                       (json.dumps(new_aliases, ensure_ascii=False), sr['subject_id']))
            alias_updated += 1
    db.commit()
    print(f"  {name_updated:,d} subject names updated, {alias_updated:,d} aliases updated")

    # ── Step 6: Verify ──
    print("\n[6] Verification ...")
    bad = db.execute("""
        SELECT venue_name, COUNT(DISTINCT venue_id) as n
        FROM dj_event WHERE venue_name != ''
        GROUP BY venue_name HAVING n > 1
    """).fetchall()
    if bad:
        print(f"  ⚠️  {len(bad)} names with multiple IDs!")
    else:
        print("  ✓ All names have unique venue_id")

    unique_now = db.execute("SELECT COUNT(DISTINCT venue_name) FROM dj_event WHERE venue_name != ''").fetchone()[0]
    print(f"  Unique names: {len(rows):,d} → {unique_now:,d}")

    print("\n[7] Top 25 venues:")
    for r in db.execute("SELECT venue_name, venue_id, COUNT(*) as cnt FROM dj_event WHERE venue_name != '' GROUP BY venue_name ORDER BY cnt DESC LIMIT 25"):
        print(f"  {r['cnt']:5d}  {r['venue_name'][:40]:40s} {r['venue_id']}")

    db.execute("DROP TABLE _venue_norm")
    db.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
