# deplacer_lignes_mal_placees.py
"""
Déplace les 9 lignes de scraping qui se sont retrouvées dans 'annales'
(résidu d'un import antérieur au 26 juillet) vers leur vraie place :
'annales_externes'. Copie puis supprime de l'ancienne table -- rien
n'est perdu, juste remis au bon endroit.

Usage : python deplacer_lignes_mal_placees.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

lignes = conn.execute("""
    SELECT * FROM annales
    WHERE type_hebergement='externe' OR source_site IS NOT NULL
""").fetchall()

print(f"{len(lignes)} ligne(s) à déplacer.\n")
confirmation = input("Confirmer le déplacement vers annales_externes ? (oui/non) : ").strip().lower()

if confirmation == "oui":
    deplacees = 0
    for l in lignes:
        try:
            conn.execute("""
                INSERT INTO annales_externes (
                    niveau, serie, matiere, annee, titre, etablissement,
                    region, sequence, type_evaluation, classe_detectee,
                    lien_externe, lien_page_source, source_site, actif
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                l['niveau'], l['serie'], l['matiere'], l['annee'], l['titre'],
                l['etablissement'], l['region'], l['sequence'],
                l['type_evaluation'], l['classe_detectee'],
                l['lien_externe'], l['lien_page_source'], l['source_site']
            ))
            conn.execute("DELETE FROM annales WHERE id=?", (l['id'],))
            deplacees += 1
            print(f"  ✅ {l['niveau']} {l['serie']} {l['matiere']} {l['annee']} déplacée")
        except sqlite3.IntegrityError:
            print(f"  ⚠️ {l['niveau']} {l['serie']} {l['matiere']} {l['annee']} : déjà présente dans annales_externes (lien_externe en doublon) -- supprimée de 'annales' quand même")
            conn.execute("DELETE FROM annales WHERE id=?", (l['id'],))

    conn.commit()
    print(f"\n=== TERMINÉ — {deplacees} ligne(s) déplacée(s) ===")
else:
    print("Annulé.")

conn.close()