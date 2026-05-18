#!/usr/bin/env python3
"""
SUPPRIMEUR DE FILIGRANES PDF
============================
Un seul fichier, complet et prêt à l'emploi.
"""

import shutil
import argparse
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

# ============================================================
# CONFIGURATION - Modifie ici tes filigranes
# ============================================================

FILIGRANES_CONNUS = [
    'educamer', 'edumathcamer', 'mongosukulu', 'easy-maths',
    'easymaths', 'sujetexa', 'maxiepreuves', 'camscanner',
    'prépas probatoire', 'prepas probatoire', 'be ready for your probat',
    'powered by', 'téléchargez gratuitement', 'telechargez gratuitement',
    'annales probatoire', 'http://maths', 'www.edumathcamer',
    'www.mongosukulu', 'www.easy-maths', 'http://sujetexa',
]

# ============================================================
# MODÈLES DE DONNÉES
# ============================================================

@dataclass
class Zone:
    """Représente une zone à effacer sur le PDF."""
    x: float
    y: float          # depuis le bas (système PDF)
    largeur: float
    hauteur: float


@dataclass
class Resultat:
    """Résultat du traitement d'un fichier."""
    nom_fichier: str
    succes: bool
    filigranes_trouves: int
    message: str = ""


# ============================================================
# DÉTECTION DES FILIGRANES
# ============================================================

def contient_filigrane(texte: str) -> bool:
    """Vérifie si un texte contient un filigrane connu."""
    texte_lower = texte.lower()
    return any(mot in texte_lower for mot in FILIGRANES_CONNUS)


def trouver_zones_filigrane(chemin_pdf: str) -> Dict[int, List[Zone]]:
    """
    Analyse le PDF et trouve les coordonnées des filigranes.
    Retourne: {numero_page: [Zone, Zone, ...]}
    """
    import pdfplumber
    
    zones_par_page: Dict[int, List[Zone]] = {}
    
    try:
        with pdfplumber.open(chemin_pdf) as pdf:
            for i, page in enumerate(pdf.pages):
                hauteur_page = page.height
                zones_par_page[i] = []
                
                # Extraire tous les mots
                mots = page.extract_words() or []
                
                for mot in mots:
                    if contient_filigrane(mot['text']):
                        # Convertir coordonnées pdfplumber → PDF standard
                        x0 = mot['x0'] - 5
                        x1 = mot['x1'] + 5
                        y0_plumber = mot['top']
                        y1_plumber = mot['bottom']
                        
                        # pdfplumber: y depuis le haut
                        # PDF: y depuis le bas
                        y_pdf = hauteur_page - y1_plumber - 5
                        hauteur = (y1_plumber - y0_plumber) + 10
                        largeur = (x1 - x0)
                        
                        zones_par_page[i].append(Zone(x0, y_pdf, largeur, hauteur))
                
                # Fusionner les zones proches (même ligne)
                if zones_par_page[i]:
                    zones_par_page[i] = fusionner_zones(
                        zones_par_page[i], 
                        page.width
                    )
                    
    except Exception as e:
        print(f"  ⚠️ Erreur lecture PDF: {e}")
        
    return zones_par_page


def fusionner_zones(zones: List[Zone], largeur_page: float) -> List[Zone]:
    """Fusionne les zones sur la même ligne horizontale."""
    if not zones:
        return zones
    
    # Trier par position Y
    zones_triees = sorted(zones, key=lambda z: z.y)
    fusionnees: List[Zone] = []
    
    for zone in zones_triees:
        fusionnee = False
        
        for j, existante in enumerate(fusionnees):
            if abs(zone.y - existante.y) < 20:  # Même ligne
                # Étendre sur toute la largeur
                nouveau_y = min(zone.y, existante.y) - 3
                nouvelle_hauteur = max(
                    zone.y + zone.hauteur, 
                    existante.y + existante.hauteur
                ) - nouveau_y + 3
                
                fusionnees[j] = Zone(0, nouveau_y, largeur_page, nouvelle_hauteur)
                fusionnee = True
                break
        
        if not fusionnee:
            fusionnees.append(Zone(0, zone.y - 3, largeur_page, zone.hauteur + 6))
    
    return fusionnees


# ============================================================
# NETTOYAGE DU PDF
# ============================================================

def effacer_filigranes(
    chemin_entree: str, 
    chemin_sortie: str, 
    zones_par_page: Dict[int, List[Zone]]
) -> bool:
    """Dessine des rectangles blancs sur les filigranes."""
    import pikepdf
    
    try:
        with pikepdf.open(chemin_entree) as pdf:
            for numero_page, zones in zones_par_page.items():
                if numero_page >= len(pdf.pages):
                    continue
                    
                page = pdf.pages[numero_page]
                
                # Construire les rectangles blancs
                rectangles = ""
                for zone in zones:
                    rectangles += f"{zone.x:.2f} {zone.y:.2f} {zone.largeur:.2f} {zone.hauteur:.2f} re f "
                
                # Commande PDF: blanc + rectangles
                contenu_overlay = f"q 1 1 1 rg {rectangles}Q".encode('latin-1')
                stream_overlay = pikepdf.Stream(pdf, contenu_overlay)
                
                # Ajouter au contenu de la page
                contenu_existant = page.get('/Contents')
                
                if contenu_existant is None:
                    page['/Contents'] = stream_overlay
                elif isinstance(contenu_existant, pikepdf.Array):
                    contenu_existant.append(stream_overlay)
                else:
                    page['/Contents'] = pikepdf.Array([contenu_existant, stream_overlay])
            
            pdf.save(chemin_sortie)
            return True
            
    except Exception as e:
        print(f"  ❌ Erreur écriture PDF: {e}")
        return False


# ============================================================
# TRAITEMENT PRINCIPAL
# ============================================================

def traiter_pdf(chemin_entree: Path, chemin_sortie: Path) -> Resultat:
    """Traite un seul fichier PDF."""
    print(f"\n📄 {chemin_entree.name}")
    
    # Étape 1: Détecter
    zones = trouver_zones_filigrane(str(chemin_entree))
    total_zones = sum(len(z) for z in zones.values())
    
    # Étape 2: Si pas de filigrane, copier tel quel
    if total_zones == 0:
        print("  ℹ️ Aucun filigrane — copie sans modification")
        shutil.copy2(chemin_entree, chemin_sortie)
        return Resultat(chemin_entree.name, True, 0)
    
    # Étape 3: Afficher ce qu'on a trouvé
    print(f"  🎯 {total_zones} zone(s) détectée(s)")
    for page_num, page_zones in zones.items():
        for zone in page_zones:
            print(f"     Page {page_num + 1} → y={zone.y:.0f}, h={zone.hauteur:.0f}")
    
    # Étape 4: Effacer
    if effacer_filigranes(str(chemin_entree), str(chemin_sortie), zones):
        print(f"  ✅ Nettoyé")
        return Resultat(chemin_entree.name, True, total_zones)
    else:
        return Resultat(chemin_entree.name, False, 0, "Erreur lors du nettoyage")


def traiter_dossier(dossier_entree: str, dossier_sortie: str) -> None:
    """Traite tous les PDF d'un dossier."""
    entree = Path(dossier_entree)
    sortie = Path(dossier_sortie)
    sortie.mkdir(parents=True, exist_ok=True)
    
    # Trouver tous les PDF
    pdfs = list(entree.glob('*.pdf'))
    
    print("=" * 50)
    print(f"📂 {len(pdfs)} PDF(s) à traiter")
    print(f"   Entrée:  {entree.absolute()}")
    print(f"   Sortie:  {sortie.absolute()}")
    print("=" * 50)
    
    reussis = 0
    echoues = 0
    total_filigranes = 0
    
    for pdf in pdfs:
        resultat = traiter_pdf(pdf, sortie / pdf.name)
        
        if resultat.succes:
            reussis += 1
            total_filigranes += resultat.filigranes_trouves
        else:
            echoues += 1
    
    # Rapport final
    print("\n" + "=" * 50)
    print("📊 RAPPORT FINAL")
    print("=" * 50)
    print(f"  ✅ Réussis:  {reussis}")
    print(f"  ❌ Échoués:  {echoues}")
    print(f"  🧹 Filigranes supprimés: {total_filigranes}")
    print("=" * 50)


# ============================================================
# POINT D'ENTRÉE
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Supprime les filigranes des PDF",
        epilog="Exemple: python watermark_remover.py -i data/raw -o data/clean"
    )
    parser.add_argument('-i', '--input', required=True, help='Dossier avec les PDF')
    parser.add_argument('-o', '--output', required=True, help='Dossier de sortie')
    
    args = parser.parse_args()
    
    if not Path(args.input).exists():
        print(f"❌ Le dossier '{args.input}' n'existe pas !")
        sys.exit(1)
    
    traiter_dossier(args.input, args.output)


if __name__ == '__main__':
    main()