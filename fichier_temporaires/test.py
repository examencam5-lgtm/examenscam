# verifier_donnees_test.py
"""
Vérifie combien de données de test existent réellement pour chaque
combinaison, plutôt que de supposer que l'injection a marché partout.

Usage : python verifier_donnees_test.py
"""

import sqlite3
from pathlib import Path

DB_PATH = Path('data') / 'annales.db'
TAG = "TEST_TEMPORAIRE"

COMBINAISONS = [
    ("BEPC", None, "Mathematiques"),
    ("BEPC", None, "Français"),
    ("Probatoire", "C", "Mathematiques"),
    ("Probatoire", "A4", "Philosophie"),
    ("BAC", "C", "Mathematiques"),
    ("BAC", "D", "SVT"),
    ("BAC", "TI", "Informatique"),
    ("BAC", "A4", "Philosophie"),
]

conn = sqlite3.connect(DB_PATH)

print("=== ÉTAT RÉEL DES DONNÉES DE TEST PAR COMBINAISON ===\n")

for niveau, serie, matiere in COMBINAISONS:
    print(f"→ {niveau} {serie or '(sans série)'} {matiere}")

    # 1. Officiel
    q = "SELECT COUNT(*) FROM annales WHERE niveau=? AND matiere=? AND source=?"
    p = [niveau, matiere, TAG]
    if serie:
        q += " AND serie=?"; p.append(serie)
    nb_off = conn.execute(q, p).fetchone()[0]

    # 2. Pack officiel
    q = "SELECT COUNT(*) FROM packs_corriges WHERE niveau=? AND matiere=? AND categorie='officiel' AND titre LIKE '[TEST]%'"
    p = [niveau, matiere]
    if serie:
        q += " AND serie=?"; p.append(serie)
    else:
        q += " AND serie IS NULL"
    nb_pack_off = conn.execute(q, p).fetchone()[0]

    # 3. Blancs
    q = "SELECT COUNT(*) FROM annales_blanches WHERE niveau=? AND matiere=? AND titre LIKE '[TEST]%'"
    p = [niveau, matiere]
    if serie:
        q += " AND serie=?"; p.append(serie)
    nb_blanc = conn.execute(q, p).fetchone()[0]

    # 4. Pack blanc
    q = "SELECT COUNT(*) FROM packs_corriges WHERE niveau=? AND matiere=? AND categorie='blanc' AND titre LIKE '[TEST]%'"
    p = [niveau, matiere]
    if serie:
        q += " AND serie=?"; p.append(serie)
    else:
        q += " AND serie IS NULL"
    nb_pack_blanc = conn.execute(q, p).fetchone()[0]

    # 5. Établissements
    q = "SELECT COUNT(*) FROM annales_externes WHERE niveau=? AND matiere=? AND source_site=?"
    p = [niveau, matiere, TAG]
    if serie:
        q += " AND serie=?"; p.append(serie)
    nb_etab = conn.execute(q, p).fetchone()[0]

    print(f"    officiel={nb_off}  pack_officiel={nb_pack_off}  blanc={nb_blanc}  pack_blanc={nb_pack_blanc}  etablissement={nb_etab}")

    manquants = []
    if nb_off == 0: manquants.append("officiel")
    if nb_pack_off == 0: manquants.append("pack_officiel")
    if nb_blanc == 0: manquants.append("blanc")
    if nb_pack_blanc == 0: manquants.append("pack_blanc")
    if nb_etab == 0: manquants.append("etablissement")
    if manquants:
        print(f"    ⚠️ MANQUANT : {manquants}")
    print()

conn.close()