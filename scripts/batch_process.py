# batch_porcess.
# scripts/batch_final.py
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from pdf_pipeline.generate_title import generate_footer_overlay
from pdf_pipeline.merge_pdfs import merge_title_with_annale

def extraire_infos(nom_fichier: str) -> dict:
    """
    Extrait niveau, serie, matiere, annee depuis le nom du fichier.
    Exemple : Probatoire_D_2023_Mathematiques.pdf
              BAC_C_2022_Mathematiques.pdf
              BEPC_NA_2021_Mathematiques.pdf
    """
    nom = nom_fichier.replace('.pdf', '')
    parties = nom.split('_')

    try:
        # Trouver l'année (4 chiffres)
        annee_idx = next(i for i, p in enumerate(parties) if p.isdigit() and len(p) == 4)
        annee = int(parties[annee_idx])
        niveau = parties[0]
        serie = parties[1] if parties[1] not in ['NA', str(annee)] else None
        if serie == 'NA':
            serie = None
        matiere = '_'.join(parties[annee_idx + 1:]) or 'Mathematiques'
        return {'niveau': niveau, 'serie': serie, 'matiere': matiere, 'annee': annee}
    except Exception as e:
        print(f" ⚠️ Impossible d'extraire les infos de : {nom_fichier} ({e})")
        return None


def batch_pipeline(dossier_clean: str = 'data/clean',
                   dossier_final: str = 'data/final'):
    """Traite tous les PDFs de data/clean/ vers data/final/"""

    clean_dir = Path(dossier_clean)
    final_dir = Path(dossier_final)
    titres_dir = Path('data/titres')

    final_dir.mkdir(parents=True, exist_ok=True)
    titres_dir.mkdir(parents=True, exist_ok=True)

    pdfs = list(clean_dir.glob('*.pdf'))

    print(f"\n{'='*55}")
    print(f"🚀 BATCH PIPELINE — {len(pdfs)} épreuve(s)")
    print(f"{'='*55}")

    rapport = {'réussis': [], 'échoués': [], 'ignorés': []}

    for pdf in pdfs:
        print(f"\n📄 {pdf.name}")

        infos = extraire_infos(pdf.name)
        if not infos:
            rapport['ignorés'].append(pdf.name)
            continue

        print(f" Niveau : {infos['niveau']} | Série : {infos['serie']} | "
              f"Matière : {infos['matiere']} | Année : {infos['annee']}")

        # Générer le footer
        titre_path = titres_dir / f"{pdf.stem}_footer.pdf"
        generate_footer_overlay(
            str(titre_path),
            infos['niveau'],
            infos['serie'],
            infos['matiere'],
            infos['annee']
        )

        # Fusionner
        final_path = final_dir / pdf.name
        if merge_title_with_annale(str(titre_path), str(pdf), str(final_path)):
            rapport['réussis'].append(pdf.name)
        else:
            rapport['échoués'].append(pdf.name)

    print(f"\n{'='*55}")
    print(f"📊 RAPPORT FINAL")
    print(f" ✅ Réussis : {len(rapport['réussis'])}")
    print(f" ❌ Échoués : {len(rapport['échoués'])}")
    print(f" ⏭️ Ignorés : {len(rapport['ignorés'])}")
    if rapport['échoués']:
        print("\n Fichiers échoués :")
        for f in rapport['échoués']:
            print(f" - {f}")
    print(f"{'='*55}")
    print(f"\n✅ PDFs finaux dans : {dossier_final}/")


if __name__ == '__main__':
    batch_pipeline()

