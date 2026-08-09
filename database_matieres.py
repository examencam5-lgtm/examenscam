"""
database_matieres.py — ExamensCam
Liste les matieres reellement disponibles pour un niveau/serie
donne, en croisant les 2 tables (annales, annales_externes) --
pas seulement 'annales' comme le faisait get_matieres_fallback()
jusqu'ici.

Pourquoi ce fichier est separe : eviter les imports circulaires
entre database.py et database_externes.py -- celui-ci se contente
d'ouvrir sa propre connexion et de lire, sans dependre des autres
modules.
"""
import sqlite3
from pathlib import Path
from typing import Optional

DB_PATH = Path('data') / 'annales.db'

# Ordre pedagogique par serie -- connaissance du terrain, pas un tri
# alphabetique. Les matieres non listees ici suivent, triees par
# ordre alphabetique, a la fin de la liste (jamais perdues, juste
# moins prioritaires visuellement).
ORDRE_PAR_SERIE = {
    "C": ["Mathematiques", "Physique", "Chimie"],
    "D": ["SVT", "Mathematiques", "Physique", "Chimie"],
    "TI": ["Mathematiques", "Physique", "Informatique", "Chimie"],
    "A4": ["Litterature", "Anglais", "Allemand", "Espagnol", "Francais", "Histoire", "Geographie"],
}

TABLES_SOURCES = ("annales", "annales_externes")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def trier_matieres(matieres: set, serie: Optional[str]) -> list[str]:
    """
    Trie selon ORDRE_PAR_SERIE si la serie est connue, sinon
    alphabetique simple (cas BEPC, ou serie non couverte).
    """
    ordre = ORDRE_PAR_SERIE.get(serie, [])
    prioritaires = [m for m in ordre if m in matieres]
    reste = sorted(m for m in matieres if m not in ordre)
    return prioritaires + reste


def get_toutes_matieres(niveau: str, serie: Optional[str] = None) -> list[str]:
    """
    Union des matieres presentes dans les tables sources pour ce
    niveau/serie, triee selon l'ordre pedagogique, sans doublons.
    """
    conn = get_connection()
    try:
        matieres = set()

        for table in TABLES_SOURCES:
            query = f"SELECT DISTINCT matiere FROM {table} WHERE niveau = ? AND actif = 1"
            params = [niveau]
            if serie:
                if niveau == 'BEPC':
                    query += " AND (serie = ? OR serie IS NULL)"
                else:
                    query += " AND serie = ?"
                params.append(serie)
            rows = conn.execute(query, params).fetchall()
            matieres.update(r['matiere'] for r in rows if r['matiere'])

        return trier_matieres(matieres, serie)
    except Exception as e:
        print(f"get_toutes_matieres error: {e}")
        return []
    finally:
        conn.close()