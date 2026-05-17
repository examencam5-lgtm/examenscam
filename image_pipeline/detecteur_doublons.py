"""
Détecte les exercices redondants (même exercice photographié 2 fois)
et fusionne les meilleures versions.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple
import Levenshtein
from dataclasses import dataclass


@dataclass
class ExerciceCandidate:
    chemin: str
    nom: str
    numero: str
    sujet: str
    contenu: str
    qualite: float
    image: np.ndarray
    analyse: Dict


def calculer_similarite_texte(texte1: str, texte2: str) -> float:
    """
    Calcule la similarité entre deux textes (0 à 1).
    """
    if not texte1 or not texte2:
        return 0.0
    
    distance = Levenshtein.distance(texte1.lower(), texte2.lower())
    max_len = max(len(texte1), len(texte2))
    
    if max_len == 0:
        return 1.0
    
    return 1.0 - (distance / max_len)


def calculer_similarite_visuelle(img1: np.ndarray, img2: np.ndarray) -> float:
    """
    Compare visuellement deux images (histogramme + ORB).
    """
    h, w = 400, 300
    r1 = cv2.resize(img1, (w, h))
    r2 = cv2.resize(img2, (w, h))
    
    hist1 = cv2.calcHist([r1], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    hist2 = cv2.calcHist([r2], [0, 1, 2], None, [8, 8, 8], [0, 256, 0, 256, 0, 256])
    
    hist1 = cv2.normalize(hist1, hist1).flatten()
    hist2 = cv2.normalize(hist2, hist2).flatten()
    
    sim_hist = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
    
    orb = cv2.ORB_create(nfeatures=100)
    kp1, des1 = orb.detectAndCompute(cv2.cvtColor(r1, cv2.COLOR_BGR2GRAY), None)
    kp2, des2 = orb.detectAndCompute(cv2.cvtColor(r2, cv2.COLOR_BGR2GRAY), None)
    
    if des1 is None or des2 is None or len(des1) < 10 or len(des2) < 10:
        sim_orb = 0.5
    else:
        bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = bf.match(des1, des2)
        sim_orb = len(matches) / max(len(des1), len(des2))
    
    return 0.6 * max(0, sim_hist) + 0.4 * sim_orb


def sont_doublons(ex1: ExerciceCandidate, ex2: ExerciceCandidate, seuil: float = 0.75) -> bool:
    """
    Détermine si deux exercices sont des doublons.
    """
    if ex1.nom == ex2.nom and ex1.numero == ex2.numero and ex1.numero != "XX":
        return True
    
    sim_texte = calculer_similarite_texte(ex1.contenu, ex2.contenu)
    if sim_texte > 0.85:
        return True
    
    sim_visuelle = calculer_similarite_visuelle(ex1.image, ex2.image)
    score_combined = 0.5 * sim_texte + 0.5 * sim_visuelle
    
    return score_combined > seuil


def fusionner_exercices(doublons: List[ExerciceCandidate]) -> ExerciceCandidate:
    """
    Fusionne plusieurs versions d'un même exercice en gardant le meilleur.
    """
    if len(doublons) == 1:
        return doublons[0]
    
    meilleur = max(doublons, key=lambda e: e.qualite * e.image.shape[0] * e.image.shape[1])
    
    print(f"   🔗 Fusion de {len(doublons)} versions → {meilleur.nom}")
    for d in doublons:
        if d.chemin != meilleur.chemin:
            print(f"      └─ Supprimé: {Path(d.chemin).name}")
    
    return meilleur


def dedupliquer_exercices(candidates: List[ExerciceCandidate]) -> List[ExerciceCandidate]:
    """
    Déduplique une liste d'exercices et retourne les uniques.
    """
    if not candidates:
        return []
    
    candidates.sort(key=lambda c: c.nom)
    
    groupes = []
    groupe_actuel = [candidates[0]]
    
    for i in range(1, len(candidates)):
        if sont_doublons(candidates[i], groupe_actuel[0]):
            groupe_actuel.append(candidates[i])
        else:
            groupes.append(groupe_actuel)
            groupe_actuel = [candidates[i]]
    
    groupes.append(groupe_actuel)
    
    uniques = []
    for groupe in groupes:
        unique = fusionner_exercices(groupe)
        uniques.append(unique)
    
    uniques.sort(key=lambda u: u.nom)
    
    for i, ex in enumerate(uniques):
        if ex.numero == "XX":
            ex.nom = f"Exercice_{i+1:02d}"
            ex.numero = f"{i+1:02d}"
    
    return uniques