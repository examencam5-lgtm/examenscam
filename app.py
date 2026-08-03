# app.py — ExamensCam — Version finale complète
import os, csv, io, re, sqlite3
from pathlib import Path
from io import BytesIO
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, abort, send_file, jsonify
from database_carrefour import get_carrefour
from database_blanches import get_epreuves_blanches, get_regions_disponibles
from database_matieres import get_toutes_matieres
from database_corriges import get_pack_detail, get_packs_catalogue
from database_externes import (
    get_matieres_externes, get_annales_externes, get_annale_externe_by_id,
    increment_vue_externe, get_annees_disponibles, get_sequences_disponibles
)
from database import (get_annales, get_matieres, get_all_annales, add_annale,
                      delete_annale, increment_vues, get_stats, get_connection,
                      get_annale_by_id, create_table, get_total_blancs,
                      get_derniere_maj)  
from database_search import rechercher, enregistrer_recherche_infructueuse
app = Flask(__name__)
app.config.update(
    SECRET_KEY = os.environ.get('SECRET_KEY', 'SECRET_SUPPRIME_DE_LHISTORIQUE'),
    DEBUG = os.environ.get('DEBUG', 'True') == 'True',
    ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'TOKEN_SUPPRIME_DE_LHISTORIQUE'),
)

with app.app_context():
    create_table()

SERIES_VALIDES = ['C', 'D', 'TI', 'A4']

CATALOGUE = {
    'BEPC': ['Mathematiques','Physique','Chimie','SVT','Français','Anglais','Histoire-Géo'],
    'Probatoire': {
        'C': ['Mathematiques','Physique','Chimie','Philosophie','Français','Anglais'],
        'D': ['Mathematiques','Physique','Chimie','SVT','Philosophie','Français','Anglais'],
        'TI': ['Mathematiques','Physique','Chimie','Informatique','Philosophie','Français','Anglais'],
        'A4': ['Philosophie','Français','Anglais','Histoire-Géo'],
    },
    'Probatoire Blanc': {
        'C': ['Mathematiques','Physique','Chimie','Philosophie','Français','Anglais'],
        'D': ['Mathematiques','Physique','Chimie','SVT','Philosophie','Français','Anglais'],
        'TI': ['Mathematiques','Physique','Chimie','Informatique','Français','Anglais'],
        'A4': ['Philosophie','Français','Anglais','Histoire-Géo'],
    },
    'BAC': {
        'C': ['Mathematiques','Physique','Chimie','SVT','Philosophie','Français','Anglais'],
        'D': ['Mathematiques','Physique','Chimie','SVT','Philosophie','Français','Anglais'],
        'TI': ['Mathematiques','Physique','Chimie','Informatique','Dessin Industriel','Philosophie','Français','Anglais'],
        'A4': ['Philosophie','Français','Anglais','Histoire-Géo','Latin','Economie'],
    },
    'BAC Blanc': {
        'C': ['Mathematiques','Physique','Chimie','SVT','Philosophie','Français','Anglais'],
        'D': ['Mathematiques','Physique','Chimie','SVT','Philosophie','Français','Anglais'],
        'TI': ['Mathematiques','Physique','Chimie','Informatique','Français','Anglais'],
        'A4': ['Philosophie','Français','Anglais','Histoire-Géo'],
    },
}

# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════

def convertir_lien_drive(url):
    if not url or not url.strip():
        return url
    url = url.strip()
    for p in [r'/file/d/([a-zA-Z0-9_-]+)', r'id=([a-zA-Z0-9_-]+)', r'/d/([a-zA-Z0-9_-]+)/']:
        m = re.search(p, url)
        if m:
            return f"https://drive.google.com/file/d/{m.group(1)}/preview"
    return url

def verifier_token(token):
    if token != app.config['ADMIN_TOKEN']:
        abort(403)

# À AJOUTER dans app.py, en haut avec les autres imports :
#     from database_matieres import get_toutes_matieres
#
# PUIS remplacer la fonction get_matieres_fallback existante par celle-ci :

def get_matieres_fallback(niveau, serie=None):
    # Priorite : matieres reellement presentes en base, croisees sur
    # les 3 tables (annales officielles + blanches + etablissements).
    # Avant, seule 'annales' etait consultee -- un eleve BEPC ne
    # voyait que Maths/PCT alors que ~870 epreuves d'etablissement
    # existaient deja pour d'autres matieres, invisibles sans passer
    # par la recherche.
    m = get_toutes_matieres(niveau, serie)
    if m:
        return m
    # Repli sur l'ancien comportement (annales seule, puis CATALOGUE
    # statique) si les 3 tables ne renvoient vraiment rien -- garde
    # une securite pour ne rien casser sur un niveau/serie tres vide
    m = get_matieres(niveau, serie)
    if m:
        return m
    if serie:
        return CATALOGUE.get(niveau, {}).get(serie, [])
    return CATALOGUE.get(niveau, [])

@app.context_processor
def inject_globals():
    return {'site_nom': 'ExamensCam'}

# ══════════════════════════════════════════
# ROUTES PRINCIPALES
# ══════════════════════════════════════════

@app.route('/')
def index():
    stats = get_stats()
    total_blancs = get_total_blancs()
    derniere_maj = get_derniere_maj()
    return render_template('index.html', stats=stats, total=stats['total'], total_blancs=total_blancs, derniere_maj=derniere_maj)

# A ajouter dans app.py, avec tes autres routes.
# Zero dependance backend : le texte est directement dans le
# template, cette route se contente de le rendre.

@app.route('/conditions')
def conditions():
    return render_template('conditions.html')
# A ajouter dans app.py, avec tes autres routes.

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
    blancs = get_annales('BEPC', matiere=matiere, type_sujet='blanc')
    return render_template('choix_type.html',
        niveau='BEPC', serie=None, matiere=matiere,
        nb_officiels=len(officiels),
        nb_blancs=len(blancs),
        nb_corriges=len([a for a in officiels + blancs if a.get('corrige_dispo')]),
        url_off_enonces=f'/annales/BEPC/{matiere}/officiel/enonces',
        url_off_corriges=f'/annales/BEPC/{matiere}/officiel/corriges',
        url_blanc_enonces=f'/annales/BEPC/{matiere}/blanc/enonces',
        url_blanc_corriges=f'/annales/BEPC/{matiere}/blanc/corriges')

@app.route('/probatoire/<serie>/<matiere>')
def probatoire_choix(serie, matiere):
    if serie not in SERIES_VALIDES:
        abort(404)
    officiels = get_annales('Probatoire', serie=serie, matiere=matiere, type_sujet='officiel')
    blancs = get_annales('Probatoire', serie=serie, matiere=matiere, type_sujet='blanc')
    return render_template('choix_type.html',
        niveau='Probatoire', serie=serie, matiere=matiere,
        nb_officiels=len(officiels),
        nb_blancs=len(blancs),
        nb_corriges=len([a for a in officiels + blancs if a.get('corrige_dispo')]),
        url_off_enonces=f'/annales/Probatoire/{serie}/{matiere}/officiel/enonces',
        url_off_corriges=f'/annales/Probatoire/{serie}/{matiere}/officiel/corriges',
        url_blanc_enonces=f'/annales/Probatoire/{serie}/{matiere}/blanc/enonces',
        url_blanc_corriges=f'/annales/Probatoire/{serie}/{matiere}/blanc/corriges')


@app.route('/bac/<serie>/<matiere>')
def bac_choix(serie, matiere):
    if serie not in SERIES_VALIDES:
        abort(404)
    officiels = get_annales('BAC', serie=serie, matiere=matiere, type_sujet='officiel')
    blancs = get_annales('BAC', serie=serie, matiere=matiere, type_sujet='blanc')
    return render_template('choix_type.html',
        niveau='BAC', serie=serie, matiere=matiere,
        nb_officiels=len(officiels),
        nb_blancs=len(blancs),
        nb_corriges=len([a for a in officiels + blancs if a.get('corrige_dispo')]),
        url_off_enonces=f'/annales/BAC/{serie}/{matiere}/officiel/enonces',
        url_off_corriges=f'/annales/BAC/{serie}/{matiere}/officiel/corriges',
        url_blanc_enonces=f'/annales/BAC/{serie}/{matiere}/blanc/enonces',
        url_blanc_corriges=f'/annales/BAC/{serie}/{matiere}/blanc/corriges')

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



@app.route('/generateur', methods=['GET', 'POST'])
def generateur():
    return render_template('generateur.html', message=None)

# ══════════════════════════════════════════
# PAIEMENT
# ══════════════════════════════════════════

@app.route('/paiement/<int:annale_id>', methods=['GET', 'POST'])
def paiement(annale_id):
    annale = get_annale_by_id(annale_id)
    if not annale:
        abort(404)
    if not annale.get('corrige_dispo'):
        return render_template('paiement.html', annale=annale, paiement_actif=False)
    if request.method == 'GET':
        return render_template('paiement.html', annale=annale, paiement_actif=True)
    telephone = request.form.get('telephone', '').strip()
    methode = request.form.get('methode', 'mtn')
    if not telephone or len(telephone) != 9:
        return render_template('paiement.html', annale=annale,
                               paiement_actif=True, erreur="Numéro invalide.")
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO transactions
            (annale_id, telephone, methode, montant, statut, date_creation)
        VALUES (?, ?, ?, 1000, 'en_attente', datetime('now'))
    """, (annale_id, f"237{telephone}", methode))
    tid = cursor.lastrowid
    conn.commit()
    conn.close()
    return redirect(url_for('paiement_confirmation', transaction_id=tid))

@app.route('/paiement/confirmation/<int:transaction_id>')
def paiement_confirmation(transaction_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM transactions WHERE id=?", (transaction_id,)
    ).fetchone()
    conn.close()
    if not row:
        abort(404)
    return render_template('paiement_confirmation.html', transaction=dict(row))

# ══════════════════════════════════════════
# ADMIN
# ══════════════════════════════════════════

@app.route('/admin/<token>', methods=['GET', 'POST'])
def admin(token):
    verifier_token(token)
    message = None
    if request.method == 'POST':
        try:
            niveau = request.form.get('niveau', '').strip()
            serie = request.form.get('serie', '').strip() or None
            matiere = request.form.get('matiere', '').strip()
            annee = int(request.form.get('annee', 0))
            lien_drive = convertir_lien_drive(request.form.get('lien_drive', '').strip())
            corrige_dispo = 'corrige_dispo' in request.form
            lien_corrige = convertir_lien_drive(request.form.get('lien_corrige', '').strip()) or None
            source = request.form.get('source', 'inconnu')
            if not niveau:
                message = "❌ Niveau obligatoire."
            elif not matiere:
                message = "❌ Matière obligatoire."
            elif not (1990 <= annee <= 2030):
                message = "❌ Année invalide."
            elif not lien_drive:
                message = "❌ Lien Drive obligatoire."
            else:
                nid = add_annale(niveau=niveau, serie=serie, matiere=matiere,
                                 annee=annee, lien_drive=lien_drive,
                                 corrige_dispo=corrige_dispo,
                                 lien_corrige=lien_corrige, source=source)
                message = f"✅ Annale ajoutée — ID {nid}" if nid > 0 else "❌ Erreur ajout."
        except Exception as e:
            message = f"❌ Erreur : {e}"
    return render_template('admin.html', token=token, message=message,
                           csv_message=None, annales=get_all_annales(),
                           stats=get_stats())

@app.route('/admin/<token>/supprimer/<int:annale_id>')
def admin_supprimer(token, annale_id):
    verifier_token(token)
    delete_annale(annale_id)
    return redirect(url_for('admin', token=token))

@app.route('/admin/<token>/supprimer-multiple', methods=['POST'])
def admin_supprimer_multiple(token):
    verifier_token(token)
    for aid in request.form.getlist('ids'):
        try:
            delete_annale(int(aid))
        except Exception:
            pass
    return redirect(url_for('admin', token=token))

@app.route('/admin/<token>/masse', methods=['GET', 'POST'])
def admin_masse(token):
    verifier_token(token)
    message = None
    count = 0
    if request.method == 'POST':
        niveau = request.form.get('niveau', '').strip()
        serie = request.form.get('serie', '').strip() or None
        matiere = request.form.get('matiere', '').strip()
        source = request.form.get('source', 'inconnu')
        corrige_dispo = 'corrige_dispo' in request.form
        annee_debut = int(request.form.get('annee_debut', 2025))
        liens = [l.strip() for l in
                 request.form.get('liens_drive', '').strip().splitlines()
                 if l.strip()]
        if not liens:
            message = "❌ Aucun lien détecté."
        elif not niveau or not matiere:
            message = "❌ Niveau et matière obligatoires."
        else:
            annee_courante = annee_debut
            for lien in liens:
                try:
                    nid = add_annale(niveau=niveau, serie=serie, matiere=matiere,
                                     annee=annee_courante,
                                     lien_drive=convertir_lien_drive(lien),
                                     corrige_dispo=corrige_dispo, source=source)
                    if nid > 0:
                        count += 1
                    annee_courante -= 1
                except Exception as e:
                    print(f"Erreur: {e}")
            message = f"✅ {count} annales ajoutées ({annee_debut} → {annee_courante+1})"
    return render_template('admin_masse.html', token=token,
                           message=message, count=count)

@app.route('/admin/<token>/import-csv', methods=['POST'])
def admin_import_csv(token):
    verifier_token(token)
    fichier = request.files.get('csv_file')
    if not fichier or not fichier.filename:
        msg = "❌ Aucun fichier."
    else:
        try:
            content = fichier.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(content))
            ok = err = 0
            for row in reader:
                try:
                    nid = add_annale(
                        niveau=row.get('niveau', '').strip(),
                        serie=row.get('serie', '').strip() or None,
                        matiere=row.get('matiere', '').strip(),
                        annee=int(row.get('annee', 0)),
                        lien_drive=convertir_lien_drive(row.get('lien_drive', '').strip()),
                        corrige_dispo=row.get('corrige_dispo', '0').strip() in ('1', 'oui', 'yes', 'true'),
                        source=row.get('source', 'inconnu').strip())
                    if nid > 0:
                        ok += 1
                    else:
                        err += 1
                except Exception:
                    err += 1
            msg = f"✅ {ok} importées · ❌ {err} erreurs"
        except Exception as e:
            msg = f"❌ Erreur : {e}"
    return render_template('admin.html', token=token, message=None,
                           csv_message=msg, annales=get_all_annales(),
                           stats=get_stats())

@app.route('/admin/<token>/template-csv')
def admin_template_csv(token):
    verifier_token(token)
    contenu = (
        "niveau,serie,matiere,annee,lien_drive,corrige_dispo,source\n"
        "BEPC,,Mathematiques,2023,https://drive.google.com/file/d/TON_ID/preview,0,sujetexa\n"
        "BAC,C,Mathematiques,2023,https://drive.google.com/file/d/TON_ID/preview,0,sujetexa\n"
    )
    buf = io.BytesIO(contenu.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, mimetype='text/csv', as_attachment=True,
                     download_name='modele_examenscam.csv')

@app.route('/api/admin/ajouter', methods=['POST'])
def api_admin_ajouter():
    if request.form.get('token', '') != app.config['ADMIN_TOKEN']:
        return 'Unauthorized', 403
    try:
        nid = add_annale(
            niveau=request.form.get('niveau', '').strip(),
            serie=request.form.get('serie', '').strip() or None,
            matiere=request.form.get('matiere', '').strip(),
            annee=int(request.form.get('annee', 0)),
            lien_drive=convertir_lien_drive(request.form.get('lien_drive', '').strip()),
            corrige_dispo=request.form.get('corrige_dispo', '0') == '1',
            source=request.form.get('source', 'inconnu'))
        return ('OK', 200) if nid > 0 else ('Error', 500)
    except Exception as e:
        return str(e), 500
    # Redirections compatibilité anciens liens
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
# ═══════════════════════════════════════
# CARREFOUR (5 branches)
# ═══════════════════════════════════════
@app.route('/carrefour/<niveau>/<matiere>')
def carrefour_niveau(niveau, matiere):
    serie = request.args.get('serie')
    data = get_carrefour(niveau, matiere, serie=serie)
    return render_template('carrefour.html', niveau=niveau, serie=serie, matiere=matiere, data=data)


# ═══════════════════════════════════════
# EXAMENS BLANCS
# ═══════════════════════════════════════

@app.route('/blancs/<niveau>/<serie>/<matiere>')
def blancs_liste(niveau, serie, matiere):
    serie_reelle = None if serie == 'na' else serie
    region = request.args.get('region')
    epreuves = get_epreuves_blanches(niveau, matiere, serie=serie_reelle, region=region)
    regions = get_regions_disponibles(niveau, matiere, serie=serie_reelle)
    return render_template('blancs_liste.html', niveau=niveau, serie=serie_reelle,
                            matiere=matiere, epreuves=epreuves,
                            regions_disponibles=regions, region_active=region)


@app.route('/voir-blanc/<int:epreuve_id>')
def voir_blanche(epreuve_id):
    from database_blanches import get_connection
    conn = get_connection()
    epreuve = conn.execute(
        "SELECT * FROM annales_blanches WHERE id=? AND actif=1", (epreuve_id,)
    ).fetchone()
    conn.close()
    if not epreuve:
        return "Épreuve introuvable", 404
    return render_template('voir_blanche.html', epreuve=epreuve)

# ═══════════════════════════════════════
# CORRIGÉS (officiel + blanc)
# ═══════════════════════════════════════

@app.route('/corriges')
def corriges_catalogue():
    packs = get_packs_catalogue()
    return render_template('corriges_catalogue.html', packs=packs)


@app.route('/corriges/<niveau>/<serie>/<matiere>')
def corriges_fiche(niveau, serie, matiere):
    # TODO : remplacer par une vraie recherche de pack par niveau/serie/matiere
    # (get_pack_par_matiere existe déjà dans database_corriges.py)
    from database_corriges import get_pack_par_matiere
    serie_reelle = None if serie == 'na' else serie
    pack_resume = get_pack_par_matiere(niveau, serie_reelle, matiere)
    if not pack_resume:
        return "Pack introuvable", 404
    pack = get_pack_detail(pack_resume['id'])
    return render_template('corriges_fiche.html', pack=pack)


@app.route('/corriges-blancs/<niveau>/<serie>/<matiere>')
def corriges_fiche_blanc(niveau, serie, matiere):
    return "Page en construction", 200


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
    # Decision strategique (doc section 4.1) : on redirige vers la page
    # article, jamais vers le PDF direct — neutralite envers la source
    # tierce + coherence avec la CGU (indexation de metadonnees, pas
    # d'hebergement). lien_page_source contient la page article ;
    # lien_externe contient le PDF direct et ne doit jamais etre expose.
    return redirect(entree['lien_page_source'])


# À AJOUTER dans app.py
# ═══════════════════════════════════════
# RECHERCHE UNIFIEE — autocompletion "mini Google" (doc section 3)
# ═══════════════════════════════════════
#
# Ajoute cet import en haut de app.py :
#   from database_search import rechercher, enregistrer_recherche_infructueuse
#
# Puis colle la route ci-dessous avec tes autres routes.


@app.route('/api/search')
def api_search():
    q = request.args.get('q', '').strip()
    niveau = request.args.get('niveau') or None
    matiere = request.args.get('matiere') or None

    if len(q) < 2:
        return jsonify({'resultats': [], 'suggestions': []})

    from database_search import rechercher_avec_scoring
    reponse = rechercher_avec_scoring(q, limite=8, niveau=niveau, matiere=matiere)
    
    resultats = reponse['resultats']
    suggestions = reponse['suggestions']

    if not resultats and len(q) >= 3:
        enregistrer_recherche_infructueuse(q)

    return jsonify({
        'resultats': resultats,
        'suggestions': suggestions
    })
    
if __name__ == '__main__':
    app.run(debug=app.config['DEBUG'])

