"""
Nettoyage de filigranes sur des images (screenshots d'exercices).
Détecte le texte via OCR (easyocr) et recouvre les zones de filigrane.
"""

import cv2
import numpy as np
from pathlib import Path
from PIL import Image
import easyocr

FILIGRANES_CONNUS = [
    'educamer', 'edumathcamer', 'mongosukulu', 'easy-maths',
    'easymaths', 'sujetexa', 'maxiepreuves', 'camscanner',
    'prépas probatoire', 'prepas probatoire', 'be ready for your probat',
    'powered by', 'téléchargez gratuitement', 'telechargez gratuitement',
    'annales probatoire', 'http://maths', 'www.edumathcamer',
    'www.mongosukulu', 'www.easy-maths', 'http://sujetexa',
    'scanner', 'scanné', 'scanne', 'pdf scanner', 'document scanner',
    'adobe scan', 'office lens', 'vflat', 'genius scan',
]

_reader = None

def get_ocr_reader():
    global _reader
    if _reader is None:
        print(" 🔄 Chargement du modèle OCR (première fois, ~10s)...")
        _reader = easyocr.Reader(['fr', 'en'], gpu=False)
    return _reader

def contient_filigrane(texte: str) -> bool:
    texte_lower = texte.lower().replace('-', '').replace(' ', '')
    for mot in FILIGRANES_CONNUS:
        mot_clean = mot.lower().replace('-', '').replace(' ', '')
        if mot_clean in texte_lower or texte_lower in mot_clean:
            return True
    return False

def trouver_zones_filigrane(image_path: str, confiance_min: float = 0.3):
    """
    Utilise EasyOCR pour trouver les coordonnées des filigranes sur une image.
    Retourne: liste de tuples (x_min, y_min, x_max, y_max)
    """
    reader = get_ocr_reader()
    img = cv2.imread(str(image_path))
    if img is None:
        raise ValueError(f"Impossible de lire l'image: {image_path}")
    
    hauteur = img.shape[0]
    largeur = img.shape[1]
    
    resultats = reader.readtext(str(image_path), detail=1)
    
    zones = []
    for (bbox, texte, confiance) in resultats:
        if confiance < confiance_min:
            continue
        if contient_filigrane(texte):
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x_min, x_max = int(min(xs)), int(max(xs))
            y_min, y_max = int(min(ys)), int(max(ys))
            
            x_min = max(0, x_min - 10)
            y_min = max(0, y_min - 5)
            x_max = min(largeur, x_max + 10)
            y_max = min(hauteur, y_max + 5)
            
            zones.append((x_min, y_min, x_max, y_max))
            print(f"   🔍 Filigrane détecté: '{texte}' → zone ({x_min},{y_min},{x_max},{y_max})")
    
    return zones

def fusionner_zones(zones, marge_y: int = 30):
    """Fusionne les zones proches verticalement en bandes horizontales."""
    if not zones:
        return zones
    
    zones_sorted = sorted(zones, key=lambda z: z[1])
    fusionnees = []
    
    for z in zones_sorted:
        x1, y1, x2, y2 = z
        merged = False
        
        for i, f in enumerate(fusionnees):
            fx1, fy1, fx2, fy2 = f
            if abs(y1 - fy1) < marge_y or abs(y2 - fy2) < marge_y:
                new_x1 = 0
                new_x2 = max(x2, fx2)
                new_y1 = min(y1, fy1) - 3
                new_y2 = max(y2, fy2) + 3
                fusionnees[i] = (new_x1, new_y1, new_x2, new_y2)
                merged = True
                break
        
        if not merged:
            fusionnees.append((0, y1 - 3, x2 + 10, y2 + 3))
    
    final = []
    for z in fusionnees:
        _, y1, _, y2 = z
        final.append((0, y1, 99999, y2))
    
    return final

def nettoyer_image(input_path: str, output_path: str, methode: str = "inpaint") -> bool:
    """
    Nettoie les filigranes d'une image.
    méthodes: 'inpaint' (reconstruction), 'blanc' (rectangle blanc), 'moyenne' (couleur moyenne)
    """
    print(f"\n📷 Traitement: {Path(input_path).name}")
    
    img = cv2.imread(str(input_path))
    if img is None:
        print(f" ❌ Impossible de lire l'image")
        return False
    
    hauteur, largeur = img.shape[:2]
    
    zones = trouver_zones_filigrane(input_path)
    zones = fusionner_zones(zones)
    
    zones = [(max(0,x1), max(0,y1), min(largeur,x2), min(hauteur,y2)) for (x1,y1,x2,y2) in zones]
    zones = [z for z in zones if z[2] > z[0] and z[3] > z[1]]
    
    if not zones:
        print(f" ℹ️ Aucun filigrane détecté — copie sans modification")
        Image.open(input_path).save(output_path, quality=95)
        return True
    
    print(f" 🎯 {len(zones)} zone(s) à nettoyer")
    
    masque = np.zeros((hauteur, largeur), dtype=np.uint8)
    for (x1, y1, x2, y2) in zones:
        masque[y1:y2, x1:x2] = 255
        print(f"   → Bande y={y1}-{y2}, toute la largeur")
    
    if methode == "inpaint":
        resultat = cv2.inpaint(img, masque, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
    elif methode == "ns":
        resultat = cv2.inpaint(img, masque, inpaintRadius=3, flags=cv2.INPAINT_NS)
    elif methode == "blanc":
        resultat = img.copy()
        resultat[masque > 0] = [255, 255, 255]
    elif methode == "moyenne":
        resultat = img.copy()
        couleur_moy = np.mean(img[masque == 0], axis=0) if np.any(masque == 0) else [255,255,255]
        resultat[masque > 0] = couleur_moy
    else:
        resultat = cv2.inpaint(img, masque, inpaintRadius=3, flags=cv2.INPAINT_TELEA)
    
    cv2.imwrite(str(output_path), resultat, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f" ✅ Nettoyé → {output_path}")
    return True

def nettoyer_dossier_images(dossier_input: str, dossier_output: str, methode: str = "inpaint") -> dict:
    input_dir = Path(dossier_input)
    output_dir = Path(dossier_output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    extensions = ('*.png', '*.jpg', '*.jpeg', '*.bmp', '*.tiff', '*.webp')
    images = []
    for ext in extensions:
        images.extend(input_dir.glob(ext))
        images.extend(input_dir.glob(ext.upper()))
    
    images = sorted(set(images))
    
    rapport = {'réussis': [], 'échoués': []}
    
    print(f"\n{'='*50}")
    print(f"📂 {len(images)} image(s) à traiter")
    print(f"{'='*50}")
    
    for img_path in images:
        sortie = output_dir / img_path.name
        if nettoyer_image(str(img_path), str(sortie), methode):
            rapport['réussis'].append(img_path.name)
        else:
            rapport['échoués'].append(img_path.name)
    
    print(f"\n{'='*50}")
    print(f"📊 {len(rapport['réussis'])} réussis / {len(rapport['échoués'])} échoués")
    print(f"{'='*50}")
    return rapport

if __name__ == '__main__':
    nettoyer_dossier_images('data/screenshots', 'data/images_clean')