#!/usr/bin/env python3
"""Entity normalization: merge duplicate DJ/venue names into canonical forms.
Uses LLM entities.jsonl.gz + aliases + SoundCloud handles to resolve identity."""
import sqlite3, json, gzip, re
from pathlib import Path
from collections import defaultdict

MINIAPP_DB = Path("/mnt/c/code/githubstar/wechathtmldownload/services/weekly_activity_cloudrun/data/atlas_miniapp.sqlite")
ENTITIES_GZ = Path("/mnt/c/code/githubstar/wechathtmldownload/services/weekly_activity_cloudrun/data/stage7_atlas_all_full_llm/entities.jsonl.gz")

def norm(s):
    return re.sub(r'[^a-z0-9]', '', str(s).lower())

# 低质量DJ名 (通用词/单字符/数字) — 不过滤但标记，防止作为canonical
NOISE_NAMES = {'dj', 'mc', 'vj', 'live', 'djset', 'b2b', 'tba', 'tbc', 'guest', 'support'}
def is_noise_name(name):
    n = norm(name)
    if not n: return True
    if len(n) <= 1: return True
    if n in NOISE_NAMES: return True
    if n.isdigit(): return True
    return False

db = sqlite3.connect(str(MINIAPP_DB))
db.row_factory = sqlite3.Row

# Step 1: Build subject index
print("[1] Building subject index ...")
subjects_by_id = {}
name_to_ids = defaultdict(set)  # normalized_name → {subject_ids}
for row in db.execute("SELECT * FROM subject"):
    subjects_by_id[row['subject_id']] = dict(row)
    name_to_ids[row['normalized_name']].add(row['subject_id'])
    # Also index display_name and aliases
    name_to_ids[norm(row['display_name'])].add(row['subject_id'])
    try:
        for a in (json.loads(row['aliases_json']) if row['aliases_json'] else []):
            name_to_ids[norm(a)].add(row['subject_id'])
    except: pass
print(f"  {len(subjects_by_id):,d} subjects, {len(name_to_ids):,d} name keys")

# Step 2: Find merge groups from LLM entities (same entity, different names)
print("[2] Finding merge groups from LLM entities ...")
# Entities with same eid but different names → merge
eid_to_names = defaultdict(set)
name_to_eids = defaultdict(set)
with gzip.open(ENTITIES_GZ, 'rt', encoding='utf-8') as gz:
    for line in gz:
        if not line.strip(): continue
        try:
            ent = json.loads(line)
            if ent.get('type') not in ('person', 'organization'): continue
            eid = ent.get('eid', '')
            name = (ent.get('name') or '').strip()
            if not eid or not name: continue
            eid_to_names[eid].add(name)
            name_to_eids[norm(name)].add(eid)
        except: pass

# Entities that appear with multiple names → likely same entity
merge_groups = []
for eid, names in eid_to_names.items():
    if len(names) >= 2:
        merge_groups.append(list(names))
print(f"  {len(merge_groups):,d} multi-name entity groups")

# Step 3: Find subject merge candidates
print("[3] Finding subject merge candidates ...")
merges = []  # [(canonical_id, duplicate_id, reason)]
canonical_names = {}  # name → canonical subject_id

for group in merge_groups:
    # Find which subjects these names map to
    sids_in_group = set()
    for name in group:
        n = norm(name)
        if n in name_to_ids:
            sids_in_group.update(name_to_ids[n])
    if len(sids_in_group) >= 2:
        # Pick canonical: DJ with most events
        best_sid = None
        best_ec = -1
        for sid in sids_in_group:
            subj = subjects_by_id.get(sid, {})
            ec = subj.get('event_count', 0)
            if ec > best_ec:
                best_ec = ec
                best_sid = sid
        for sid in sids_in_group:
            if sid != best_sid:
                merges.append((best_sid, sid, f"LLM entity merge group: {group[:3]}"))

# Step 4: Find same-name duplicates — ONLY within same subject_type
print("[4] Finding same-name duplicates (per-type) ...")
for nname, sids in name_to_ids.items():
    if len(sids) < 2: continue
    # Group by subject_type
    by_type = defaultdict(set)
    for sid in sids:
        if sid in subjects_by_id:
            by_type[subjects_by_id[sid].get('subject_type', '')].add(sid)
    # Merge within each type group
    for stype, typed_sids in by_type.items():
        if len(typed_sids) < 2: continue
        # Pick canonical: highest event_count
        best_sid = max(typed_sids, key=lambda sid: subjects_by_id.get(sid, {}).get('event_count', 0))
        for sid in typed_sids:
            if sid != best_sid:
                merges.append((best_sid, sid, f"same normalized name ({stype}): {nname}"))

print(f"  {len(merges):,d} total merges")

# Step 5: Apply merges — REMAP foreign keys BEFORE zeroing old profiles
print("[5] Applying merges with FK remapping ...")
merge_map = {}
skipped_cross_type = 0
skipped_cross_city = 0
skipped_over_threshold = 0
MAX_MERGED_EVENTS = 300  # 合并后超过此值拒绝合并，防止venue误标为DJ
for canonical, duplicate, reason in merges:
    old_type = subjects_by_id.get(duplicate, {}).get('subject_type', '')
    new_type = subjects_by_id.get(canonical, {}).get('subject_type', '')
    if old_type and new_type and old_type != new_type:
        skipped_cross_type += 1
        continue
    old_city = (subjects_by_id.get(duplicate, {}).get('city_primary', '') or '').strip()
    new_city = (subjects_by_id.get(canonical, {}).get('city_primary', '') or '').strip()
    if old_city and new_city and old_city != new_city:
        skipped_cross_city += 1
        continue
    # 合并后 event_count 超阈值则跳过，防止 entity 归一化过度合并
    old_ec = subjects_by_id.get(duplicate, {}).get('event_count', 0) or 0
    new_ec = subjects_by_id.get(canonical, {}).get('event_count', 0) or 0
    if old_ec + new_ec > MAX_MERGED_EVENTS:
        skipped_over_threshold += 1
        continue
    merge_map[duplicate] = canonical

print(f"  Cross-type skipped: {skipped_cross_type:,d}")
print(f"  Cross-city skipped: {skipped_cross_city:,d}")
print(f"  Over-threshold skipped: {skipped_over_threshold:,d}")
print(f"  Merges to apply: {len(merge_map):,d}")

# Remap foreign keys in dj_event, dj_venue, dj_collaborator
remapped_events = 0
remapped_venues = 0
remapped_collabs = 0
for old_id, new_id in merge_map.items():
    # dj_event: UPDATE where dj_id = old_id (skip PK conflicts)
    r = db.execute("UPDATE OR IGNORE dj_event SET dj_id = ? WHERE dj_id = ?", (new_id, old_id))
    remapped_events += r.rowcount

    # Delete remaining orphan events that conflicted
    r2 = db.execute("DELETE FROM dj_event WHERE dj_id = ?", (old_id,))
    remapped_events += r2.rowcount

    # dj_venue: UPDATE where dj_id = old_id (skip if conflict)
    r = db.execute("UPDATE OR IGNORE dj_venue SET dj_id = ? WHERE dj_id = ?", (new_id, old_id))
    remapped_venues += r.rowcount

    # dj_collaborator: UPDATE both src and dst references
    r = db.execute("UPDATE OR IGNORE dj_collaborator SET src_dj_id = ? WHERE src_dj_id = ?", (new_id, old_id))
    remapped_collabs += r.rowcount
    r = db.execute("UPDATE OR IGNORE dj_collaborator SET dst_dj_id = ? WHERE dst_dj_id = ?", (new_id, old_id))
    remapped_collabs += r.rowcount

print(f"  FK remapped: {remapped_events:,d} events, {remapped_venues:,d} venues, {remapped_collabs:,d} collabs")

# Update dj_profile: merge counts
for old_id, new_id in merge_map.items():
    old_p = db.execute("SELECT * FROM dj_profile WHERE dj_id = ?", (old_id,)).fetchone()
    new_p = db.execute("SELECT * FROM dj_profile WHERE dj_id = ?", (new_id,)).fetchone()
    if old_p and new_p:
        # Merge bio: keep longest
        old_bio = old_p['bio'] or ''
        new_bio = new_p['bio'] or ''
        merged_bio = old_bio if len(old_bio) > len(new_bio) else new_bio
        actual_events = db.execute("SELECT COUNT(*) FROM dj_event WHERE dj_id = ?", (new_id,)).fetchone()[0]
        actual_venues = db.execute("SELECT COUNT(DISTINCT venue_id) FROM dj_venue WHERE dj_id = ?", (new_id,)).fetchone()[0]
        actual_collabs = db.execute("SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id = ?", (new_id,)).fetchone()[0]
        db.execute("UPDATE dj_profile SET bio = ?, event_count = ?, venue_count = ?, collaborator_count = ? WHERE dj_id = ?",
                   (merged_bio, actual_events, actual_venues, actual_collabs, new_id))
        # Mark old as merged
        db.execute("UPDATE dj_profile SET event_count = 0, venue_count = 0, collaborator_count = 0 WHERE dj_id = ?", (old_id,))

# Filter noise DJs: zero out event counts for low-quality names
noise_cleared = 0
for row in db.execute("SELECT dj_id, display_name, normalized_name FROM dj_profile"):
    if is_noise_name(row['display_name']) or is_noise_name(row['normalized_name']):
        db.execute("UPDATE dj_profile SET event_count = 0, venue_count = 0, collaborator_count = 0 WHERE dj_id = ?", (row['dj_id'],))
        noise_cleared += 1
print(f"  Noise DJs cleared: {noise_cleared:,d}")

# Update subject: merge event_counts
for old_id, new_id in merge_map.items():
    old_s = db.execute("SELECT event_count FROM subject WHERE subject_id = ?", (old_id,)).fetchone()
    if old_s:
        db.execute("UPDATE subject SET event_count = event_count + ? WHERE subject_id = ?", (old_s['event_count'] or 0, new_id))
        db.execute("UPDATE subject SET event_count = 0 WHERE subject_id = ?", (old_id,))

db.commit()

# Step 6: Re-extract ALL bios from entities.jsonl.gz with better matching
print("[6] Final bio extraction pass ...")
# Rebuild name index
name_to_id_final = {}
alias_to_id_final = defaultdict(set)
for row in db.execute("SELECT subject_id, display_name, normalized_name, aliases_json FROM subject WHERE subject_type='dj'"):
    sid, dn, nn = row['subject_id'], row['display_name'], row['normalized_name']
    name_to_id_final[nn] = sid
    name_to_id_final[norm(dn)] = sid
    try:
        for a in (json.loads(row['aliases_json']) if row['aliases_json'] else []):
            alias_to_id_final[norm(a)].add(sid)
    except: pass

# Full scan entities for bios
new_bios = defaultdict(str)  # sid → bio
with gzip.open(ENTITIES_GZ, 'rt', encoding='utf-8') as gz:
    for line in gz:
        if not line.strip(): continue
        try:
            ent = json.loads(line)
            if ent.get('type') != 'person': continue
            bio = (ent.get('bio') or '').strip()
            if len(bio) < 25: continue
            name = norm(ent.get('name') or '')
            if not name: continue
            # Match: direct, alias, substring
            sids = set()
            if name in name_to_id_final: sids.add(name_to_id_final[name])
            if name in alias_to_id_final: sids.update(alias_to_id_final[name])
            if not sids:
                # Substring match
                for nn, sid in name_to_id_final.items():
                    if len(name) >= 3 and len(nn) >= 3 and (name in nn or nn in name):
                        sids.add(sid)
                        break
            for sid in sids:
                if len(bio) > len(new_bios.get(sid, '')):
                    new_bios[sid] = bio
        except: pass

updated = 0
for sid, bio in new_bios.items():
    existing = db.execute("SELECT bio FROM dj_profile WHERE dj_id = ?", (sid,)).fetchone()
    if not existing or not existing['bio'] or len(existing['bio'] or '') < len(bio):
        db.execute("UPDATE dj_profile SET bio = ?, bio_source = 'llm_normalized_rescan' WHERE dj_id = ?", (bio[:500], sid))
        updated += 1
db.commit()

total = db.execute("SELECT COUNT(*) FROM dj_profile").fetchone()[0]
with_bio = db.execute("SELECT COUNT(*) FROM dj_profile WHERE bio IS NOT NULL AND bio != ''").fetchone()[0]
print(f"  Bio updated: {updated:,d}")
print(f"  With bio: {with_bio:,d}/{total:,d} ({100*with_bio/total:.1f}%)")
print(f"  Merges applied: {len(merges):,d}")

# Step 7: Recalculate same_event_count from actual dj_event data
# (Pre-computed counts get stale after entity merges — this is the source of truth)
print("[7] Recalculating same_event_count from dj_event ...")
db.execute("DELETE FROM dj_collaborator")
recalc = db.execute("""
    INSERT INTO dj_collaborator (src_dj_id, dst_dj_id, same_event_count, relation_label_zh, relation_score)
    SELECT e1.dj_id, e2.dj_id, COUNT(DISTINCT e1.event_id),
      CASE
        WHEN COUNT(DISTINCT e1.event_id) >= 5 THEN '高频同台'
        WHEN COUNT(DISTINCT e1.event_id) >= 2 THEN '多次同台'
        ELSE '同台出现'
      END,
      COUNT(DISTINCT e1.event_id) * 3.0
    FROM dj_event e1
    JOIN dj_event e2 ON e1.event_id = e2.event_id AND e1.dj_id < e2.dj_id
    GROUP BY e1.dj_id, e2.dj_id
""").rowcount
print(f"  Rebuilt {recalc:,d} collaborator pairs from actual shared events")

# Update collaborator_count in dj_profile from recalculated data
updated_cc = db.execute("""
    UPDATE dj_profile SET collaborator_count = (
        SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id = dj_profile.dj_id
    )
""").rowcount
print(f"  Updated {updated_cc:,d} dj_profile.collaborator_count")

# Update subject.event_count and subject.relation_count
db.execute("""
    UPDATE subject SET event_count = (
        SELECT COUNT(DISTINCT event_id) FROM dj_event WHERE dj_id = subject.subject_id
    )
""")
db.execute("""
    UPDATE subject SET relation_count = (
        SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id = subject.subject_id
    )
""")
db.commit()
print(f"  Subject event/relation counts updated")

db.close()
print("Done.")
