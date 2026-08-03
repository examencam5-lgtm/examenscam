"""
scripts/import_liens_externes.py — ExamensCam
Importe un CSV classifie 'externe' (issu de classifier_epreuves.py)
dans la table 'annales_externes'.

Dedoublonnage a deux niveaux :
  1. UNIQUE(lien_externe) -- meme lien PDF exact, deja gere par la
     contrainte SQL existante (INSERT OR IGNORE)
  2. signature_dedup -- meme devoir scrape sur DEUX sites differents
     (sujetexa ET epreuvesetcorriges), donc deux lien_externe
     differents mais le meme etablissement/matiere/annee/sequence.
     Verifie manuellement avant insert (pas de contrainte UNIQUE
     stricte dessus -- trop risque de rejeter de vrais doublons
     legitimes, voir migration_signature_dedup.py pour le detail).

Usage :
    python scripts/import_liens_externes.py data/liens_externes/a_indexer_externe.csv terminale-c
"""

import csv
import sys
import sqlite3
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generer_search_index import generer as regenerer_index
from migration_signature_dedup import calculer_signature
from extracteur_matiere import detecter_matiere

# On importe le parseur -- il doit etre dans le meme dossier scripts/
from parser_titre_sujetexa import parser_titre

DB_PATH = Path('data') / 'annales.db'

CORRESPONDANCE_NIVEAU_SERIE = {
    "troisieme": ("BEPC", None),
    "premiere-a": ("Probatoire", "A"),
    "premiere-c": ("Probatoire", "C"),
    "premiere-d": ("Probatoire", "D"),
    "terminale-a": ("BAC", "A"),
    "terminale-c": ("BAC", "C"),
    "terminale-d": ("BAC", "D"),
}


def extraire_serie_depuis_classe(niveau: str, classe_detectee: str) -> str | None:
    """
    Deduit la serie (C, D, A4, TI...) depuis le code de classe
    detecte par le parseur (ex: 'TLeC' -> 'C', 'PA' -> 'A').
    Retourne None pour BEPC (pas de serie) ou si aucun code de
    classe n'a ete detecte dans le titre -- dans ce dernier cas,
    la ligne sera importee avec serie=NULL plutot que devinee a tort.
    """
    if niveau == "BEPC" or not classe_detectee:
        return None

    c = classe_detectee.upper()
    # Retire le prefixe Terminale (T, TLE, LE...) pour le BAC
    c = re.sub(r"^T?LE?", "", c)
    # Retire le prefixe Probatoire (P) -- uniquement si le reste
    # ressemble a un code serie valide, pour ne pas casser un code
    # qui commencerait deja par une lettre serie coincidant avec 'P'
    if niveau == "Probatoire" and c.startswith("P"):
        c = c[1:]
    c = c.strip()
    return c or None


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def importer_csv(chemin_csv: str, niveau_serie: str = None):
    """
    Deux modes :
    - niveau_serie fourni (ex: 'terminale-c') : TOUTES les lignes du
      CSV recoivent ce niveau/serie -- adapte a sujetexa, dont un
      fichier scrape correspond deja a UN SEUL niveau/serie.
    - niveau_serie absent : chaque ligne deduit son propre
      niveau/serie depuis 'niveau_devine' (colonne CSV) + le code de
      classe detecte dans le titre -- adapte a epreuvesetcorriges,
      dont un seul fichier melange tous les niveaux/series.
    """
    mode_uniforme = niveau_serie is not None

    if mode_uniforme:
        if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
            print(f"niveau_serie inconnu : {niveau_serie}")
            print(f"Options : {list(CORRESPONDANCE_NIVEAU_SERIE.keys())}")
            return
        niveau_fixe, serie_fixe = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]

    chemin = Path(chemin_csv)
    if not chemin.exists():
        print(f"Fichier introuvable : {chemin_csv}")
        return

    conn = get_connection()
    inseres = 0
    ignores_sans_pdf = 0
    ignores_sans_annee = 0
    ignores_sans_matiere = 0
    ignores_sans_niveau_serie = 0
    doublons_lien = 0
    doublons_signature = 0
    erreurs = 0

    with open(chemin, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)

        for ligne in reader:
            lien_pdf = (ligne.get("lien_pdf") or ligne.get("lien_externe") or "").strip()
            if not lien_pdf:
                ignores_sans_pdf += 1
                continue

            titre = ligne.get("titre", "")
            infos = parser_titre(titre)
            annee = ligne.get("annee") or ligne.get("annee_devinee") or infos["annee_detectee"]

            if not annee or not (1990 <= int(annee) <= 2030):
                ignores_sans_annee += 1
                print(f"Ignoree (annee invalide/absente) : '{titre[:60]}...'")
                continue

            annee = int(annee)

            # Matiere : utilise la colonne CSV si presente et non-vide
            # (cas sujetexa, ou la sous-categorie EST la matiere),
            # sinon la deduit du titre (cas epreuvesetcorriges, qui
            # n'expose pas la matiere comme colonne separee)
            matiere = (ligne.get("matiere") or "").strip()
            if not matiere:
                matiere = detecter_matiere(titre)
            if not matiere:
                ignores_sans_matiere += 1
                print(f"Ignoree (matiere indetectable) : '{titre[:60]}...'")
                continue

            # Niveau/serie : fixe (mode uniforme) ou deduit ligne par
            # ligne (mode auto-detection, epreuvesetcorriges)
            if mode_uniforme:
                niveau, serie = niveau_fixe, serie_fixe
            else:
                niveau = (ligne.get("niveau_devine") or "").strip()
                if niveau not in ("BAC", "Probatoire", "BEPC"):
                    ignores_sans_niveau_serie += 1
                    print(f"Ignoree (niveau non reconnu '{niveau}') : '{titre[:60]}...'")
                    continue
                serie = extraire_serie_depuis_classe(niveau, infos["classe_detectee"])
                # Pas de serie detectee pour un niveau qui en a besoin
                # (BAC/Probatoire) -- on importe quand meme avec
                # serie=NULL plutot que de rejeter : mieux vaut une
                # ligne visible sans filtre serie precis qu'une ligne
                # perdue. L'eleve la retrouvera via la recherche/matiere.

            # Dedup cross-sites : verifie si une ligne avec la meme
            # signature existe deja (meme devoir vu sur un autre site)
            # Dedup cross-sites : verifie si une ligne avec la meme
            # signature existe deja (meme devoir vu sur un autre site).
            # UNIQUEMENT si la sequence est connue -- sans elle, la
            # signature fusionnerait a tort des devoirs differents du
            # meme etablissement/matiere/annee (ex: 20 devoirs de
            # Francais 2022 au meme college, sequences 1 a 6, tous
            # traites comme UN SEUL devoir si sequence=None pour tous).
            # Mieux vaut un doublon rate qu'une vraie donnee perdue.
            if infos["sequence"] is not None:
                signature = calculer_signature(
                    niveau, serie, matiere, annee,
                    infos["etablissement"], infos["sequence"]
                )
                existe_deja = conn.execute(
                    "SELECT id, source_site FROM annales_externes WHERE signature_dedup = ?",
                    (signature,)
                ).fetchone()
                if existe_deja:
                    doublons_signature += 1
                    continue
            else:
                signature = None

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
                    niveau, serie,
                    matiere,
                    annee,
                    titre,
                    infos["etablissement"],
                    infos["region"],
                    infos["sequence"],
                    infos["type_evaluation"],
                    infos["classe_detectee"],
                    lien_pdf,
                    ligne.get("lien_page") or ligne.get("lien_page_source", ""),
                    ligne.get("source_site", "sujetexa"),
                    signature,
                ))
                inseres += 1
            except sqlite3.IntegrityError:
                doublons_lien += 1
            except (sqlite3.Error, ValueError) as e:
                print(f"Erreur sur '{titre[:50]}...' : {e}")
                erreurs += 1

    conn.commit()
    conn.close()

    print(f"\nImport termine pour {chemin.name}")
    print(f"  Inserees : {inseres}")
    print(f"  Ignorees (pas de lien PDF) : {ignores_sans_pdf}")
    print(f"  Ignorees (annee invalide/absente) : {ignores_sans_annee}")
    print(f"  Ignorees (matiere indetectable) : {ignores_sans_matiere}")
    print(f"  Ignorees (niveau non reconnu) : {ignores_sans_niveau_serie}")
    print(f"  Doublons (meme lien exact) : {doublons_lien}")
    print(f"  Doublons (meme devoir, autre site) : {doublons_signature}")
    print(f"  Erreurs : {erreurs}")

    if inseres > 0:
        print("\nRegeneration de l'index de recherche...")
        regenerer_index()
    else:
        print("\nIndex non regenere (aucune nouvelle ligne importee).")


if __name__ == "__main__":
    if len(sys.argv) not in (2, 3):
        print("Usage :")
        print("  python import_liens_externes.py <chemin_csv> <niveau-serie>   # mode uniforme (sujetexa)")
        print("  python import_liens_externes.py <chemin_csv>                 # mode auto-detection (epreuvesetcorriges)")
        sys.exit(1)

    chemin = sys.argv[1]
    niveau_serie_arg = sys.argv[2] if len(sys.argv) == 3 else None
    importer_csv(chemin, niveau_serie_arg)