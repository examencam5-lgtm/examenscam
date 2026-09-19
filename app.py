# app.py — ExamensCam — Version finale complète
import os
import re
import json
import io
import time
from pathlib import Path
from datetime import timedelta, datetime
import secrets
from functools import wraps
from urllib.parse import urlparse
from dotenv import load_dotenv
load_dotenv()
from flask import send_file
from authlib.integrations.flask_client import OAuth
from scripts.generer_epreuve_json import generer_epreuve_json
from scripts.construire_pdf_officiel import construire_pdf
from scripts.chat_contexte import repondre_eleve, repondre_eleve_stream, repondre_chronologie_datee
from generer_search_index import generer as generer_index
from scripts.chat_parcourir import get_niveaux, get_series, lister_epreuves, get_annees
from scripts.image_utils import compresser_image_pour_gemini, ImageInvalideError
from scripts.gemini_client import envoyer_image_gemini
from database_credits import (
    create_table as create_table_credits,
    peut_poser_question,
    consommer_credits,
    get_solde,
)
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
import database_credits
from database_matieres import get_toutes_matieres
from database_externes import (
    get_matieres_externes, get_annales_externes, get_annale_externe_by_id,
    increment_vue_externe, get_annees_disponibles, get_sequences_disponibles,
    CORRESPONDANCE_NIVEAU_SERIE
)
from database import (get_annales, get_matieres, increment_vues, get_stats,
                      get_derniere_maj, create_table, get_connection)
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
    create_table as create_table_eleves, creer_ou_recuperer_compte_google,
    completer_profil, marquer_connexion, get_eleve_par_id, modifier_profil,
    supprimer_compte, incrementer_usage_mensuel,
    NIVEAUX_VALIDES as NIVEAUX_VALIDES_ELEVES, SERIES_VALIDES as SERIES_VALIDES_ELEVES,
)
from paiement_monetbil import (
    initier_paiement, verifier_signature_notification,
    verifier_paiement_par_transaction, PaiementMonetbilEchoue,
)
from database_paiements import (
    create_table as create_table_paiements, creer_paiement, get_paiement_par_ref,
    confirmer_paiement, abonnement_est_actif, MONTANT_ABONNEMENT_FCFA,
)
from database_conversations import (
    create_table as create_table_conversations,
    enregistrer_tour, charger_historique, effacer_conversation,
)
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
    # MODIFIÉ (16/09/2026, durcissement session) : 30 jours ramené à 7.
    # Beaucoup d'élèves utilisent un téléphone familial partagé (frère,
    # sœur, parent) plutôt qu'un appareil personnel -- une session
    # valide 30 jours multiplie le risque qu'un autre membre de la
    # famille retombe sur le compte de l'élève précédent sans jamais
    # avoir vu d'écran de connexion. 7 jours réduit nettement cette
    # fenêtre sans gêner un usage normal (l'élève qui revient chaque
    # jour ou presque reste connecté).
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)
    # ═══════════════════════════════════════════════════════
# AUTHENTIFICATION GOOGLE
# ═══════════════════════════════════════════════════════
_GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
_GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')

if not _GOOGLE_CLIENT_ID or not _GOOGLE_CLIENT_SECRET:
    raise RuntimeError(
        "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET manquants. Configure ces "
        "variables d'environnement sur Render avec les identifiants OAuth "
        "obtenus depuis console.cloud.google.com."
    )

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=_GOOGLE_CLIENT_ID,
    client_secret=_GOOGLE_CLIENT_SECRET,
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    # MODIFIÉ (17/09/2026, minimisation de la friction d'inscription) :
    # ajout du scope 'profile' -- Google fournit alors given_name et
    # family_name dans userinfo, ce qui permet de ne plus jamais
    # demander le prénom/nom par formulaire (voir
    # connexion_google_callback ci-dessous). Reste conforme au
    # principe de minimisation : on ne demande toujours QUE
    # l'identité (email/sub) et le nom d'affichage, jamais les
    # contacts, photos ou l'agenda.
    client_kwargs={'scope': 'openid email profile'},
)
with app.app_context():
    create_table()
    create_table_eleves()
    create_table_conversations()
    create_table_credits()
ROUTES_IGNOREES_TRACKING = ('/static/', '/api/', '/admin/', '/favicon.ico', '/ping')
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
# FONCTION UTILITAIRE - PROTECTION OPEN REDIRECT
# ══════════════════════════════════════════

def redirection_sure(cible: str, defaut: str = '/mon-compte') -> str:
    """Valide qu'une destination de redirection post-connexion est un
    chemin LOCAL, jamais une URL externe -- protection contre l'open
    redirect. Voir commentaire détaillé plus haut dans ce fichier."""
    if not cible:
        return defaut
    if not cible.startswith('/') or cible.startswith('//'):
        return defaut
    parsed = urlparse(cible)
    if parsed.netloc or parsed.scheme:
        return defaut
    return cible


# ══════════════════════════════════════════
# ROUTES PRINCIPALES
# ══════════════════════════════════════════

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
        disponible = True
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

@app.route('/ping')
def ping():
    conn = get_connection()
    try:
        conn.cursor().execute("SELECT 1")
    finally:
        conn.close()
    return '', 204

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

# ══════════════════════════════════════════
# API - VÉRIFICATION D'IDENTIFIANT EN DIRECT (AJAX)
# ══════════════════════════════════════════

@app.route('/api/identifiant-disponible')
@limiter_debit(max_requetes=20, fenetre_sec=10)
def api_identifiant_disponible():
    identifiant = (request.args.get('identifiant') or '').strip()
    if len(identifiant) < 3:
        return jsonify({'disponible': None})  # trop court pour juger, pas d'avis
    return jsonify({'disponible': identifiant_disponible(identifiant)})

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
            return redirect(url_for('connexion_google', next=request.path))
        eleve = get_eleve_par_id(eleve_id)
        if not eleve:
            session.pop('eleve_id', None)
            return redirect(url_for('connexion_google', next=request.path))
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

# ══════════════════════════════════════════
# RECHARGE MANUELLE — ADMIN (06/09/2026)
# ══════════════════════════════════════════

@app.route('/admin/recharges')
@admin_requis
def admin_recharges():
    return render_template(
        'admin_recharges.html',
        demandes=database_credits.lister_demandes_en_attente(),
    )


@app.route('/admin/recharges/<int:demande_id>/valider', methods=['POST'])
@admin_requis
def admin_valider_recharge(demande_id):
    resultat = database_credits.valider_demande_recharge(demande_id)
    if not resultat['ok']:
        app.logger.error(f"Échec validation recharge {demande_id}: {resultat.get('erreur')}")
    return redirect(url_for('admin_recharges'))


@app.route('/admin/recharges/<int:demande_id>/rejeter', methods=['POST'])
@admin_requis
def admin_rejeter_recharge(demande_id):
    note = request.form.get('note_admin', '').strip() or None
    resultat = database_credits.rejeter_demande_recharge(demande_id, note)
    if not resultat['ok']:
        app.logger.error(f"Échec rejet recharge {demande_id}: {resultat.get('erreur')}")
    return redirect(url_for('admin_recharges'))


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

@app.route('/admin/regenerer-index', methods=['POST'])
@admin_requis
def admin_regenerer_index():
    resultat = generer_index()
    if not resultat['ok']:
        app.logger.error(f"Échec régénération search_index : {resultat['erreur']}")
        return jsonify(resultat), 500
    return jsonify(resultat)


@app.route('/connexion/google')
@limiter_debit(max_requetes=15, fenetre_sec=600)
def connexion_google():
    # NOUVEAU (16/09/2026, durcissement session) : session.clear() AVANT
    # de lancer le flux OAuth -- sans ça, un cookie de session valide
    # déjà présent dans ce navigateur (session d'un précédent élève sur
    # un appareil familial partagé, jamais explicitement fermée) reste
    # actif pendant tout l'aller-retour Google, et rien ne garantit que
    # connexion_google_callback() écrase proprement l'ancien eleve_id.
    # Repartir d'une session vide à chaque clic sur "Se connecter" est
    # la seule garantie fiable : après ce point, la session ne peut
    # contenir que ce que CE flux de connexion y aura mis.
    session.clear()
    next_url = redirection_sure(request.args.get('next'))
    session['next_apres_connexion'] = next_url
    redirect_uri = url_for('connexion_google_callback', _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route('/connexion/google/callback')
def connexion_google_callback():
    try:
        token = google.authorize_access_token()
    except Exception as e:
        print(f"connexion_google_callback erreur token: {e}")
        return redirect(url_for('connexion_google', erreur='echec_google'))

    userinfo = token.get('userinfo')
    if not userinfo or not userinfo.get('sub') or not userinfo.get('email'):
        return redirect(url_for('connexion_google', erreur='profil_google_incomplet'))

    # MODIFIÉ (17/09/2026, minimisation de la friction d'inscription) :
    # prénom/nom viennent directement de Google (given_name/family_name,
    # disponibles grâce au scope 'profile' ajouté ci-dessus) -- on ne
    # les demande plus jamais par formulaire, exactement comme
    # Anthropic/OpenAI le font pour leurs propres comptes. Repli sur
    # 'name' (découpé au premier espace) si given_name/family_name
    # manquent pour ce compte Google (rare, mais possible sur certains
    # comptes Workspace restreints) -- ne bloque jamais la connexion,
    # juste un profil moins précis que l'élève pourra de toute façon
    # voir sur /mon-compte.
    prenom_google = (userinfo.get('given_name') or '').strip()
    nom_google = (userinfo.get('family_name') or '').strip()
    if not prenom_google and not nom_google:
        nom_complet = (userinfo.get('name') or '').strip()
        if nom_complet:
            morceaux = nom_complet.split(' ', 1)
            prenom_google = morceaux[0]
            nom_google = morceaux[1] if len(morceaux) > 1 else ''

    eleve = creer_ou_recuperer_compte_google(
        google_sub=userinfo['sub'],
        email=userinfo['email'],
        prenom=prenom_google or None,
        nom=nom_google or None,
    )

    session.permanent = True
    session['eleve_id'] = eleve['id']
    marquer_connexion(eleve['id'])

    if not eleve.get('profil_complet'):
        return redirect(url_for('completer_profil_vue'))

    next_url = session.pop('next_apres_connexion', None) or '/'
    return redirect(next_url)


@app.route('/completer-profil', methods=['GET', 'POST'])
def completer_profil_vue():
    eleve_id = session.get('eleve_id')
    if not eleve_id:
        return redirect(url_for('connexion_google'))

    eleve = get_eleve_par_id(eleve_id)
    if not eleve:
        session.pop('eleve_id', None)
        return redirect(url_for('connexion_google'))

    erreur = None
    if request.method == 'POST':
        # MODIFIÉ (17/09/2026) : prenom/nom ne sont plus lus depuis le
        # formulaire -- ils ont déjà été fixés à la création du compte
        # depuis les données Google (voir connexion_google_callback).
        # Seuls le niveau/série/classe/établissement/consentement
        # restent à renseigner par l'élève -- c'est la seule
        # information que Google ne peut pas fournir.
        niveau = request.form.get('niveau', '')
        serie = request.form.get('serie') or None
        classe = request.form.get('classe', '').strip() or None
        etablissement = request.form.get('etablissement', '').strip() or None
        consentement_parental = request.form.get('consentement_parental') == 'on'

        erreur = completer_profil(
            eleve_id, niveau, serie, classe,
            etablissement, consentement_parental
        )
        if not erreur:
            session.pop('next_apres_connexion', None)
            return redirect('/')

    return render_template(
        'completer_profil.html', erreur=erreur, eleve=eleve,
        niveaux=NIVEAUX_VALIDES_ELEVES, series=SERIES_VALIDES_ELEVES,
    )

@app.route('/deconnexion')
def deconnexion():
    # MODIFIÉ (16/09/2026, durcissement session) : session.clear() au
    # lieu de session.pop('eleve_id', None) seul -- sur un appareil
    # familial partagé, ne retirer QUE eleve_id pouvait laisser
    # d'autres clés de session (tokens OAuth temporaires,
    # next_apres_connexion, csrf_token_*) accessibles à la personne
    # suivante qui ouvre le site sur ce même navigateur. Une
    # déconnexion doit repartir d'un état totalement vierge.
    session.clear()
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

    if not peut_poser_question(eleve_id):
        return jsonify({
            'erreur': "Crédits épuisés. Recharge ton compte pour continuer.",
            'code': 'credits_epuises',
        }), 402

    question = (payload.get('question') or '').strip()
    if not question:
        return jsonify({'erreur': "Message vide."}), 400
    if len(question) > 2000:
        return jsonify({'erreur': "Message trop long."}), 400

    matiere = (payload.get('matiere') or 'Mathematiques').strip()
    if not matiere_disponible_pour(eleve['niveau'], eleve['serie'], matiere):
        return jsonify({'reponse': message_indisponible(eleve['niveau'], eleve['serie'], matiere)})

    historique = charger_historique(eleve_id, matiere, limite_tours=LIMITE_HISTORIQUE_TOURS)
    reponse_chronologie = repondre_chronologie_datee(question, eleve, matiere)
    if reponse_chronologie is not None:
        return jsonify({'reponse': reponse_chronologie})

    if detecter_demande_epreuve(question):
        resultat_recherche = chercher_epreuves(question)
        return jsonify(preparer_resultats_epreuves(resultat_recherche))
    criteres_bac = detecter_demande_exercice_bac(question)
    if criteres_bac is not None:
        exercice = obtenir_exercice_bac(criteres_bac['annee'], criteres_bac['numero'], matiere, eleve['niveau'])
        texte_bac = formuler_reponse_exercice_bac(exercice, criteres_bac['annee'], criteres_bac['numero'])
        return jsonify({'reponse': texte_bac})

    # Streaming (SSE) -- `matiere` est transmis pour que chat_contexte
    # choisisse le bon mode (RAG Maths/Physique vs générique), voir
    # chat_scope.py.
    #
    # NOTE (chantier en cours, crédits) : contrairement à
    # assistant_eleve_generer() et assistant_eleve_repondre_image(),
    # aucune déduction de crédits n'a lieu ici pour l'instant --
    # repondre_eleve_stream() ne renvoie pas encore de compte de
    # tokens exploitable par consommer_credits(). Le garde-fou
    # peut_poser_question() plus haut bloque déjà l'accès si l'élève
    # n'a plus de crédit, mais le chat texte ne les décrémente pas
    # encore. À câbler une fois chat_llm_client.py confirmé comme
    # source de tokens_entree/tokens_sortie pour ce chemin.
    def flux_evenements():
        texte_complet = []
        try:
            for morceau in repondre_eleve_stream(question, historique, eleve=eleve, matiere=matiere):
                texte_complet.append(morceau)
                yield f"data: {json.dumps({'type': 'morceau', 'texte': morceau})}\n\n"
        except Exception as e:
            app.logger.error(f"Échec réponse assistant élève (stream) : {e}")
            message_erreur = "Je n'arrive pas à continuer, réessaie dans un instant."
            yield f"data: {json.dumps({'type': 'erreur', 'texte': message_erreur})}\n\n"
            return

        reponse_complete = ''.join(texte_complet)
        enregistrer_tour(eleve_id, matiere, question, reponse_complete)
        incrementer_usage_mensuel(eleve_id)
        yield f"data: {json.dumps({'type': 'fin', 'texte_complet': reponse_complete})}\n\n"

    return Response(
        flux_evenements(),
        mimetype='text/event-stream',
        headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'},
    )


# NOUVEAU : historique persistant de la conversation (eleve_id, matiere)
# -- utilisée par le front au chargement de la page et à chaque
# changement de matière dans la sidebar. Route manquante en prod : le
# template l'appelait via url_for('assistant_eleve_historique') alors
# qu'elle avait disparu du fichier, causant un 500 sur TOUTE la page
# d'accueil (BuildError Jinja2, voir diagnostic du 15/09/2026).
@app.route('/assistant-eleve/historique')
def assistant_eleve_historique():
    eleve_id = session.get('eleve_id')
    if not eleve_id:
        return jsonify({'erreur': "Connecte-toi.", 'code': 'non_connecte'}), 401

    matiere = (request.args.get('matiere') or 'Mathematiques').strip()
    historique = charger_historique(eleve_id, matiere, limite_tours=LIMITE_HISTORIQUE_TOURS)
    return jsonify({'historique': historique})


# NOUVEAU : "Nouvelle conversation" doit effacer la conversation
# persistée côté serveur, pas seulement l'affichage local. Route
# manquante en prod, même cause que ci-dessus.
@app.route('/assistant-eleve/nouvelle-conversation', methods=['POST'])
def assistant_eleve_nouvelle_conversation():
    eleve_id = session.get('eleve_id')
    if not eleve_id:
        return jsonify({'erreur': "Connecte-toi.", 'code': 'non_connecte'}), 401

    payload = request.get_json(silent=True) or {}
    matiere = (payload.get('matiere') or 'Mathematiques').strip()
    effacer_conversation(eleve_id, matiere)
    return jsonify({'ok': True})


TAILLE_MAX_UPLOAD_OCTETS = 15 * 1024 * 1024  # 15 Mo -- voir POIDS_MAX_ENTREE_MO dans image_utils.py, cohérent
 
 
@app.route('/assistant-eleve/repondre-image', methods=['POST'])
@limiter_debit(max_requetes=10, fenetre_sec=600)
def assistant_eleve_repondre_image():
    eleve_id = session.get('eleve_id')
    if not eleve_id:
        return jsonify({'erreur': "Connecte-toi pour utiliser l'assistant.", 'code': 'non_connecte'}), 401
    eleve = get_eleve_par_id(eleve_id)
    if not eleve:
        session.pop('eleve_id', None)
        return jsonify({'erreur': "Session invalide, reconnecte-toi.", 'code': 'non_connecte'}), 401
 
    if not peut_poser_question(eleve_id):
        return jsonify({
            'erreur': "Crédits épuisés. Recharge ton compte pour continuer.",
            'code': 'credits_epuises',
        }), 402
 
    fichier_image = request.files.get('image')
    if not fichier_image or fichier_image.filename == '':
        return jsonify({'erreur': "Aucune image reçue."}), 400
 
    donnees_brutes = fichier_image.read()
    if len(donnees_brutes) > TAILLE_MAX_UPLOAD_OCTETS:
        return jsonify({'erreur': "Image trop lourde (maximum 15 Mo)."}), 413
 
    question = (request.form.get('question') or '').strip()
    if not question:
        question = "Aide-moi à résoudre cet exercice."
    if len(question) > 2000:
        return jsonify({'erreur': "Message trop long."}), 400
 
    matiere = (request.form.get('matiere') or 'Mathematiques').strip()
    if not matiere_disponible_pour(eleve['niveau'], eleve['serie'], matiere):
        return jsonify({'reponse': message_indisponible(eleve['niveau'], eleve['serie'], matiere)})
 
    try:
        image_compressee = compresser_image_pour_gemini(donnees_brutes)
    except ImageInvalideError as e:
        return jsonify({'erreur': str(e)}), 400
    finally:
        del donnees_brutes
 
    contexte_systeme = (
        f"Tu es le tuteur ExamensCam pour un élève de {eleve['niveau']}"
        + (f" série {eleve['serie']}" if eleve.get('serie') else "")
        + f", en {matiere}. L'élève a photographié un exercice. "
        "Aide-le à comprendre et résoudre, en expliquant le raisonnement "
        "étape par étape, comme au tableau, sans juste donner le résultat final."
    )
 
    try:
        resultat = envoyer_image_gemini(image_compressee, question, contexte_systeme)
    except RuntimeError as e:
        print(f"assistant_eleve_repondre_image erreur Gemini: {e}")
        return jsonify({'erreur': "Le tuteur est momentanément indisponible, réessaie dans un instant."}), 503
    finally:
        del image_compressee
 
    consommer_credits(
        eleve_id,
        resultat['tokens_entree'],
        resultat['tokens_sortie'],
        fournisseur=resultat['fournisseur'],
        source_modele=resultat['modele'],
    )
 
    return jsonify({'reponse': resultat['texte']})
 


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

    if not peut_poser_question(eleve_id):
        return jsonify({
            'erreur': "Crédits épuisés. Recharge ton compte pour continuer.",
            'code': 'credits_epuises',
        }), 402

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
        chemin_json, tokens_entree, tokens_sortie = generer_epreuve_json(
            sequence, metadonnees,
            type_document=type_document, serie=serie,
        )
        chemin_pdf = construire_pdf(chemin_json)
    except RuntimeError as e:
        cible = f"Examen série {serie}" if type_document == 'Examen' else f"séquence {sequence}"
        app.logger.error(f"Échec génération épreuve élève ({cible}): {e}")
        return jsonify({'erreur': "La génération a échoué. Réessaie dans quelques minutes."}), 500

    incrementer_usage_mensuel(eleve_id)

    consommer_credits(eleve_id, tokens_entree, tokens_sortie, fournisseur='gemini', source_modele='generer_epreuve_json')

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
    annee = request.args.get('annee', type=int)   # <-- AJOUT
    if not niveau or not matiere:
        return jsonify({'erreur': 'Niveau et matière requis.'}), 400
    resultats = lister_epreuves(niveau, matiere, serie, annee)   # <-- annee passé ici
    return jsonify({'resultats': resultats})
@app.route('/chat/annees')
def chat_annees():
    niveau = request.args.get('niveau', '')
    matiere = request.args.get('matiere', '')
    serie = request.args.get('serie') or None
    if not niveau or not matiere:
        return jsonify({'erreur': 'Niveau et matière requis.'}), 400
    return jsonify({'annees': get_annees(niveau, matiere, serie)})

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
            # MODIFIÉ (17/09/2026) : prenom/nom viennent de Google et ne
            # sont plus modifiables ici -- seuls niveau/série/classe/
            # établissement restent éditables par l'élève.
            erreur = modifier_profil(
                g.eleve['id'],
                niveau=request.form.get('niveau'),
                serie=request.form.get('serie') or None,
                classe=request.form.get('classe'),
                etablissement=request.form.get('etablissement'),
            )
            if not erreur:
                succes = "Profil mis à jour."
                g.eleve = get_eleve_par_id(g.eleve['id'])

            session['csrf_token_mon_compte'] = secrets.token_urlsafe(32)

    if 'csrf_token_mon_compte' not in session:
        session['csrf_token_mon_compte'] = secrets.token_urlsafe(32)

    return render_template(
        'mon_compte.html', eleve=g.eleve, erreur=erreur, succes=succes,
        niveaux=NIVEAUX_VALIDES_ELEVES, series=SERIES_VALIDES_ELEVES,
        csrf_token=session['csrf_token_mon_compte'],
    )

# ══════════════════════════════════════════
# SUPPRESSION DE COMPTE
# ══════════════════════════════════════════

@app.route('/mon-compte/supprimer', methods=['POST'])
@eleve_requis
def mon_compte_supprimer():
    token_soumis = request.form.get('csrf_token', '')
    token_attendu = session.get('csrf_token_mon_compte', '')
    if not token_attendu or not secrets.compare_digest(token_soumis, token_attendu):
        return redirect('/mon-compte')

    erreur = supprimer_compte(g.eleve['id'])
    if erreur:
        return render_template(
            'mon_compte.html', eleve=g.eleve, erreur=erreur, succes=None,
            niveaux=NIVEAUX_VALIDES_ELEVES, series=SERIES_VALIDES_ELEVES,
            csrf_token=session['csrf_token_mon_compte'],
        )

    session.pop('eleve_id', None)
    return redirect('/')

@app.route('/abonnement')
@eleve_requis
def abonnement_page():
    eleve = get_eleve_par_id(session['eleve_id'])
    abonne = abonnement_est_actif(eleve)
    expire_le = None
    if abonne and eleve.get('abonnement_expire_le'):
        expire_le = datetime.strptime(
            eleve['abonnement_expire_le'], '%Y-%m-%d %H:%M:%S'
        ).strftime('%d/%m/%Y')
    return render_template('abonnement.html', eleve=eleve, abonne=abonne,
                            expire_le=expire_le, montant=MONTANT_ABONNEMENT_FCFA)

@app.route('/abonnement/payer', methods=['POST'])
@eleve_requis
@limiter_debit(max_requetes=5, fenetre_sec=600)
def abonnement_payer():
    eleve_id = session['eleve_id']
    eleve = get_eleve_par_id(eleve_id)
    if not eleve:
        return jsonify({'erreur': 'Compte introuvable.'}), 404

    payment_ref = creer_paiement(eleve_id, MONTANT_ABONNEMENT_FCFA)
    base_url = request.host_url.rstrip('/')

    try:
        payment_url = initier_paiement(
            payment_ref=payment_ref,
            montant=MONTANT_ABONNEMENT_FCFA,
            notify_url=f'{base_url}/paiement/notification',
            return_url=f'{base_url}/paiement/retour?ref={payment_ref}',
            user=str(eleve_id),
            first_name=eleve.get('prenom') or eleve['nom'],
        )
    except PaiementMonetbilEchoue as e:
        app.logger.error(f"Échec initiation paiement (élève {eleve_id}) : {e}")
        return jsonify({'erreur': "Impossible de démarrer le paiement pour l'instant, réessaie."}), 500

    return redirect(payment_url)


@app.route('/abonnement/statut')
def abonnement_statut():
    ref = request.args.get('ref')
    if not ref:
        return jsonify({'erreur': 'Référence manquante.'}), 400
    paiement = get_paiement_par_ref(ref)
    if not paiement:
        return jsonify({'erreur': 'Paiement introuvable.'}), 404
    return jsonify({'statut': paiement['statut']})

@app.route('/mes-credits')
@eleve_requis
def mes_credits():
    eleve_id = session['eleve_id']

    try:
        eleve = get_eleve_par_id(eleve_id)
        if not eleve:
            session.pop('eleve_id', None)
            return redirect(url_for('connexion'))

        solde = get_solde(eleve_id)

        conn = database_credits.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT type, credits, cree_le
                FROM transactions_credits
                WHERE eleve_id = %s
                ORDER BY id DESC
                LIMIT 30
                """,
                (eleve_id,),
            )
            historique_brut = cur.fetchall()
        finally:
            conn.close()

        libelles_type = {
            'achat': 'Achat de crédits',
            'consommation': 'Question posée au tuteur',
            'reset_mensuel': 'Crédits gratuits du mois',
        }

        historique = [
            {
                'libelle': libelles_type.get(
                    ligne['type'],
                    ligne['type']
                ),
                'credits': ligne['credits'],
                'date': ligne['cree_le'],
            }
            for ligne in historique_brut
        ]

        return render_template(
            'mes_credits.html',
            eleve=eleve,
            solde=solde,
            historique=historique,
            prix_credit_fcfa=database_credits.PRIX_CREDIT_FCFA,
            credits_gratuits_mensuels=database_credits.CREDITS_GRATUITS_MENSUELS,
        )

    except Exception as e:
        app.logger.exception(
            f"Erreur page mes crédits pour élève {eleve_id}: {e}"
        )
        return render_template(
            '500.html'
        ), 500

# ══════════════════════════════════════════
# RECHARGE MANUELLE — ÉLÈVE (06/09/2026)
# ══════════════════════════════════════════

@app.route('/mes-credits/recharger', methods=['GET', 'POST'])
@eleve_requis
def recharger_credits():
    erreur = None

    if request.method == 'POST':
        token_soumis = request.form.get('csrf_token', '')
        token_attendu = session.get('csrf_token_recharge', '')
        if not token_attendu or not secrets.compare_digest(token_soumis, token_attendu):
            erreur = "Session expirée, réessaie."
        else:
            pack_id = request.form.get('pack_id', '')
            operateur = request.form.get('operateur', '')
            telephone_envoyeur = request.form.get('telephone_envoyeur', '').strip()
            reference_operateur = request.form.get('reference_operateur', '').strip()

            resultat = database_credits.demander_recharge(
                g.eleve['id'], pack_id, operateur, telephone_envoyeur, reference_operateur
            )

            if resultat['ok']:
                session.pop('csrf_token_recharge', None)
                return render_template('recharge_confirmation.html', eleve=g.eleve)
            else:
                erreur = resultat['erreur']

    session['csrf_token_recharge'] = secrets.token_urlsafe(32)
    return render_template(
        'recharge_credits.html',
        eleve=g.eleve,
        packs=database_credits.PACKS_RECHARGE,
        erreur=erreur,
        csrf_token=session['csrf_token_recharge'],
    )
@app.route('/sw.js')
def service_worker():
    reponse = send_file('static/sw.js', mimetype='application/javascript')
    reponse.headers['Cache-Control'] = 'no-cache'
    return reponse

@app.route('/.well-known/assetlinks.json')
def asset_links():
    return send_file('static/.well-known/assetlinks.json', mimetype='application/json')

@app.route('/admin/audit-sqlite-local')
@admin_requis
def audit_sqlite_local():
    import sqlite3
    from pathlib import Path

    resultat = {}
    # Cherche tous les fichiers .db sous le dossier de travail --
    # capture data/annales.db, data/rag_maths_bac_c/rag.db, et
    # tout autre fichier .db qu'on aurait oublié.
    for chemin_db in Path('.').rglob('*.db'):
        cle = str(chemin_db)
        try:
            conn = sqlite3.connect(chemin_db)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cur.fetchall()]

            detail_tables = {}
            for table in tables:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {table}")
                    detail_tables[table] = cur.fetchone()[0]
                except sqlite3.OperationalError as e:
                    detail_tables[table] = f"erreur: {e}"

            resultat[cle] = {
                'taille_octets': chemin_db.stat().st_size,
                'tables': detail_tables,
            }
            conn.close()
        except Exception as e:
            resultat[cle] = {'erreur': str(e)}

    return jsonify(resultat)
if __name__ == '__main__':
    app.run(debug=app.config['DEBUG'])