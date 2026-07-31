# diagnostic_doublons_annales.py
"""
Liste tous les groupes de lignes 'annales' qui partagent la même
combinaison niveau/serie/matiere/annee -- ne supprime RIEN, affiche
seulement, pour qu'on décide ensemble quoi faire.

Usage : python diagnostic_doublons_annales.py
"""

import sqlite3
from pathlib import Path

conn = sqlite3.connect(Path('data') / 'annales.db')
conn.row_factory = sqlite3.Row

print("=== GROUPES DE DOUBLONS DANS 'annales' ===\n")

groupes = conn.execute("""
    SELECT niveau, serie, matiere, annee, COUNT(*) as nb
    FROM annales
    GROUP BY niveau, serie, matiere, annee
    HAVING COUNT(*) > 1
    ORDER BY nb DESC
""").fetchall()

print(f"Total de groupes en doublon : {len(groupes)}\n")

for g in groupes:
    print(f"--- {g['niveau']} {g['serie'] or ''} {g['matiere']} {g['annee']} ({g['nb']} lignes) ---")
    lignes = conn.execute("""
        SELECT id, source, lien_drive, date_ajout, actif
        FROM annales
        WHERE niveau=? AND matiere=? AND annee=?
          AND (serie=? OR (serie IS NULL AND ? IS NULL))
        ORDER BY id
    """, (g['niveau'], g['matiere'], g['annee'], g['serie'], g['serie'])).fetchall()
    for l in lignes:
        lien_court = (l['lien_drive'] or '')[:60]
        print(f"    id={l['id']:5d}  source='{l['source']:15s}'  actif={l['actif']}  ajouté={l['date_ajout']}  lien='{lien_court}'")
    print()

conn.close()