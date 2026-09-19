import sqlite3

DB = "data/rag_maths_bac_c/rag.db"  # ajuste avec le chemin trouvé à l'étape 1

conn = sqlite3.connect(DB)
cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'")
for (sql,) in cur.fetchall():
    print(sql)
    print("---")
conn.close()