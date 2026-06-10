import sqlite3, json

db = sqlite3.connect(r"D:\downstream_results\stage7_rewrite\stage8\production\pc_vector_production.sqlite")
db.row_factory = sqlite3.Row

tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
for t in tables:
    cnt = db.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
    print(f"  {t}: {cnt} rows")

print()
print("=== production_runs (last 10) ===")
try:
    cols = [c[1] for c in db.execute("PRAGMA table_info(production_runs)")]
    print("cols:", cols)
    for row in db.execute("SELECT * FROM production_runs ORDER BY rowid DESC LIMIT 10"):
        print(dict(zip(cols, row)))
except Exception as e:
    print("error:", e)

print()
print("=== vector_objects sample ===")
try:
    cols2 = [c[1] for c in db.execute("PRAGMA table_info(vector_objects)")]
    print("cols:", cols2)
    for row in db.execute("SELECT * FROM vector_objects ORDER BY rowid DESC LIMIT 3"):
        d = dict(zip(cols2, row))
        d_short = {k: (str(v)[:80] if isinstance(v, str) and len(str(v)) > 80 else v) for k, v in d.items()}
        print(d_short)
except Exception as e:
    print("error:", e)

db.close()
