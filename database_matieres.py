"""
database_matieres.py — ExamensCam
Liste les matieres reellement disponibles pour un niveau/serie
donne, en croisant les 3 tables (annales, annales_blanches,
annales_externes) -- pas seulement 'annales' comme le faisait
get_matieres_fallback() jusqu'ici.

Pourquoi ce fichier est separe : eviter les imports circulaires
entre database.py, database_blanches.py et database_externes.py --
celui-ci se contente d'ouvrir sa propre connexion et de lire, sans
dependre des autres modules.
"""
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path('data') / 'annales.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_toutes_matieres(niveau: str, serie: Optional[str] = None) -> list[str]:
    """
    Union des matieres presentes dans les 3 tables pour ce
    niveau/serie, triee alphabetiquement, sans doublons.
    """
    conn = get_connection()
    try:
        matieres = set()

        for table in ("annales", "annales_blanches", "annales_externes"):
            query = f"SELECT DISTINCT matiere FROM {table} WHERE niveau = ? AND actif = 1"
            params = [niveau]
            if serie:
                query += " AND (serie = ? OR serie IS NULL)"
                params.append(serie)
            rows = conn.execute(query, params).fetchall()
            matieres.update(r['matiere'] for r in rows if r['matiere'])

        return sorted(matieres)
    except Exception as e:
        print(f"get_toutes_matieres error: {e}")
        return []
    finally:
        conn.close()