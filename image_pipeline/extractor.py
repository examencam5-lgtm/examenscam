"""
EXTRACTEUR INTELLIGENT - Sans dépendances lourdes.
Utilise OpenCV + EasyOCR avec algorithmes maison pour détecter la structure.
"""

import cv2
import numpy as np
from pathlib import Path
import fitz  # PyMuPDF
import re
import shutil
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import easyocr


@dataclass
class Zone:
    """Une zone détectée sur la page."""
    type_zone: str  # 'titre', 'texte', 'tableau', 'image', 'formule'
    x: int
    y: int
    w: int
    h: int
    texte: str = ""
    confiance: float = 0.0


@dataclass
class Exercice:
    """Un exercice extrait."""
    numero: int
    type_exo: str  # 'exercice', 'partie_b', 'qcm'
    points: Optional[int]
    titre: str
    zones: List[Zone]  # Toutes les zones de l'exercice
    image: np.ndarray  # Image complète de l'exercice
    pages: List[int]  # Numéros de pages


class AnalyseurPage:
    """Analyse la structure d'une page avec OpenCV."""
    
    def __init__(self):
        self.ocr = None
    
    def get_ocr(self):
        """Lazy load OCR."""
        if self.ocr is None:
            print("🔄 Chargement EasyOCR...")
            self.ocr = easyocr.Reader(['fr'], gpu=False)
        return self.ocr
    
    def extraire_page(self, chemin_pdf: str, page_num: int) -> np.ndarray:
        """Extrait une page du PDF en image haute qualité."""
        doc = fitz.open(chemin_pdf)
        page = doc[page_num]
        
        # 300 DPI
        mat = fitz.Matrix(3, 3)
        pix = page.get_pixmap(matrix=mat)
        
        # Convertir en numpy
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        
        if img.shape[2] == 4:
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        
        doc.close()
        return img
    
    def nettoyer_page(self, img: np.ndarray) -> np.ndarray:
        """Nettoie la page (QR codes, filigranes)."""
        h, w = img.shape[:2]
        result = img.copy()
        
        # Masquer les 4 coins (QR codes)
        marge = int(min(h, w) * 0.12)
        result[0:marge, 0:marge] = [255, 255, 255]
        result[0:marge, w-marge:w] = [255, 255, 255]
        result[h-marge:h, 0:marge] = [255, 255, 255]
        result[h-marge:h, w-marge:w] = [255, 255, 255]
        
        # Bandes haut/bas (filigranes)
        bande = int(h * 0.05)
        result[0:bande, :] = [255, 255, 255]
        result[h-bande:h, :] = [255, 255, 255]
        
        return result
    
    def detecter_zones(self, img: np.ndarray) -> List[Zone]:
        """
        Détecte toutes les zones de la page: titres, textes, tableaux, images.
        """
        h, w = img.shape[:2]
        zones = []
        
        # 1. Détecter les lignes de texte avec projection
        lignes = self._detecter_lignes_texte(img)
        
        # 2. Regrouper les lignes en blocs
        blocs = self._regrouper_lignes(lignes)
        
        # 3. Classifier chaque bloc
        for bloc in blocs:
            type_zone = self._classifier_bloc(img, bloc)
            
            zone = Zone(
                type_zone=type_zone,
                x=bloc['x'],
                y=bloc['y'],
                w=bloc['w'],
                h=bloc['h'],
                texte="",
                confiance=0.8
            )
            zones.append(zone)
        
        # 4. Extraire le texte de chaque zone avec OCR
        zones = self._extraire_texte_zones(img, zones)
        
        # 5. Détecter les tableaux et images spécifiquement
        zones = self._detecter_tableaux_et_images(img, zones)
        
        return zones
    
    def _detecter_lignes_texte(self, img: np.ndarray) -> List[Dict]:
        """Détecte les lignes de texte par projection horizontale."""
        gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binaire = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Projection horizontale
        projection = np.sum(binaire, axis=1)
        
        # Trouver les lignes (pics de la projection)
        moyenne = np.mean(projection)
        seuil_bas = moyenne * 0.3
        seuil_haut = moyenne * 2
        
        lignes = []
        en_ligne = False
        debut = 0
        
        for i, val in enumerate(projection):
            if not en_ligne and val > seuil_bas:
                en_ligne = True
                debut = i
            elif en_ligne and val < seuil_bas:
                en_ligne = False
                if i - debut > 10:  # Ligne significative
                    lignes.append({
                        'y': debut,
                        'h': i - debut,
                        'densite': np.mean(projection[debut:i])
                    })
        
        return lignes
    
    def _regrouper_lignes(self, lignes: List[Dict]) -> List[Dict]:
        """Regroupe les lignes proches en blocs de texte."""
        if not lignes:
            return []
        
        # Trier par position Y
        lignes = sorted(lignes, key=lambda l: l['y'])
        
        blocs = []
        bloc_actuel = [lignes[0]]
        
        for ligne in lignes[1:]:
            # Si proche de la dernière ligne du bloc
            derniere = bloc_actuel[-1]
            if ligne['y'] - (derniere['y'] + derniere['h']) < 30:
                bloc_actuel.append(ligne)
            else:
                # Nouveau bloc
                blocs.append(self._creer_bloc(bloc_actuel))
                bloc_actuel = [ligne]
        
        # Dernier bloc
        if bloc_actuel:
            blocs.append(self._creer_bloc(bloc_actuel))
        
        return blocs
    
    def _creer_bloc(self, lignes: List[Dict]) -> Dict:
        """Crée un bloc à partir de lignes regroupées."""
        y_min = min(l['y'] for l in lignes)
        y_max = max(l['y'] + l['h'] for l in lignes)
        
        return {
            'x': 0,  # Sera ajusté après
            'y': y_min,
            'w': 0,  # Sera ajusté après
            'h': y_max - y_min,
            'lignes': lignes,
            'densite_moyenne': np.mean([l['densite'] for l in lignes])
        }
    
    def _classifier_bloc(self, img: np.ndarray, bloc: Dict) -> str:
        """Classifie un bloc: titre, texte, ou autre."""
        h_bloc = bloc['h']
        densite = bloc['densite_moyenne']
        
        # Analyser la hauteur des caractères dans le bloc
        zone = img[bloc['y']:bloc['y']+bloc['h'], :]
        gris = cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY)
        _, binaire = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Hauteur moyenne des caractères
        contours, _ = cv2.findContours(binaire, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        hauteurs = [cv2.boundingRect(c)[3] for c in contours if cv2.boundingRect(c)[3] > 5]
        
        if not hauteurs:
            return 'image'
        
        hauteur_moy = np.mean(hauteurs)
        
        # Titre = gros caractères, peu de lignes
        if hauteur_moy > 35 and len(bloc['lignes']) <= 3:
            return 'titre'
        
        # Tableau = lignes régulières, structure
        if self._est_structure_reguliere(bloc):
            return 'tableau'
        
        # Formule = caractères spéciaux, disposition
        if self._contient_formules(zone):
            return 'formule'
        
        return 'texte'
    
    def _est_structure_reguliere(self, bloc: Dict) -> bool:
        """Détecte si un bloc a une structure régulière (tableau)."""
        lignes = bloc['lignes']
        if len(lignes) < 3:
            return False
        
        # Vérifier espacement régulier
        espacements = []
        for i in range(len(lignes)-1):
            esp = lignes[i+1]['y'] - (lignes[i]['y'] + lignes[i]['h'])
            espacements.append(esp)
        
        # Si espacements similaires = structure régulière
        if len(espacements) > 1:
            ecart_type = np.std(espacements)
            moyenne = np.mean(espacements)
            if moyenne > 0 and ecart_type / moyenne < 0.5:
                return True
        
        return False
    
    def _contient_formules(self, zone: np.ndarray) -> bool:
        """Détecte si une zone contient des formules mathématiques."""
        # Chercher des caractères spéciaux: fractions, racines, etc.
        gris = cv2.cvtColor(zone, cv2.COLOR_BGR2GRAY)
        
        # Détecter lignes horizontales (fractions)
        lignes_h = cv2.HoughLinesP(gris, 1, np.pi/180, 50, minLineLength=30, maxLineGap=5)
        
        if lignes_h is not None and len(lignes_h) > 2:
            return True
        
        return False
    
    def _extraire_texte_zones(self, img: np.ndarray, zones: List[Zone]) -> List[Zone]:
        """Extrait le texte de chaque zone avec OCR."""
        ocr = self.get_ocr()
        
        for zone in zones:
            # Extraire la zone de l'image
            x1 = max(0, zone.x)
            y1 = max(0, zone.y)
            x2 = min(img.shape[1], zone.x + zone.w)
            y2 = min(img.shape[0], zone.y + zone.h)
            
            zone_img = img[y1:y2, x1:x2]
            
            # OCR
            resultats = ocr.readtext(zone_img, detail=0, paragraph=True)
            zone.texte = " ".join(resultats)
        
        return zones
    
    def _detecter_tableaux_et_images(self, img: np.ndarray, zones: List[Zone]) -> List[Zone]:
        """Améliore la détection des tableaux et images."""
        # Chercher les zones qui n'ont pas été détectées (images)
        h, w = img.shape[:2]
        
        # Masque des zones déjà détectées
        masque = np.zeros((h, w), dtype=np.uint8)
        for zone in zones:
            masque[zone.y:zone.y+zone.h, zone.x:zone.x+zone.w] = 255
        
        # Trouver les zones non couvertes
        contours, _ = cv2.findContours(255 - masque, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for cnt in contours:
            x, y, w_c, h_c = cv2.boundingRect(cnt)
            if w_c > 100 and h_c > 100:
                # Vérifier si c'est une image ou un tableau
                zone_img = img[y:y+h_c, x:x+w_c]
                
                if self._est_tableau_visuel(zone_img):
                    zones.append(Zone(
                        type_zone='tableau',
                        x=x, y=y, w=w_c, h=h_c,
                        texte="",
                        confiance=0.7
                    ))
                elif self._est_image(zone_img):
                    zones.append(Zone(
                        type_zone='image',
                        x=x, y=y, w=w_c, h=h_c,
                        texte="",
                        confiance=0.7
                    ))
        
        # Trier par position Y
        zones.sort(key=lambda z: z.y)
        
        return zones
    
    def _est_tableau_visuel(self, img: np.ndarray) -> bool:
        """Détecte visuellement un tableau (lignes droites)."""
        gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binaire = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        
        # Détecter lignes horizontales et verticales
        lignes_h = cv2.HoughLinesP(binaire, 1, np.pi/180, 50, minLineLength=50)
        lignes_v = cv2.HoughLinesP(binaire, 1, np.pi/2, 50, minLineLength=50)
        
        if lignes_h is not None and lignes_v is not None:
            return len(lignes_h) > 2 and len(lignes_v) > 2
        
        return False
    
    def _est_image(self, img: np.ndarray) -> bool:
        """Détecte si c'est une image (contenu non textuel)."""
        # Vérifier la complexité de la texture
        gris = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Variance élevée = image (pas texte uniforme)
        variance = np.var(gris)
        
        # Beaucoup de contours = image
        edges = cv2.Canny(gris, 50, 150)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        return variance > 1000 and len(contours) > 50


class ExtracteurExercices:
    """Extrait les exercices d'une épreuve complète."""
    
    def __init__(self):
        self.analyseur = AnalyseurPage()
    
    def traiter_pdf(self, chemin_pdf: str, dossier_output: str,
                    annee: int, examen: str, serie: str) -> List[str]:
        """
        Traite un PDF d'épreuve et génère les PDFs d'exercices.
        """
        print(f"\n{'='*70}")
        print(f"📄 {Path(chemin_pdf).name}")
        print(f"   {annee} | {examen.upper()} | Série {serie}")
        print(f"{'='*70}")
        
        # Ouvrir PDF
        doc = fitz.open(chemin_pdf)
        nb_pages = len(doc)
        doc.close()
        
        # Dossiers
        temp = "data/temp_intel"
        if Path(temp).exists():
            shutil.rmtree(temp)
        Path(temp).mkdir(parents=True, exist_ok=True)
        
        Path(dossier_output).mkdir(parents=True, exist_ok=True)
        
        # Analyser chaque page
        print(f"\n🔹 Analyse des {nb_pages} pages...")
        pages_zones = []
        
        for i in range(nb_pages):
            print(f"\n   Page {i+1}/{nb_pages}:")
            
            # Extraire et nettoyer
            img = self.analyseur.extraire_page(chemin_pdf, i)
            img_propre = self.analyseur.nettoyer_page(img)
            
            # Détecter zones
            zones = self.analyseur.detecter_zones(img_propre)
            print(f"      {len(zones)} zones détectées")
            
            for z in zones[:5]:  # Afficher les 5 premières
                print(f"      → {z.type_zone}: '{z.texte[:40]}...'")
            
            pages_zones.append({
                'page': i + 1,
                'image': img_propre,
                'zones': zones
            })
        
        # Identifier les exercices (titres "Exercice X")
        print(f"\n🔹 Identification des exercices...")
        exercices = self._identifier_exercices(pages_zones)
        print(f"   {len(exercices)} exercices identifiés")
        
        # Fusionner les exercices sur plusieurs pages
        print(f"\n🔹 Fusion multi-pages...")
        exercices_fusionnes = self._fusionner_exercices(exercices)
        print(f"   {len(exercices_fusionnes)} exercices finaux")
        
        # Générer les PDFs
        print(f"\n🔹 Génération des PDFs...")
        chemins = []
        
        for exo in exercices_fusionnes:
            chemin = self._generer_pdf(exo, dossier_output, annee, examen, serie)
            chemins.append(chemin)
            print(f"   ✅ {Path(chemin).name}")
        
        # Nettoyer
        shutil.rmtree(temp)
        
        print(f"\n✅ {len(chemins)} exercices générés")
        return chemins
    
    def _identifier_exercices(self, pages_zones: List[Dict]) -> List[Dict]:
        """Identifie les exercices à partir des zones détectées."""
        exercices = []
        exercice_actuel = None
        
        for page_info in pages_zones:
            for zone in page_info['zones']:
                # Vérifier si c'est un titre d'exercice
                if zone.type_zone == 'titre':
                    texte = zone.texte.lower()
                    
                    # Patterns d'exercice
                    match_exo = re.search(r'exercice\s*(\d+)', texte)
                    match_partie = re.search(r'partie\s*b', texte)
                    match_qcm = re.search(r'qcm|questionnaire', texte)
                    
                    if match_exo or match_partie or match_qcm:
                        # Sauvegarder l'exercice précédent
                        if exercice_actuel:
                            exercices.append(exercice_actuel)
                        
                        # Nouvel exercice
                        numero = int(match_exo.group(1)) if match_exo else (0 if match_partie else 0)
                        type_exo = 'partie_b' if match_partie else ('qcm' if match_qcm else 'exercice')
                        
                        # Extraire points
                        match_pts = re.search(r'(\d+)\s*points?', texte)
                        points = int(match_pts.group(1)) if match_pts else None
                        
                        exercice_actuel = {
                            'numero': numero,
                            'type': type_exo,
                            'points': points,
                            'titre': zone.texte,
                            'zones': [zone],
                            'pages': [page_info['page']],
                            'debut_y': zone.y
                        }
                    else:
                        # Ajouter au titre actuel
                        if exercice_actuel:
                            exercice_actuel['zones'].append(zone)
                else:
                    # Ajouter la zone à l'exercice actuel
                    if exercice_actuel:
                        exercice_actuel['zones'].append(zone)
        
        # Dernier exercice
        if exercice_actuel:
            exercices.append(exercice_actuel)
        
        return exercices
    
    def _fusionner_exercices(self, exercices: List[Dict]) -> List[Exercice]:
        """Fusionne les exercices qui se continuent sur plusieurs pages."""
        if not exercices:
            return []
        
        fusionnes = []
        actuel = exercices[0]
        
        for exo in exercices[1:]:
            # Si même numéro = continuation
            if exo['numero'] == actuel['numero'] and exo['numero'] != 0:
                # Fusionner
                actuel['zones'].extend(exo['zones'])
                actuel['pages'].extend(exo['pages'])
                actuel['pages'] = list(set(actuel['pages']))  # Unique
            else:
                # Nouvel exercice
                fusionnes.append(self._creer_exercice_objet(actuel))
                actuel = exo
        
        fusionnes.append(self._creer_exercice_objet(actuel))
        
        return fusionnes
    
    def _creer_exercice_objet(self, exo_dict: Dict) -> Exercice:
        """Crée un objet Exercice à partir du dictionnaire."""
        # Trouver les limites de l'exercice
        zones = exo_dict['zones']
        if not zones:
            return None
        
        y_min = min(z.y for z in zones)
        y_max = max(z.y + z.h for z in zones)
        x_min = min(z.x for z in zones)
        x_max = max(z.x + z.w for z in zones)
        
        # Extraire l'image complète de l'exercice
        # Note: nécessite l'image de la page - simplifié ici
        
        return Exercice(
            numero=exo_dict['numero'],
            type_exo=exo_dict['type'],
            points=exo_dict['points'],
            titre=exo_dict['titre'],
            zones=zones,
            image=None,  # Sera extrait lors de la génération
            pages=exo_dict['pages']
        )
    
    def _generer_pdf(self, exo: Exercice, dossier_output: str,
                     annee: int, examen: str, serie: str) -> str:
        """Génère un PDF pour un exercice."""
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
        
        # Construire le nom
        num = exo.numero if exo.numero > 0 else 'B'
        type_str = exo.type_exo
        pts = exo.points or 'X'
        
        nom = f"{annee}_{examen}_{serie}_Exo{num}_{type_str}_{pts}pts.pdf"
        chemin = Path(dossier_output) / nom
        
        # Éviter doublons
        compteur = 1
        while chemin.exists():
            nom = f"{annee}_{examen}_{serie}_Exo{num}_{type_str}_{pts}pts_{compteur}.pdf"
            chemin = Path(dossier_output) / nom
            compteur += 1
        
        # TODO: Extraire l'image de l'exercice et générer le PDF
        # Pour l'instant, créer un PDF vide avec le nom
        
        c = canvas.Canvas(str(chemin), pagesize=A4)
        c.drawString(100, 700, f"Exercice {num} - {type_str}")
        c.drawString(100, 680, f"{annee} {examen} Série {serie}")
        c.drawString(100, 660, f"Points: {pts}")
        c.save()
        
        return str(chemin)


def traiter_tous_pdfs():
    """Traite tous les PDFs du dossier epreuves_completes."""
    input_dir = Path("data/epreuves_completes")
    output_dir = Path("data/exercices_pdf_intel")
    
    if not input_dir.exists():
        print(f"❌ Crée le dossier: {input_dir}")
        return []
    
    pdfs = list(input_dir.glob("*.pdf"))
    
    print(f"\n{'='*70}")
    print(f"  🤖 EXTRACTEUR INTELLIGENT")
    print(f"  {len(pdfs)} PDF(s) à traiter")
    print(f"{'='*70}")
    
    extracteur = ExtracteurExercices()
    total = 0
    chemins = []
    
    for pdf in sorted(pdfs):
        nom = pdf.stem.lower()
        
        # Détecter métadonnées du nom
        annee = 2025
        examen = "probatoire"
        serie = "D"
        
        m = re.search(r'(20\d{2})', nom)
        if m:
            annee = int(m.group(1))
        
        if '_c' in nom or 'serie_c' in nom:
            serie = 'C'
        elif '_e' in nom:
            serie = 'E'
        
        if 'bac' in nom:
            examen = 'bac'
        elif 'bepc' in nom:
            examen = 'bepc'
        elif 'blanc' in nom:
            examen = 'blanc'
        
        try:
            c = extracteur.traiter_pdf(str(pdf), str(output_dir), annee, examen, serie)
            total += len(c)
            chemins.extend(c)
        except Exception as e:
            print(f"\n❌ ERREUR sur {pdf.name}: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*70}")
    print(f"  🎉 TOTAL: {total} exercices extraits!")
    print(f"  📁 Dans: {output_dir.absolute()}")
    print(f"{'='*70}")
    
    return chemins


if __name__ == '__main__':
    traiter_tous_pdfs()