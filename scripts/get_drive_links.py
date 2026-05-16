# scripts/pipeline_master.py
"""
Pipeline maître ExamensCam — une commande pour tout faire.

Usage :
    python scripts/pipeline_master.py --niveau Probatoire --serie C --matiere Mathematiques --drive FOLDER_ID
    python scripts/pipeline_master.py --niveau BEPC --serie NA --matiere Mathematiques --drive FOLDER_ID
    python scripts/pipeline_master.py --niveau BAC --serie C --matiere Mathematiques --drive FOLDER_ID
"""
import sys
import os
import re
import json
import shutil
import argparse
import subprocess
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from database import get_connection
from pdf_pipeline.remove_watermark import nettoyer_pdf
from pdf_pipeline.generate_title import generate_footer_overlay
from pdf_pipeline.merge_pdfs import merge_title_with_annale

# ── Configuration ─────────────────────────────────────────────────
API_KEY = 'AlzaSyCx3pL4X8wvF8LGm0d33GOSITSW62SCYpQ' # Remplace par ta vraie clé

DOSSIER_RAW = Path('data/raw')
DOSSIER_CLEAN = Path('data/clean')
DOSSIER_TITRES = Path('data/titres')
DOSSIER_FINAL = Path('data/final')
DOSSIER_PDFS = Path('data/pdfs')

# ── Utilitaires ───────────────────────────────────────────────────

def extraire_annee(nom: str) -> int:
    """Extrait l'année depuis un nom de fichier."""
    matches = re.findall(r'\b(19|20)\d{2}\b', nom)
    return int(matches[0] + matches[0][2:]) if matches else None

def extraire_annee_v2(nom: str) -> int:
    """Version robuste — cherche un nombre à 4 chiffres."""
    parties = re.findall(r'\d{4}', nom)
    for p in parties:
        if 1990 <= int(p) <= 2030:
            return int(p)
    return None

def get_drive_files(folder_id: str) -> list:
    """Récupère tous les fichiers d'un dossier Drive public."""
    url = (
        f'https://www.googleapis.com/drive/v3/files'
        f'?q=%27{folder_id}%27+in+parents'
        f'&key={API_KEY}'
        f'&fields=files(id,name)'
        f'&pageSize=100'
    )
    try:
        req = urllib.request.urlopen(url, timeout=15)
        data = json.loads(req.read())
        return data.get('files', [])
    except Exception as e:
        print(f" ⚠️ Drive API erreur : {e}")
        return []

# ── Étapes du pipeline ────────────────────────────────────────────

def etape1_nettoyer(niveau, serie, matiere):
    """Nettoie tous les PDFs de data/raw/"""
    print("\n📋 ÉTAPE 1 — Nettoyage des filigranes")
    DOSSIER_CLEAN.mkdir(parents=True, exist_ok=True)

    pdfs = list(DOSSIER_RAW.glob('*.pdf'))
    print(f" {len(pdfs)} PDF(s) trouvé(s) dans data/raw/")

    resultats = []
    for pdf in pdfs:
        sortie = DOSSIER_CLEAN / pdf.name
        if nettoyer_pdf(str(pdf), str(sortie)):
            resultats.append(pdf)

    print(f" ✅ {len(resultats)} PDF(s) nettoyé(s)")
    return resultats

def etape2_personnaliser(niveau, serie, matiere):
    """Génère footer + fusionne pour tous les PDFs clean"""
    print("\n📋 ÉTAPE 2 — Personnalisation ExamensCam")
    DOSSIER_TITRES.mkdir(parents=True, exist_ok=True)
    DOSSIER_FINAL.mkdir(parents=True, exist_ok=True)

    serie_str = serie if serie and serie != 'NA' else None
    pdfs = list(DOSSIER_CLEAN.glob('*.pdf'))
    resultats = []

    for pdf in pdfs:
        annee = extraire_annee_v2(pdf.stem)
        if not annee:
            print(f" ⚠️ Année non détectée : {pdf.name}")
            continue

        titre_path = DOSSIER_TITRES / f"{pdf.stem}_footer.pdf"
        final_path = DOSSIER_FINAL / pdf.name

        generate_footer_overlay(str(titre_path), niveau, serie_str, matiere, annee)
        if merge_title_with_annale(str(titre_path), str(pdf), str(final_path)):
            resultats.append((annee, final_path))

    print(f" ✅ {len(resultats)} PDF(s) finalisé(s)")
    return resultats

def etape3_importer_base(niveau, serie, matiere):
    """Importe tous les PDFs finaux en base SQLite"""
    print("\n📋 ÉTAPE 3 — Import en base de données")
    DOSSIER_PDFS.mkdir(parents=True, exist_ok=True)

    serie_db = serie if serie and serie != 'NA' else None
    conn = get_connection()
    pdfs = list(DOSSIER_FINAL.glob('*.pdf'))
    ajoutes = 0

    for pdf in pdfs:
        annee = extraire_annee_v2(pdf.stem)
        if not annee:
            continue

        # Vérifier si déjà en base
        existe = conn.execute(
            'SELECT id FROM annales WHERE niveau=? AND serie=? AND matiere=? AND annee=?',
            (niveau, serie_db, matiere, annee)
        ).fetchone()

        # Copier dans data/pdfs/
        dest = DOSSIER_PDFS / pdf.name
        shutil.copy2(str(pdf), str(dest))

        if existe:
            # Mettre à jour chemin
            conn.execute(
                'UPDATE annales SET chemin_fichier=? WHERE niveau=? AND serie=? AND matiere=? AND annee=?',
                (pdf.name, niveau, serie_db, matiere, annee)
            )
        else:
            conn.execute(
                '''INSERT INTO annales (niveau, serie, matiere, annee, chemin_fichier, corrige_dispo)
                   VALUES (?, ?, ?, ?, ?, 0)''',
                (niveau, serie_db, matiere, annee, pdf.name)
            )
            ajoutes += 1

    conn.commit()
    conn.close()
    print(f" ✅ {ajoutes} nouvelle(s) annale(s) ajoutée(s) en base")

def etape4_liens_drive(niveau, serie, matiere, folder_id):
    """Récupère les liens Drive et met à jour la base"""
    print(f"\n📋 ÉTAPE 4 — Récupération liens Drive (dossier : {folder_id})")

    serie_db = serie if serie and serie != 'NA' else None
    fichiers = get_drive_files(folder_id)

    if not fichiers:
        print(" ⚠️ Aucun fichier trouvé sur Drive — vérifie que le dossier est public")
        return

    print(f" {len(fichiers)} fichier(s) trouvé(s) sur Drive")

    conn = get_connection()
    mis_a_jour = 0

    for f in fichiers:
        annee = extraire_annee_v2(f['name'])
        if not annee:
            continue

        lien = f"https://drive.google.com/file/d/{f['id']}/preview"

        result = conn.execute(
            '''UPDATE annales SET lien_drive=?
               WHERE niveau=? AND serie=? AND matiere=? AND annee=?''',
            (lien, niveau, serie_db, matiere, annee)
        )
        if result.rowcount > 0:
            print(f" ✅ {annee} → lien Drive ajouté")
            mis_a_jour += 1

    conn.commit()
    conn.close()
    print(f" ✅ {mis_a_jour} lien(s) Drive mis à jour")

def etape5_git_push(niveau, serie, matiere):
    """Commit et push automatique"""
    print("\n📋 ÉTAPE 5 — Git commit & push")
    try:
        subprocess.run(['git', 'add', 'data/annales.db', 'data/pdfs/'], check=True)
        msg = f"Add: {niveau} {serie or ''} {matiere} — pipeline complet"
        subprocess.run(['git', 'commit', '-m', msg], check=True)
        subprocess.run(['git', 'push', 'origin', 'main'], check=True)
        print(" ✅ Déployé sur Render")
    except subprocess.CalledProcessError as e:
        print(f" ⚠️ Git erreur : {e}")

def nettoyer_raw():
    """Vide data/raw/ après traitement"""
    for f in DOSSIER_RAW.glob('*.pdf'):
        f.unlink()
    print(" 🗑️ data/raw/ vidé — prêt pour la prochaine série")

# ── Pipeline principal ────────────────────────────────────────────

def run(niveau, serie, matiere, folder_id, skip_git=False):
    print(f"\n{'='*55}")
    print(f"🚀 PIPELINE EXAMENSCAM")
    print(f" Niveau : {niveau}")
    print(f" Série : {serie or 'NA'}")
    print(f" Matière : {matiere}")
    print(f"{'='*55}")

    etape1_nettoyer(niveau, serie, matiere)
    etape2_personnaliser(niveau, serie, matiere)
    etape3_importer_base(niveau, serie, matiere)

    if folder_id:
        etape4_liens_drive(niveau, serie, matiere, folder_id)

    if not skip_git:
        etape5_git_push(niveau, serie, matiere)

    nettoyer_raw()

    print(f"\n{'='*55}")
    print(f"✅ PIPELINE TERMINÉ — {niveau} {serie or ''} {matiere} en ligne")
    print(f"{'='*55}\n")

# ── Point d'entrée ────────────────────────────────────────────────

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Pipeline ExamensCam')
    parser.add_argument('--niveau', required=True, help='BEPC, Probatoire, BAC')
    parser.add_argument('--serie', default='NA', help='C, D, TI, A4, NA')
    parser.add_argument('--matiere', required=True, help='Mathematiques, PCT...')
    parser.add_argument('--drive', default='', help='Google Drive Folder ID')
    parser.add_argument('--no-git', action='store_true', help='Ne pas push sur Git')
    args = parser.parse_args()

    run(
        niveau=args.niveau,
        serie=args.serie,
        matiere=args.matiere,
        folder_id=args.drive,
        skip_git=args.no_git
    )
