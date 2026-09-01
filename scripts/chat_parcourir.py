# scripts/chat_parcourir.py
"""
Fonction de listing pour le bouton "Parcourir" du chat élève
(27/08/2026). Contrairement à chat_intent_epreuve.py (recherche par
texte libre), ici l'élève navigue par clics successifs
(niveau -> série -> matière), donc pas besoin du scoring de
database_search.py -- une simple requête filtrée sur search_index
suffit, cette table est déjà la source unifiée officiel+externe
(voir generer_search_index.py).

STRUCTURE NIVEAU/SÉRIE : codée en dur ici (pas de table dédiée dans
le projet à ce jour) -- reflète l'organisation réelle du programme
camerounais telle que documentée dans le mémoire du projet (BEPC sans
série, Probatoire A/C/D, BAC C/D/TI/A4). Si cette structure change,
c'est ICI qu'il faut la mettre à jour, pas dans le front.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path("data") / "annales.db"

SERIES_PAR_NIVEAU = {
    "BEPC": [],
    "Probatoire": ["A", "C", "D"],
    "BAC": ["C", "D", "TI", "A4"],
}

NB_RESULTATS_PARCOURIR = 8


def get_niveaux() -> list[str]:
    return list(SERIES_PAR_NIVEAU.keys())


def get_series(niveau: str) -> list[str]:
    return SERIES_PAR_NIVEAU.get(niveau, [])


def lister_epreuves(niveau: str, matiere: str, serie: str | None = None) -> list[dict]:
    """Interroge search_index directement -- déjà la table unifiée
    officiel+externe (voir generer_search_index.py), pas besoin de
    croiser 'annales' et 'annales_externes' séparément ici.

    Retourne au plus NB_RESULTATS_PARCOURIR entrées {libelle, destination},
    triées par libelle décroissant -- pour les épreuves officielles, le
    libellé se termine par l'année (ex: "BAC C Mathematiques 2023"),
    donc ce tri approxime un tri par année récente d'abord. Pour les
    externes, le tri est moins significatif mais reste stable et
    prévisible."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        query = "SELECT libelle, destination, type_source FROM search_index WHERE niveau=? AND matiere=?"
        params = [niveau, matiere]
        if serie:
            query += " AND serie=?"
            params.append(serie)
        elif niveau == "BEPC":
            # BEPC n'a pas de série -- cohérent avec la convention déjà
            # en place ailleurs (database.get_annales, serie IS NULL).
            query += " AND serie IS NULL"
        query += " ORDER BY libelle DESC LIMIT ?"
        params.append(NB_RESULTATS_PARCOURIR)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()