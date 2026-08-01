"""
database_search.py — ExamensCam
Fonctions de lecture sur 'search_index' (autocompletion) et
d'ecriture sur 'recherches_infructueuses' (signal strategique,
doc section 3.5 : les recherches sans resultat orientent les
prochaines priorites de scraping).

Import dans app.py :
    from database_search import rechercher, enregistrer_recherche_infructueuse
"""
import sqlite3
from pathlib import Path
from generer_search_index import normaliser

DB_PATH = Path('data') / 'annales.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def creer_table_recherches_infructueuses():
    """A appeler une fois (ou via create_table() dans database.py)."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recherches_infructueuses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            requete TEXT NOT NULL,
            nombre_occurrences INTEGER DEFAULT 1,
            date_derniere TEXT DEFAULT (datetime('now')),
            UNIQUE(requete)
        );
    """)
    conn.commit()
    conn.close()


def rechercher(q: str, limite: int = 8) -> list[dict]:
    """
    Recherche par pertinence pure (doc section 3.3) : aucune priorite
    donnee au contenu officiel. Le classement se fait uniquement sur
    la position du match (un match en debut de libelle est plus
    pertinent qu'un match au milieu).
    """
    conn = get_connection()
    try:
        q_normalisee = normaliser(q)

        # Deux passes : d'abord ce qui COMMENCE par la requete
        # (le plus pertinent, cas "Lyc" -> "Lycee..."), puis ce qui
        # la CONTIENT ailleurs, pour completer jusqu'a la limite.
        debut = conn.execute("""
            SELECT libelle, destination, type_source
            FROM search_index
            WHERE libelle_recherche LIKE ?
            ORDER BY libelle
            LIMIT ?
        """, (f"{q_normalisee}%", limite)).fetchall()

        resultats = [dict(r) for r in debut]

        if len(resultats) < limite:
            reste = limite - len(resultats)
            contient = conn.execute("""
                SELECT libelle, destination, type_source
                FROM search_index
                WHERE libelle_recherche LIKE ? AND libelle_recherche NOT LIKE ?
                ORDER BY libelle
                LIMIT ?
            """, (f"%{q_normalisee}%", f"{q_normalisee}%", reste)).fetchall()
            resultats.extend([dict(r) for r in contient])

        return resultats
    except Exception as e:
        print(f"rechercher error: {e}")
        return []
    finally:
        conn.close()


def enregistrer_recherche_infructueuse(q: str):
    """
    Incremente le compteur si la requete existe deja, sinon la cree.
    Signal gratuit de la demande reelle (doc section 3.5) -- a
    consulter periodiquement pour prioriser le scraping.
    """
    conn = get_connection()
    try:
        conn.execute("""
            INSERT INTO recherches_infructueuses (requete)
            VALUES (?)
            ON CONFLICT(requete) DO UPDATE SET
                nombre_occurrences = nombre_occurrences + 1,
                date_derniere = datetime('now')
        """, (q,))
        conn.commit()
    except Exception as e:
        print(f"enregistrer_recherche_infructueuse error: {e}")
    finally:
        conn.close()


def get_recherches_infructueuses_frequentes(limite: int = 20) -> list[dict]:
    """Pour un futur dashboard admin -- les requetes les plus demandees sans resultat."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT requete, nombre_occurrences, date_derniere
            FROM recherches_infructueuses
            ORDER BY nombre_occurrences DESC
            LIMIT ?
        """, (limite,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()