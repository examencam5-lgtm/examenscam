"""
scripts/import_sigmaths.py

Import dedie pour le CSV genere par scrape_sigmaths.py.

Contrairement a sujetexa/epreuvesetcorriges, sigmaths n'a pas de
notion d'etablissement ni de sequence -- le CSV expose deja niveau,
serie, matiere, annee et titre directement en colonnes. Pas besoin
du parser_titre_sujetexa ni de detecter_matiere : on utilise donc un
import dedie plutot que de forcer ce format dans
scripts/import_liens_externes.py (qui est fait pour l'auto-detection
sujetexa/epreuvesetcorriges et ne doit pas etre modifie pour ca).

Meme table, memes colonnes, meme logique d'insertion que
import_liens_externes.py -- juste sans l'etape de parsing de titre.

Usage :
    python scripts/import_sigmaths.py data/scraped/sigmaths_cameroun.csv
"""

import csv
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generer_search_index import generer as regenerer_index

DB_PATH = Path('data') / 'annales.db'
SOURCE_PAGE = "https://www.sigmaths.net/bac2/Cameroun.php"


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

            # source_site lit explicitement la colonne du CSV -- si le
            # CSV ne l'a pas (ancien format), on met 'sigmaths' en dur
            # plutot qu'un defaut generique, puisque ce script ne sert
            # qu'a importer du sigmaths.
            source_site = (ligne.get("source_site") or "sigmaths").strip() or "sigmaths"

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
                    None,  # pas d'etablissement pour sigmaths
                    None,  # pas de region
                    None,  # pas de sequence
                    None,  # pas de type_evaluation
                    None,  # pas de classe_detectee
                    lien_pdf,
                    SOURCE_PAGE,
                    source_site,
                    None,  # signature_dedup : pas de dedup cross-site pour sigmaths
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
        print("Usage : python scripts/import_sigmaths.py <chemin_csv>")
        sys.exit(1)

    importer_csv(sys.argv[1])