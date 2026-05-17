"""
Découpe intelligente des screenshots pour isoler les exercices.
Gère: bords irréguliers, pages coupées, inclinaison, fonds variés.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional
import math


def detecter_inclinaison(image: np.ndarray) -> float:
    """Détecte l'angle d'inclinaison du texte via transformée de Hough."""
    gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binaire = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    lignes = cv2.HoughLinesP(binaire, 1, np.pi/180, 100, minLineLength=100, maxLineGap=10)
    
    if lignes is None or len(lignes) == 0:
        return 0.0
    
    angles = []
    for ligne in lignes:
        x1, y1, x2, y2 = ligne[0]
        if abs(x2 - x1) > 10:
            angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
            if -45 < angle < 45:
                angles.append(angle)
    
    return np.median(angles) if angles else 0.0


def redresser_image(image: np.ndarray, angle: float) -> np.ndarray:
    """Redresse l'image selon l'angle détecté."""
    if abs(angle) < 0.5:
        return image
    
    h, w = image.shape[:2]
    centre = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(centre, angle, 1.0)
    
    cos = abs(np.cos(np.radians(angle)))
    sin = abs(np.sin(np.radians(angle)))
    new_w = int(h * sin + w * cos)
    new_h = int(h * cos + w * sin)
    
    M[0, 2] += (new_w - w) / 2
    M[1, 2] += (new_h - h) / 2
    
    return cv2.warpAffine(image, M, (new_w, new_h), borderValue=(255, 255, 255))


def trouver_zone_texte(image: np.ndarray, marge: int = 20) -> Tuple[int, int, int, int]:
    """
    Trouve la zone contenant du texte en analysant la densité de pixels sombres.
    Retourne: (x, y, largeur, hauteur)
    """
    gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    binaire = cv2.adaptiveThreshold(
        gris, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY_INV, 15, 10
    )
    
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 5))
    dilate = cv2.dilate(binaire, kernel, iterations=2)
    
    contours, _ = cv2.findContours(dilate, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return (0, 0, image.shape[1], image.shape[0])
    
    zones_significatives = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        aire = w * h
        if aire > 5000:
            zones_significatives.append((x, y, w, h))
    
    if not zones_significatives:
        return (0, 0, image.shape[1], image.shape[0])
    
    x_min = min(z[0] for z in zones_significatives)
    y_min = min(z[1] for z in zones_significatives)
    x_max = max(z[0] + z[2] for z in zones_significatives)
    y_max = max(z[1] + z[3] for z in zones_significatives)
    
    x_min = max(0, x_min - marge)
    y_min = max(0, y_min - marge)
    x_max = min(image.shape[1], x_max + marge)
    y_max = min(image.shape[0], y_max + marge)
    
    return (x_min, y_min, x_max - x_min, y_max - y_min)


def detecter_lignes_separation(image: np.ndarray) -> List[int]:
    """
    Détecte les lignes horizontales qui séparent les exercices.
    Retourne les positions Y des séparations.
    """
    gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binaire = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    
    projection = np.sum(binaire, axis=1)
    projection_lisse = np.convolve(projection, np.ones(20)/20, mode='same')
    
    moyenne = np.mean(projection_lisse)
    creux = []
    
    for i, val in enumerate(projection_lisse):
        if val < moyenne * 0.15:
            creux.append(i)
    
    if not creux:
        return []
    
    groupes = [[creux[0]]]
    for c in creux[1:]:
        if c - groupes[-1][-1] < 50:
            groupes[-1].append(c)
        else:
            groupes.append([c])
    
    separations = [int(np.mean(g)) for g in groupes]
    
    hauteur = image.shape[0]
    separations = [s for s in separations if 100 < s < hauteur - 100]
    
    return separations


def decouper_exercices(image_path: str) -> List[np.ndarray]:
    """
    Découpe un screenshot en un ou plusieurs exercices.
    Gère: inclinaison, bords irréguliers, multi-exercices par page.
    """
    image = cv2.imread(str(image_path))
    if image is None:
        return []
    
    print(f"\n📷 Analyse: {Path(image_path).name}")
    
    angle = detecter_inclinaison(image)
    if abs(angle) > 0.5:
        print(f"   ↺ Redressement: {angle:.1f}°")
        image = redresser_image(image, angle)
    
    x, y, w, h = trouver_zone_texte(image)
    image_croppee = image[y:y+h, x:x+w]
    print(f"   ✂️ Crop: ({x},{y}) {w}x{h}")
    
    separations = detecter_lignes_separation(image_croppee)
    
    if not separations or len(separations) == 0:
        print(f"   📄 1 exercice détecté")
        return [image_croppee]
    
    exercices = []
    y_positions = [0] + separations + [image_croppee.shape[0]]
    
    for i in range(len(y_positions) - 1):
        y1 = y_positions[i]
        y2 = y_positions[i + 1]
        
        zone = image_croppee[y1:y2, :]
        gris = cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY)
        if np.mean(gris) < 250:
            exercices.append(zone)
    
    print(f"   📄 {len(exercices)} exercice(s) détecté(s)")
    return exercices


def sauver_exercices(image_path: str, output_dir: str, prefix: str) -> List[str]:
    """
    Découpe et sauvegarde les exercices d'une image.
    Retourne la liste des chemins créés.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    exercices = decouper_exercices(image_path)
    chemins = []
    
    for i, exo in enumerate(exercices):
        h, w = exo.shape[:2]
        marge = 40
        avec_marge = np.full((h + 2*marge, w + 2*marge, 3), 255, dtype=np.uint8)
        avec_marge[marge:marge+h, marge:marge+w] = exo
        
        nom = f"{prefix}_part{i+1}.png"
        chemin = output_dir / nom
        cv2.imwrite(str(chemin), avec_marge)
        chemins.append(str(chemin))
    
    return chemins