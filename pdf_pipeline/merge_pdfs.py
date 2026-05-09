# pdf_pipeline/merge_pdfs.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pypdf import PdfReader, PdfWriter
from pathlib import Path


def merge_title_with_annale(title_pdf: str, annale_pdf: str,
                             output_pdf: str) -> bool:
    """
    Colle le footer ExamensCam sur chaque page de l'épreuve.
    L'épreuve n'est pas modifiée — juste un bandeau de 8mm en bas.
    """
    try:
        writer = PdfWriter()
        footer = PdfReader(title_pdf).pages[0]
        annale_pages = PdfReader(annale_pdf).pages

        for page in annale_pages:
            page.merge_page(footer)
            writer.add_page(page)

        with open(output_pdf, 'wb') as f:
            writer.write(f)

        print(f"✅ PDF final : {output_pdf} ({len(writer.pages)} pages)")
        return True

    except Exception as e:
        print(f"❌ Erreur : {e}")
        return False


def pipeline_complet(niveau, serie, matiere, annee, annale_clean):
    from pdf_pipeline.generate_title import generate_footer_overlay

    Path('data/titres').mkdir(parents=True, exist_ok=True)
    Path('data/final').mkdir(parents=True, exist_ok=True)

    serie_str = serie or 'NA'
    nom_base = f"{niveau}_{serie_str}_{matiere}_{annee}"

    titre_path = f"data/titres/{nom_base}_footer.pdf"
    generate_footer_overlay(titre_path, niveau, serie, matiere, annee)

    final_path = f"data/final/{nom_base}_final.pdf"
    merge_title_with_annale(titre_path, annale_clean, final_path)

    return final_path


if __name__ == '__main__':
    result = pipeline_complet(
        niveau='Probatoire',
        serie='D',
        matiere='Mathematiques',
        annee=2023,
        annale_clean='data/clean/Probatoire_D_2023_Mathematiques.pdf'
    )
    print(f"📄 {result}")
