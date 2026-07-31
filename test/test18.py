# verifier_contamination_annales.py
import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path('data') / 'annales.db')
conn.row_factory = sqlite3.Row

print("=== Lignes 'annales' qui ressemblent à du scraping (type_hebergement='externe') ===\n")
rows = conn.execute("""
    SELECT id, niveau, serie, matiere, annee, etablissement, source_site, date_ajout
    FROM annales
    WHERE type_hebergement='externe' OR source_site IS NOT NULL
""").fetchall()

print(f"Total : {len(rows)} ligne(s)\n")
for r in rows:
    print(f"  id={r['id']}  {r['niveau']} {r['serie']} {r['matiere']} {r['annee']}  etablissement='{r['etablissement']}'  source_site='{r['source_site']}'  ajouté={r['date_ajout']}")

conn.close()