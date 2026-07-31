# uniformiser_svteehb_v2.py
"""
Relance l'uniformisation SVT → SVTEEHB, maintenant que la collision
qui avait fait planter la première tentative est nettoyée.

Usage : python uniformiser_svteehb_v2.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'
conn = sqlite3.connect(DB_PATH)

print("=== AVANT renommage ===\n")
tables = ["annales", "annales_blanches", "annales_externes", "packs_corriges"]
for table in tables:
    n = conn.execute(f"SELECT COUNT(*) FROM {table} WHERE matiere='SVT'").fetchone()[0]
    print(f"  {table} : {n} ligne(s) avec matiere='SVT'")

confirmation = input("\nConfirmer le renommage SVT → SVTEEHB ? (oui/non) : ").strip().lower()

if confirmation == "oui":
    total = 0
    for table in tables:
        try:
            n = conn.execute(f"UPDATE {table} SET matiere='SVTEEHB' WHERE matiere='SVT'").rowcount
            conn.commit()
            total += n
            print(f"  ✅ {table} : {n} ligne(s) renommée(s)")
        except sqlite3.IntegrityError as e:
            print(f"  ⚠️ {table} : collision détectée, rien renommé dans cette table : {e}")
    print(f"\n=== TERMINÉ — {total} lignes renommées au total ===")
else:
    print("Annulé.")

conn.close()