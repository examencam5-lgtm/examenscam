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

═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) — 04/09/2026
═══════════════════════════════════════════════════════
Même migration que les autres modules database_*.py (voir l'en-tête
de database_eleves.py pour le raisonnement complet) :
  - sqlite3.connect(DB_PATH)        -> psycopg2.connect(DATABASE_URL)
  - conn.row_factory = sqlite3.Row  -> cursor_factory=RealDictCursor
  - placeholders '?'                -> placeholders '%s'
  - conn.execute(...) direct        -> conn.cursor() puis cur.execute(...)

Ce fichier n'écrit jamais (lecture seule) -- pas de conn.commit() ni
de conn.rollback() nécessaires, comme dans l'original.

Cette table croise `annales` et `annales_externes` -- suppose donc
que database.py ET database_externes.py sont déjà migrés et déployés
(fait, voir les échanges précédents).

CE QUI NE CHANGE PAS : trier_matieres() est de la pure logique Python
(pas de SQL) -- inchangée à l'identique.
"""
import os
from typing import Optional

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon "
        "-- sans elle, la liste des matieres ne peut pas etre calculee."
    )

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
    """Retourne une connexion Postgres dont les curseurs renvoient des
    lignes de type dict (RealDictRow) -- même ergonomie que
    sqlite3.Row d'origine : row['colonne'] fonctionne à l'identique."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def trier_matieres(matieres: set, serie: Optional[str]) -> list[str]:
    """
    Trie selon ORDRE_PAR_SERIE si la serie est connue, sinon
    alphabetique simple (cas BEPC, ou serie non couverte).

    INCHANGÉ par la migration -- logique Python pure, pas de SQL.
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
            cur = conn.cursor()
            # ATTENTION : `table` est interpolé directement dans la
            # requête (f-string), comme dans l'original -- SANS
            # risque d'injection ici car TABLES_SOURCES est une
            # constante fixe du code, jamais une valeur venant de
            # l'utilisateur. Les VALEURS (niveau, serie), elles,
            # passent bien par des paramètres liés (%s).
            query = f"SELECT DISTINCT matiere FROM {table} WHERE niveau = %s AND actif = 1"
            params = [niveau]
            if serie:
                if niveau == 'BEPC':
                    query += " AND (serie = %s OR serie IS NULL)"
                else:
                    query += " AND serie = %s"
                params.append(serie)
            cur.execute(query, params)
            rows = cur.fetchall()
            matieres.update(r['matiere'] for r in rows if r['matiere'])

        return trier_matieres(matieres, serie)
    except Exception as e:
        print(f"get_toutes_matieres error: {e}")
        return []
    finally:
        conn.close()