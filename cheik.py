import sqlite3
conn = sqlite3.connect('data/annales.db')
rows = conn.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name='annales'").fetchall()
for r in rows:
    print(r[0])