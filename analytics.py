"""
analytics.py — ExamensCam
Architecture d'observation du comportement utilisateur, sans compte
ni tracking publicitaire tiers -- juste un identifiant de session
anonyme (cookie local, jamais envoye a un tiers) pour distinguer
les visiteurs uniques des pages vues repetees.

Une seule table 'evenements' capture tout : vue de page, recherche,
clic sur un resultat, redirection etablissement. Simple a interroger,
simple a faire evoluer (ajouter un type d'evenement ne demande pas
de nouvelle table).

Usage dans app.py :
    from analytics import (
        creer_table_evenements, log_evenement, get_ou_creer_session,
        stats_resume, stats_pages_populaires, stats_recherches_populaires,
        stats_visites_par_jour, stats_matieres_populaires
    )
"""
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path('data') / 'annales.db'


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def creer_table_evenements():
    """A appeler une fois au demarrage (comme create_table() dans database.py)."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS evenements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type_evenement TEXT NOT NULL,   -- 'page_vue', 'recherche', 'clic_resultat', 'redirection_externe', 'vue_blanche'
            session_id TEXT NOT NULL,       -- UUID anonyme, cookie cote client, aucune donnee personnelle
            route TEXT,                     -- chemin de la page (ex: /bac/C)
            niveau TEXT,
            serie TEXT,
            matiere TEXT,
            requete TEXT,                   -- texte tape, si type='recherche'
            destination TEXT,               -- URL cliquee, si type='clic_resultat'
            referrer TEXT,                  -- d'ou vient le visiteur (autre page du site, ou externe)
            date_evenement TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_evt_type ON evenements(type_evenement);
        CREATE INDEX IF NOT EXISTS idx_evt_date ON evenements(date_evenement);
        CREATE INDEX IF NOT EXISTS idx_evt_session ON evenements(session_id);
    """)
    conn.commit()
    conn.close()


def get_ou_creer_session(request, response=None):
    """
    Lit le cookie de session existant, ou en cree un nouveau (UUID
    aleatoire, pas d'info personnelle dedans -- juste un identifiant
    pour compter les visiteurs uniques vs les pages vues repetees).

    Usage dans app.py (before_request) :
        g.session_id = get_ou_creer_session(request)
    Puis dans after_request, poser le cookie si nouveau :
        response.set_cookie('ec_session', g.session_id, max_age=60*60*24*365, samesite='Lax')
    """
    session_id = request.cookies.get('ec_session')
    if not session_id:
        session_id = str(uuid.uuid4())
    return session_id


def log_evenement(type_evenement, session_id, route=None, niveau=None,
                   serie=None, matiere=None, requete=None, destination=None,
                   referrer=None):
    """
    Enregistre un evenement. Ne leve jamais d'exception vers
    l'appelant -- le tracking ne doit jamais casser une page si la
    base est momentanement indisponible (ex: redemarrage Render).
    """
    try:
        conn = get_connection()
        conn.execute("""
            INSERT INTO evenements
                (type_evenement, session_id, route, niveau, serie, matiere,
                 requete, destination, referrer)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (type_evenement, session_id, route, niveau, serie, matiere,
              requete, destination, referrer))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"log_evenement error (ignore, ne bloque pas la page): {e}")


# ═══════════════════════════════════════════════════════
# REQUETES POUR LE DASHBOARD
# ═══════════════════════════════════════════════════════

def stats_resume(jours: int = 30) -> dict:
    """Chiffres cles pour l'entete du dashboard."""
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')

        total_vues = conn.execute("""
            SELECT COUNT(*) FROM evenements
            WHERE type_evenement = 'page_vue' AND date_evenement >= ?
        """, (depuis,)).fetchone()[0]

        visiteurs_uniques = conn.execute("""
            SELECT COUNT(DISTINCT session_id) FROM evenements
            WHERE date_evenement >= ?
        """, (depuis,)).fetchone()[0]

        total_recherches = conn.execute("""
            SELECT COUNT(*) FROM evenements
            WHERE type_evenement = 'recherche' AND date_evenement >= ?
        """, (depuis,)).fetchone()[0]

        total_redirections = conn.execute("""
            SELECT COUNT(*) FROM evenements
            WHERE type_evenement = 'redirection_externe' AND date_evenement >= ?
        """, (depuis,)).fetchone()[0]

        return {
            'total_vues': total_vues,
            'visiteurs_uniques': visiteurs_uniques,
            'total_recherches': total_recherches,
            'total_redirections': total_redirections,
            'periode_jours': jours,
        }
    finally:
        conn.close()


def stats_pages_populaires(jours: int = 30, limite: int = 15) -> list[dict]:
    """Les pages les plus visitees sur la periode."""
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT route, COUNT(*) as n
            FROM evenements
            WHERE type_evenement = 'page_vue' AND date_evenement >= ? AND route IS NOT NULL
            GROUP BY route
            ORDER BY n DESC
            LIMIT ?
        """, (depuis, limite)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def stats_recherches_populaires(jours: int = 30, limite: int = 20) -> list[dict]:
    """Les termes les plus recherches -- signal direct de la demande reelle."""
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT requete, COUNT(*) as n
            FROM evenements
            WHERE type_evenement = 'recherche' AND date_evenement >= ? AND requete IS NOT NULL AND requete != ''
            GROUP BY LOWER(requete)
            ORDER BY n DESC
            LIMIT ?
        """, (depuis, limite)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def stats_matieres_populaires(jours: int = 30, limite: int = 15) -> list[dict]:
    """Matieres les plus consultees (toutes sources confondues)."""
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT niveau, matiere, COUNT(*) as n
            FROM evenements
            WHERE date_evenement >= ? AND matiere IS NOT NULL AND matiere != ''
            GROUP BY niveau, matiere
            ORDER BY n DESC
            LIMIT ?
        """, (depuis, limite)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def stats_visites_par_jour(jours: int = 14) -> list[dict]:
    """Courbe de frequentation -- pour un graphique simple sur le dashboard."""
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT DATE(date_evenement) as jour, COUNT(*) as n,
                   COUNT(DISTINCT session_id) as visiteurs
            FROM evenements
            WHERE type_evenement = 'page_vue' AND date_evenement >= ?
            GROUP BY DATE(date_evenement)
            ORDER BY jour ASC
        """, (depuis,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def stats_destinations_cliquees(jours: int = 30, limite: int = 20) -> list[dict]:
    """Quels resultats de recherche sont reellement cliques -- valide (ou pas) le scoring."""
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT destination, COUNT(*) as n
            FROM evenements
            WHERE type_evenement = 'clic_resultat' AND date_evenement >= ? AND destination IS NOT NULL
            GROUP BY destination
            ORDER BY n DESC
            LIMIT ?
        """, (depuis, limite)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def stats_journal_recherches(jours: int = 30, limite: int = 200) -> list[dict]:
    """
    Journal brut, ligne par ligne : qui (session anonyme) a cherche
    quoi et quand. Contrairement a stats_recherches_populaires() qui
    agrege par terme, ceci montre chaque recherche individuellement
    dans l'ordre chronologique -- utile pour comprendre le parcours
    reel d'un visiteur, pas juste des totaux.
    """
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT session_id, requete, niveau, matiere, route, date_evenement
            FROM evenements
            WHERE type_evenement = 'recherche' AND date_evenement >= ?
            ORDER BY date_evenement DESC
            LIMIT ?
        """, (depuis, limite)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def stats_journal_clics(jours: int = 30, limite: int = 200) -> list[dict]:
    """Journal brut des clics sur resultats de recherche, meme logique."""
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT session_id, requete, destination, niveau, matiere, date_evenement
            FROM evenements
            WHERE type_evenement = 'clic_resultat' AND date_evenement >= ?
            ORDER BY date_evenement DESC
            LIMIT ?
        """, (depuis, limite)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def stats_parcours_session(session_id: str, jours: int = 30) -> list[dict]:
    """
    Tout ce qu'UNE session precise a fait, dans l'ordre -- pour
    suivre le parcours complet d'un visiteur particulier (clique sur
    une session dans le journal pour voir son historique).
    """
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT type_evenement, route, niveau, serie, matiere, requete,
                   destination, date_evenement
            FROM evenements
            WHERE session_id = ? AND date_evenement >= ?
            ORDER BY date_evenement ASC
        """, (session_id, depuis)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()