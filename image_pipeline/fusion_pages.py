"""
Fusionne 2 screenshots qui représentent la suite d'un même exercice.
Détecte: continuité du texte, numérotation, formules coupées.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional
import easyocr


_reader = None

def get_ocr_reader():
    global _reader
    if _reader is None:
        print(" 🔄 Chargement OCR...")
        _reader = easyocr.Reader(['fr', 'en'], gpu=False)
    return _reader


def extraire_texte_bas(image: np.ndarray) -> str:
    """Extrait le texte du bas de l'image (30% inférieur)."""
    h = image.shape[0]
    zone_bas = image[int(h*0.7):, :]
    
    reader = get_ocr_reader()
    resultats = reader.readtext(zone_bas, detail=0)
    return " ".join(resultats).lower()


def extraire_texte_haut(image: np.ndarray) -> str:
    """Extrait le texte du haut de l'image (30% supérieur)."""
    h = image.shape[0]
    zone_haut = image[:int(h*0.3), :]
    
    reader = get_ocr_reader()
    resultats = reader.readtext(zone_haut, detail=0)
    return " ".join(resultats).lower()


def score_continuite(bas_page1: str, haut_page2: str) -> float:
    """
    Calcule un score de continuité entre la fin d'une page et le début de la suivante.
    """
    mots_bas = set(bas_page1.split())
    mots_haut = set(haut_page2.split())
    
    if not mots_bas or not mots_haut:
        return 0.0
    
    communs = mots_bas & mots_haut
    score = len(communs) / max(len(mots_bas), len(mots_haut))
    
    continuations = ['suite', 'donc', 'ainsi', 'or', 'de plus', 'par ailleurs',
                     'en effet', "d'où", 'alors', 'ainsi', 'rappelons',
                     'question', 'exercice', 'partie', 'b)', 'c)', 'd)',
                     '2.', '3.', 'ii)', 'iii)']
    
    texte_haut_complet = haut_page2
    for cont in continuations:
        if cont in texte_haut_complet:
            score += 0.3
    
    nouveaux = ['exercice 1', 'exercice 2', 'exercice 3', 'exercice i',
                'problème 1', 'partie a', '1.', 'a)']
    for nouv in nouveaux:
        if nouv in texte_haut_complet[:50]:
            score -= 0.5
    
    return min(1.0, max(0.0, score))


def sont_pages_consecutives(img1: np.ndarray, img2: np.ndarray, seuil: float = 0.3) -> bool:
    """Détermine si 2 images sont des pages consécutives d'un même exercice."""
    bas_p1 = extraire_texte_bas(img1)
    haut_p2 = extraire_texte_haut(img2)
    
    score = score_continuite(bas_p1, haut_p2)
    print(f"   Score continuité: {score:.2f}")
    
    return score > seuil


def fusionner_images_verticale(img1: np.ndarray, img2: np.ndarray, chevauchement: int = 50) -> np.ndarray:
    """
    Fusionne 2 images verticalement en éliminant le chevauchement.
    """
    h1, w1 = img1.shape[:2]
    h2, w2 = img2.shape[:2]
    
    w = max(w1, w2)
    if w1 != w:
        img1 = cv2.resize(img1, (w, h1))
    if w2 != w:
        img2 = cv2.resize(img2, (w, h2))
    
    zone_transition = min(chevauchement, h1 // 4, h2 // 4)
    
    partie_haute = img1[:-zone_transition, :]
    partie_basse = img2[zone_transition:, :]
    
    transition = np.zeros((zone_transition, w, 3), dtype=np.uint8)
    for i in range(zone_transition):
        alpha = i / zone_transition
        idx1 = h1 - zone_transition + i
        idx2 = i
        if idx1 < h1 and idx2 < h2:
            transition[i] = (1 - alpha) * img1[idx1] + alpha * img2[idx2]
    
    resultat = np.vstack([partie_haute, transition, partie_basse])
    
    return resultat


def grouper_pages_consecutives(chemins_images: List[str]) -> List[List[str]]:
    """
    Groupe les images en séquences de pages consécutives.
    Retourne des groupes: [['page1.png'], ['page2a.png', 'page2b.png'], ...]
    """
    if not chemins_images:
        return []
    
    chemins = sorted(chemins_images)
    
    groupes = [[chemins[0]]]
    
    for i in range(1, len(chemins)):
        img_prev = cv2.imread(chemins[i-1])
        img_curr = cv2.imread(chemins[i])
        
        if img_prev is None or img_curr is None:
            groupes.append([chemins[i]])
            continue
        
        if sont_pages_consecutives(img_prev, img_curr):
            groupes[-1].append(chemins[i])
            print(f"   🔗 Fusion: {Path(chemins[i-1]).name} + {Path(chemins[i]).name}")
        else:
            groupes.append([chemins[i]])
    
    return groupes