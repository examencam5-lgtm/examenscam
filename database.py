# database.py — ExamensCam
import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime

DB_PATH = Path('data') / 'annales.db'

def get_connection():
    Path('data').mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def create_table():
    Path('data').mkdir(exist_ok=True)
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS annales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            date_ajout TEXT DEFAULT (datetime('now')),
            actif INTEGER DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_niveau_serie ON annales(niveau, serie);
        CREATE INDEX IF NOT EXISTS idx_matiere ON annales(matiere);
        CREATE INDEX IF NOT EXISTS idx_annee ON annales(annee);
    """)
    conn.commit()
    conn.close()

def get_matieres(niveau: str, serie: Optional[str] = None) -> list:
    conn = get_connection()
    try:
        if serie:
            rows = conn.execute("""
                SELECT DISTINCT matiere FROM annales
                WHERE niveau = ? AND serie = ? AND actif = 1
                ORDER BY matiere
            """, (niveau, serie)).fetchall()
        else:
            rows = conn.execute("""
                SELECT DISTINCT matiere FROM annales
                WHERE niveau = ? AND actif = 1
                ORDER BY matiere
            """, (niveau,)).fetchall()
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
        query = "SELECT * FROM annales WHERE actif = 1"
        params = []
        if niveau:
            query += " AND niveau = ?"
            params.append(niveau)
        if serie:
            query += " AND (serie = ? OR serie IS NULL)"
            params.append(serie)
        if matiere:
            query += " AND matiere = ?"
            params.append(matiere)
        if type_sujet:
            query += " AND type_sujet = ?"
            params.append(type_sujet)
        query += " ORDER BY annee DESC"
        rows = conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"get_annales error: {e}")
        return []
    finally:
        conn.close()

def increment_vues(annale_id: int):
    conn = get_connection()
    conn.execute("UPDATE annales SET vues = vues + 1 WHERE id = ?", (annale_id,))
    conn.commit()
    conn.close()

def get_derniere_maj():
    """
    Renvoie la date de la derniere annale ajoutee en base,
    formatee en francais (ex: '28 juillet 2026').
    Renvoie None si la table est vide.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT MAX(date_ajout) as derniere FROM annales WHERE actif = 1"
        ).fetchone()

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
    """
    conn = get_connection()
    try:
        total_officiel = conn.execute(
            "SELECT COUNT(*) as n FROM annales WHERE actif = 1"
        ).fetchone()['n']

        total_externe = conn.execute(
            "SELECT COUNT(*) as n FROM annales_externes WHERE actif = 1"
        ).fetchone()['n']

        par_niveau = conn.execute("""
            SELECT niveau, COUNT(*) as n FROM annales
            WHERE actif = 1 GROUP BY niveau ORDER BY n DESC
        """).fetchall()

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