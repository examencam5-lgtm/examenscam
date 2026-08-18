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

STOCKAGE : toujours en UTC (datetime('now') en SQLite = UTC). C'est
la bonne pratique -- ne jamais stocker une heure locale, car si un
jour le serveur change de fuseau ou que tu compares des donnees
d'origines differentes, l'UTC est la seule reference stable.

AFFICHAGE : converti en heure de Maroua (UTC+1, fixe, le Cameroun ne
change pas d'heure) au moment de la LECTURE, jamais au stockage.
C'est pour ca que chaque fonction stats_* qui renvoie une date fait
`datetime(date_evenement, '+1 hour')` dans le SELECT -- mais le
FILTRE WHERE sur date_evenement reste toujours en UTC, parce qu'il
compare a la colonne stockee brute. Ne jamais mélanger les deux.

Usage dans app.py :
    from analytics import (
        creer_table_evenements, log_evenement, get_ou_creer_session,
        est_probablement_bot, stats_resume, stats_pages_populaires,
        stats_recherches_populaires, stats_visites_par_jour,
        stats_matieres_populaires, stats_destinations_cliquees,
        stats_sources, stats_nouveaux_vs_recurrents, stats_duree_sessions,
        stats_journal_recherches, stats_journal_clics, stats_parcours_session,
    )
"""
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path('data') / 'annales.db'

# Decalage Maroua par rapport a UTC. Fixe a l'annee -- le Cameroun
# n'applique pas de changement d'heure saisonnier.
DECALAGE_HORAIRE_SQL = '+1 hour'

# User-agents de bots/crawlers connus a exclure du tracking public.
# 'whatsapp' est inclus expres : quand quelqu'un partage un lien
# ExamensCam sur WhatsApp, l'app fait un fetch automatique pour
# generer l'apercu du lien -- ce fetch n'est pas un vrai visiteur et
# fausserait les stats s'il etait compte. Le vrai clic humain arrive
# ensuite avec un User-Agent de navigateur normal (Chrome Android
# typiquement) et sera compte normalement.
BOTS_CONNUS = (
    'bot', 'crawl', 'spider', 'slurp', 'facebookexternalhit', 'whatsapp',
    'telegrambot', 'preview', 'headless',
)


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


def est_probablement_bot(user_agent) -> bool:
    """
    True si le User-Agent ressemble a un bot/crawler, ou est absent.
    Un vrai navigateur envoie toujours un User-Agent -- son absence
    totale est deja suspecte.
    """
    if not user_agent:
        return True
    ua = user_agent.lower()
    return any(b in ua for b in BOTS_CONNUS)


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
    """
    Courbe de frequentation -- pour le graphique du dashboard.
    Le regroupement DATE(...) se fait apres conversion en heure
    locale, sinon une visite a 23h30 Maroua (minuit UTC+1 = 22h30 UTC
    la veille) se retrouverait comptee sur le mauvais jour.
    """
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        rows = conn.execute(f"""
            SELECT DATE(date_evenement, '{DECALAGE_HORAIRE_SQL}') as jour,
                   COUNT(*) as n,
                   COUNT(DISTINCT session_id) as visiteurs
            FROM evenements
            WHERE type_evenement = 'page_vue' AND date_evenement >= ?
            GROUP BY jour
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


def stats_sources(jours: int = 30) -> list[dict]:
    """
    Categorise les visites par origine (whatsapp, google, facebook,
    direct, autre) a partir du referrer. Repond a la question
    strategique : le canal WhatsApp enseignants convertit-il
    reellement, ou le trafic vient-il d'ailleurs ?
    """
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT referrer, COUNT(*) as n
            FROM evenements
            WHERE type_evenement = 'page_vue' AND date_evenement >= ?
            GROUP BY referrer
        """, (depuis,)).fetchall()

        categories = {'whatsapp': 0, 'google': 0, 'facebook': 0, 'direct': 0, 'autre': 0}
        for r in rows:
            ref = (r['referrer'] or '').lower()
            n = r['n']
            if not ref:
                categories['direct'] += n
            elif 'whatsapp' in ref or 'wa.me' in ref:
                categories['whatsapp'] += n
            elif 'google' in ref:
                categories['google'] += n
            elif 'facebook' in ref or 'fb.com' in ref:
                categories['facebook'] += n
            else:
                categories['autre'] += n

        total = sum(categories.values()) or 1
        return [
            {'source': k, 'n': v, 'pct': round(v / total * 100)}
            for k, v in categories.items() if v > 0
        ]
    finally:
        conn.close()


def stats_nouveaux_vs_recurrents(jours: int = 30) -> dict:
    """
    Parmi les sessions actives sur la periode, combien sont vues
    pour la premiere fois (nouveaux) vs deja vues avant la periode
    (recurrents). Un ratio recurrents/nouveaux qui grimpe est un bon
    signal de fidelisation.
    """
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')

        premiere_visite_par_session = conn.execute("""
            SELECT session_id, MIN(date_evenement) as premiere
            FROM evenements
            GROUP BY session_id
        """).fetchall()
        premiere_par_id = {r['session_id']: r['premiere'] for r in premiere_visite_par_session}

        actifs = conn.execute("""
            SELECT DISTINCT session_id FROM evenements WHERE date_evenement >= ?
        """, (depuis,)).fetchall()
        actifs_ids = [r['session_id'] for r in actifs]

        nouveaux = sum(1 for sid in actifs_ids if premiere_par_id.get(sid, '') >= depuis)
        recurrents = len(actifs_ids) - nouveaux

        return {'nouveaux': nouveaux, 'recurrents': recurrents}
    finally:
        conn.close()


def stats_duree_sessions(jours: int = 30) -> dict:
    """
    Duree moyenne d'une session (dernier evenement - premier, en
    secondes) et nombre de sessions a un seul evenement (proxy du
    taux de rebond -- le visiteur repart apres une seule page).
    """
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')
        rows = conn.execute("""
            SELECT session_id,
                   (julianday(MAX(date_evenement)) - julianday(MIN(date_evenement))) * 86400 as duree_sec,
                   COUNT(*) as n_evenements
            FROM evenements
            WHERE date_evenement >= ?
            GROUP BY session_id
        """, (depuis,)).fetchall()

        if not rows:
            return {'duree_moyenne_sec': 0, 'sessions_1_page': 0, 'total_sessions': 0, 'taux_rebond_pct': 0}

        durees = [r['duree_sec'] for r in rows]
        sessions_1_page = sum(1 for r in rows if r['n_evenements'] == 1)
        total = len(rows)

        return {
            'duree_moyenne_sec': round(sum(durees) / total),
            'sessions_1_page': sessions_1_page,
            'total_sessions': total,
            'taux_rebond_pct': round(sessions_1_page / total * 100),
        }
    finally:
        conn.close()


def stats_journal_recherches(jours: int = 30, limite: int = 50, offset: int = 0) -> dict:
    """
    Journal brut, paginable : qui (session anonyme) a cherche quoi
    et quand, dans l'ordre chronologique. Renvoie aussi le total
    reel sur la periode, pour savoir s'il y a d'autres pages au-dela
    de la limite affichee.
    """
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')

        total = conn.execute("""
            SELECT COUNT(*) FROM evenements
            WHERE type_evenement = 'recherche' AND date_evenement >= ?
        """, (depuis,)).fetchone()[0]

        rows = conn.execute(f"""
            SELECT session_id, requete, niveau, matiere, route,
                   datetime(date_evenement, '{DECALAGE_HORAIRE_SQL}') as date_evenement
            FROM evenements
            WHERE type_evenement = 'recherche' AND date_evenement >= ?
            ORDER BY date_evenement DESC
            LIMIT ? OFFSET ?
        """, (depuis, limite, offset)).fetchall()

        return {
            'lignes': [dict(r) for r in rows],
            'total': total,
            'offset': offset,
            'limite': limite,
            'a_plus': offset + limite < total,
        }
    finally:
        conn.close()


def stats_journal_clics(jours: int = 30, limite: int = 50, offset: int = 0) -> dict:
    """Journal brut des clics sur resultats de recherche, meme logique de pagination."""
    conn = get_connection()
    try:
        depuis = (datetime.now() - timedelta(days=jours)).strftime('%Y-%m-%d')

        total = conn.execute("""
            SELECT COUNT(*) FROM evenements
            WHERE type_evenement = 'clic_resultat' AND date_evenement >= ?
        """, (depuis,)).fetchone()[0]

        rows = conn.execute(f"""
            SELECT session_id, requete, destination, niveau, matiere,
                   datetime(date_evenement, '{DECALAGE_HORAIRE_SQL}') as date_evenement
            FROM evenements
            WHERE type_evenement = 'clic_resultat' AND date_evenement >= ?
            ORDER BY date_evenement DESC
            LIMIT ? OFFSET ?
        """, (depuis, limite, offset)).fetchall()

        return {
            'lignes': [dict(r) for r in rows],
            'total': total,
            'offset': offset,
            'limite': limite,
            'a_plus': offset + limite < total,
        }
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
        rows = conn.execute(f"""
            SELECT type_evenement, route, niveau, serie, matiere, requete,
                   destination, datetime(date_evenement, '{DECALAGE_HORAIRE_SQL}') as date_evenement
            FROM evenements
            WHERE session_id = ? AND date_evenement >= ?
            ORDER BY date_evenement ASC
        """, (session_id, depuis)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()