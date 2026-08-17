"""
scripts/import_concourscameroon.py

Import dedie pour le CSV genere par scrape_concourscameroon.py.

Meme schema que import_sigmaths.py, avec une difference cle tiree
du bug sigmaths corrige : lien_page_source = lien_externe directement
(le lien EST deja le PDF/Drive final, pas une page intermediaire a
lister separement). La route redirection_externe() redirige vers
lien_page_source -- donc si ce champ pointe vers une page d'index au
lieu du PDF, le clic emmene l'utilisateur au mauvais endroit (voir
le bug sigmaths : 126 lignes redirigeaient toutes vers la meme page
Cameroun.php au lieu du PDF individuel).

Usage :
    python scripts/import_concourscameroon.py data/scraped/concourscameroon.csv
"""

import csv
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generer_search_index import generer as regenerer_index

DB_PATH = Path('data') / 'annales.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def importer_csv(chemin_csv: str):
    chemin = Path(chemin_csv)
    if not chemin.exists():
        print(f"Fichier introuvable : {chemin_csv}")
        return

    conn = get_connection()
    inseres = 0
    doublons_lien = 0
    ignores = 0
    erreurs = 0

    with open(chemin, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for ligne in reader:
            lien_pdf = (ligne.get("lien_externe") or "").strip()
            if not lien_pdf:
                ignores += 1
                continue

            niveau = (ligne.get("niveau") or "").strip()
            serie = (ligne.get("serie") or "").strip() or None
            matiere = (ligne.get("matiere") or "").strip()
            titre = (ligne.get("titre") or "").strip()

            try:
                annee = int(ligne.get("annee") or 0)
            except ValueError:
                annee = 0

            if not (niveau and matiere and 1900 <= annee <= 2030):
                ignores += 1
                print(f"Ignoree (donnees incompletes) : '{titre[:60]}'")
                continue

            source_site = (ligne.get("source_site") or "concourscameroon").strip() or "concourscameroon"

            try:
                conn.execute("""
                    INSERT INTO annales_externes (
                        niveau, serie, matiere, annee, titre,
                        etablissement, region,
                        sequence, type_evaluation, classe_detectee,
                        lien_externe, lien_page_source, source_site,
                        signature_dedup
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    niveau, serie, matiere, annee, titre,
                    None, None, None, None, None,
                    lien_pdf,
                    lien_pdf,  # IMPORTANT : lien direct, pas une page listing
                    source_site,
                    None,
                ))
                inseres += 1
            except sqlite3.IntegrityError:
                doublons_lien += 1
            except (sqlite3.Error, ValueError) as e:
                print(f"Erreur sur '{titre[:50]}' : {e}")
                erreurs += 1

    conn.commit()
    conn.close()

    print(f"\nImport termine pour {chemin.name}")
    print(f"  Inserees : {inseres}")
    print(f"  Doublons (meme lien exact) : {doublons_lien}")
    print(f"  Ignorees (donnees incompletes) : {ignores}")
    print(f"  Erreurs : {erreurs}")

    if inseres > 0:
        print("\nRegeneration de l'index de recherche...")
        regenerer_index()
    else:
        print("\nIndex non regenere (aucune nouvelle ligne importee).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage : python scripts/import_concourscameroon.py <chemin_csv>")
        sys.exit(1)

    importer_csv(sys.argv[1])