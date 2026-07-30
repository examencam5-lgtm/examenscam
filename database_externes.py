# database_externes.py
"""
Fonctions de LECTURE pour la table 'annales_externes' (Ã©tablissements).
import_liens_externes.py gÃ¨re l'Ã©criture (scraping) ; ce fichier gÃ¨re
la lecture pour affichage sur le site.
"""

import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path('data') / 'annales.db'

# MÃªme correspondance que import_liens_externes.py, dans les deux sens
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


def get_matieres_externes(niveau_serie: str) -> list[dict]:
    """Liste les matiÃ¨res disponibles pour un niveau_serie, avec le
    nombre d'Ã©preuves indexÃ©es par matiÃ¨re (pour les badges du menu)."""
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        return []
    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]

    conn = get_connection()
    query = "SELECT matiere, COUNT(*) as nombre FROM annales_externes WHERE niveau=? AND actif=1"
    params = [niveau]
    if serie:
        query += " AND serie=?"
        params.append(serie)
    query += " GROUP BY matiere ORDER BY matiere"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]



def get_annales_externes(niveau_serie: str, matiere: str, region: Optional[str] = None,
                          sequence: Optional[int] = None) -> list[dict]:
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        return []
    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]
    conn = get_connection()
    query = "SELECT * FROM annales_externes WHERE niveau=? AND matiere=? AND actif=1"
    params = [niveau, matiere]
    if serie:
        query += " AND serie=?"
        params.append(serie)
    if region:
        query += " AND region=?"
        params.append(region)
    if sequence:
        query += " AND sequence=?"
        params.append(sequence)
    query += " ORDER BY date_ajout DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_annale_externe_by_id(annale_id: int) -> Optional[dict]:
    """RÃ©cupÃ¨re une Ã©preuve prÃ©cise -- utilisÃ© par la route de redirection."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM annales_externes WHERE id=?", (annale_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def increment_vue_externe(annale_id: int):
    """IncrÃ©mente le compteur de vues avant la redirection -- garde
    tes stats de trafic mÃªme sans hÃ©berger le contenu."""
    conn = get_connection()
    conn.execute("UPDATE annales_externes SET vues = vues + 1 WHERE id=?", (annale_id,))
    conn.commit()
    conn.close()


REGIONS_CAMEROUN = [
    "Adamaoua", "Centre", "Est", "Extreme-Nord", "Littoral",
    "Nord", "Nord-Ouest", "Ouest", "Sud", "Sud-Ouest",
]

def get_regions_disponibles_externes(niveau_serie: str, matiere: str) -> list[dict]:
    """
    Retourne TOUJOURS les 10 régions du Cameroun, avec un flag
    'disponible' selon qu'il y a au moins une épreuve ou non.
    Permet d'afficher la couverture nationale complète même si
    incomplète -- utile pour suivre visuellement la progression
    de la collecte.
    """
    if niveau_serie not in CORRESPONDANCE_NIVEAU_SERIE:
        return [{"nom": r, "disponible": False} for r in REGIONS_CAMEROUN]
    niveau, serie = CORRESPONDANCE_NIVEAU_SERIE[niveau_serie]
    conn = get_connection()
    query = """
        SELECT DISTINCT region FROM annales_externes
        WHERE niveau=? AND matiere=? AND actif=1 AND region IS NOT NULL AND region != ''
    """
    params = [niveau, matiere]
    if serie:
        query += " AND serie=?"
        params.append(serie)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    regions_avec_donnees = {r[0] for r in rows}
    return [{"nom": r, "disponible": r in regions_avec_donnees} for r in REGIONS_CAMEROUN]


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
    print("MatiÃ¨res terminale-c :", get_matieres_externes("terminale-c"))
    print("Ã‰preuves Maths :", get_annales_externes("terminale-c", "Mathematiques"))
