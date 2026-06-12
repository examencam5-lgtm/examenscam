"""
ExamensCam — Découpeur par année — Version finale
Détecte les DEBUTS d'annale (en-tête officiel) pas juste l'année.
Usage : python scripts/decouper_par_annee.py
        python scripts/decouper_par_annee.py fichier.pdf
        python scripts/decouper_par_annee.py --debug
"""

import re
import sys
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter

try:
    import pypdfium2 as pdfium
    from PIL import Image, ImageEnhance
    VISION_OK = True
except ImportError:
    VISION_OK = False
    print('⚠️  pypdfium2/Pillow manquants')

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    pytesseract.get_tesseract_version()
    TESS_OK = True
except Exception:
    TESS_OK = False
    print('⚠️  Tesseract non disponible — scans ignorés')

RAW         = Path('pdf_pipeline/raw')
OUTPUT_BASE = Path('pdf_pipeline/outputs')
DEBUG_DIR   = Path('pdf_pipeline/debug_annees')

ANNEE_RE = re.compile(r'\b(19[89]\d|200\d|201\d|202[0-9])\b')

# Mots-clés qui marquent une VRAIE première page d'annale camerounaise
MOTS_CLES_ENTETE = [
    'ministère', 'ministere',
    'office du baccalauréat', 'office du baccalaureat',
    'enseignements secondaires',
    'office du bepc', 'office national',
    'brevet d\'études', 'brevet d\'etudes',
    'république du cameroun', 'republique du cameroun',
    'examen :', 'examen:', 'épreuve :', 'epreuve :',
    'serie :', 'série :', 'coefficient',
    'durée', 'duree',
]


# ──────────────────────────────────────────────
# NORMALISATION OCR
# ──────────────────────────────────────────────
def normaliser(t: str) -> str:
    t = re.sub(r'20\s+(\d)\s*/\s*(\d)', lambda m: '20' + m.group(1) + m.group(2), t)
    t = re.sub(r'(20)\s+(\d)\s+(\d)\b', r'\1\2\3', t)
    t = re.sub(r'SESSION\s*/\s*(\d{4})', r'SESSION \1', t)
    t = re.sub(r'SESS[I1L]ON', 'SESSION', t)
    t = re.sub(r'2[oO](\d{2})\b', r'20\1', t)
    return t


# ──────────────────────────────────────────────
# DÉTECTION ANNÉE
# ──────────────────────────────────────────────
PATTERNS_ANNEE = [
    re.compile(r'[Ss]ession\s*[:\s/]+(\d{4})'),
    re.compile(r'[Bb]accalaur[eé]at\s+(\d{4})'),
    re.compile(r'[Ee]xamen\s*:.*?(\d{4})'),
    re.compile(r'[Aa]nn[eé]e\s*:?\s*(\d{4})'),
    re.compile(r'\b(19[89]\d|200\d|201\d|202\d)\b'),
]

def extraire_annee(texte: str) -> str | None:
    texte = normaliser(texte)
    for pat in PATTERNS_ANNEE:
        m = pat.search(texte)
        if m:
            a = m.group(1)
            if re.match(r'^(19[89]\d|200\d|201\d|202[0-9])$', a):
                return a
    return None


# ──────────────────────────────────────────────
# SCORE D'EN-TÊTE : est-ce une première page ?
# ──────────────────────────────────────────────
def score_entete(texte: str) -> int:
    """
    Compte combien de mots-clés d'en-tête officiel sont présents.
    Score >= 2 = début d'une nouvelle annale.
    """
    t = texte.lower()
    return sum(1 for kw in MOTS_CLES_ENTETE if kw in t)


# ──────────────────────────────────────────────
# OCR SUR UNE PAGE SCANNÉE
# ──────────────────────────────────────────────
def ocr_page(pdf_path: Path, page_idx: int, debug: bool = False) -> str:
    """Rend la page en image et retourne le texte OCR."""
    if not VISION_OK or not TESS_OK:
        return ''
    try:
        doc    = pdfium.PdfDocument(str(pdf_path))
        page   = doc[page_idx]
        bitmap = page.render(scale=3.0)
        img    = bitmap.to_pil()

        w, h   = img.size
        # En-tête = 35% supérieur de la page
        header = img.crop((0, 0, w, int(h * 0.35)))

        # Prétraitement
        header = header.convert('L')
        header = ImageEnhance.Contrast(header).enhance(2.0)
        header = header.point(lambda p: 255 if p > 150 else 0)

        if debug:
            DEBUG_DIR.mkdir(exist_ok=True)
            header.save(DEBUG_DIR / f'page_{page_idx+1:03d}.png')

        config = '--oem 3 --psm 6 -l fra+eng'
        return pytesseract.image_to_string(header, config=config)

    except Exception as e:
        print(f'  (OCR p.{page_idx+1} échoué : {e})')
        return ''


# ──────────────────────────────────────────────
# ANALYSE PAGE PAR PAGE
# ──────────────────────────────────────────────
def analyser_pages(pdf_path: Path, debug: bool = False) -> list[dict]:
    """
    Pour chaque page retourne :
      idx, texte, annee, score_entete, est_debut, source
    """
    resultats = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        n = len(pdf.pages)
        print(f'  {n} page(s)...')

        for i, page in enumerate(pdf.pages):
            texte  = page.extract_text() or ''
            source = 'texte'

            # Si pas de texte extractible → OCR
            if len(texte.strip()) < 30:
                texte  = ocr_page(pdf_path, i, debug=debug)
                source = 'ocr' if texte.strip() else 'vide'

            annee  = extraire_annee(texte)
            score  = score_entete(texte)
            # Une vraie première page = année trouvée + au moins 2 mots-clés officiels
            est_debut = bool(annee and score >= 2)

            resultats.append({
                'idx'      : i,
                'texte'    : texte,
                'annee'    : annee,
                'score'    : score,
                'est_debut': est_debut,
                'source'   : source,
            })

            statut = '🟢 DÉBUT' if est_debut else ('🔵 suite' if annee else '⬜ ?')
            print(f'  p{i+1:03d} | {statut} | année={annee or "?"} | score={score} | [{source}]')

    return resultats


# ──────────────────────────────────────────────
# GROUPEMENT PAR BLOCS SÉQUENTIELS
# ──────────────────────────────────────────────
def grouper(pages: list[dict]) -> list[dict]:
    """
    Groupe les pages en blocs :
    - Un nouveau bloc commence à chaque page marquée est_debut=True
    - Les pages sans début rattachées au bloc précédent
    - Retourne liste de {annee, indices}
    """
    blocs  = []
    actuel = None

    for p in pages:
        if p['est_debut']:
            if actuel:
                blocs.append(actuel)
            actuel = {'annee': p['annee'], 'indices': [p['idx']]}
        elif actuel:
            actuel['indices'].append(p['idx'])
        else:
            # Pages avant le premier début détecté → on les met en attente
            if not blocs:
                blocs.append({'annee': p['annee'] or 'INCONNUE', 'indices': [p['idx']]})
            else:
                blocs[-1]['indices'].append(p['idx'])

    if actuel:
        blocs.append(actuel)

    # Dédoublonner les années (si même année apparaît 2 fois → partie1, partie2)
    compteur: dict[str, int] = {}
    for b in blocs:
        a = b['annee'] or 'INCONNUE'
        compteur[a] = compteur.get(a, 0) + 1
        b['cle'] = a if compteur[a] == 1 else f'{a}_p{compteur[a]}'

    return blocs


# ──────────────────────────────────────────────
# NOM DE BASE PROPRE
# ──────────────────────────────────────────────
def nom_base(pdf_path: Path) -> str:
    s = pdf_path.stem
    s = re.sub(r'^[0-9a-f]{6,}_', '', s)        # hash préfixe
    s = re.sub(r'_copie.*$', '', s, re.IGNORECASE)
    s = re.sub(r'_\d{4}(_\d+)?$', '', s)         # année en fin
    return s.strip('_') or pdf_path.stem


# ──────────────────────────────────────────────
# DÉCOUPAGE
# ──────────────────────────────────────────────
def decouper_pdf(pdf_path: Path, debug: bool = False) -> int:
    print(f'\n{"─"*55}')
    print(f'📄 {pdf_path.name}')

    base   = nom_base(pdf_path)
    outdir = OUTPUT_BASE / base
    outdir.mkdir(parents=True, exist_ok=True)

    pages  = analyser_pages(pdf_path, debug=debug)
    blocs  = grouper(pages)

    if not blocs:
        print('  ❌ Aucun bloc détecté.')
        return 0

    reader = PdfReader(str(pdf_path))
    ok     = 0

    print(f'\n  → {len(blocs)} annale(s) détectée(s)')

    for b in blocs:
        writer = PdfWriter()
        for idx in b['indices']:
            writer.add_page(reader.pages[idx])

        nom = f'{base}_{b["cle"]}.pdf'
        with open(outdir / nom, 'wb') as f:
            writer.write(f)

        print(f'  ✅ {nom} ({len(b["indices"])} p.)')
        ok += 1

    return ok


# ──────────────────────────────────────────────
# POINT D'ENTRÉE
# ──────────────────────────────────────────────
def main():
    debug = '--debug' in sys.argv
    args  = [a for a in sys.argv[1:] if a != '--debug']

    print(f'\nExamensCam — Découpeur par année')
    print(f'  Tesseract : {"✅" if TESS_OK else "❌"}')
    print(f'  Vision    : {"✅" if VISION_OK else "❌"}')

    if args:
        cible = Path(args[0])
        if not cible.exists():
            print(f'❌ Introuvable : {cible}')
            sys.exit(1)
        pdfs = list(cible.glob('*.pdf')) if cible.is_dir() else [cible]
    else:
        RAW.mkdir(parents=True, exist_ok=True)
        OUTPUT_BASE.mkdir(parents=True, exist_ok=True)
        pdfs = sorted(RAW.glob('*.pdf'))

    if not pdfs:
        print(f'📂 Aucun PDF dans {RAW}/')
        sys.exit(0)

    print(f'\n🔍 {len(pdfs)} PDF(s)\n')
    total = 0
    for p in pdfs:
        try:
            total += decouper_pdf(p, debug=debug) or 0
        except Exception as e:
            print(f'  ❌ {p.name} : {e}')

    print(f'\n{"═"*55}')
    print(f'✅ {total} fichier(s) → {OUTPUT_BASE}/')


if __name__ == '__main__':
    main()