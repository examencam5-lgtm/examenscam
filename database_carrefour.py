"""
Fonction centrale pour la nouvelle page "carrefour" (les 5 branches
entre le choix de matière et les épreuves elles-mêmes).

Une seule fonction interroge les 4 tables concernées et retourne les
compteurs nécessaires pour afficher des badges vivants sur chaque
branche (ex: "6 années", "23 épreuves indexées", "4/7 corrigés prêts")
au lieu de chiffres statiques codés en dur dans le HTML.
"""

import sqlite3
from pathlib import Path
from typing import Optional
from database_externes import CORRESPONDANCE_NIVEAU_SERIE

DB_PATH = Path('data') / 'annales.db'

# ── Pont entre les deux conventions de nomenclature ──
# officiel/blanc : niveau='BAC'/'Probatoire'/'BEPC', serie='C'/'D'/'A4'/'TI'
# établissements (scraping sujetexa) : niveau='BAC'/'Premiere', serie='A'/'C'/'D'
#
# Plutôt qu'une liste figée paire par paire (source d'oublis -- Probatoire D
# avait été oublié), le slug se construit automatiquement à partir d'une
# base par niveau + normalisation de la série.

BASE_SLUG_ETABLISSEMENTS = {
    "BAC": "terminale",
    "Premiere": "premiere",
    "Probatoire": "premiere",  # Probatoire partage le corpus sujetexa de Première
}

# Séries réellement couvertes par le scraping (voir CATEGORIES dans
# scrape_sujetexa.py). Toute série absente d'ici n'aura simplement pas
# de branche établissements -- comportement voulu, pas un bug.
SERIES_SCRAPEES = {"A", "C", "D"}


def get_slug_etablissements(niveau: str, serie: Optional[str]) -> Optional[str]:
    """
    Construit le slug établissements (ex: 'terminale-c', 'premiere-d')
    à partir du niveau et de la série. Retourne None si aucune
    correspondance sujetexa n'existe pour cette combinaison.
    """
    if niveau == "BEPC":
        return "troisieme"

    base = BASE_SLUG_ETABLISSEMENTS.get(niveau)
    if not base or not serie:
        return None

    # A4 (Probatoire/BAC) correspond à la catégorie 'a' côté sujetexa
    serie_normalisee = "A" if serie == "A4" else serie

    if serie_normalisee not in SERIES_SCRAPEES:
        return None  # ex: TI -- pas de catégorie sujetexa correspondante

    return f"{base}-{serie_normalisee.lower()}"


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_carrefour(niveau: str, matiere: str, serie: Optional[str] = None) -> dict:
    """
    Retourne l'état des 5 branches pour un niveau/série/matière donné.
    Utilisé pour peupler la page carrefour avec des chiffres réels.
    """
    conn = get_connection()

    # ── Branche 1 : Énoncés officiels ──
    q1 = "SELECT COUNT(*) FROM annales WHERE niveau=? AND matiere=? AND actif=1"
    p1 = [niveau, matiere]
    if serie:
        q1 += " AND serie=?"
        p1.append(serie)
    nb_officiel = conn.execute(q1, p1).fetchone()[0]

    # ── Branche 2 : Pack corrigés officiels (progression) ──
    q2 = """
        SELECT p.id, p.titre, p.prix,
               COUNT(c.id) AS total, SUM(CASE WHEN c.statut='pret' THEN 1 ELSE 0 END) AS prets
        FROM packs_corriges p
        LEFT JOIN corriges_fichiers c ON c.pack_id = p.id
        WHERE p.niveau=? AND p.matiere=? AND p.categorie='officiel' AND p.actif=1
    """
    p2 = [niveau, matiere]
    if serie:
        q2 += " AND p.serie=?"
        p2.append(serie)
    q2 += " GROUP BY p.id ORDER BY p.annee_fin DESC LIMIT 1"
    pack_officiel = conn.execute(q2, p2).fetchone()

    # ── Branche 3 : Énoncés blancs ──
    q3 = "SELECT COUNT(*) FROM annales_blanches WHERE niveau=? AND matiere=? AND actif=1"
    p3 = [niveau, matiere]
    if serie:
        q3 += " AND serie=?"
        p3.append(serie)
    nb_blancs = conn.execute(q3, p3).fetchone()[0]

    # ── Branche 4 : Pack corrigés blancs (progression) ──
    q4 = q2.replace("categorie='officiel'", "categorie='blanc'")
    pack_blanc = conn.execute(q4, p2).fetchone()

    # ── Branche 5 : Énoncés établissements ──
    # annales_externes utilise sa propre nomenclature (niveau='Premiere'
    # au lieu de 'Probatoire', par ex.) -- on traduit via le slug avant
    # d'interroger cette table.
    slug = get_slug_etablissements(niveau, serie)
    if slug and slug in CORRESPONDANCE_NIVEAU_SERIE:
        niveau_reel, serie_reel = CORRESPONDANCE_NIVEAU_SERIE[slug]
        q5 = "SELECT COUNT(*) FROM annales_externes WHERE niveau=? AND matiere=? AND actif=1"
        p5 = [niveau_reel, matiere]
        if serie_reel:
            q5 += " AND serie=?"
            p5.append(serie_reel)
        nb_etablissements = conn.execute(q5, p5).fetchone()[0]
    else:
        nb_etablissements = 0

    conn.close()

    return {
        "officiel_enonces": {"nombre": nb_officiel},
        "officiel_corriges": dict(pack_officiel) if pack_officiel else None,
        "blancs_enonces": {"nombre": nb_blancs},
        "blancs_corriges": dict(pack_blanc) if pack_blanc else None,
        "etablissements_enonces": {"nombre": nb_etablissements},
        "slug_etablissements": slug,
    }


if __name__ == "__main__":
    import json
    for niveau, serie in [("BAC", "C"), ("BAC", "D"), ("Probatoire", "C"),
                          ("Probatoire", "D"), ("Probatoire", "TI")]:
        print(f"\n{niveau} {serie} :")
        print(json.dumps(get_carrefour(niveau, "Mathematiques", serie=serie),
                         indent=2, ensure_ascii=False))