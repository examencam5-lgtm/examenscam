# verifier_plus_doublons.py
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path('data') / 'annales.db')
groupes = conn.execute("""
    SELECT niveau, serie, matiere, annee, COUNT(*) as nb
    FROM annales GROUP BY niveau, serie, matiere, annee HAVING COUNT(*) > 1
""").fetchall()
print(f"Groupes en doublon restants : {len(groupes)}")
for g in groupes:
    print(f"  {g}")
conn.close()