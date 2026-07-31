# diagnostic_matieres_svt.py
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path('data') / 'annales.db')

print("=== Recherche de toutes les variantes 'SVT' dans chaque table ===\n")

for table, colonne_matiere in [
    ("annales", "matiere"),
    ("annales_blanches", "matiere"),
    ("annales_externes", "matiere"),
    ("packs_corriges", "matiere"),
]:
    rows = conn.execute(f"""
        SELECT DISTINCT {colonne_matiere}, COUNT(*)
        FROM {table}
        WHERE {colonne_matiere} LIKE '%SVT%'
        GROUP BY {colonne_matiere}
    """).fetchall()
    print(f"{table} :")
    for matiere, nb in rows:
        print(f"  '{matiere}' → {nb} ligne(s)")
    print()

conn.close()