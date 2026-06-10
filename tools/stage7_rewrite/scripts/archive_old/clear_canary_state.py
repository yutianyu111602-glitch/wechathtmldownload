"""Clear canary state for fresh re-run."""
import sqlite3
conn = sqlite3.connect(r'D:\downstream_results\stage7_rewrite\state\pipeline.sqlite')
conn.execute("DELETE FROM article_status WHERE mode='canary'")
conn.execute("DELETE FROM run_log")
conn.execute("DELETE FROM run_counters")
conn.commit()
print('Cleared canary state')
conn.close()
