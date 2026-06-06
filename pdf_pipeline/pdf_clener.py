# pdf_cleaner.py — ExamensCam — Version Sophistiquée
# ═══════════════════════════════════════════════════════
# Installe :
# pip install pikepdf pypdf reportlab Pillow pypdfium2 opencv-python numpy
#
# Usage :
# python pdf_cleaner.py ← raw/ → outputs/
# python pdf_cleaner.py fichier.pdf
# python pdf_cleaner.py --image ← nettoyage visuel activé
# ═══════════════════════════════════════════════════════

import sys, re, shutil, math
from pathlib import Path
from io import BytesIO

import pikepdf
import numpy as np
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.pdfgen import canvas as rl_canvas

try:
    import cv2
    CV2_OK = True
except ImportError:
    CV2_OK = False

try:
    import pypdfium2 as pdfium
    PDFIUM_OK = True
except ImportError:
    PDFIUM_OK = False

# ══════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════

SITE_URL = "https://examenscam.onrender.com"
SITE_NOM = "ExamensCam"
COULEUR_LIEN = colors.HexColor("#00B2CA") # Vert-bleu entre WhatsApp et bleu
DPI_RENDU = 200

# ══════════════════════════════════════════
# MOTS-CLÉS — AJOUTE TES PROPRES SITES ICI
# ══════════════════════════════════════════

WATERMARK_KEYWORDS = [
    # Sites camerounais
    'mongosukulu', 'mongosukulu.com',
    'sujetexa', 'sujetexa.com',
    'orniformation', 'orniformation.com',
    'exosujet', 'exosujet.com',
    'camerounexam', 'annalescam',
    'lewebpedagogique', 'minesec',
    'educam', 'docucam', 'examplus',
    # Scanners
    'camscanner', 'cam scanner', 'cam-scanner',
    'adobe scan', 'microsoft lens', 'scanbot',
    'genius scan', 'tiny scanner', 'turboscan',
    # Plateformes
    'scribd', 'slideshare', 'academia.edu',
    'docuprint', 'issuu', 'calameo', 'yumpu',
    # Génériques
    'watermark', 'filigrane', 'draft', 'brouillon',
    'sample', 'specimen', 'confidentiel',
    'do not copy', 'ne pas copier', 'copy protected',
    'all rights reserved', 'tous droits',
    'free download', 'downloaded from',
    'visit our website', 'visitez notre',
    'unregistered', 'evaluation copy',
    'for review only', 'not for distribution',
    # ── AJOUTE ICI ──────────────────────────
    # 'nouveau_site.com',
]


# ══════════════════════════════════════════
# COUCHE 1 — FLUX DE CONTENU
# Supprime blocs BT/ET + textes diagonaux
# + textes semi-transparents
# ══════════════════════════════════════════

def couche_flux(src: Path, dst: Path) -> bool:
    try:
        with pikepdf.open(str(src)) as pdf:
            modifie = False
            for page in pdf.pages:
                if '/Contents' not in page:
                    continue
                contents = page['/Contents']
                streams = list(contents) if isinstance(contents, pikepdf.Array) else [contents]
                for stream in streams:
                    try:
                        data = stream.read_bytes()
                        texte = data.decode('latin-1', errors='ignore')
                        avant = texte

                        # 1a — Mots-clés dans blocs BT...ET
                        for kw in WATERMARK_KEYWORDS:
                            pat = r'BT[\s\S]{0,3000}?' + re.escape(kw) + r'[\s\S]{0,3000}?ET'
                            texte = re.sub(pat, 'BT ET', texte, flags=re.IGNORECASE | re.DOTALL)

                        # 1b — Blocs q...Q avec rotation diagonale
                        def remplacer_diagonal(m):
                            bloc = m.group(0)
                            cm = re.search(r'((?:[-\d.]+\s+){6})cm', bloc)
                            if cm:
                                try:
                                    vals = cm.group(1).split()
                                    angle = abs(math.degrees(math.atan2(float(vals[1]), float(vals[0]))))
                                    if 20 < angle < 70 or 110 < angle < 160:
                                        return 'q Q'
                                except Exception:
                                    pass
                            return bloc

                        texte = re.sub(
                            r'(q\s+(?:[-\d.]+\s+){6}cm[\s\S]{0,5000}?Q)',
                            remplacer_diagonal, texte, flags=re.DOTALL
                        )

                        # 1c — États graphiques avec alpha faible (filigranes transparents)
                        try:
                            resources = page.get('/Resources', {})
                            ext_gstate = resources.get('/ExtGState', {})
                            for gs_name in ext_gstate:
                                gs_obj = ext_gstate[gs_name]
                                ca = float(gs_obj.get('/ca', 1))
                                CA = float(gs_obj.get('/CA', 1))
                                if ca < 0.5 or CA < 0.5:
                                    texte = re.sub(
                                        r'(q[\s\S]{0,100}?' + re.escape(str(gs_name)) +
                                        r'[\s\S]{0,3000}?Q)',
                                        'q Q', texte, flags=re.DOTALL
                                    )
                        except Exception:
                            pass

                        if texte != avant:
                            stream.write_raw(texte.encode('latin-1', errors='ignore'))
                            modifie = True

                    except Exception:
                        continue

            pdf.save(str(dst))
            return modifie

    except Exception as e:
        print(f" Erreur couche flux: {e}")
        shutil.copy(str(src), str(dst))
        return False


# ══════════════════════════════════════════
# COUCHE 2 — XOBJECTS ET IMAGES OVERLAY
# ══════════════════════════════════════════

def couche_xobjects(src: Path, dst: Path) -> bool:
    try:
        with pikepdf.open(str(src)) as pdf:
            modifie = False
            for page in pdf.pages:
                if '/Resources' not in page:
                    continue
                resources = page['/Resources']
                if '/XObject' not in resources:
                    continue
                xobjects = resources['/XObject']
                a_supprimer = []

                for key in xobjects:
                    try:
                        xobj = xobjects[key]
                        subtype = str(xobj.get('/Subtype', ''))

                        if subtype == '/Form':
                            content = xobj.read_raw_bytes().decode('latin-1', errors='ignore')
                            for kw in WATERMARK_KEYWORDS:
                                if kw.lower() in content.lower():
                                    a_supprimer.append(key)
                                    break

                        elif subtype == '/Image':
                            # Image pleine page avec masque = overlay watermark
                            if '/SMask' in xobj:
                                pw = float(page.mediabox.width)
                                ph = float(page.mediabox.height)
                                w = int(xobj.get('/Width', 0))
                                h = int(xobj.get('/Height', 0))
                                if w > pw * 0.7 and h > ph * 0.7:
                                    a_supprimer.append(key)

                    except Exception:
                        continue

                if a_supprimer:
                    for key in a_supprimer:
                        try:
                            del xobjects[key]
                        except Exception:
                            pass
                    modifie = True

            pdf.save(str(dst))
            return modifie

    except Exception as e:
        print(f" Erreur couche xobjects: {e}")
        shutil.copy(str(src), str(dst))
        return False


# ══════════════════════════════════════════
# COUCHE 3 — ANNOTATIONS
# ══════════════════════════════════════════

def couche_annotations(src: Path, dst: Path) -> bool:
    try:
        with pikepdf.open(str(src)) as pdf:
            modifie = False
            for page in pdf.pages:
                if '/Annots' not in page:
                    continue
                annots = page['/Annots']
                a_supprimer = []

                for i, annot in enumerate(annots):
                    try:
                        subtype = str(annot.get('/Subtype', ''))
                        if subtype in ['/Stamp', '/FreeText', '/Widget',
                                       '/Watermark', '/FileAttachment']:
                            a_supprimer.append(i)
                            continue
                        for field in ['/Contents', '/T', '/TU', '/DA']:
                            if field in annot:
                                val = str(annot[field]).lower()
                                for kw in WATERMARK_KEYWORDS:
                                    if kw in val:
                                        if i not in a_supprimer:
                                            a_supprimer.append(i)
                                        break
                    except Exception:
                        continue

                if a_supprimer:
                    for i in reversed(a_supprimer):
                        try:
                            del annots[i]
                        except Exception:
                            pass
                    modifie = True

            pdf.save(str(dst))
            return modifie

    except Exception as e:
        print(f" Erreur couche annotations: {e}")
        shutil.copy(str(src), str(dst))
        return False


# ══════════════════════════════════════════
# COUCHE 4 — NETTOYAGE VISUEL PAR IMAGE
# Détecte visuellement + inpainting OpenCV
# ══════════════════════════════════════════

def nettoyer_visuellement(img: np.ndarray) -> np.ndarray:
    if not CV2_OK:
        return img

    gris = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if len(img.shape) == 3 else img.copy()
    h, w = gris.shape

    seuil = cv2.adaptiveThreshold(
        gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 15, 3
    )

    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(seuil)
    masque = np.zeros(gris.shape, dtype=np.uint8)

    for i in range(1, num_labels):
        x, y, cw, ch, area = stats[i]
        if area < 50 or area > (w * h * 0.3):
            continue
        zone = gris[y:y+ch, x:x+cw]
        lum_moy = np.mean(zone)
        if 170 < lum_moy < 245:
            ratio = cw / ch if ch > 0 else 0
            if ratio > 3 or ratio < 0.3:
                masque[y:y+ch, x:x+cw] = 255

    if np.sum(masque) > 0:
        kernel = np.ones((3, 3), np.uint8)
        masque_dilat = cv2.dilate(masque, kernel, iterations=2)
        if len(img.shape) == 3:
            bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            result = cv2.inpaint(bgr, masque_dilat, 3, cv2.INPAINT_TELEA)
            return cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
        else:
            return cv2.inpaint(img, masque_dilat, 3, cv2.INPAINT_TELEA)

    return img


def couche_image(src: Path, dst: Path) -> bool:
    if not PDFIUM_OK:
        print(" ⚠️ pypdfium2 manquant — pip install pypdfium2")
        shutil.copy(str(src), str(dst))
        return False

    try:
        doc = pdfium.PdfDocument(str(src))
        writer = PdfWriter()

        for page in doc:
            scale = DPI_RENDU / 72.0
            bitmap = page.render(scale=scale)
            img = bitmap.to_pil()
            arr = np.array(img)
            if CV2_OK:
                arr = nettoyer_visuellement(arr)
                img = Image.fromarray(arr)
            buf = BytesIO()
            img.save(buf, format='PDF', resolution=DPI_RENDU)
            buf.seek(0)
            writer.add_page(PdfReader(buf).pages[0])

        with open(str(dst), 'wb') as f:
            writer.write(f)
        return True

    except Exception as e:
        print(f" Erreur couche image: {e}")
        shutil.copy(str(src), str(dst))
        return False


# ══════════════════════════════════════════
# COUCHE 5 — MÉTADONNÉES
# ══════════════════════════════════════════

def couche_metadonnees(src: Path, dst: Path):
    try:
        with pikepdf.open(str(src)) as pdf:
            with pdf.open_metadata() as meta:
                for key in list(meta.keys()):
                    try:
                        del meta[key]
                    except Exception:
                        pass
                meta['{http://purl.org/dc/elements/1.1/}creator'] = SITE_NOM
                meta['{http://purl.org/dc/elements/1.1/}publisher'] = SITE_URL
            pdf.save(str(dst))
    except Exception as e:
        print(f" Erreur métadonnées: {e}")
        shutil.copy(str(src), str(dst))


# ══════════════════════════════════════════
# FOOTER — BLANC + LIEN VERT-BLEU
# ══════════════════════════════════════════

def creer_footer(pw: float, ph: float) -> bytes:
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(pw, ph))
    fh = 20

    c.setFillColor(colors.white)
    c.rect(0, 0, pw, fh, fill=True, stroke=False)

    c.setStrokeColor(colors.HexColor("#CCCCCC"))
    c.setLineWidth(0.4)
    c.line(0, fh, pw, fh)

    c.setFillColor(colors.HexColor("#222222"))
    c.setFont("Helvetica", 6.5)
    c.drawString(12, 7, f"{SITE_NOM} · Annales officielles du Cameroun")

    c.setFillColor(COULEUR_LIEN)
    c.setFont("Helvetica-Bold", 6.5)
    lw = c.stringWidth(SITE_URL, "Helvetica-Bold", 6.5)
    lx = pw - 12
    c.drawRightString(lx, 7, SITE_URL)
    c.linkURL(SITE_URL, (lx - lw, 0, lx, fh), relative=0)

    c.save()
    return buf.getvalue()


def ajouter_footer(src: Path, dst: Path) -> bool:
    try:
        reader = PdfReader(str(src))
        writer = PdfWriter()
        for page in reader.pages:
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            footer = PdfReader(BytesIO(creer_footer(w, h))).pages[0]
            page.merge_page(footer)
            writer.add_page(page)
        with open(str(dst), 'wb') as f:
            writer.write(f)
        return True
    except Exception as e:
        print(f" Erreur footer: {e}")
        shutil.copy(str(src), str(dst))
        return False


# ══════════════════════════════════════════
# PIPELINE PRINCIPAL
# ══════════════════════════════════════════

def traiter_pdf(input_path: Path, output_path: Path = None,
                forcer_image: bool = False) -> Path:

    if output_path is None:
        Path('outputs').mkdir(exist_ok=True)
        output_path = Path('outputs') / f"[ExamensCam] {input_path.name}"

    tmp = Path(f".tmp_{input_path.stem}")
    tmp.mkdir(exist_ok=True)

    t = [tmp / f"{i}.pdf" for i in range(7)]

    print(f"\n{'─'*54}")
    print(f" {input_path.name}")
    print(f"{'─'*54}")

    print(" [1/5] Flux de contenu (textes, diagonaux, transparents)...")
    r1 = couche_flux(input_path, t[1])
    s = t[1] if t[1].exists() else input_path
    print(f" {'✅ Modifié' if r1 else '⬜ Rien détecté'}")

    print(" [2/5] XObjects et images overlay...")
    r2 = couche_xobjects(s, t[2])
    s = t[2] if t[2].exists() else s
    print(f" {'✅ Modifié' if r2 else '⬜ Rien détecté'}")

    print(" [3/5] Annotations et tampons...")
    r3 = couche_annotations(s, t[3])
    s = t[3] if t[3].exists() else s
    print(f" {'✅ Modifié' if r3 else '⬜ Rien détecté'}")

    print(" [4/5] Métadonnées...")
    couche_metadonnees(s, t[4])
    s = t[4] if t[4].exists() else s
    print(f" ✅ → ExamensCam")

    if forcer_image:
        print(" [5/5] Nettoyage visuel (rendu image + OpenCV)...")
        r5 = couche_image(s, t[5])
        s = t[5] if t[5].exists() else s
        print(f" {'✅ Effectué' if r5 else '⬜ Non disponible'}")
    else:
        print(" [5/5] Nettoyage visuel : désactivé (ajoute --image pour activer)")

    print(" Footer ExamensCam...")
    ajouter_footer(s, output_path)
    print(f" ✅ Fond blanc · lien {SITE_URL}")

    for f in t[1:]:
        try: f.unlink(missing_ok=True)
        except: pass
    try: tmp.rmdir()
    except: pass

    print(f"\n ✅ Produit : {output_path.name}")
    return output_path


# ══════════════════════════════════════════
# POINT D'ENTRÉE
# ══════════════════════════════════════════

if __name__ == '__main__':

    print(f"\n ExamensCam PDF Cleaner")
    print(f" opencv : {'✅' if CV2_OK else '❌ pip install opencv-python'}")
    print(f" pypdfium2 : {'✅' if PDFIUM_OK else '❌ pip install pypdfium2'}")

    forcer_image = '--image' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--image']

    if not args:
        raw = Path('raw')
        out = Path('outputs')
        raw.mkdir(exist_ok=True)
        out.mkdir(exist_ok=True)

        pdfs = [f for f in raw.glob('*.pdf')
                if not f.name.startswith('[ExamensCam]')]

        if not pdfs:
            print(f"\n 📂 Mets tes PDFs dans raw/ puis relance.\n")
            sys.exit(0)

        print(f"\n {len(pdfs)} PDF(s) dans raw/")
        if forcer_image:
            print(f" Mode : nettoyage visuel activé")

        count = 0
        for pdf in pdfs:
            try:
                traiter_pdf(pdf, out / f"[ExamensCam] {pdf.name}",
                            forcer_image=forcer_image)
                count += 1
            except Exception as e:
                print(f" ❌ {pdf.name}: {e}")

        print(f"\n ✅ {count}/{len(pdfs)} PDFs traités → outputs/\n")

    else:
        cible = Path(args[0])
        if not cible.exists():
            print(f"\n ❌ Introuvable : {cible}\n")
            sys.exit(1)
        if cible.is_dir():
            for pdf in cible.glob('*.pdf'):
                traiter_pdf(pdf, forcer_image=forcer_image)
        else:
            traiter_pdf(cible, forcer_image=forcer_image)

