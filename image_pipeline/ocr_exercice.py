"""
OCR spécialisé pour extraire le nom, le sujet et le contenu d'exercices scolaires.
"""

import cv2
import numpy as np
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import easyocr


_reader = None

def get_ocr_reader():
    global _reader
    if _reader is None:
        print(" 🔄 Chargement modèle OCR...")
        _reader = easyocr.Reader(['fr', 'en'], gpu=False)
    return _reader


# Patterns pour reconnaître les titres d'exercices
PATTERNS_EXERCICE = [
    r'exercice\s*([0-9]+[a-zA-Z]?)',
    r'exo\s*([0-9]+[a-zA-Z]?)',
    r'probl[eè]me\s*([0-9]+[a-zA-Z]?)',
    r'question\s*([0-9]+[a-zA-Z]?)',
    r'partie\s*([0-9]+[a-zA-Z]?)',
    r'tp\s*([0-9]+[a-zA-Z]?)',
    r'td\s*([0-9]+[a-zA-Z]?)',
    r'devoir\s*([0-9]+[a-zA-Z]?)',
    r'interrogation\s*([0-9]+[a-zA-Z]?)',
    r'sujet\s*([0-9]+[a-zA-Z]?)',
    r'ann[eé]e\s*([0-9]{4})',
    r'session\s*([0-9]{4})',
    r's[eé]rie\s*([A-Z][0-9]?)',
]

# Patterns pour le sujet/mathématique
PATTERNS_SUJET = {
    'algebre': ['algèbre', 'algebre', 'polynôme', 'polynome', 'équation', 'equation', 
                'inéquation', 'inequation', 'fonction', 'ensemble', 'complexe', 'matrice'],
    'analyse': ['analyse', 'limite', 'continuité', 'continuite', 'dérivée', 'derivee',
                'intégrale', 'integrale', 'série', 'serie', 'suite', 'primitive'],
    'geometrie': ['géométrie', 'geometrie', 'triangle', 'cercle', 'droite', 'plan',
                  'vecteur', 'angle', 'distance', 'aire', 'volume', 'espace'],
    'trigonometrie': ['trigonométrie', 'trigonometrie', 'sinus', 'cosinus', 'tangente',
                      'angle', 'radian', 'degré'],
    'probabilites': ['probabilité', 'probabilités', 'proba', 'statistique', 'loi',
                     'binomiale', 'normale', 'espérance', 'variance'],
    'arithmetique': ['arithmétique', 'arithmetique', 'divisibilité', 'premier', 'modulo',
                     'pgcd', 'ppcm', 'congruence'],
    'logique': ['logique', 'raisonnement', 'récurrence', 'recurrence', 'démonstration',
                'demonstration', 'preuve'],
    'nombres_complexes': ['complexe', 'imaginaire', 'module', 'argument', 'affixe'],
    'fonctions': ['fonction', 'bijection', 'composition', 'réciproque', 'reciproque'],
    'suites': ['suite', 'récurrente', 'recurrente', 'arithmético-géométrique'],
}


def extraire_texte_complet(image: np.ndarray, detail: int = 1) -> List[Dict]:
    """
    Extrait tout le texte d'une image avec positions et confiances.
    """
    reader = get_ocr_reader()
    resultats = reader.readtext(image, detail=detail, paragraph=False)
    
    blocs = []
    for item in resultats:
        if detail == 1:
            (bbox, texte, confiance) = item
            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
        else:
            texte = item
            confiance = 0.5
            x_min = y_min = x_max = y_max = 0
        
        blocs.append({
            'texte': texte.strip(),
            'x': x_min,
            'y': y_min,
            'w': x_max - x_min,
            'h': y_max - y_min,
            'centre_x': (x_min + x_max) / 2,
            'centre_y': (y_min + y_max) / 2,
            'confiance': confiance
        })
    
    blocs.sort(key=lambda b: b['y'])
    return blocs


def detecter_nom_exercice(blocs: List[Dict]) -> Tuple[str, str]:
    """
    Détecte le vrai nom de l'exercice et son numéro.
    Retourne: (nom_complet, numero)
    """
    if not blocs:
        return ("Exercice_inconnu", "XX")
    
    hauteur_max = max(b['y'] + b['h'] for b in blocs) if blocs else 1000
    limite_haut = hauteur_max * 0.35
    
    textes_haut = [b['texte'] for b in blocs if b['y'] < limite_haut]
    texte_complet_haut = " ".join(textes_haut).lower()
    
    for pattern in PATTERNS_EXERCICE:
        matches = re.finditer(pattern, texte_complet_haut, re.IGNORECASE)
        for match in matches:
            numero = match.group(1).upper()
            mot = match.group(0).lower()
            if 'problème' in mot or 'probleme' in mot:
                return (f"Probleme_{numero}", numero)
            elif 'question' in mot:
                return (f"Question_{numero}", numero)
            elif 'partie' in mot:
                return (f"Partie_{numero}", numero)
            elif 'sujet' in mot:
                return (f"Sujet_{numero}", numero)
            elif 'devoir' in mot:
                return (f"Devoir_{numero}", numero)
            elif 'serie' in mot or 'série' in mot:
                return (f"Serie_{numero}", numero)
            else:
                return (f"Exercice_{numero}", numero)
    
    match = re.search(r'^\s*([0-9]+[a-zA-Z]?)', texte_complet_haut)
    if match:
        return (f"Exercice_{match.group(1).upper()}", match.group(1).upper())
    
    return ("Exercice_inconnu", "XX")


def detecter_sujet_exercice(blocs: List[Dict]) -> str:
    """
    Détecte le sujet mathématique de l'exercice.
    """
    texte_complet = " ".join(b['texte'].lower() for b in blocs)
    
    scores = {}
    for sujet, mots_cles in PATTERNS_SUJET.items():
        score = sum(2 if mot in texte_complet else 0 for mot in mots_cles)
        texte_debut = texte_complet[:500]
        score += sum(3 if mot in texte_debut else 0 for mot in mots_cles)
        scores[sujet] = score
    
    if scores:
        meilleur = max(scores, key=scores.get)
        if scores[meilleur] > 0:
            return meilleur
    
    return "general"


def extraire_contenu_pertinent(blocs: List[Dict]) -> List[str]:
    """
    Extrait le contenu utile en éliminant les filigranes et en-têtes répétitifs.
    """
    filigranes = ['educamer', 'edumath', 'mongosukulu', 'easy-maths', 'easymaths',
                  'sujetexa', 'maxiepreuves', 'camscanner', 'scanner', 'téléchargez',
                  'telechargez', 'gratuitement', 'annales', 'probatoire', 'prépas',
                  'prepas', 'powered by', 'be ready', 'http', 'www.']
    
    lignes_propres = []
    for bloc in blocs:
        texte = bloc['texte']
        texte_lower = texte.lower()
        
        if any(f in texte_lower for f in filigranes):
            continue
        if len(texte.strip()) < 2:
            continue
        
        lignes_propres.append(texte)
    
    return lignes_propres


def analyser_exercice(image: np.ndarray) -> Dict:
    """
    Analyse complète d'un exercice: nom, sujet, contenu, qualité.
    """
    blocs = extraire_texte_complet(image)
    
    nom, numero = detecter_nom_exercice(blocs)
    sujet = detecter_sujet_exercice(blocs)
    contenu = extraire_contenu_pertinent(blocs)
    
    formules = []
    for ligne in contenu:
        if any(c in ligne for c in ['=', '∫', '∑', '√', '²', '³', '×', '÷', 'lim', '→', '∈', '∀', '∃']):
            formules.append(ligne)
    
    return {
        'nom': nom,
        'numero': numero,
        'sujet': sujet,
        'contenu': contenu,
        'formules': formules,
        'nb_blocs': len(blocs),
        'qualite': np.mean([b['confiance'] for b in blocs]) if blocs else 0,
        'texte_brut': " ".join(contenu)
    }