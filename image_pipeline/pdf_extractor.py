"""
Extracteur d'exercices depuis des PDFs d'épreuves scannées.
Découpe chaque épreuve en exercices individuels avec texte, figures et tableaux conservés.
"""

import cv2
import numpy as np
from pathlib import Path
import re
import fitz  # PyMuPDF
from PIL import Image
import shutil


def extraire_pages_pdf(chemin_pdf: str, dossier_temp: str) -> list:
    """
    Extrait chaque page du PDF en image haute qualité.
    """
    doc = fitz.open(chemin_pdf)
    pages_images = []
    
    dossier_temp = Path(dossier_temp)
    dossier_temp.mkdir(parents=True, exist_ok=True)
    
    for i, page in enumerate(doc):
        # Rendu haute résolution (300 DPI)
        mat = fitz.Matrix(3, 3)
        pix = page.get_pixmap(matrix=mat)
        
        chemin_image = dossier_temp / f"page_{i+1:02d}.png"
        pix.save(str(chemin_image))
        pages_images.append(str(chemin_image))
        
        print(f"   📄 Page {i+1} extraite")
    
    doc.close()
    return pages_images


def nettoyer_image(image_path: str) -> np.ndarray:
    """
    Nettoie l'image : supprime QR codes, filigranes, mais GARDE le contenu principal.
    """
    img = cv2.imread(str(image_path))
    if img is None:
        return None
    
    h, w = img.shape[:2]
    
    # 1. Supprimer les QR codes (coins supérieurs et inférieurs)
    marge_qr = int(min(h, w) * 0.15)
    
    # Masquer les 4 coins (où sont les QR codes)
    img[0:marge_qr, 0:marge_qr] = [255, 255, 255]  # Haut-gauche
    img[0:marge_qr, w-marge_qr:w] = [255, 255, 255]  # Haut-droite
    img[h-marge_qr:h, 0:marge_qr] = [255, 255, 255]  # Bas-gauche
    img[h-marge_qr:h, w-marge_qr:w] = [255, 255, 255]  # Bas-droite
    
    # 2. Supprimer les bandes de filigranes (haut et bas de page)
    bande = int(h * 0.08)
    img[0:bande, :] = [255, 255, 255]  # Bande haute
    img[h-bande:h, :] = [255, 255, 255]  # Bande basse
    
    return img


def detecter_separations(image: np.ndarray) -> list:
    """
    Détecte les lignes de séparation entre exercices.
    Cherche "Exercice X", "Partie B", etc.
    """
    h, w = image.shape[:2]
    
    # Zone de recherche : haut de page (où sont les titres)
    zone_titre = image[0:int(h*0.15), :]
    
    # Convertir en gris pour analyse
    gris = cv2.cvtColor(zone_titre, cv2.COLOR_BGR2GRAY)
    _, binaire = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    # Projeter horizontalement pour trouver les lignes de texte
    projection = np.sum(binaire, axis=1)
    
    # Les pics = lignes de texte (titres d'exercices)
    seuil = np.mean(projection) * 2
    lignes_texte = np.where(projection > seuil)[0]
    
    if len(lignes_texte) == 0:
        return []
    
    # Grouper les lignes proches
    groupes = [[lignes_texte[0]]]
    for ligne in lignes_texte[1:]:
        if ligne - groupes[-1][-1] < 30:
            groupes[-1].append(ligne)
        else:
            groupes.append([ligne])
    
    # Prendre le milieu de chaque groupe
    positions = [int(np.mean(g)) for g in groupes]
    
    return positions


def decouper_exercices(image: np.ndarray, positions: list) -> list:
    """
    Découpe l'image en zones d'exercices selon les positions détectées.
    """
    if not positions:
        return [image]
    
    h, w = image.shape[:2]
    exercices = []
    
    # Ajouter le début et la fin
    y_positions = [0] + positions + [h]
    
    for i in range(len(y_positions) - 1):
        y1 = y_positions[i]
        y2 = y_positions[i + 1]
        
        # Vérifier que la zone contient du contenu
        zone = image[y1:y2, :]
        gris = cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY)
        
        # Si pas juste du blanc
        if np.mean(gris) < 250:
            # Ajouter une petite marge
            y1 = max(0, y1 - 10)
            y2 = min(h, y2 + 10)
            exercices.append(image[y1:y2, :])
    
    return exercices


def generer_pdf_exercice(image: np.ndarray, output_path: str, metadata: dict):
    """
    Génère un PDF propre à partir d'une image d'exercice.
    """
    h, w = image.shape[:2]
    
    # Créer le PDF avec la bonne taille
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    
    # Calculer les dimensions pour A4
    a4_w, a4_h = A4
    
    c = canvas.Canvas(output_path, pagesize=A4)
    
    # Sauvegarder temporairement l'image
    temp_path = output_path.replace('.pdf', '_temp.png')
    cv2.imwrite(temp_path, image)
    
    # Dessiner l'image centrée
    ratio = min(a4_w / w, a4_h / h)
    new_w = w * ratio * 0.95  # 95% pour la marge
    new_h = h * ratio * 0.95
    
    x = (a4_w - new_w) / 2
    y = (a4_h - new_h) / 2
    
    c.drawImage(temp_path, x, y, width=new_w, height=new_h)
    c.save()
    
    # Nettoyer
    Path(temp_path).unlink(missing_ok=True)
    
    print(f"   ✅ PDF généré: {Path(output_path).name}")


def extraire_metadonnees(image: np.ndarray) -> dict:
    """
    Essaie d'extraire les métadonnées de l'exercice (numéro, points).
    """
    import easyocr
    
    reader = easyocr.Reader(['fr'], gpu=False)
    
    # Zone du titre (haut de l'image)
    h = image.shape[0]
    zone_titre = image[0:int(h*0.15), :]
    
    resultats = reader.readtext(zone_titre, detail=0)
    texte_titre = " ".join(resultats).lower()
    
    metadata = {
        'numero': None,
        'points': None,
        'type': 'exercice'
    }
    
    # Détecter "Exercice X"
    match_exo = re.search(r'exercice\s*(\d+)', texte_titre)
    if match_exo:
        metadata['numero'] = int(match_exo.group(1))
    
    # Détecter "Partie B"
    if 'partie b' in texte_titre or 'competence' in texte_titre:
        metadata['type'] = 'partie_b'
        metadata['numero'] = 'B'
    
    # Détecter les points "(5 points)"
    match_pts = re.search(r'(\d+)\s*points?', texte_titre)
    if match_pts:
        metadata['points'] = int(match_pts.group(1))
    
    return metadata


def traiter_epreuve(chemin_pdf: str, dossier_output: str, annee: int, examen: str, serie: str):
    """
    Traite une épreuve complète : extrait, nettoie, découpe, génère les PDFs.
    """
    print(f"\n{'='*60}")
    print(f"📄 Traitement: {Path(chemin_pdf).name}")
    print(f"   Année: {annee}, Examen: {examen}, Série: {serie}")
    print(f"{'='*60}")
    
    # Dossiers temporaires
    temp_dir = Path('data/temp_extraction')
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Dossier de sortie
    output_dir = Path(dossier_output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. Extraire les pages
    print("\n🔹 Étape 1: Extraction des pages")
    pages = extraire_pages_pdf(chemin_pdf, str(temp_dir / 'pages'))
    
    # 2. Traiter chaque page
    print("\n🔹 Étape 2: Nettoyage et découpage")
    tous_exercices = []
    
    for page_path in pages:
        img = nettoyer_image(page_path)
        if img is None:
            continue
        
        # Détecter les séparations
        separations = detecter_separations(img)
        
        # Découper en exercices
        exercices = decouper_exercices(img, separations)
        tous_exercices.extend(exercices)
        
        print(f"   📄 {len(exercices)} exercice(s) sur cette page")
    
    # 3. Générer les PDFs individuels
    print(f"\n🔹 Étape 3: Génération des PDFs ({len(tous_exercices)} exercices)")
    
    for i, exo_img in enumerate(tous_exercices, 1):
        # Extraire métadonnées
        meta = extraire_metadonnees(exo_img)
        
        # Construire le nom
        numero = meta.get('numero') or i
        points = meta.get('points') or 'X'
        
        nom_fichier = f"{annee}_{examen}_{serie}_Exo{numero}_{points}pts.pdf"
        chemin_output = output_dir / nom_fichier
        
        # Éviter les doublons
        compteur = 1
        while chemin_output.exists():
            nom_fichier = f"{annee}_{examen}_{serie}_Exo{numero}_{points}pts_{compteur}.pdf"
            chemin_output = output_dir / nom_fichier
            compteur += 1
        
        # Générer le PDF
        generer_pdf_exercice(exo_img, str(chemin_output), meta)
    
    # Nettoyer
    shutil.rmtree(temp_dir)
    
    print(f"\n✅ Terminé: {len(tous_exercices)} exercices générés")
    return len(tous_exercices)


def traiter_dossier_epreuves(dossier_input: str, dossier_output: str):
    """
    Traite toutes les épreuves d'un dossier.
    """
    input_dir = Path(dossier_input)
    output_dir = Path(dossier_output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Chercher tous les PDFs
    pdfs = list(input_dir.glob('*.pdf'))
    
    print(f"\n{'='*70}")
    print(f"  🤖 TRAITEMENT MASSIF: {len(pdfs)} épreuve(s)")
    print(f"{'='*70}")
    
    total_exercices = 0
    
    for pdf in sorted(pdfs):
        # Essayer d'extraire les infos du nom de fichier
        # Format attendu: 2025_Probatoire_D.pdf ou Probatoire_D_2025.pdf
        nom = pdf.stem.lower()
        
        # Détection simple
        annee = 2025  # Par défaut
        examen = 'probatoire'
        serie = 'D'
        
        # Chercher l'année
        match_annee = re.search(r'(20\d{2})', nom)
        if match_annee:
            annee = int(match_annee.group(1))
        
        # Chercher la série
        if '_c' in nom or ' serie c' in nom:
            serie = 'C'
        elif '_e' in nom or ' serie e' in nom:
            serie = 'E'
        elif '_ti' in nom or ' serie ti' in nom:
            serie = 'TI'
        
        # Chercher le type d'examen
        if 'bac' in nom:
            examen = 'bac'
        elif 'bepc' in nom:
            examen = 'bepc'
        elif 'blanc' in nom:
            examen = 'blanc'
        
        # Traiter
        nb = traiter_epreuve(str(pdf), str(output_dir), annee, examen, serie)
        total_exercices += nb
    
    print(f"\n{'='*70}")
    print(f"  🎉 TOTAL: {total_exercices} exercices extraits de {len(pdfs)} épreuves")
    print(f"  📁 Résultats dans: {output_dir.absolute()}")
    print(f"{'='*70}")


if __name__ == '__main__':
    # Mode simple: traiter un dossier
    traiter_dossier_epreuves('data/epreuves_completes', 'data/exercices_pdf')