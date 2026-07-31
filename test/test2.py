# verifier_import_externes.py
"""
Vérifie ce qui existe réellement dans annales_externes, groupé par
niveau/serie, pour comparer avec ce que le site affiche (ou n'affiche pas).

Usage : python verifier_import_externes.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'

conn = sqlite3.connect(DB_PATH)

print("=== CONTENU RÉEL DE annales_externes PAR NIVEAU/SÉRIE ===\n")

rows = conn.execute("""
    SELECT niveau, serie, matiere, COUNT(*) as nb
    FROM annales_externes
    WHERE actif=1
    GROUP BY niveau, serie, matiere
    ORDER BY niveau, serie, matiere
""").fetchall()

for niveau, serie, matiere, nb in rows:
    print(f"  niveau='{niveau}'  serie='{serie}'  matiere='{matiere}'  → {nb} épreuve(s)")

print(f"\nTotal lignes actives : {sum(r[3] for r in rows)}")
conn.close()