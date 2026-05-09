# pdf_pipeline/generate_title.py
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from io import BytesIO

COULEURS = {
    'BEPC': '#1A5276',
    'Probatoire': '#1A5276',
    'BAC_C_Maths': '#154360',
    'BAC_C_PCT': '#922B21',
    'BAC_D': '#145A32',
    'BAC_TI': '#4A235A',
    'BAC_A4': '#784212',
}

def couleur_pour(niveau, serie=None, matiere=None):
    if niveau == 'BAC':
        if serie == 'C':
            if matiere and 'PCT' in matiere.upper():
                return COULEURS['BAC_C_PCT']
            return COULEURS['BAC_C_Maths']
        if serie == 'D': return COULEURS['BAC_D']
        if serie == 'TI': return COULEURS['BAC_TI']
        if serie == 'A4': return COULEURS['BAC_A4']
    return COULEURS.get(niveau, '#1A5276')


def generate_footer_overlay(output_path: str, niveau: str, serie: str,
                             matiere: str, annee: int) -> bool:
    """
    Génère un overlay A4 avec seulement un petit footer en bas.
    Transparent partout sauf la bande du bas.
    """
    couleur = colors.HexColor(couleur_pour(niveau, serie, matiere))
    OR = colors.HexColor('#D4AC0D')
    width, height = A4

    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    # ── Bande footer (22 points = ~8mm en bas) ────────────────────
    c.setFillColor(couleur)
    c.rect(0, 0, width, 22, fill=True, stroke=False)

    # ── Ligne or fine au-dessus ───────────────────────────────────
    c.setFillColor(OR)
    c.rect(0, 22, width, 2, fill=True, stroke=False)

    # ── Texte footer ──────────────────────────────────────────────
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(10, 8, "ExamensCam")

    c.setFont("Helvetica", 7)
    c.drawCentredString(width / 2, 8, "examenscam.onrender.com | Tes annales, organisées.")

    serie_str = serie or ''
    label = f"{niveau} {serie_str} — {matiere} {annee}".strip()
    c.setFont("Helvetica", 7)
    c.drawRightString(width - 10, 8, label)

    c.save()

    with open(output_path, 'wb') as f:
        f.write(buffer.getvalue())

    print(f"✅ Footer généré : {output_path}")
    return True


if __name__ == '__main__':
    generate_footer_overlay(
        output_path='data/test_footer.pdf',
        niveau='Probatoire',
        serie='D',
        matiere='Mathématiques',
        annee=2023
    )
