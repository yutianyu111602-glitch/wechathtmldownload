#!/usr/bin/env python3
"""
Atlas DB 计数修复 — 仅从实际数据重算，不合并/不归一化/不改 ID。
"""
import sqlite3
from pathlib import Path

MINIAPP_DB = Path("/mnt/c/code/githubstar/wechathtmldownload/services/weekly_activity_cloudrun/data/atlas_miniapp.sqlite")
BACKUP_DB = MINIAPP_DB.with_suffix(".sqlite.bak-fixcount-20260529")

print(f"[0] Backup: {MINIAPP_DB} → {BACKUP_DB}")
import shutil
shutil.copy2(MINIAPP_DB, BACKUP_DB)

db = sqlite3.connect(str(MINIAPP_DB))
db.row_factory = sqlite3.Row
db.execute("PRAGMA journal_mode=WAL")
db.execute("PRAGMA synchronous=NORMAL")

# Step 1: Recalculate dj_profile.event_count from dj_event
print("[1] Recalculating dj_profile.event_count ...")
updated = db.execute("""
    UPDATE dj_profile SET event_count = (
        SELECT COUNT(DISTINCT event_id) FROM dj_event WHERE dj_id = dj_profile.dj_id
    )
""").rowcount
print(f"  Updated {updated:,d} dj_profile rows")

# Step 2: Recalculate dj_profile.venue_count from dj_venue
print("[2] Recalculating dj_profile.venue_count ...")
updated = db.execute("""
    UPDATE dj_profile SET venue_count = (
        SELECT COUNT(DISTINCT venue_id) FROM dj_venue WHERE dj_id = dj_profile.dj_id
    )
""").rowcount
print(f"  Updated {updated:,d} dj_profile rows")

# Step 3: Recalculate subject.event_count from dj_event
print("[3] Recalculating subject.event_count ...")
updated = db.execute("""
    UPDATE subject SET event_count = (
        SELECT COUNT(DISTINCT event_id) FROM dj_event WHERE dj_id = subject.subject_id
    )
""").rowcount
print(f"  Updated {updated:,d} subject rows")

# Step 4: Recalculate subject.relation_count from dj_collaborator
print("[4] Recalculating subject.relation_count ...")
updated = db.execute("""
    UPDATE subject SET relation_count = (
        SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id = subject.subject_id
    )
""").rowcount
print(f"  Updated {updated:,d} subject rows")

# Step 5: Rebuild dj_collaborator from actual shared events
print("[5] Rebuilding dj_collaborator from actual shared events ...")
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
print(f"  Rebuilt {recalc:,d} collaborator pairs")

# Step 6: Update dj_profile.collaborator_count
print("[6] Recalculating dj_profile.collaborator_count ...")
updated = db.execute("""
    UPDATE dj_profile SET collaborator_count = (
        SELECT COUNT(*) FROM dj_collaborator WHERE src_dj_id = dj_profile.dj_id
    )
""").rowcount
print(f"  Updated {updated:,d} dj_profile rows")

db.commit()

# Verify
print()
print("=== Verification ===")
rows = db.execute("""
    SELECT s.subject_id, s.display_name, s.event_count AS subj_ec,
        (SELECT COUNT(DISTINCT event_id) FROM dj_event WHERE dj_id = s.subject_id) AS actual
    FROM subject s WHERE s.subject_type = 'dj'
    ORDER BY s.event_count DESC LIMIT 10
""").fetchall()
for r in rows:
    ok = "✅" if r["subj_ec"] == r["actual"] else "❌"
    print(f"  {ok} {r['display_name']:25s} | event_count={r['subj_ec']:5d} | actual={r['actual']:5d}")

total = db.execute("SELECT COUNT(*) FROM dj_profile").fetchone()[0]
mismatch = db.execute("""
    SELECT COUNT(*) FROM subject s
    WHERE s.subject_type = 'dj'
    AND s.event_count != (SELECT COUNT(DISTINCT event_id) FROM dj_event WHERE dj_id = s.subject_id)
""").fetchone()[0]
print(f"\n  DJs total: {total:,d}, mismatched: {mismatch} (was 6,847)")

db.close()
print("\nDone. Backup at:", BACKUP_DB)
