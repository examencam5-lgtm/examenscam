# voir_lignes_svt_annales.py
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path('data') / 'annales.db')
conn.row_factory = sqlite3.Row

print("=== Les 2 lignes 'SVT' dans annales ===\n")
rows = conn.execute("SELECT * FROM annales WHERE matiere='SVT'").fetchall()
for r in rows:
    print(dict(r))

print("\n=== Les lignes 'SVTEEHB' qui pourraient entrer en collision ===\n")
for r in rows:
    collision = conn.execute("""
        SELECT * FROM annales
        WHERE matiere='SVTEEHB' AND niveau=? AND annee=?
          AND (serie=? OR (serie IS NULL AND ? IS NULL))
    """, (r['niveau'], r['annee'], r['serie'], r['serie'])).fetchall()
    if collision:
        print(f"Collision pour {r['niveau']} {r['serie']} {r['annee']} :")
        for c in collision:
            print(f"  → {dict(c)}")

conn.close()