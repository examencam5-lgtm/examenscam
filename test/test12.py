# voir_vrais_doublons.py
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path('data') / 'annales.db')
conn.row_factory = sqlite3.Row

groupes = [
    ("BEPC", None, "PCT", 2015),
    ("BEPC", None, "Mathematiques", 2020),
    ("BEPC", None, "Mathematiques", 2023),
    ("BEPC", None, "PCT", 2022),
]

for niveau, serie, matiere, annee in groupes:
    print(f"\n--- {niveau} {matiere} {annee} ---")
    rows = conn.execute("""
        SELECT id, lien_drive FROM annales
        WHERE niveau=? AND matiere=? AND annee=?
          AND (serie=? OR (serie IS NULL AND ? IS NULL))
    """, (niveau, matiere, annee, serie, serie)).fetchall()
    for r in rows:
        print(f"  id={r['id']}  →  {r['lien_drive']}")

conn.close()