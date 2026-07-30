# scripts/import_liens_externes.py
"""
Importe un CSV généré par scrape_sujetexa.py dans la table
'annales_externes' (séparée de 'annales', pour ne pas entrer en
conflit avec sa contrainte UNIQUE niveau/serie/matiere/annee).
Enrichi via parser_titre_sujetexa.py (établissement, région,
séquence, type d'évaluation, classe détectée).

Usage :
    python scripts/import_liens_externes.py data/liens_externes/sujetexa_terminale-c_2026.csv terminale-c
"""

import csv
import sys
import sqlite3
from pathlib import Path

# On importe le parseur -- il doit être dans le même dossier scripts/
from parser_titre_sujetexa import parser_titre

DB_PATH = Path('data') / 'annales.db'

CORRESPONDANCE_NIVEAU_SERIE = {
    "troisieme": ("BEPC", None),
    "premiere-a": ("Premiere", "A"),
    "premiere-c": ("Premiere", "C"),
    "premiere-d": ("Premiere", "D"),
    "terminale-a": ("BAC", "A"),
    "terminale-c": ("BAC", "C"),
    "terminale-d": ("BAC", "D"),
}


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def importer_csv(chemin_csv: str, niveau_serie: str):
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        print(f"❌ niveau_serie inconnu : {niveau_serie}")
        print(f" Options : {list(CORRESPONDANCE_NIVEAU_SERIE.keys())}")
        return

    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]

    chemin = Path(chemin_csv)
    if not chemin.exists():
        print(f"❌ Fichier introuvable : {chemin_csv}")
        return

    conn = get_connection()
    inseres = 0
    ignores_sans_pdf = 0
    ignores_sans_annee = 0
    doublons = 0
    erreurs = 0

    with open(chemin, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for ligne in reader:
            lien_pdf = ligne.get("lien_pdf", "").strip()
            if not lien_pdf:
                ignores_sans_pdf += 1
                continue

            titre = ligne.get("titre", "")
            infos = parser_titre(titre)
            annee = ligne.get("annee") or infos["annee_detectee"]

            # Rejet explicite si aucune année fiable n'a pu être déterminée --
            # mieux vaut ignorer la ligne que l'insérer avec annee=0, ce qui
            # la rendrait invisible dans les tris (ORDER BY annee DESC) sans
            # jamais signaler le problème.
            if not annee or not (1990 <= int(annee) <= 2030):
                ignores_sans_annee += 1
                print(f" ⚠️ Ignorée (année invalide ou absente) : '{titre[:60]}...'")
                continue

            try:
                conn.execute("""
                    INSERT INTO annales_externes (
                        niveau, serie, matiere, annee, titre,
                        etablissement, region,
                        sequence, type_evaluation, classe_detectee,
                        lien_externe, lien_page_source, source_site
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'sujetexa')
                """, (
                    niveau, serie,
                    ligne.get("matiere", ""),
                    int(annee),
                    titre,
                    infos["etablissement"],
                    infos["region"],
                    infos["sequence"],
                    infos["type_evaluation"],
                    infos["classe_detectee"],
                    lien_pdf,
                    ligne.get("lien_page", ""),
                ))
                inseres += 1
            except sqlite3.IntegrityError:
                # Ce lien PDF précis a déjà été importé -- pas une erreur
                # grave, juste un doublon (ex: script relancé deux fois)
                doublons += 1
            except (sqlite3.Error, ValueError) as e:
                print(f" ❌ Erreur sur '{titre[:50]}...' : {e}")
                erreurs += 1

    conn.commit()
    conn.close()
    print(f"\n✅ Import terminé pour {chemin.name}")
    print(f" Insérées : {inseres}")
    print(f" Ignorées (pas de lien PDF) : {ignores_sans_pdf}")
    print(f" Ignorées (année invalide/absente) : {ignores_sans_annee}")
    print(f" Doublons (déjà importés) : {doublons}")
    print(f" Erreurs : {erreurs}")
    


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage : python import_liens_externes.py <chemin_csv> <niveau-serie>")
        sys.exit(1)

    importer_csv(sys.argv[1], sys.argv[2])
