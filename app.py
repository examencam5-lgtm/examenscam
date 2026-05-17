# app.py
# Application Flask principale — ExamensCam
# Maroua, Cameroun — 2026

import os
import urllib.parse
from pathlib import Path
from io import BytesIO
from datetime import datetime
import csv
import io

from flask import (
    Flask, render_template, redirect,
    url_for, request, abort, send_file
)

from database import (
    get_annales, get_matieres, get_all_annales,
    add_annale, delete_annale, increment_vues,
    get_stats, create_table, get_connection
)

from matieres import (
    get_matieres_catalogue,
    valider_combinaison,
    matieres_par_coefficient,
    get_series_disponibles
)

# ══════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════

app = Flask(__name__)

app.config.update(
    SECRET_KEY = os.environ.get('SECRET_KEY', 'SECRET_SUPPRIME_DE_LHISTORIQUE'),
    DEBUG = os.environ.get('DEBUG', 'True') == 'True',
    WHATSAPP_NUMERO = os.environ.get('WHATSAPP_NUMERO', '237 659929291'),
    ADMIN_TOKEN = os.environ.get('ADMIN_TOKEN', 'TOKEN_SUPPRIME_DE_LHISTORIQUE'),
)

SERIES_VALIDES = ['C', 'D', 'TI', 'A4']


# ══════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════


def verifier_token(token: str):
    """Bloque l'accès si le token admin est invalide."""
    if token != app.config['ADMIN_TOKEN']:
        abort(403)


@app.context_processor
def inject_globals():
    """Injecte les variables disponibles dans tous les templates."""
    return {
        'site_nom': 'ExamensCam',
    }


# ══════════════════════════════════════════
# ROUTES PUBLIQUES
# ══════════════════════════════════════════

@app.route('/')
def index():
    stats = get_stats()
    return render_template('index.html', stats=stats, total=stats['total'])
# Catalogue de secours — affiché si la base est vide
CATALOGUE = {
    'BEPC': ['Mathematiques', 'PCT', 'SVT', 
             'Français', 'Anglais', 'Histoire-Géo'],
    'Probatoire': {
        'C': ['Mathematiques', 'PCT', 'Philosophie', 
                'Français', 'Anglais'],
        'D': ['Mathematiques', 'PCT', 'SVT', 
                'Philosophie', 'Français', 'Anglais'],
        'TI': ['Mathematiques', 'PCT', 'Informatique',
                'Français', 'Anglais'],
        'A4': ['Philosophie', 'Français', 
                'Anglais', 'Histoire-Géo'],
    },
    'BAC': {
        'C': ['Mathematiques', 'PCT', 'SVT',
                'Philosophie', 'Français', 'Anglais'],
        'D': ['Mathematiques', 'PCT', 'SVT',
                'Philosophie', 'Français', 'Anglais'],
        'TI': ['Mathematiques', 'PCT', 'Informatique',
                'Philosophie', 'Français', 'Anglais'],
        'A4': ['Philosophie', 'Français',
                'Anglais', 'Histoire-Géo'],
    },
}


@app.route('/bepc')
def bepc():
    matieres = get_matieres('BEPC') or CATALOGUE['BEPC']
    return render_template('niveau.html',
                           niveau='BEPC',
                           serie=None,
                           matieres=matieres)


@app.route('/probatoire')
def probatoire():
    return render_template('probatoire_series.html')


@app.route('/probatoire/<serie>')
def probatoire_serie(serie):
    if serie not in SERIES_VALIDES:
        abort(404)
    matieres = get_matieres('Probatoire', serie) or \
               CATALOGUE['Probatoire'].get(serie, [])
    return render_template('niveau.html',
                           niveau='Probatoire',
                           serie=serie,
                           matieres=matieres)


@app.route('/bac')
def bac():
    return render_template('bac_series.html')


@app.route('/bac/<serie>')
def bac_serie(serie):
    if serie not in SERIES_VALIDES:
        abort(404)
    matieres = get_matieres('BAC', serie) or \
               CATALOGUE['BAC'].get(serie, [])
    return render_template('niveau.html',
                           niveau='BAC',
                           serie=serie,
                           matieres=matieres)


# ── ROUTE GÉNÉRIQUE SANS SÉRIE (BEPC) ────────────
@app.route('/annales/<niveau>/<matiere>')
def annales_sans_serie(niveau, matiere):
    annales = get_annales(niveau, matiere=matiere)
    return render_template('annales.html',
                           annales=annales,
                           niveau=niveau,
                           serie=None,
                           matiere=matiere,)


# ── ROUTE GÉNÉRIQUE AVEC SÉRIE (BAC + PROBATOIRE) ─
@app.route('/annales/<niveau>/<serie>/<matiere>')
def annales_avec_serie(niveau, serie, matiere):
    annales = get_annales(niveau, serie=serie, matiere=matiere)
    return render_template('annales.html',
                           annales=annales,
                           niveau=niveau,
                           serie=serie,
                           matiere=matiere,)


# ── TRACKING VUES ────────────────────────

@app.route('/voir/<int:annale_id>')
def voir_annale(annale_id):
    increment_vues(annale_id)
    return '', 204 # Réponse vide — appelé en AJAX depuis le template


# ══════════════════════════════════════════
# GÉNÉRATEUR D'EXAMENS
# ══════════════════════════════════════════

# Imports nécessaires pour le générateur
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
import sqlite3

EXERCICES_DB = Path('examenacam.db')
COULEUR_D = colors.HexColor('#145A32')
COULEUR_OR = colors.HexColor('#D4AC0D')


def _couverture(theme: str, serie: str, n: int) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    c.setFillColor(COULEUR_D)
    c.rect(0, h * 0.65, w, h * 0.35, fill=True, stroke=False)
    c.setStrokeColor(COULEUR_OR)
    c.setLineWidth(2)
    c.line(0, h * 0.65, w, h * 0.65)

    c.setFillColor(colors.white)
    c.setFont('Helvetica-Bold', 28)
    c.drawCentredString(w / 2, h * 0.82, 'ExamensCam')
    c.setFont('Helvetica', 12)
    c.drawCentredString(w / 2, h * 0.74, 'Examen d\'entraînement personnalisé')

    noms = {'fonctions': 'Fonctions', 'statistiques': 'Statistiques',
            'mix': 'Fonctions & Statistiques'}
    c.setFillColor(COULEUR_D)
    c.setFont('Helvetica-Bold', 20)
    c.drawCentredString(w / 2, h * 0.53,
                        f"BAC {serie} · {noms.get(theme, theme)}")

    c.setFillColor(colors.HexColor('#333333'))
    c.setFont('Helvetica', 14)
    c.drawCentredString(w / 2, h * 0.45,
                        f"{n} exercice{'s' if n > 1 else ''}")

    c.setFillColor(colors.HexColor('#777777'))
    c.setFont('Helvetica', 11)
    c.drawCentredString(w / 2, h * 0.38,
                        f"Généré le {datetime.now().strftime('%d/%m/%Y')}")

    c.setFillColor(COULEUR_D)
    c.rect(0, 0, w, 45, fill=True, stroke=False)
    c.setFillColor(colors.white)
    c.setFont('Helvetica', 9)
    c.drawCentredString(w / 2, 16, 'Énoncé gratuit — ExamensCam.cm')

    c.save()
    return buf.getvalue()


def _selectionner(theme: str, n: int) -> list:
    if not EXERCICES_DB.exists():
        return []
    conn = sqlite3.connect(EXERCICES_DB)
    conn.row_factory = sqlite3.Row
    if theme == 'mix':
        rows = conn.execute(
            'SELECT * FROM exercices ORDER BY RANDOM() LIMIT ?', (n,)
        ).fetchall()
    else:
        rows = conn.execute(
            'SELECT * FROM exercices WHERE theme = ? ORDER BY RANDOM() LIMIT ?',
            (theme, n)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _assembler(exercices: list, theme: str, serie: str) -> bytes:
    writer = PdfWriter()

    couv = PdfReader(BytesIO(_couverture(theme, serie, len(exercices))))
    writer.add_page(couv.pages[0])

    for ex in exercices:
        pdf_path = Path(ex['chemin_pdf'])
        if pdf_path.exists():
            for page in PdfReader(str(pdf_path)).pages:
                writer.add_page(page)

    out = BytesIO()
    writer.write(out)
    out.seek(0)
    return out.read()


@app.route('/generateur', methods=['GET', 'POST'])
def generateur():
    if request.method == 'GET':
        return render_template('generateur.html', message=None)

    theme = request.form.get('theme', 'fonctions')
    serie = request.form.get('serie', 'D')
    nombre = min(max(int(request.form.get('nombre', 5)), 1), 10)

    if theme not in ['fonctions', 'statistiques', 'mix']:
        return render_template('generateur.html',
                               message='Thème invalide.',
                               message_type='error')

    exercices = _selectionner(theme, nombre)
    if not exercices:
        return render_template('generateur.html',
                               message='Aucun exercice disponible pour ce thème.',
                               message_type='error')

    try:
        pdf_bytes = _assembler(exercices, theme, serie)
    except Exception as e:
        return render_template('generateur.html',
                               message=f'Erreur génération : {e}',
                               message_type='error')

    nom = f"ExamensCam_BAC{serie}_{theme}_{datetime.now().strftime('%Y%m%d')}.pdf"
    return send_file(BytesIO(pdf_bytes), mimetype='application/pdf',
                     as_attachment=True, download_name=nom)


# ══════════════════════════════════════════
# ROUTES ADMIN
# ══════════════════════════════════════════

import csv
import io
from flask import send_file as flask_send_file


# ── HELPER DRIVE ─────────────────────────────────────

def convertir_lien_drive(url: str) -> str:
    """
    Convertit n'importe quel lien Drive en lien embed (preview).
    Fonctionne avec tous les formats Drive courants.
    """
    import re
    if not url:
        return url

    patterns = [
        r'/file/d/([a-zA-Z0-9_-]+)',
        r'id=([a-zA-Z0-9_-]+)',
        r'/d/([a-zA-Z0-9_-]+)/',
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            file_id = match.group(1)
            return f"https://drive.google.com/file/d/{file_id}/preview"

    return url # Retourner tel quel si pas reconnu


# ── DASHBOARD ADMIN ──────────────────────────────────

@app.route('/admin/<token>', methods=['GET', 'POST'])
def admin(token):
    verifier_token(token)
    message = None
    csv_message = None

    if request.method == 'POST':
        try:
            niveau = request.form.get('niveau', '').strip()
            serie = request.form.get('serie', '').strip() or None
            matiere = request.form.get('matiere', '').strip()
            annee = int(request.form.get('annee', 0))
            lien_drive = convertir_lien_drive(
                            request.form.get('lien_drive', '').strip())
            corrige_dispo = 'corrige_dispo' in request.form
            lien_corrige = convertir_lien_drive(
                            request.form.get('lien_corrige', '').strip()) or None
            source = request.form.get('source', 'inconnu')

            if not niveau:
                message = "❌ Le niveau est obligatoire."
            elif not matiere:
                message = "❌ La matière est obligatoire."
            elif not (1990 <= annee <= 2030):
                message = "❌ Année invalide (1990–2030)."
            elif not lien_drive:
                message = "❌ Le lien Google Drive est obligatoire."
            else:
                new_id = add_annale(
                    niveau=niveau, serie=serie, matiere=matiere,
                    annee=annee, lien_drive=lien_drive,
                    corrige_dispo=corrige_dispo,
                    lien_corrige=lien_corrige, source=source
                )
                message = (f"✅ Annale ajoutée — ID {new_id}"
                           if new_id > 0
                           else "❌ Erreur lors de l'ajout.")

        except ValueError:
            message = "❌ Année invalide."
        except Exception as e:
            message = f"❌ Erreur : {str(e)}"

    annales = get_all_annales()
    stats = get_stats()

    return render_template('admin.html',
                           token=token,
                           message=message,
                           csv_message=csv_message,
                           annales=annales,
                           stats=stats)


# ── SUPPRESSION UNITAIRE ─────────────────────────────

@app.route('/admin/<token>/supprimer/<int:annale_id>')
def admin_supprimer(token, annale_id):
    verifier_token(token)
    delete_annale(annale_id)
    return redirect(url_for('admin', token=token))


# ── SUPPRESSION MULTIPLE ─────────────────────────────

@app.route('/admin/<token>/supprimer-multiple', methods=['POST'])
def admin_supprimer_multiple(token):
    verifier_token(token)

    ids = request.form.getlist('ids')
    count = 0

    for annale_id in ids:
        try:
            delete_annale(int(annale_id))
            count += 1
        except Exception as e:
            print(f"❌ Erreur suppression {annale_id} : {e}")

    print(f"✅ {count} annales supprimées")
    return redirect(url_for('admin', token=token))


# ── IMPORT CSV ───────────────────────────────────────

@app.route('/admin/<token>/import-csv', methods=['POST'])
def admin_import_csv(token):
    verifier_token(token)

    fichier = request.files.get('csv_file')

    if not fichier or fichier.filename == '':
        return render_template('admin.html',
                               token=token,
                               csv_message="❌ Aucun fichier sélectionné.",
                               annales=get_all_annales(),
                               stats=get_stats())

    try:
        content = fichier.read().decode('utf-8-sig') # utf-8-sig gère le BOM Excel
        reader = csv.DictReader(io.StringIO(content))

        count_ok = 0
        count_err = 0
        erreurs = []

        for i, row in enumerate(reader, start=2):
            try:
                niveau = row.get('niveau', '').strip()
                serie = row.get('serie', '').strip() or None
                matiere = row.get('matiere', '').strip()
                annee_str = row.get('annee', '').strip()
                lien_drive = convertir_lien_drive(row.get('lien_drive', '').strip())
                corrige = row.get('corrige_dispo', '0').strip() in ('1', 'oui', 'yes', 'true')
                source = row.get('source', 'inconnu').strip()

                if not all([niveau, matiere, annee_str, lien_drive]):
                    erreurs.append(f"Ligne {i} : champs obligatoires manquants")
                    count_err += 1
                    continue

                annee = int(annee_str)

                new_id = add_annale(
                    niveau=niveau, serie=serie, matiere=matiere,
                    annee=annee, lien_drive=lien_drive,
                    corrige_dispo=corrige, source=source
                )

                if new_id > 0:
                    count_ok += 1
                else:
                    count_err += 1

            except ValueError:
                erreurs.append(f"Ligne {i} : année invalide ({row.get('annee')})")
                count_err += 1
            except Exception as e:
                erreurs.append(f"Ligne {i} : {str(e)}")
                count_err += 1

        if erreurs:
            msg = f"✅ {count_ok} importées · ❌ {count_err} erreurs : {' | '.join(erreurs[:3])}"
        else:
            msg = f"✅ {count_ok} annales importées avec succès !"

    except Exception as e:
        msg = f"❌ Erreur lecture fichier : {str(e)}"

    return render_template('admin.html',
                           token=token,
                           csv_message=msg,
                           message=None,
                           annales=get_all_annales(),
                           stats=get_stats())


# ── TEMPLATE CSV À TÉLÉCHARGER ───────────────────────

@app.route('/admin/<token>/template-csv')
def admin_template_csv(token):
    verifier_token(token)

    contenu = """niveau,serie,matiere,annee,lien_drive,corrige_dispo,source
BEPC,,Mathematiques,2023,https://drive.google.com/file/d/TON_ID/preview,0,sujetexa
BEPC,,PCT,2022,https://drive.google.com/file/d/TON_ID/preview,0,mongosukulu
BAC,C,Mathematiques,2023,https://drive.google.com/file/d/TON_ID/preview,0,sujetexa
BAC,C,PCT,2022,https://drive.google.com/file/d/TON_ID/preview,1,muhammad
BAC,D,Mathematiques,2023,https://drive.google.com/file/d/TON_ID/preview,0,sujetexa
BAC,D,SVT,2021,https://drive.google.com/file/d/TON_ID/preview,0,orniformation
Probatoire,C,Mathematiques,2022,https://drive.google.com/file/d/TON_ID/preview,0,sujetexa
Probatoire,D,SVT,2023,https://drive.google.com/file/d/TON_ID/preview,0,mongosukulu
"""

    buffer = io.BytesIO(contenu.encode('utf-8'))
    buffer.seek(0)

    return flask_send_file(
        buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name='modele_import_examenscam.csv'
    )



# ══════════════════════════════════════════
# ERREURS
# ══════════════════════════════════════════

@app.errorhandler(404)
def page_non_trouvee(e):
    return render_template('404.html'), 404

@app.errorhandler(403)
def acces_interdit(e):
    return render_template('403.html'), 403



# ═══════════════════════════════════════════════════════
# ROUTES PAIEMENT — À ajouter dans app.py
# Avant le bloc : if __name__ == '__main__':
# ═══════════════════════════════════════════════════════

# ── PAGE CORRIGÉS ────────────────────────────────────

@app.route('/corriges')
def corriges():
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM annales
        WHERE corrige_dispo = 1 AND actif = 1
        ORDER BY niveau, serie, matiere, annee DESC
    """).fetchall()
    conn.close()
    corriges = [dict(r) for r in rows]
    return render_template('corriges.html', corriges=corriges)


# ── PAGE PAIEMENT ────────────────────────────────────

@app.route('/paiement/<int:annale_id>', methods=['GET', 'POST'])
def paiement(annale_id):
    from database import get_annale_by_id

    annale = get_annale_by_id(annale_id)

    if not annale:
        abort(404)

    # Vérifier que cet annale a bien un corrigé
    if not annale.get('corrige_dispo'):
        return render_template('paiement.html',
                               annale=annale,
                               paiement_actif=False)

    if request.method == 'GET':
        return render_template('paiement.html',
                               annale=annale,
                               paiement_actif=True)

    # ── POST : initier le paiement ──────────────────
    telephone = request.form.get('telephone', '').strip()
    methode = request.form.get('methode', 'mtn')

    if not telephone or len(telephone) != 9:
        return render_template('paiement.html',
                               annale=annale,
                               paiement_actif=True,
                               erreur="Numéro invalide — 9 chiffres requis.")

    # Phase MVP : enregistrer la transaction en attente
    # Phase 2 : appel API CinetPay / Flutterwave ici
    conn = get_connection()
    cursor = conn.execute("""
        INSERT INTO transactions
            (annale_id, telephone, methode, montant, statut, date_creation)
        VALUES (?, ?, ?, ?, 'en_attente', datetime('now'))
    """, (annale_id, f"237{telephone}", methode, 1000))
    transaction_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # Rediriger vers page de confirmation
    return redirect(url_for('paiement_confirmation',
                            transaction_id=transaction_id))


# ── CONFIRMATION ─────────────────────────────────────

@app.route('/paiement/confirmation/<int:transaction_id>')
def paiement_confirmation(transaction_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM transactions WHERE id = ?",
        (transaction_id,)
    ).fetchone()
    conn.close()

    if not row:
        abort(404)

    transaction = dict(row)
    return render_template('paiement_confirmation.html',
                           transaction=transaction)


# ── WEBHOOK CINETPAY (Phase 2) ────────────────────────
# Décommente quand CinetPay est configuré

# @app.route('/webhook/cinetpay', methods=['POST'])
# def webhook_cinetpay():
# data = request.json
# if data.get('status') == 'ACCEPTED':
# transaction_id = data.get('metadata', {}).get('transaction_id')
# if transaction_id:
# conn = get_connection()
# conn.execute("""
# UPDATE transactions SET statut = 'confirme'
# WHERE id = ?
# """, (transaction_id,))
# conn.commit()
# conn.close()
# return '', 200




# ══════════════════════════════════════════
# LANCEMENT
# ══════════════════════════════════════════

if __name__ == '__main__':
    create_table() # Crée la BDD si elle n'existe pas
    app.run(debug=app.config['DEBUG'])

