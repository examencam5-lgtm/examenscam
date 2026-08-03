"""
Fonctions de LECTURE pour la table 'annales_externes' (Ã©tablissements).
import_liens_externes.py gere l'ecriture (scraping) ; ce fichier gere
la lecture pour affichage sur le site.

Filtre change : annee + sequence (au lieu de region + sequence) --
la region est moins utile pour l'eleve qui cherche un devoir precis
que l'annee, elle reste en donnee affichee mais plus en filtre
prioritaire.
"""

import sqlite3
from pathlib import Path
from typing import Optional

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


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_matieres_externes(niveau_serie: str) -> list[dict]:
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        return []
    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]

    conn = get_connection()
    query = "SELECT matiere, COUNT(*) as nombre FROM annales_externes WHERE niveau=? AND actif=1"
    params = [niveau]
    if serie:
        # Meme regle que database_matieres.py : serie IS NULL ne
        # "compte pour toutes les series" que pour BEPC. Ici serie
        # est toujours non-None dans CORRESPONDANCE_NIVEAU_SERIE sauf
        # pour 'troisieme' -> (BEPC, None), donc ce cas ne se presente
        # jamais pour BAC/Probatoire -- comparaison stricte suffit.
        query += " AND serie=?"
        params.append(serie)
    query += " GROUP BY matiere ORDER BY matiere"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_annales_externes(niveau_serie: str, matiere: str, annee: Optional[int] = None,
                          sequence: Optional[int] = None) -> list[dict]:
    """Filtre par annee + sequence (remplace le filtre region + sequence)."""
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        return []
    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]
    conn = get_connection()
    query = "SELECT * FROM annales_externes WHERE niveau=? AND matiere=? AND actif=1"
    params = [niveau, matiere]
    if serie:
        query += " AND serie=?"
        params.append(serie)
    if annee:
        query += " AND annee=?"
        params.append(annee)
    if sequence:
        query += " AND sequence=?"
        params.append(sequence)
    query += " ORDER BY annee DESC, date_ajout DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_annale_externe_by_id(annale_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM annales_externes WHERE id=?", (annale_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def increment_vue_externe(annale_id: int):
    conn = get_connection()
    conn.execute("UPDATE annales_externes SET vues = vues + 1 WHERE id=?", (annale_id,))
    conn.commit()
    conn.close()


def get_annees_disponibles(niveau_serie: str, matiere: str) -> list[dict]:
    """
    Retourne les annees reellement presentes pour ce niveau/matiere,
    triees decroissant -- remplace get_regions_disponibles_externes
    comme filtre principal (doc : annee plus utile que region pour
    l'eleve qui cherche un devoir precis).
    """
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        return []
    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]
    conn = get_connection()
    query = """
        SELECT DISTINCT annee FROM annales_externes
        WHERE niveau=? AND matiere=? AND actif=1
    """
    params = [niveau, matiere]
    if serie:
        query += " AND serie=?"
        params.append(serie)
    query += " ORDER BY annee DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_sequences_disponibles(niveau_serie: str, matiere: str) -> list[dict]:
    """Retourne TOUJOURS les séquences 1 à 6, avec flag 'disponible'."""
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        return [{"num": s, "disponible": False} for s in range(1, 7)]
    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]
    conn = get_connection()
    query = """
        SELECT DISTINCT sequence FROM annales_externes
        WHERE niveau=? AND matiere=? AND actif=1 AND sequence IS NOT NULL
    """
    params = [niveau, matiere]
    if serie:
        query += " AND serie=?"
        params.append(serie)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    sequences_avec_donnees = {r[0] for r in rows}
    return [{"num": s, "disponible": s in sequences_avec_donnees} for s in range(1, 7)]


if __name__ == "__main__":
    print("Matieres terminale-c :", get_matieres_externes("terminale-c"))
    print("Annees disponibles :", get_annees_disponibles("terminale-c", "Mathematiques"))