# app.py — ExamensCam — Version finale complète
import os
import re
import time
from functools import wraps
from dotenv import load_dotenv
load_dotenv()

from flask import (
    Flask, render_template, redirect, request, abort, jsonify,
    g, session,
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

creer_table_evenements()
app = Flask(__name__)

# ═══════════════════════════════════════════════════════
# CONFIGURATION & SECURITE
# ═══════════════════════════════════════════════════════
# Aucun fallback en dur pour les secrets. Un fallback visible dans le
# code (meme "juste pour le dev") devient un mot de passe public des
# qu'il finit sur GitHub. Si la variable d'env manque sur Render, le
# site DOIT refuser de demarrer plutot que de tourner avec un secret
# devine par n'importe qui.
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
    # Cookies de session -- protection du cookie admin_connecte.
    # SESSION_COOKIE_SECURE=True force le cookie a n'etre envoye que
    # sur HTTPS. Render sert le site en HTTPS, donc True en prod.
    # Mais en local (python app.py sur http://127.0.0.1, jamais
    # HTTPS), un navigateur refuse d'envoyer un cookie Secure sur une
    # connexion non chiffree -- le login semblerait "ne pas retenir"
    # la connexion. On desactive donc cette protection uniquement
    # quand DEBUG est actif (donc uniquement en local, jamais sur
    # Render ou DEBUG doit rester False).
    SESSION_COOKIE_SECURE=not _DEBUG,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
)

with app.app_context():
    create_table()

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
    return {'site_nom': 'ExamensCam'}


# ═══════════════════════════════════════════════════════
# RATE-LIMITING LOGIN ADMIN — en memoire, pas de dependance externe
# ═══════════════════════════════════════════════════════
# Structure : { ip: [timestamp_echec_1, timestamp_echec_2, ...] }
# Au-dela de MAX_TENTATIVES echecs dans la fenetre glissante de
# FENETRE_BLOCAGE_SEC, l'IP est bloquee jusqu'a expiration du plus
# ancien echec de la fenetre. Limite connue et acceptee : ce compteur
# se remet a zero si Render redemarre le process (redeploy, reveil
# apres veille sur le free tier) -- compromis correct pour un site
# mono-instance, pas une solution entreprise.
_TENTATIVES_LOGIN = {}
MAX_TENTATIVES = 5
FENETRE_BLOCAGE_SEC = 15 * 60


def _ip_client():
    # Render est derriere un proxy -- X-Forwarded-For contient la vraie IP.
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

@app.route('/')
def index():
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

@app.route('/bepc')
def bepc():
    return render_template('niveau.html', niveau='BEPC', serie=None,
                           matieres=get_matieres_fallback('BEPC'))

@app.route('/probatoire')
def probatoire():
    return render_template('probatoire_series.html')

@app.route('/probatoire/<serie>')
def probatoire_serie(serie):
    if serie not in SERIES_VALIDES:
        abort(404)
    return render_template('niveau.html', niveau='Probatoire', serie=serie,
                           matieres=get_matieres_fallback('Probatoire', serie))

@app.route('/bac')
def bac():
    return render_template('bac_series.html')

@app.route('/bac/<serie>')
def bac_serie(serie):
    if serie not in SERIES_VALIDES:
        abort(404)
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
    # La stack trace complete part dans les logs Render (comportement
    # normal de Flask, utile pour diagnostiquer) -- mais on ne renvoie
    # jamais ce detail au visiteur, meme si DEBUG passait a True par
    # accident un jour. Page generique uniquement, aucune info technique.
    app.logger.error(f"Erreur serveur non geree: {e}")
    return render_template('500.html'), 500

# ═══════════════════════════════════════
# CARREFOUR (2 branches V1 : officiel + établissements)
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


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    erreur = False
    bloque = False
    minutes_restantes = 0
    ip = _ip_client()

    if _login_bloque(ip):
        bloque = True
        minutes_restantes = _minutes_avant_deblocage(ip)
    elif request.method == 'POST':
        mot_de_passe = request.form.get('mot_de_passe', '')
        if mot_de_passe == app.config['ADMIN_TOKEN']:
            session['admin_connecte'] = True
            _TENTATIVES_LOGIN.pop(ip, None)
            return redirect('/admin/dashboard')
        else:
            _enregistrer_echec(ip)
            erreur = True
            if _login_bloque(ip):
                bloque = True
                minutes_restantes = _minutes_avant_deblocage(ip)

    return render_template('admin_login.html', erreur=erreur, bloque=bloque,
                            minutes_restantes=minutes_restantes)


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


if __name__ == '__main__':
    app.run(debug=app.config['DEBUG'])