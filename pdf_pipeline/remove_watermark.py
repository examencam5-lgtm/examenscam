# pdf_pipeline/remove_watermark.py
import pikepdf
import pdfplumber
from pathlib import Path

FILIGRANES_CONNUS = [
    'educamer', 'edumathcamer', 'mongosukulu', 'easy-maths',
    'easymaths', 'sujetexa', 'maxiepreuves', 'camscanner',
    'prépas probatoire', 'prepas probatoire', 'be ready for your probat',
    'powered by', 'téléchargez gratuitement', 'telechargez gratuitement',
    'annales probatoire', 'http://maths', 'www.edumathcamer',
    'www.mongosukulu', 'www.easy-maths', 'http://sujetexa',
]

def contient_filigrane(texte: str) -> bool:
    texte_lower = texte.lower()
    return any(mot in texte_lower for mot in FILIGRANES_CONNUS)

def trouver_zones_filigrane(pdf_path: str) -> dict:
    """
    Utilise pdfplumber pour trouver les coordonnées exactes
    des filigranes sur chaque page.
    Retourne : {page_index: [(x0, y0, x1, y1), ...]}
    """
    zones = {}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_height = page.height
                zones[i] = []

                # Analyser chaque mot sur la page
                mots = page.extract_words() or []
                for mot in mots:
                    if contient_filigrane(mot['text']):
                        # Convertir coords pdfplumber → pikepdf
                        # pdfplumber: y depuis le haut
                        # pikepdf: y depuis le bas
                        x0 = mot['x0'] - 5
                        x1 = mot['x1'] + 5
                        y0_plumber = mot['top']
                        y1_plumber = mot['bottom']
                        # Conversion
                        y0_pdf = page_height - y1_plumber - 5
                        y1_pdf = page_height - y0_plumber + 5
                        zones[i].append((x0, y0_pdf, x1 - x0, y1_pdf - y0_pdf))

                # Si des mots de filigrane trouvés — élargir à toute la ligne
                if zones[i]:
                    # Grouper par zone y (même ligne ≈ même y)
                    zones[i] = _fusionner_zones(zones[i], page.width)

    except Exception as e:
        print(f" ⚠️ pdfplumber erreur : {e}")
    return zones

def _fusionner_zones(zones, page_width):
    """Fusionne les zones proches en une seule bande horizontale."""
    if not zones:
        return zones
    # Trier par y
    zones_sorted = sorted(zones, key=lambda z: z[1])
    fusionnees = []
    for z in zones_sorted:
        x, y, w, h = z
        # Chercher une zone existante proche en y
        merged = False
        for i, f in enumerate(fusionnees):
            fx, fy, fw, fh = f
            if abs(y - fy) < 20: # Même bande horizontale
                # Étendre sur toute la largeur de la page
                new_y = min(y, fy) - 3
                new_h = max(y+h, fy+fh) - new_y + 3
                fusionnees[i] = (0, new_y, page_width, new_h)
                merged = True
                break
        if not merged:
            fusionnees.append((0, y - 3, page_width, h + 6))
    return fusionnees

def nettoyer_pdf(input_path: str, output_path: str) -> bool:
    print(f"\n📄 Traitement : {Path(input_path).name}")

    # Étape 1 : Détecter les zones exactes du filigrane
    zones = trouver_zones_filigrane(input_path)
    total_zones = sum(len(z) for z in zones.values())

    if total_zones == 0:
        print(f" ℹ️ Aucun filigrane détecté — copie sans modification")
        import shutil
        shutil.copy2(input_path, output_path)
        return True

    print(f" 🎯 {total_zones} zone(s) de filigrane détectée(s)")

    # Étape 2 : Couvrir uniquement ces zones avec des rectangles blancs
    try:
        with pikepdf.open(input_path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i not in zones or not zones[i]:
                    continue

                mediabox = page.mediabox
                page_height = float(mediabox[3]) - float(mediabox[1])

                # Construire le contenu overlay
                rects = ""
                for (x, y, w, h) in zones[i]:
                    rects += f"0 {y:.2f} {float(w):.2f} {h:.2f} re f "
                    print(f" Page {i+1} → rectangle blanc à y={y:.0f}, h={h:.0f}")

                overlay_content = f"q 1 1 1 rg {rects}Q".encode('latin-1')
                overlay_stream = pikepdf.Stream(pdf, overlay_content)

                if '/Contents' in page:
                    existing = page['/Contents']
                    if isinstance(existing, pikepdf.Array):
                        existing.append(overlay_stream)
                    else:
                        page['/Contents'] = pikepdf.Array([existing, overlay_stream])
                else:
                    page['/Contents'] = overlay_stream

            pdf.save(output_path)
            print(f" ✅ Nettoyé → {output_path}")
            return True

    except Exception as e:
        print(f" ❌ Erreur pikepdf : {e}")
        return False

def nettoyer_dossier(dossier_input: str, dossier_output: str) -> dict:
    input_dir = Path(dossier_input)
    output_dir = Path(dossier_output)
    output_dir.mkdir(parents=True, exist_ok=True)

    rapport = {'réussis': [], 'échoués': []}
    pdfs = list(input_dir.glob('*.pdf'))

    print(f"\n{'='*50}")
    print(f"📂 {len(pdfs)} PDF(s) à traiter")
    print(f"{'='*50}")

    for pdf in pdfs:
        sortie = output_dir / pdf.name
        if nettoyer_pdf(str(pdf), str(sortie)):
            rapport['réussis'].append(pdf.name)
        else:
            rapport['échoués'].append(pdf.name)

    print(f"\n{'='*50}")
    print(f"📊 {len(rapport['réussis'])} réussis / {len(rapport['échoués'])} échoués")
    print(f"{'='*50}")
    return rapport

if __name__ == '__main__':
    nettoyer_dossier('data/raw', 'data/clean')
