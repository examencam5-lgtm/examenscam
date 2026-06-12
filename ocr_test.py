# test_ocr.py — à créer à la racine du projet
import pypdfium2 as pdfium
from PIL import Image, ImageEnhance
import pytesseract
from pathlib import Path

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

PDF = Path(r'C:\Users\GENIUS ELECTRONICS\examenscam\pdf_pipeline\outputs\BACC-E1999-2025\BACC-E1999-2025_2019.pdf')
doc = pdfium.PdfDocument(str(PDF))
print(f'{len(doc)} pages\n')

for i in range(min(4, len(doc))):
    page   = doc[i]
    bitmap = page.render(scale=3.0)
    img    = bitmap.to_pil()
    w, h   = img.size

    # En-tête : 35% supérieur
    header = img.crop((0, 0, w, int(h * 0.35)))
    header = header.convert('L')
    header = ImageEnhance.Contrast(header).enhance(2.0)
    header = header.point(lambda p: 255 if p > 150 else 0)
    header.save(f'debug_p{i+1}.png')

    texte = pytesseract.image_to_string(header, config='--oem 3 --psm 6 -l fra+eng')
    print(f'--- Page {i+1} ---')
    print(texte[:200])
    print()