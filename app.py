# app.py — ExamensCam — Version finale complète
import os
import re
import json
import io
import time
from pathlib import Path
import secrets
from functools import wraps
from dotenv import load_dotenv
load_dotenv()
from flask import send_file
from scripts.generer_epreuve_json import generer_epreuve_json
from scripts.construire_pdf_officiel import construire_pdf
from scripts.chat_contexte import repondre_eleve, repondre_eleve_stream
from scripts.extraire_entete_personnalisable import (
    extraire_entete_pour_upload, personnaliser_et_decouper, generer_apercu_brut,
    supprimer_extraction_temporaire, ExtractionEnteteEchouee, EnteteSourceIncomplete,
    DOSSIER_ENTETES_TMP, nettoyer_entetes_expirees,
)
from scripts.chat_bac_officiel import detecter_demande_exercice_bac, obtenir_exercice_bac, formuler_reponse_exercice_bac
from scripts.chat_intent_epreuve import detecter_demande_epreuve, chercher_epreuves, preparer_resultats_epreuves
from scripts.metadonnees_defaut import metadonnees_defaut_eleve
import tempfile


from flask import (
    Flask, render_template, redirect, request, abort, jsonify,
    g, session, Response, url_for
)

from database_carrefour import get_carrefour
from database_matieres import get_toutes_matieres
from database_externes import (
    get_matieres_externes, get_annales_externes, get_annale_externe_by_id,
    increment_vue_externe, get_annees_disponibles, get_sequences_disponibles,
    CORRESPONDANCE_NIVEAU_SERIE
)
from database import (get_annales, get_matieres, increment_vues, get_stats,
                      get_derniere_maj, create_table)
from database_search import rechercher_avec_scoring, enregistrer_recherche_infructueuse

from analytics import (
    creer_table_evenements, log_evenement, get_ou_creer_session,
    est_probablement_bot, stats_resume, stats_pages_populaires,
    stats_recherches_populaires, stats_matieres_populaires,
    stats_visites_par_jour, stats_destinations_cliquees,
    stats_sources, stats_nouveaux_vs_recurrents, stats_duree_sessions,
    stats_journal_recherches, stats_journal_clics, stats_parcours_session,
)
from database_eleves import (
    create_table as create_table_eleves, creer_compte, verifier_identifiants,
    marquer_connexion, get_eleve_par_id, modifier_profil, changer_mot_de_passe,
    incrementer_usage_mensuel, login_identifiant_bloque, enregistrer_echec_identifiant,
    reinitialiser_echecs_identifiant, minutes_avant_deblocage_identifiant,
    NIVEAUX_VALIDES as NIVEAUX_VALIDES_ELEVES, SERIES_VALIDES as SERIES_VALIDES_ELEVES,
)
# MODIFIÉ (29/08/2026, extension multi-matières) : import de
# matiere_disponible_pour et matieres_disponibles en plus des 2
# fonctions déjà utilisées -- chat_disponible_pour et
# message_indisponible gardent leur usage EXACT d'avant (génération
# PDF, toujours Mathématiques), voir scripts/chat_scope.py.
from scripts.chat_scope import (
    chat_disponible_pour, message_indisponible,
    matiere_disponible_pour, matieres_disponibles,
)
from scripts.chat_parcourir import get_niveaux, get_series, lister_epreuves
from database_matieres import get_toutes_matieres

creer_table_evenements()
app = Flask(__name__)

# ═══════════════════════════════════════════════════════
# CONFIGURATION & SECURITE
# ═══════════════════════════════════════════════════════
_SECRET_KEY = os.environ.get('SECRET_KEY')
_ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN')
_DEBUG = os.environ.get('DEBUG', 'False') == 'True'

if not _SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY manquant. Configure cette variable d'environnement sur "
        "Render avant de deployer -- sans elle, les cookies de session "
        "admin peuvent etre forges par n'importe qui."
    )
if not _ADMIN_TOKEN:
    raise RuntimeError(
        "ADMIN_TOKEN manquant. Configure cette variable d'environnement sur "
        "Render avant de deployer -- sans elle, l'admin est inaccessible "
        "(ou pire, accessible avec un mot de passe devinable)."
    )

app.config.update(
    SECRET_KEY=_SECRET_KEY,
    DEBUG=_DEBUG,
    ADMIN_TOKEN=_ADMIN_TOKEN,
    SESSION_COOKIE_SECURE=not _DEBUG,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

with app.app_context():
    create_table()
with app.app_context():
    create_table()
    create_table_eleves()          # <-- AJOUT

ROUTES_IGNOREES_TRACKING = ('/static/', '/api/', '/admin/', '/favicon.ico')
SERIES_VALIDES = ['C', 'D', 'TI', 'A4']

CATALOGUE = {
    'BEPC': ['Mathematiques','Physique','Chimie','SVT','Français','Anglais','Histoire-Géo'],
    'Probatoire': {
        'C': ['Mathematiques','Physique','Chimie','Philosophie','Français','Anglais'],
        'D': ['Mathematiques','Physique','Chimie','SVT','Philosophie','Français','Anglais'],
        'TI': ['Mathematiques','Physique','Chimie','Informatique','Philosophie','Français','Anglais'],
        'A4': ['Philosophie','Français','Anglais','Histoire','Mathematiques','Geographie'],
    },
    'BAC': {
        'C': ['Mathematiques','Physique','Chimie','SVT','Philosophie','Français','Anglais'],
        'D': ['Mathematiques','Physique','Chimie','SVT','Philosophie','Français','Anglais'],
        'TI': ['Mathematiques','Physique','Chimie','Informatique','Dessin Industriel','Philosophie','Français','Anglais'],
        'A4': ['Philosophie','Français','Anglais','Histoire-Géo','Latin','Economie'],
    },
}

def get_matieres_fallback(niveau, serie=None):
    m = get_toutes_matieres(niveau, serie)
    if m:
        return m
    m = get_matieres(niveau, serie)
    if m:
        return m
    if serie:
        return CATALOGUE.get(niveau, {}).get(serie, [])
    return CATALOGUE.get(niveau, [])

@app.context_processor
def inject_globals():
    eleve_nav = None
    eleve_id = session.get('eleve_id')
    if eleve_id:
        eleve_nav = get_eleve_par_id(eleve_id)
        if not eleve_nav:
            session.pop('eleve_id', None)
    return {'site_nom': 'ExamensCam', 'eleve_nav': eleve_nav}


# ═══════════════════════════════════════════════════════
# RATE-LIMITING LOGIN ADMIN
# ═══════════════════════════════════════════════════════
_TENTATIVES_LOGIN = {}
MAX_TENTATIVES = 5
FENETRE_BLOCAGE_SEC = 15 * 60


def _ip_client():
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or 'inconnu'


def _login_bloque(ip: str) -> bool:
    maintenant = time.time()
    echecs = [t for t in _TENTATIVES_LOGIN.get(ip, []) if maintenant - t < FENETRE_BLOCAGE_SEC]
    _TENTATIVES_LOGIN[ip] = echecs
    return len(echecs) >= MAX_TENTATIVES


def _enregistrer_echec(ip: str):
    _TENTATIVES_LOGIN.setdefault(ip, []).append(time.time())


def _minutes_avant_deblocage(ip: str) -> int:
    echecs = _TENTATIVES_LOGIN.get(ip, [])
    if not echecs:
        return 0
    plus_ancien = min(echecs)
    reste = FENETRE_BLOCAGE_SEC - (time.time() - plus_ancien)
    return max(1, round(reste / 60))


# ═══════════════════════════════════════════════════════
# RATE-LIMITING GLOBAL
# ═══════════════════════════════════════════════════════
_REQUETES_PAR_IP = {}


def _rate_limit_depasse(cle: str, max_requetes: int, fenetre_sec: int) -> bool:
    maintenant = time.time()
    requetes = [t for t in _REQUETES_PAR_IP.get(cle, []) if maintenant - t < fenetre_sec]
    requetes.append(maintenant)
    _REQUETES_PAR_IP[cle] = requetes
    return len(requetes) > max_requetes


def limiter_debit(max_requetes: int, fenetre_sec: int):
    def decorateur(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cle = f"{_ip_client()}:{f.__name__}"
            if _rate_limit_depasse(cle, max_requetes, fenetre_sec):
                return jsonify({'erreur': 'Trop de requetes, ralentis un peu.'}), 429
            return f(*args, **kwargs)
        return wrapper
    return decorateur


# ═══════════════════════════════════════════════════════
# TRACKING GLOBAL
# ═══════════════════════════════════════════════════════

@app.before_request
def _avant_requete():
    g.session_id = get_ou_creer_session(request)

    route_ignoree = any(request.path.startswith(p) for p in ROUTES_IGNOREES_TRACKING)
    admin_actif = session.get('admin_connecte', False)
    bot = est_probablement_bot(request.headers.get('User-Agent'))

    if request.method == 'GET' and not route_ignoree and not admin_actif and not bot:
        vargs = request.view_args or {}
        log_evenement(
            'page_vue',
            g.session_id,
            route=request.path,
            niveau=vargs.get('niveau'),
            serie=vargs.get('serie'),
            matiere=vargs.get('matiere'),
            referrer=request.referrer,
        )

@app.after_request
def _apres_requete(response):
    if not request.cookies.get('ec_session') and hasattr(g, 'session_id'):
        response.set_cookie('ec_session', g.session_id, max_age=60*60*24*365, samesite='Lax')
    return response


# ══════════════════════════════════════════
# ROUTES PRINCIPALES
# ══════════════════════════════════════════

# MODIFIÉ (29/08/2026, extension multi-matières) : calcule aussi
# `matieres_dispo` -- liste des matières que le chat peut réellement
# discuter pour le niveau/série de l'élève (RAG ou générique, voir
# chat_scope.matieres_disponibles). `disponible` NE CHANGE PAS de
# sens : il reste spécifique à Mathématiques/génération PDF (voir
# chat_scope.chat_disponible_pour) -- ne pas le confondre avec
# `matieres_dispo`.
@app.route('/')
def index():
    eleve = None
    eleve_id = session.get('eleve_id')
    if eleve_id:
        eleve = get_eleve_par_id(eleve_id)
        if not eleve:
            session.pop('eleve_id', None)

    if eleve:
        disponible = chat_disponible_pour(eleve['niveau'], eleve['serie'])
        matieres_dispo = matieres_disponibles(eleve['niveau'], eleve['serie'])
    else:
        disponible = True  # mode démo -- le vrai scope est de toute façon imposé côté serveur
        matieres_dispo = []

    return render_template(
        'assistant_eleve.html',
        eleve=eleve,
        disponible=disponible,
        mode_demo=(eleve is None),
        matieres_dispo=matieres_dispo,
    )


@app.route('/decouvrir')
def decouvrir():
    stats = get_stats()
    derniere_maj = get_derniere_maj()
    return render_template(
        'index.html',
        stats=stats,
        total=stats['total'],
        total_officiel=stats['total_officiel'],
        total_externe=stats['total_externe'],
        derniere_maj=derniere_maj
    )

@app.route('/conditions')
def conditions():
    return render_template('conditions.html')

@app.route('/a-propos')
def a_propos():
    return render_template('a_propos.html')
@app.route('/confidentialite')
def confidentialite():
    return render_template('confidentialite.html')

def scope_eleve_autorise(niveau, serie=None):
    eleve_id = session.get('eleve_id')
    if not eleve_id:
        return True
    eleve = get_eleve_par_id(eleve_id)
    if not eleve:
        return True
    if eleve['niveau'] != niveau:
        return False
    if serie is not None and eleve.get('serie') and eleve['serie'] != serie:
        return False
    return True


def rediriger_hors_scope():
    return redirect(url_for('index'))


@app.route('/bepc')
def bepc():
    if not scope_eleve_autorise('BEPC'):
        return rediriger_hors_scope()
    return render_template('niveau.html', niveau='BEPC', serie=None,
                           matieres=get_matieres_fallback('BEPC'))


@app.route('/probatoire')
def probatoire():
    eleve_id = session.get('eleve_id')
    if eleve_id:
        eleve = get_eleve_par_id(eleve_id)
        if eleve:
            if eleve['niveau'] != 'Probatoire':
                return rediriger_hors_scope()
            if eleve.get('serie'):
                return redirect(url_for('probatoire_serie', serie=eleve['serie']))
    return render_template('probatoire_series.html')


@app.route('/probatoire/<serie>')
def probatoire_serie(serie):
    if serie not in SERIES_VALIDES:
        abort(404)
    if not scope_eleve_autorise('Probatoire', serie):
        return rediriger_hors_scope()
    return render_template('niveau.html', niveau='Probatoire', serie=serie,
                           matieres=get_matieres_fallback('Probatoire', serie))


@app.route('/bac')
def bac():
    eleve_id = session.get('eleve_id')
    if eleve_id:
        eleve = get_eleve_par_id(eleve_id)
        if eleve:
            if eleve['niveau'] != 'BAC':
                return rediriger_hors_scope()
            if eleve.get('serie'):
                return redirect(url_for('bac_serie', serie=eleve['serie']))
    return render_template('bac_series.html')


@app.route('/bac/<serie>')
def bac_serie(serie):
    if serie not in SERIES_VALIDES:
        abort(404)
    if not scope_eleve_autorise('BAC', serie):
        return rediriger_hors_scope()
    return render_template('niveau.html', niveau='BAC', serie=serie,
                           matieres=get_matieres_fallback('BAC', serie))
# ══════════════════════════════════════════
# PAGE CHOIX : ÉNONCÉ OU CORRIGÉ
# ══════════════════════════════════════════

@app.route('/bepc/<matiere>')
def bepc_choix(matiere):
    officiels = get_annales('BEPC', matiere=matiere, type_sujet='officiel')
    return render_template('choix_type.html',
        niveau='BEPC', serie=None, matiere=matiere,
        nb_officiels=len(officiels),
        url_off_enonces=f'/annales/BEPC/{matiere}/officiel/enonces')

@app.route('/probatoire/<serie>/<matiere>')
def probatoire_choix(serie, matiere):
    if serie not in SERIES_VALIDES:
        abort(404)
    officiels = get_annales('Probatoire', serie=serie, matiere=matiere, type_sujet='officiel')
    return render_template('choix_type.html',
        niveau='Probatoire', serie=serie, matiere=matiere,
        nb_officiels=len(officiels),
        url_off_enonces=f'/annales/Probatoire/{serie}/{matiere}/officiel/enonces')

@app.route('/bac/<serie>/<matiere>')
def bac_choix(serie, matiere):
    if serie not in SERIES_VALIDES:
        abort(404)
    officiels = get_annales('BAC', serie=serie, matiere=matiere, type_sujet='officiel')
    return render_template('choix_type.html',
        niveau='BAC', serie=serie, matiere=matiere,
        nb_officiels=len(officiels),
        url_off_enonces=f'/annales/BAC/{serie}/{matiere}/officiel/enonces')

@app.route('/annales/<niveau>/<matiere>/<type_sujet>/<type_doc>')
def annales_bepc(niveau, matiere, type_sujet, type_doc):
    corrige = (type_doc == 'corriges')
    annales = get_annales(niveau, matiere=matiere, type_sujet=type_sujet)
    if corrige:
        annales = [a for a in annales if a.get('corrige_dispo')]
    return render_template('annales.html',
        niveau=niveau, serie=None, matiere=matiere,
        type_sujet=type_sujet, type_doc=type_doc,
        annales=annales)

@app.route('/annales/<niveau>/<serie>/<matiere>/<type_sujet>/<type_doc>')
def annales_serie(niveau, serie, matiere, type_sujet, type_doc):
    corrige = (type_doc == 'corriges')
    annales = get_annales(niveau, serie=serie, matiere=matiere, type_sujet=type_sujet)
    if corrige:
        annales = [a for a in annales if a.get('corrige_dispo')]
    return render_template('annales.html',
        niveau=niveau, serie=serie, matiere=matiere,
        type_sujet=type_sujet, type_doc=type_doc,
        annales=annales)

# ══════════════════════════════════════════
# ROUTES ANNALES
# ══════════════════════════════════════════

@app.route('/annales/<niveau>/<matiere>/enonces')
def annales_sans_serie_enonces(niveau, matiere):
    annales = get_annales(niveau, matiere=matiere)
    return render_template('annales.html', annales=annales, niveau=niveau,
                           serie=None, matiere=matiere, type_doc='Énoncés')

@app.route('/annales/<niveau>/<matiere>/corriges')
def annales_sans_serie_corriges(niveau, matiere):
    annales = [a for a in get_annales(niveau, matiere=matiere)
               if a.get('corrige_dispo')]
    return render_template('annales.html', annales=annales, niveau=niveau,
                           serie=None, matiere=matiere, type_doc='Corrigés')

@app.route('/annales/<niveau>/<serie>/<matiere>/enonces')
def annales_avec_serie_enonces(niveau, serie, matiere):
    annales = get_annales(niveau, serie=serie, matiere=matiere)
    return render_template('annales.html', annales=annales, niveau=niveau,
                           serie=serie, matiere=matiere, type_doc='Énoncés')

@app.route('/annales/<niveau>/<serie>/<matiere>/corriges')
def annales_avec_serie_corriges(niveau, serie, matiere):
    annales = [a for a in get_annales(niveau, serie=serie, matiere=matiere)
               if a.get('corrige_dispo')]
    return render_template('annales.html', annales=annales, niveau=niveau,
                           serie=serie, matiere=matiere, type_doc='Corrigés')

@app.route('/voir/<int:annale_id>')
def voir_annale(annale_id):
    increment_vues(annale_id)
    return '', 204

@app.route('/annales/<niveau>/<matiere>')
def redirect_sans_serie(niveau, matiere):
    return redirect(f'/{niveau.lower()}/{matiere}')

@app.route('/annales/<niveau>/<serie>/<matiere>')
def redirect_avec_serie(niveau, serie, matiere):
    return redirect(f'/{niveau.lower()}/{serie}/{matiere}')

# ══════════════════════════════════════════
# ERREURS
# ══════════════════════════════════════════

@app.errorhandler(404)
def page_non_trouvee(e):
    return render_template('404.html'), 404

@app.errorhandler(403)
def acces_interdit(e):
    return render_template('403.html'), 403

@app.errorhandler(500)
def erreur_serveur(e):
    app.logger.error(f"Erreur serveur non geree: {e}")
    return render_template('500.html'), 500

# ═══════════════════════════════════════
# CARREFOUR
# ═══════════════════════════════════════
@app.route('/carrefour/<niveau>/<matiere>')
def carrefour_niveau(niveau, matiere):
    serie = request.args.get('serie')
    data = get_carrefour(niveau, matiere, serie=serie)
    return render_template('carrefour.html', niveau=niveau, serie=serie, matiere=matiere, data=data)

# ═══════════════════════════════════════
# ÉTABLISSEMENTS
# ═══════════════════════════════════════

@app.route('/etablissements')
def etablissements_index():
    niveaux = [(slug, slug.replace('-', ' ').title()) for slug in CORRESPONDANCE_NIVEAU_SERIE.keys()]
    return render_template('etablissements_index.html', niveaux=niveaux)

@app.route('/etablissements/<niveau_serie>')
def etablissements_niveau(niveau_serie):
    matieres = get_matieres_externes(niveau_serie)
    return render_template('etablissements_niveau.html', niveau_serie=niveau_serie,
                            label_niveau=niveau_serie.replace('-', ' ').title(),
                            matieres=matieres)

@app.route('/etablissements/<niveau_serie>/<matiere>')
def etablissements_matiere(niveau_serie, matiere):
    annee = request.args.get('annee', type=int)
    sequence = request.args.get('sequence', type=int)
    epreuves = get_annales_externes(niveau_serie, matiere, annee=annee, sequence=sequence)
    annees = get_annees_disponibles(niveau_serie, matiere)
    sequences = get_sequences_disponibles(niveau_serie, matiere)
    return render_template('etablissements_matiere.html',
                           niveau_serie=niveau_serie, matiere=matiere,
                           epreuves=epreuves,
                           annees_disponibles=annees, annee_active=annee,
                           sequences_disponibles=sequences, sequence_active=sequence)

@app.route('/redirection/<int:annale_id>')
def redirection_externe(annale_id):
    entree = get_annale_externe_by_id(annale_id)
    if not entree:
        return "Épreuve introuvable", 404
    increment_vue_externe(annale_id)
    log_evenement('redirection_externe', g.session_id,
                  niveau=entree['niveau'], serie=entree['serie'],
                  matiere=entree['matiere'], destination=entree['lien_page_source'])
    return redirect(entree['lien_page_source'])

@app.route('/api/search')
@limiter_debit(max_requetes=40, fenetre_sec=10)
def api_search():
    q = request.args.get('q', '').strip()
    niveau = request.args.get('niveau') or None
    serie = request.args.get('serie') or None
    matiere = request.args.get('matiere') or None

    if len(q) < 2:
        return jsonify({'resultats': [], 'suggestions': [], 'total_trouve': 0})

    resultat = rechercher_avec_scoring(q, limite=8, niveau=niveau, serie=serie, matiere=matiere)

    if len(q) >= 3:
        log_evenement(
            'recherche', g.session_id, route=request.path,
            niveau=niveau, matiere=matiere, requete=q
        )

    if not resultat['resultats'] and len(q) >= 3:
        enregistrer_recherche_infructueuse(q)

    return jsonify(resultat)

@app.route('/api/log-clic', methods=['POST'])
@limiter_debit(max_requetes=20, fenetre_sec=10)
def api_log_clic():
    data = request.get_json(silent=True) or {}
    log_evenement(
        'clic_resultat',
        request.cookies.get('ec_session', 'inconnu'),
        requete=data.get('requete'),
        destination=data.get('destination'),
        niveau=data.get('niveau'),
        matiere=data.get('matiere'),
    )
    return '', 204


# ══════════════════════════════════════════
# ADMIN — AUTHENTIFICATION
# ══════════════════════════════════════════

def admin_requis(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get('admin_connecte'):
            return redirect('/admin/login')
        return f(*args, **kwargs)
    return wrapper

def eleve_requis(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        eleve_id = session.get('eleve_id')
        if not eleve_id:
            return redirect('/connexion')
        eleve = get_eleve_par_id(eleve_id)
        if not eleve:
            session.pop('eleve_id', None)
            return redirect('/connexion')
        g.eleve = eleve
        return f(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_eleve():
    eleve_id = session.get('eleve_id')
    eleve = get_eleve_par_id(eleve_id) if eleve_id else None
    return {'eleve_connecte': eleve}


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    erreur = False
    bloque = False
    csrf_invalide = False
    minutes_restantes = 0
    ip = _ip_client()

    if _login_bloque(ip):
        bloque = True
        minutes_restantes = _minutes_avant_deblocage(ip)
    elif request.method == 'POST':
        token_soumis = request.form.get('csrf_token', '')
        token_attendu = session.get('csrf_token', '')
        if not token_attendu or not secrets.compare_digest(token_soumis, token_attendu):
            csrf_invalide = True
            erreur = True
        else:
            mot_de_passe = request.form.get('mot_de_passe', '')
            if mot_de_passe == app.config['ADMIN_TOKEN']:
                session['admin_connecte'] = True
                session.pop('csrf_token', None)
                _TENTATIVES_LOGIN.pop(ip, None)
                return redirect('/admin/dashboard')
            else:
                _enregistrer_echec(ip)
                erreur = True
                if _login_bloque(ip):
                    bloque = True
                    minutes_restantes = _minutes_avant_deblocage(ip)

    session['csrf_token'] = secrets.token_urlsafe(32)

    return render_template('admin_login.html', erreur=erreur, bloque=bloque,
                            minutes_restantes=minutes_restantes,
                            csrf_token=session['csrf_token'])


@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_connecte', None)
    return redirect('/admin/login')


# ══════════════════════════════════════════
# ADMIN — DASHBOARD & ANALYTICS
# ══════════════════════════════════════════

@app.route('/admin/dashboard')
@admin_requis
def admin_dashboard():
    jours = request.args.get('jours', 30, type=int)
    return render_template('admin_dashboard.html',
        resume=stats_resume(jours),
        pages=stats_pages_populaires(jours),
        recherches=stats_recherches_populaires(jours),
        matieres=stats_matieres_populaires(jours),
        visites_par_jour=stats_visites_par_jour(min(jours, 30)),
        destinations=stats_destinations_cliquees(jours),
        sources=stats_sources(jours),
        visiteurs=stats_nouveaux_vs_recurrents(jours),
        duree=stats_duree_sessions(jours),
        jours=jours,
    )

@app.route('/admin/dashboard/journal')
@admin_requis
def admin_journal():
    jours = request.args.get('jours', 30, type=int)
    offset_recherches = request.args.get('or_', 0, type=int)
    offset_clics = request.args.get('oc', 0, type=int)
    return render_template('admin_journal.html',
        recherches=stats_journal_recherches(jours, offset=offset_recherches),
        clics=stats_journal_clics(jours, offset=offset_clics),
        jours=jours,
    )

@app.route('/admin/session/<session_id>')
@admin_requis
def admin_parcours(session_id):
    jours = request.args.get('jours', 30, type=int)
    return render_template('admin_parcours.html',
        session_id=session_id,
        evenements=stats_parcours_session(session_id, jours),
        jours=jours,
    )


@app.route('/inscription', methods=['GET', 'POST'])
def inscription():
    erreur = None
    if request.method == 'POST':
        token_soumis = request.form.get('csrf_token', '')
        token_attendu = session.get('csrf_token_inscription', '')
        if not token_attendu or not secrets.compare_digest(token_soumis, token_attendu):
            erreur = "Session expirée, réessaie."
        else:
            identifiant = request.form.get('identifiant', '').strip()
            mot_de_passe = request.form.get('mot_de_passe', '')
            nom = request.form.get('nom', '').strip()
            niveau = request.form.get('niveau', '')
            serie = request.form.get('serie') or None
            classe = request.form.get('classe', '').strip() or None
            email = request.form.get('email', '').strip() or None
            telephone = request.form.get('telephone', '').strip() or None

            eleve_id, erreur = creer_compte(
                identifiant, mot_de_passe, nom, niveau, serie, classe, email, telephone
            )
            if eleve_id:
                session.pop('csrf_token_inscription', None)
                session['eleve_id'] = eleve_id
                marquer_connexion(eleve_id)
                return redirect('/mon-compte')

    session['csrf_token_inscription'] = secrets.token_urlsafe(32)
    return render_template(
        'inscription.html', erreur=erreur,
        csrf_token=session['csrf_token_inscription'],
        niveaux=NIVEAUX_VALIDES_ELEVES, series=SERIES_VALIDES_ELEVES,
    )


@app.route('/connexion', methods=['GET', 'POST'])
def connexion():
    erreur = None
    bloque = False
    minutes_restantes = 0

    if request.method == 'POST':
        identifiant = request.form.get('identifiant', '').strip()
        token_soumis = request.form.get('csrf_token', '')
        token_attendu = session.get('csrf_token_connexion', '')

        if login_identifiant_bloque(identifiant):
            bloque = True
            minutes_restantes = minutes_avant_deblocage_identifiant(identifiant)
        elif not token_attendu or not secrets.compare_digest(token_soumis, token_attendu):
            erreur = "Session expirée, réessaie."
        else:
            mot_de_passe = request.form.get('mot_de_passe', '')
            eleve = verifier_identifiants(identifiant, mot_de_passe)
            if eleve:
                reinitialiser_echecs_identifiant(identifiant)
                session.pop('csrf_token_connexion', None)
                session['eleve_id'] = eleve['id']
                marquer_connexion(eleve['id'])
                return redirect('/mon-compte')
            else:
                enregistrer_echec_identifiant(identifiant)
                erreur = "Identifiant ou mot de passe incorrect."
                if login_identifiant_bloque(identifiant):
                    bloque = True
                    minutes_restantes = minutes_avant_deblocage_identifiant(identifiant)

    session['csrf_token_connexion'] = secrets.token_urlsafe(32)
    return render_template(
        'connexion.html', erreur=erreur, bloque=bloque,
        minutes_restantes=minutes_restantes,
        csrf_token=session['csrf_token_connexion'],
    )


@app.route('/deconnexion')
def deconnexion():
    session.pop('eleve_id', None)
    return redirect('/')

# ═══════════════════════════════════════
# GÉNÉRATEUR D'ÉPREUVES (RAG Maths BAC C)
# ═══════════════════════════════════════
MOTIF_JETON_VALIDE = re.compile(r'^[0-9a-f]{32}$')
@app.route('/generateur-epreuves')
def generateur_epreuves():
    return render_template('generateur.html', erreur=None)


@app.route('/generateur-epreuves/extraire-entete', methods=['POST'])
@limiter_debit(max_requetes=4, fenetre_sec=600)
def generateur_epreuves_extraire_entete():
    nettoyer_entetes_expirees()

    fichier = request.files.get('exemple_entete')
    if not fichier or fichier.filename == '':
        return jsonify({'ok': False, 'erreur': "Aucun fichier reçu."}), 400

    suffixe = Path(fichier.filename).suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffixe, delete=False) as tmp:
        chemin_tmp = Path(tmp.name)
        fichier.save(chemin_tmp)

    try:
        jeton, confiance, champs = extraire_entete_pour_upload(chemin_tmp)
    except EnteteSourceIncomplete as e:
        app.logger.info(f"Photo d'en-tête incomplète (haut coupé) : {e}")
        return jsonify({'ok': False, 'erreur': str(e), 'code': 'haut_tronque'})
    except ExtractionEnteteEchouee as e:
        app.logger.warning(f"Extraction en-tête échouée : {e}")
        return jsonify({'ok': False, 'erreur': str(e)})
    finally:
        chemin_tmp.unlink(missing_ok=True)
    return jsonify({'ok': True, 'jeton': jeton, 'confiance': confiance, 'champs': champs})


@app.route('/generateur-epreuves/apercu-entete/<jeton>')
def generateur_epreuves_apercu_entete(jeton):
    if not MOTIF_JETON_VALIDE.match(jeton):
        abort(404)
    try:
        png_bytes = generer_apercu_brut(jeton)
    except ExtractionEnteteEchouee:
        abort(404)
    return send_file(io.BytesIO(png_bytes), mimetype='image/png')


@app.route('/generateur-epreuves/generer', methods=['POST'])
@limiter_debit(max_requetes=2, fenetre_sec=600)
def generateur_epreuves_generer():
    payload = request.get_json(silent=True) or {}

    type_document = payload.get('type_document') or 'Sequence'
    if type_document not in ('Sequence', 'Examen'):
        return jsonify({'erreur': 'Type de document invalide.'}), 400

    sequence = 0
    serie = None

    if type_document == 'Sequence':
        try:
            sequence = int(payload.get('sequence'))
        except (TypeError, ValueError):
            return jsonify({'erreur': 'Séquence invalide.'}), 400
        if sequence not in (1, 2, 3, 4, 5, 6):
            return jsonify({'erreur': 'Séquence invalide.'}), 400
    else:  # type_document == 'Examen'
        serie = payload.get('serie')
        if serie not in ('C', 'E'):
            return jsonify({'erreur': "Série invalide ou manquante ('C' ou 'E') pour un Examen officiel."}), 400

    jeton = payload.get('jeton', '')
    if not MOTIF_JETON_VALIDE.match(jeton):
        return jsonify({'erreur': "En-tête manquante ou invalide -- réuploade un exemple."}), 400

    valeurs_editees = payload.get('valeurs') or {}
    if not isinstance(valeurs_editees, dict):
        valeurs_editees = {}

    try:
        chemin_entete, contexte_regional = personnaliser_et_decouper(jeton, valeurs_editees)
    except ExtractionEnteteEchouee as e:
        return jsonify({'erreur': str(e)}), 400

    metadonnees = {'chemin_image_entete': str(chemin_entete)}

    try:
        chemin_json = generer_epreuve_json(
            sequence, metadonnees, contexte_regional=contexte_regional,
            type_document=type_document, serie=serie,
        )
        chemin_pdf = construire_pdf(chemin_json)
    except RuntimeError as e:
        cible = f"Examen série {serie}" if type_document == 'Examen' else f"séquence {sequence}"
        app.logger.error(f"Échec génération épreuve ({cible}): {e}")
        return jsonify({'erreur': "La génération a échoué. Réessaie dans quelques minutes."}), 500
    finally:
        supprimer_extraction_temporaire(jeton)

    return send_file(chemin_pdf, as_attachment=True, download_name=chemin_pdf.name)


# ═══════════════════════════════════════
# ASSISTANT ÉLÈVE (chat conversationnel)
# ═══════════════════════════════════════
LIMITE_HISTORIQUE_TOURS = 12

@app.route('/assistant-eleve')
def assistant_eleve():
    return redirect(url_for('index'))


# CORRECTIF (29/08/2026) : l'ancienne version avait deux décorateurs
# @app.route identiques empilés sur cette fonction (copier-coller) --
# inoffensif en pratique mais source de confusion. Un seul décorateur.
#
# MODIFIÉ (29/08/2026, extension multi-matières) : la matière choisie
# par l'élève dans la sidebar (voir assistant_eleve.html, nouvelle
# section "Matière") est lue dans le payload et vérifiée via
# chat_scope.matiere_disponible_pour() -- remplace l'ancien contrôle
# qui ne vérifiait que le niveau/série (chat_disponible_pour reste
# réservé à la génération PDF désormais, voir chat_scope.py).
@app.route('/assistant-eleve/repondre', methods=['POST'])
@limiter_debit(max_requetes=15, fenetre_sec=600)
def assistant_eleve_repondre():
    payload = request.get_json(silent=True) or {}

    eleve_id = session.get('eleve_id')
    if not eleve_id:
        return jsonify({'erreur': "Connecte-toi pour utiliser l'assistant.", 'code': 'non_connecte'}), 401
    eleve = get_eleve_par_id(eleve_id)
    if not eleve:
        session.pop('eleve_id', None)
        return jsonify({'erreur': "Session invalide, reconnecte-toi.", 'code': 'non_connecte'}), 401

    question = (payload.get('question') or '').strip()
    if not question:
        return jsonify({'erreur': "Message vide."}), 400
    if len(question) > 2000:
        return jsonify({'erreur': "Message trop long."}), 400

    # NOUVEAU (29/08/2026, extension multi-matières) : défaut
    # "Mathematiques" si le front n'envoie pas encore ce champ (vieux
    # cache navigateur, etc.) -- rétrocompatible. Un seul contrôle
    # (matiere_disponible_pour) couvre à la fois "niveau/série pas
    # actif" et "matière pas couverte pour cette série".
    matiere = (payload.get('matiere') or 'Mathematiques').strip()
    if not matiere_disponible_pour(eleve['niveau'], eleve['serie'], matiere):
        return jsonify({'reponse': message_indisponible(eleve['niveau'], eleve['serie'], matiere)})

    historique_brut = payload.get('historique') or []
    if not isinstance(historique_brut, list):
        historique_brut = []

    historique = []
    for tour in historique_brut[-LIMITE_HISTORIQUE_TOURS:]:
        if not isinstance(tour, dict):
            continue
        role = tour.get('role')
        contenu = tour.get('content')
        if role in ('user', 'assistant') and isinstance(contenu, str) and contenu.strip():
            historique.append({'role': role, 'content': contenu.strip()})

    if detecter_demande_epreuve(question):
        resultat_recherche = chercher_epreuves(question)
        return jsonify(preparer_resultats_epreuves(resultat_recherche))
    criteres_bac = detecter_demande_exercice_bac(question)
    if criteres_bac is not None:
        exercice = obtenir_exercice_bac(criteres_bac['annee'], criteres_bac['numero'])
        texte_bac = formuler_reponse_exercice_bac(exercice, criteres_bac['annee'], criteres_bac['numero'])
        return jsonify({'reponse': texte_bac})

    # Streaming (SSE) -- `matiere` est transmis pour que chat_contexte
    # choisisse le bon mode (RAG Maths vs générique), voir chat_scope.py.
    def flux_evenements():
        texte_complet = []
        try:
            for morceau in repondre_eleve_stream(question, historique, eleve=eleve, matiere=matiere):
                texte_complet.append(morceau)
                yield f"data: {json.dumps({'type': 'morceau', 'texte': morceau})}\n\n"
        except RuntimeError as e:
            app.logger.error(f"Échec réponse assistant élève (stream) : {e}")
            message_erreur = "Je n'arrive pas à continuer, réessaie dans un instant."
            yield f"data: {json.dumps({'type': 'erreur', 'texte': message_erreur})}\n\n"
            return

        incrementer_usage_mensuel(eleve_id)
        yield f"data: {json.dumps({'type': 'fin', 'texte_complet': ''.join(texte_complet)})}\n\n"

    return Response(
        flux_evenements(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


@app.route('/assistant-eleve/generer', methods=['POST'])
def assistant_eleve_generer():
    payload = request.get_json(silent=True) or {}

    eleve_id = session.get('eleve_id')
    if not eleve_id:
        return jsonify({'erreur': "Connecte-toi pour utiliser l'assistant.", 'code': 'non_connecte'}), 401
    eleve = get_eleve_par_id(eleve_id)
    if not eleve:
        session.pop('eleve_id', None)
        return jsonify({'erreur': "Session invalide, reconnecte-toi.", 'code': 'non_connecte'}), 401
    # Génération de PDF -- reste Mathématiques uniquement, donc
    # chat_disponible_pour(niveau, serie) à 2 arguments reste le bon
    # contrôle ici, INCHANGÉ.
    if not chat_disponible_pour(eleve['niveau'], eleve['serie']):
        return jsonify({'erreur': message_indisponible(eleve['niveau'], eleve['serie']), 'code': 'niveau_indisponible'}), 403

    type_document = payload.get('type_document') or 'Examen'
    if type_document not in ('Sequence', 'Examen'):
        return jsonify({'erreur': 'Type de document invalide.'}), 400

    sequence = 0
    serie = None

    if type_document == 'Sequence':
        try:
            sequence = int(payload.get('sequence'))
        except (TypeError, ValueError):
            return jsonify({'erreur': 'Séquence invalide.'}), 400
        if sequence not in (1, 2, 3, 4, 5, 6):
            return jsonify({'erreur': 'Séquence invalide.'}), 400
    else:  # Examen -- scope actuel du chat élève : série C par défaut
        serie = payload.get('serie') or 'C'
        if serie not in ('C', 'E'):
            return jsonify({'erreur': "Série invalide ('C' ou 'E')."}), 400

    metadonnees = metadonnees_defaut_eleve(type_document, serie)

    try:
        chemin_json = generer_epreuve_json(
            sequence, metadonnees,
            type_document=type_document, serie=serie,
        )
        chemin_pdf = construire_pdf(chemin_json)
    except RuntimeError as e:
        cible = f"Examen série {serie}" if type_document == 'Examen' else f"séquence {sequence}"
        app.logger.error(f"Échec génération épreuve élève ({cible}): {e}")
        return jsonify({'erreur': "La génération a échoué. Réessaie dans quelques minutes."}), 500

    incrementer_usage_mensuel(eleve_id)

    return send_file(chemin_pdf, as_attachment=True, download_name=chemin_pdf.name)


@app.route('/chat/niveaux')
def chat_niveaux():
    return jsonify({'niveaux': get_niveaux()})


@app.route('/chat/series')
def chat_series():
    niveau = request.args.get('niveau', '')
    return jsonify({'series': get_series(niveau)})


@app.route('/chat/matieres')
def chat_matieres():
    niveau = request.args.get('niveau', '')
    serie = request.args.get('serie') or None
    if not niveau:
        return jsonify({'erreur': 'Niveau requis.'}), 400
    return jsonify({'matieres': get_toutes_matieres(niveau, serie)})


@app.route('/chat/parcourir')
def chat_parcourir_route():
    niveau = request.args.get('niveau', '')
    matiere = request.args.get('matiere', '')
    serie = request.args.get('serie') or None
    if not niveau or not matiere:
        return jsonify({'erreur': 'Niveau et matière requis.'}), 400
    resultats = lister_epreuves(niveau, matiere, serie)
    return jsonify({'resultats': resultats})

@app.route('/mon-compte', methods=['GET', 'POST'])
@eleve_requis
def mon_compte():
    erreur = None
    succes = None

    if request.method == 'POST':
        token_soumis = request.form.get('csrf_token', '')
        token_attendu = session.get('csrf_token_mon_compte', '')
        if not token_attendu or not secrets.compare_digest(token_soumis, token_attendu):
            erreur = "Session expirée, réessaie."
        else:
            action = request.form.get('action')
            if action == 'profil':
                erreur = modifier_profil(
                    g.eleve['id'],
                    nom=request.form.get('nom'),
                    niveau=request.form.get('niveau'),
                    serie=request.form.get('serie') or None,
                    classe=request.form.get('classe'),
                )
                if not erreur:
                    succes = "Profil mis à jour."
                    g.eleve = get_eleve_par_id(g.eleve['id'])
            elif action == 'mot_de_passe':
                erreur = changer_mot_de_passe(
                    g.eleve['id'],
                    request.form.get('ancien_mot_de_passe', ''),
                    request.form.get('nouveau_mot_de_passe', ''),
                )
                if not erreur:
                    succes = "Mot de passe changé."

            session['csrf_token_mon_compte'] = secrets.token_urlsafe(32)

    if 'csrf_token_mon_compte' not in session:
        session['csrf_token_mon_compte'] = secrets.token_urlsafe(32)

    return render_template(
        'mon_compte.html', eleve=g.eleve, erreur=erreur, succes=succes,
        niveaux=NIVEAUX_VALIDES_ELEVES, series=SERIES_VALIDES_ELEVES,
        csrf_token=session['csrf_token_mon_compte'],
    )
if __name__ == '__main__':
    app.run(debug=app.config['DEBUG'])