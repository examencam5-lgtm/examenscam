# database.py — ExamensCam
"""
═══════════════════════════════════════════════════════
MIGRATION POSTGRES (NEON) — 04/09/2026
═══════════════════════════════════════════════════════
Même migration que database_eleves.py et database_conversations.py
(voir l'en-tête de database_eleves.py pour le raisonnement complet) :
SQLite sur disque éphémère Render -> Postgres géré chez Neon, via la
variable d'environnement DATABASE_URL.

CE QUI CHANGE (implémentation interne uniquement) :
  - sqlite3.connect(DB_PATH)        -> psycopg2.connect(DATABASE_URL)
  - conn.row_factory = sqlite3.Row  -> cursor_factory=RealDictCursor
  - placeholders '?'                -> placeholders '%s'
  - INTEGER PRIMARY KEY AUTOINCREMENT -> GENERATED ALWAYS AS IDENTITY
  - datetime('now')                 -> NOW()
  - conn.execute(...) direct        -> conn.cursor() puis cur.execute(...)
  - NOUVEAU : conn.rollback() dans les blocs qui écrivent (Postgres
    abandonne la transaction en cours dès qu'une erreur survient,
    contrairement à SQLite).

CE QUI NE CHANGE PAS : tous les noms de fonctions, leurs signatures,
leurs valeurs de retour -- aucune modification nécessaire côté app.py.

⚠️ DÉPENDANCE INTER-FICHIERS : get_stats() interroge la table
`annales_externes`, qui appartient à database_externes.py (pas encore
migré au moment où ce fichier est écrit). Ce fichier suppose que
database_externes.py est migré et déployé EN MÊME TEMPS -- sinon
get_stats() échouera avec une erreur "relation annales_externes does
not exist" côté Postgres, la table n'y existant pas encore. Ne pas
déployer ce fichier seul tant que database_externes.py n'est pas
migré en parallèle.

BUG PRÉEXISTANT NON CORRIGÉ (présent dans l'original SQLite, conservé
à l'identique pour fidélité de migration) : get_annales() filtre sur
une colonne `type_sujet` qui n'existe pas dans le schéma de la table
`annales` ci-dessous -- ce paramètre plantera en pratique s'il est
utilisé. À signaler séparément si une correction est souhaitée.
"""

import os
from typing import Optional
from datetime import datetime

import psycopg2
import psycopg2.extras

DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL manquant. Configure cette variable d'environnement "
        "sur Render avec la chaine de connexion Postgres fournie par Neon "
        "-- sans elle, les annales officielles ne peuvent ni etre lues ni "
        "ecrites."
    )


def get_connection():
    """Retourne une connexion Postgres dont les curseurs renvoient des
    lignes de type dict (RealDictRow) -- même ergonomie que
    sqlite3.Row d'origine : row['colonne'] et dict(row) fonctionnent
    à l'identique."""
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def create_table():
    """Idempotent comme l'original -- appelée au démarrage de app.py,
    jamais destructive sur une table existante."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS annales (
                id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                niveau TEXT NOT NULL,
                serie TEXT,
                matiere TEXT NOT NULL,
                annee INTEGER NOT NULL,
                lien_drive TEXT NOT NULL,
                corrige_dispo INTEGER DEFAULT 0,
                lien_corrige TEXT,
                source TEXT DEFAULT 'inconnu',
                qualite TEXT DEFAULT 'bonne',
                vues INTEGER DEFAULT 0,
                date_ajout TEXT DEFAULT (NOW()::text),
                actif INTEGER DEFAULT 1
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_niveau_serie ON annales(niveau, serie);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_matiere ON annales(matiere);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_annee ON annales(annee);")
        conn.commit()
    finally:
        conn.close()


def get_matieres(niveau: str, serie: Optional[str] = None) -> list:
    conn = get_connection()
    try:
        cur = conn.cursor()
        if serie:
            cur.execute("""
                SELECT DISTINCT matiere FROM annales
                WHERE niveau = %s AND serie = %s AND actif = 1
                ORDER BY matiere
            """, (niveau, serie))
        else:
            cur.execute("""
                SELECT DISTINCT matiere FROM annales
                WHERE niveau = %s AND actif = 1
                ORDER BY matiere
            """, (niveau,))
        rows = cur.fetchall()
        return [row['matiere'] for row in rows]
    except Exception as e:
        print(f"get_matieres error: {e}")
        return []
    finally:
        conn.close()


def get_annales(niveau: str, serie: Optional[str] = None,
                matiere: Optional[str] = None, type_sujet: Optional[str] = None) -> list:
    conn = get_connection()
    try:
        cur = conn.cursor()
        query = "SELECT * FROM annales WHERE actif = 1"
        params = []
        if niveau:
            query += " AND niveau = %s"
            params.append(niveau)
        if serie:
            query += " AND (serie = %s OR serie IS NULL)"
            params.append(serie)
        if matiere:
            query += " AND matiere = %s"
            params.append(matiere)
        if type_sujet:
            query += " AND type_sujet = %s"
            params.append(type_sujet)
        query += " ORDER BY annee DESC"
        cur.execute(query, params)
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"get_annales error: {e}")
        return []
    finally:
        conn.close()


def increment_vues(annale_id: int):
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE annales SET vues = vues + 1 WHERE id = %s", (annale_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"increment_vues error: {e}")
    finally:
        conn.close()


def get_derniere_maj():
    """
    Renvoie la date de la derniere annale ajoutee en base,
    formatee en francais (ex: '28 juillet 2026').
    Renvoie None si la table est vide.
    """
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT MAX(date_ajout) as derniere FROM annales WHERE actif = 1"
        )
        row = cur.fetchone()

        if not row or not row['derniere']:
            return None

        valeur = row['derniere'].split('.')[0]
        dt = datetime.strptime(valeur, "%Y-%m-%d %H:%M:%S")

        mois_fr = [
            "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre"
        ]

        return f"{dt.day} {mois_fr[dt.month - 1]} {dt.year}"
    except Exception as e:
        print(f"get_derniere_maj error: {e}")
        return None
    finally:
        conn.close()


def get_stats() -> dict:
    """
    Statistiques pour la page d'accueil.
    total_officiel : annales self-hosted (table annales)
    total_externe  : etablissements + ex-blanches, indexes uniquement (table annales_externes)
    Les deux compteurs restent separes -- jamais additionnes,
    car ils ne representent pas la meme nature de contenu.

    ⚠️ Suppose que la table annales_externes existe déjà côté Postgres
    (voir database_externes.py) -- voir avertissement en tête de
    fichier."""
    conn = get_connection()
    try:
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) as n FROM annales WHERE actif = 1")
        total_officiel = cur.fetchone()['n']

        cur.execute("SELECT COUNT(*) as n FROM annales_externes WHERE actif = 1")
        total_externe = cur.fetchone()['n']

        cur.execute("""
            SELECT niveau, COUNT(*) as n FROM annales
            WHERE actif = 1 GROUP BY niveau ORDER BY n DESC
        """)
        par_niveau = cur.fetchall()

        return {
            'total': total_officiel,          # compat : index.html utilise deja 'total'
            'total_officiel': total_officiel,
            'total_externe': total_externe,
            'par_niveau': [dict(r) for r in par_niveau],
        }
    except Exception as e:
        print(f"get_stats error: {e}")
        return {'total': 0, 'total_officiel': 0, 'total_externe': 0, 'par_niveau': []}
    finally:
        conn.close()