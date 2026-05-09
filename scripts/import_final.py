# import_final.py
# scripts/import_final.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from database import get_connection

def extraire_infos(nom_fichier: str) -> dict:
    """Extrait niveau, serie, matiere, annee depuis le nom du fichier."""
    nom = nom_fichier.replace('.pdf', '').replace('_final', '')
    parties = nom.split('_')

    try:
        annee_idx = next(i for i, p in enumerate(parties) if p.isdigit() and len(p) == 4)
        annee = int(parties[annee_idx])
        niveau = parties[0]
        serie = parties[1] if parties[1] not in ['NA'] else None
        matiere = '_'.join(parties[annee_idx + 1:]) or 'Mathematiques'
        return {'niveau': niveau, 'serie': serie, 'matiere': matiere, 'annee': annee}
    except Exception as e:
        print(f" ⚠️ Infos non extraites : {nom_fichier} ({e})")
        return None


def importer_tous(dossier_final: str = 'data/final'):
    """Importe tous les PDFs de data/final/ dans la base SQLite."""

    
    conn = get_connection()
    cursor = conn.cursor()

    pdfs = list(Path(dossier_final).glob('*.pdf'))

    print(f"\n{'='*55}")
    print(f"📥 IMPORT EN BASE — {len(pdfs)} fichier(s)")
    print(f"{'='*55}")

    rapport = {'ajoutés': [], 'ignorés': [], 'échoués': []}

    for pdf in pdfs:
        infos = extraire_infos(pdf.name)
        if not infos:
            rapport['échoués'].append(pdf.name)
            continue

        # Vérifier si déjà en base
        cursor.execute(
            'SELECT id FROM annales WHERE niveau=? AND serie=? AND matiere=? AND annee=?',
            (infos['niveau'], infos['serie'], infos['matiere'], infos['annee'])
        )
        existe = cursor.fetchone()

        if existe:
            print(f" ⏭️ Déjà en base : {pdf.name}")
            rapport['ignorés'].append(pdf.name)
            continue

        # Copier le PDF dans data/pdfs/
        import shutil
        Path('data/pdfs').mkdir(parents=True, exist_ok=True)
        destination = Path('data/pdfs') / pdf.name
        shutil.copy2(str(pdf), str(destination))

        # Enregistrer en base
        nom_fichier = pdf.name
        cursor.execute(
            '''INSERT INTO annales (niveau, serie, matiere, annee, chemin_fichier, corrige_dispo)
               VALUES (?, ?, ?, ?, ?, 0)''',
            (infos['niveau'], infos['serie'], infos['matiere'], infos['annee'], nom_fichier)
        )
        conn.commit()

        print(f" ✅ Ajouté : {infos['niveau']} {infos['serie'] or ''} "
              f"{infos['matiere']} {infos['annee']}")
        rapport['ajoutés'].append(pdf.name)

    conn.close()

    print(f"\n{'='*55}")
    print(f"📊 RAPPORT")
    print(f" ✅ Ajoutés : {len(rapport['ajoutés'])}")
    print(f" ⏭️ Ignorés : {len(rapport['ignorés'])}")
    print(f" ❌ Échoués : {len(rapport['échoués'])}")
    print(f"{'='*55}")
    print(f"\n✅ Lance le site et vérifie : http://127.0.0.1:5000")


if __name__ == '__main__':
    importer_tous()
