#!/usr/bin/env python3
"""
EXAMENSCAM ULTRA PRO - VERSION CORRIGÉE
=======================================
- Supprime UNIQUEMENT les filigranes (pas le texte)
- Détection fine par position et contenu
- Renommage automatique intelligent
"""

import re
import csv
import shutil
import argparse
import sys
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Dict, List
from datetime import datetime

import pikepdf
import pdfplumber
from pikepdf import Pdf, Stream, Object


# ============================================================
# CONFIGURATION
# ============================================================

FILIGRANES_TEXTES = [
    'sujetexa', 'sujetexa.com', 'educamer', 'edumathcamer', 
    'mongosukulu', 'easy-maths', 'easymaths', 'maxiepreuves', 
    'camscanner', 'prépas probatoire', 'prepas probatoire', 
    'be ready for your probat', 'powered by', 
    'téléchargez gratuitement', 'telechargez gratuitement',
    'annales probatoire', 'http://maths', 'www.edumathcamer',
    'www.mongosukulu', 'www.easy-maths', 'http://sujetexa',
    'examenscam', 'examenscam.onrender.com',
    'tes annales', 'organisees', 'annales', 'probat',
]

MATIERES = {
    'mathematiques': 'Mathematiques', 'mathematique': 'Mathematiques',
    'maths': 'Mathematiques', 'math': 'Mathematiques',
    'mathematique': 'Mathematiques',
    'physique': 'Physique', 'physiques': 'Physique',
    'physique_chimie': 'Physique-Chimie', 'pc': 'Physique-Chimie',
    'chimie': 'Chimie', 'chimies': 'Chimie',
    'svt': 'SVT', 'sciences_vie': 'SVT', 'biologie': 'SVT',
    'anglais': 'Anglais', 'francais': 'Francais', 'français': 'Francais',
    'philosophie': 'Philosophie', 'philo': 'Philosophie',
    'histoire': 'Histoire', 'geographie': 'Geographie', 'geo': 'Geographie',
    'hg': 'Histoire-Geographie', 'histoire_geographie': 'Histoire-Geographie',
    'economie': 'Economie', 'eco': 'Economie',
    'informatique': 'Informatique', 'info': 'Informatique',
    'algorithme': 'Algorithme', 'algo': 'Algorithme',
    'eps': 'EPS', 'sport': 'EPS',
    'espagnol': 'Espagnol', 'allemand': 'Allemand', 'latin': 'Latin',
}

NIVEAUX = {
    'probatoire': 'Probatoire', 'prob': 'Probatoire',
    'bac': 'Baccalaureat', 'baccalaureat': 'Baccalaureat', 
    'baccalauréat': 'Baccalaureat',
    'cap': 'CAP', 'bepc': 'BEPC', 'cepe': 'CEPE',
}

SERIES = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'TI', 'SE', 'SMS', 'STG']


# ============================================================
# MODÈLES
# ============================================================

@dataclass
class Zone:
    """Zone précise d'un filigrane."""
    x: float
    y: float
    largeur: float
    hauteur: float


@dataclass
class ExtractionResult:
    niveau: str = "Inconnu"
    serie: str = "X"
    annee: str = "0000"
    matiere: str = "Inconnu"
    confiance: int = 0


@dataclass
class ProcessingResult:
    fichier_original: str
    fichier_renomme: str
    niveau: str
    serie: str
    annee: str
    matiere: str
    pages: int
    filigranes_supprimes: int
    filigrane_ajoute: str
    date_traitement: str
    erreur: str = ""


# ============================================================
# EXTRACTEUR INTELLIGENT
# ============================================================

class SmartExtractor:
    """Extrait niveau/série/année/matière depuis PDF + nom de fichier."""
    
    def extract(self, filename: str, pdf_path: str) -> ExtractionResult:
        info_content = self._from_pdf_content(pdf_path)
        info_name = self._from_filename(filename)
        
        result = ExtractionResult()
        
        # Fusionner : privilégier le contenu PDF
        if info_content.confiance > 30 and info_content.niveau != "Inconnu":
            result.niveau = info_content.niveau
            result.serie = info_content.serie
            result.confiance += info_content.confiance
        elif info_name.niveau != "Inconnu":
            result.niveau = info_name.niveau
            result.serie = info_name.serie
            result.confiance += info_name.confiance
        
        if info_content.annee != "0000":
            result.annee = info_content.annee
            result.confiance += 20
        elif info_name.annee != "0000":
            result.annee = info_name.annee
            result.confiance += 15
        
        if info_content.matiere != "Inconnu":
            result.matiere = info_content.matiere
            result.confiance += 25
        elif info_name.matiere != "Inconnu":
            result.matiere = info_name.matiere
            result.confiance += 20
        
        if result.matiere == "Inconnu":
            result.matiere = self._guess_matiere(filename)
        
        return result
    
    def _from_pdf_content(self, pdf_path: str) -> ExtractionResult:
        info = ExtractionResult()
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                texte_total = ""
                for i, page in enumerate(pdf.pages[:3]):
                    texte = page.extract_text() or ""
                    texte_total += texte + " "
                
                texte_lower = texte_total.lower()
                
                # Niveau et série
                for niveau_key, niveau_val in NIVEAUX.items():
                    pattern = rf'{niveau_key}\s+([a-zA-Z]{{1,3}})'
                    match = re.search(pattern, texte_lower)
                    if match:
                        info.niveau = niveau_val
                        serie = match.group(1).upper()
                        if serie in SERIES:
                            info.serie = serie
                        info.confiance += 40
                        break
                
                # Année
                for pattern in [r'session\s+(\d{4})', r'ann[ée]e\s+(\d{4})', r'(\d{4})\s*-\s*\d{4}']:
                    match = re.search(pattern, texte_lower)
                    if match:
                        for group in match.groups():
                            if group and len(group) == 4 and 1980 <= int(group) <= 2030:
                                info.annee = group
                                info.confiance += 30
                                break
                        if info.annee != "0000":
                            break
                
                # Matière
                for key, val in MATIERES.items():
                    if key in texte_lower:
                        info.matiere = val
                        info.confiance += 35
                        break
                
                # Épreuve de...
                if info.matiere == "Inconnu":
                    match = re.search(r'[ée]preuve\s+de\s+([a-z\s\-]+?)(?:\s|$)', texte_lower)
                    if match:
                        brut = match.group(1).strip()
                        for key, val in MATIERES.items():
                            if key in brut:
                                info.matiere = val
                                info.confiance += 25
                                break
        
        except Exception as e:
            print(f"   ⚠️ Erreur lecture PDF: {e}")
        
        return info
    
    def _from_filename(self, filename: str) -> ExtractionResult:
        info = ExtractionResult()
        base = Path(filename).stem.lower().replace('-', '_').replace(' ', '_').replace('.', '_')
        parts = base.split('_')
        
        for part in parts:
            if part.isdigit() and len(part) == 4 and 1980 <= int(part) <= 2030:
                info.annee = part
                info.confiance += 20
        
        for part in parts:
            if part.upper() in SERIES:
                info.serie = part.upper()
                info.confiance += 15
        
        for part in parts:
            for key, val in NIVEAUX.items():
                if key in part:
                    info.niveau = val
                    info.confiance += 15
        
        for part in parts:
            for key, val in MATIERES.items():
                if key in part:
                    info.matiere = val
                    info.confiance += 20
        
        return info
    
    def _guess_matiere(self, filename: str) -> str:
        base = Path(filename).stem.lower()
        if any(x in base for x in ['math', 'calc', 'alg', 'geo', 'analyse']):
            return "Mathematiques"
        elif any(x in base for x in ['phys', 'meca', 'elec', 'thermo']):
            return "Physique"
        elif any(x in base for x in ['chim', 'reac', 'mole']):
            return "Chimie"
        elif any(x in base for x in ['bio', 'svt', 'zoo', 'botan']):
            return "SVT"
        elif any(x in base for x in ['ang', 'english']):
            return "Anglais"
        elif any(x in base for x in ['fran', 'lettre', 'gramm', 'litte']):
            return "Francais"
        elif any(x in base for x in ['philo', 'socrate', 'platon']):
            return "Philosophie"
        elif any(x in base for x in ['hist', 'guerre', 'revolut']):
            return "Histoire"
        elif any(x in base for x in ['geo', 'carte', 'climat']):
            return "Geographie"
        elif any(x in base for x in ['eco', 'monnaie', 'marche']):
            return "Economie"
        elif any(x in base for x in ['info', 'program', 'python', 'code']):
            return "Informatique"
        return "Inconnu"


# ============================================================
# DÉTECTEUR DE FILIGRANES - VERSION PRÉCISE
# ============================================================

class PreciseWatermarkDetector:
    """Détecte UNIQUEMENT les filigranes, pas le texte normal."""
    
    def __init__(self):
        self.filigranes = [f.lower() for f in FILIGRANES_TEXTES]
    
    def detect(self, pdf_path: str) -> Dict[int, List[Zone]]:
        """Détecte les zones précises des filigranes."""
        zones_par_page: Dict[int, List[Zone]] = {}
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for i, page in enumerate(pdf.pages):
                    hauteur_page = page.height
                    largeur_page = page.width
                    zones_par_page[i] = []
                    
                    mots = page.extract_words() or []
                    
                    for mot in mots:
                        texte = mot['text'].lower()
                        
                        # Vérifier si c'est un filigrane
                        if any(fil in texte for fil in self.filigranes):
                            # Zone EXACTE du mot (pas toute la page !)
                            x0 = mot['x0'] - 2  # Petit padding
                            x1 = mot['x1'] + 2
                            y0_plumber = mot['top']
                            y1_plumber = mot['bottom']
                            
                            # Conversion pdfplumber → PDF
                            y_pdf = hauteur_page - y1_plumber - 2
                            hauteur = (y1_plumber - y0_plumber) + 4
                            largeur = (x1 - x0)
                            
                            # Vérifier que c'est raisonnable (pas toute la page)
                            if largeur < largeur_page * 0.9 and hauteur < 50:
                                zones_par_page[i].append(Zone(x0, y_pdf, largeur, hauteur))
                    
                    # Fusionner SEULEMENT les zones très proches (même mot)
                    if zones_par_page[i]:
                        zones_par_page[i] = self._merge_tight_zones(zones_par_page[i])
        
        except Exception as e:
            print(f"   ⚠️ Erreur détection: {e}")
        
        return zones_par_page
    
    def _merge_tight_zones(self, zones: List[Zone]) -> List[Zone]:
        """Fusionne uniquement les zones qui touchent (même filigrane)."""
        if not zones:
            return zones
        
        zones_sorted = sorted(zones, key=lambda z: z.y)
        fusionnees: List[Zone] = []
        
        for zone in zones_sorted:
            merged = False
            
            for j, existante in enumerate(fusionnees):
                # Fusionner seulement si très proche (même ligne de texte)
                if abs(zone.y - existante.y) < 5 and abs(zone.x - (existante.x + existante.largeur)) < 10:
                    # Étendre la zone existante
                    new_x = min(zone.x, existante.x)
                    new_y = min(zone.y, existante.y)
                    new_x1 = max(zone.x + zone.largeur, existante.x + existante.largeur)
                    new_y1 = max(zone.y + zone.hauteur, existante.y + existante.hauteur)
                    
                    fusionnees[j] = Zone(new_x, new_y, new_x1 - new_x, new_y1 - new_y)
                    merged = True
                    break
            
            if not merged:
                fusionnees.append(zone)
        
        return fusionnees


# ============================================================
# NETTOYEUR PRÉCIS
# ============================================================

class PreciseCleaner:
    """Supprime UNIQUEMENT les zones de filigranes."""
    
    def clean(self, pdf_path: str, output_path: str, zones_par_page: Dict[int, List[Zone]]) -> bool:
        try:
            with pikepdf.open(pdf_path) as pdf:
                for numero_page, zones in zones_par_page.items():
                    if numero_page >= len(pdf.pages) or not zones:
                        continue
                    
                    page = pdf.pages[numero_page]
                    
                    # Dessiner des rectangles blancs UNIQUEMENT sur les zones des filigranes
                    rectangles = ""
                    for zone in zones:
                        # Vérifier que la zone est raisonnable
                        if zone.largeur > 0 and zone.hauteur > 0 and zone.largeur < 1000:
                            rectangles += f"{zone.x:.2f} {zone.y:.2f} {zone.largeur:.2f} {zone.hauteur:.2f} re f "
                    
                    if rectangles:
                        overlay_content = f"q 1 1 1 rg {rectangles}Q".encode('latin-1')
                        overlay_stream = Stream(pdf, overlay_content)
                        
                        existing = page.get('/Contents')
                        if existing is None:
                            page['/Contents'] = overlay_stream
                        elif isinstance(existing, pikepdf.Array):
                            existing.append(overlay_stream)
                        else:
                            page['/Contents'] = pikepdf.Array([existing, overlay_stream])
                
                pdf.save(output_path)
                return True
                
        except Exception as e:
            print(f"   ❌ Erreur nettoyage: {e}")
            return False


# ============================================================
# AJOUTEUR DE FILIGRANE EXAMENSCAM
# ============================================================

class ExamensCamWatermarker:
    """Ajoute le filigrane ExamensCam en bas de page."""
    
    def add(self, pdf_path: str, output_path: str, info: ExtractionResult) -> bool:
        try:
            with pikepdf.open(pdf_path) as pdf:
                # Métadonnées
                try:
                    with pdf.open_metadata() as meta:
                        meta['dc:title'] = f"{info.niveau} {info.serie} {info.annee} - {info.matiere}"
                        meta['dc:creator'] = "ExamensCam"
                        meta['dc:publisher'] = "examenscam.onrender.com"
                except:
                    pass
                
                texte = f"ExamensCam | {info.niveau} {info.serie} {info.annee} | examenscam.onrender.com"
                
                for i, page in enumerate(pdf.pages):
                    mediabox = page.mediabox
                    width = float(mediabox[2]) - float(mediabox[0])
                    
                    font_size = 6
                    text_width = len(texte) * font_size * 0.45
                    x_center = (width - text_width) / 2
                    y_pos = 12  # Bas de page
                    
                    r, g, b = 0.2, 0.4, 0.8
                    
                    link_rect = [x_center - 10, y_pos - 2, x_center + text_width + 10, y_pos + font_size + 2]
                    
                    content = f"""
                    q
                    0.5 gs
                    BT
                    /Helvetica {font_size} Tf
                    {r} {g} {b} rg
                    {x_center} {y_pos} Td
                    ({texte}) Tj
                    ET
                    Q
                    """
                    
                    stream = Stream(pdf, content.encode('latin-1'))
                    
                    existing = page.get('/Contents')
                    if existing is None:
                        page['/Contents'] = stream
                    elif isinstance(existing, pikepdf.Array):
                        existing.append(stream)
                    else:
                        page['/Contents'] = pikepdf.Array([existing, stream])
                    
                    # Lien cliquable
                    try:
                        annot = pikepdf.Dictionary({
                            '/Type': '/Annot',
                            '/Subtype': '/Link',
                            '/Rect': pikepdf.Array([
                                Object.parse(str(link_rect[0])),
                                Object.parse(str(link_rect[1])),
                                Object.parse(str(link_rect[2])),
                                Object.parse(str(link_rect[3]))
                            ]),
                            '/Border': pikepdf.Array([0, 0, 0]),
                            '/A': pikepdf.Dictionary({
                                '/Type': '/Action',
                                '/S': '/URI',
                                '/URI': "https://examenscam.onrender.com"
                            }),
                            '/H': '/I',
                        })
                        
                        if '/Annots' in page:
                            page['/Annots'].append(annot)
                        else:
                            page['/Annots'] = pikepdf.Array([annot])
                    except:
                        pass
                
                pdf.save(output_path)
                return True
                
        except Exception as e:
            print(f"   ❌ Erreur ajout filigrane: {e}")
            return False


# ============================================================
# PIPELINE PRINCIPAL
# ============================================================

class ExamensCamUltraPro:
    """Pipeline complet."""
    
    def __init__(self):
        self.extractor = SmartExtractor()
        self.detector = PreciseWatermarkDetector()
        self.cleaner = PreciseCleaner()
        self.watermarker = ExamensCamWatermarker()
        self.results: List[ProcessingResult] = []
    
    def process_file(self, input_path: Path, output_dir: Path) -> Optional[ProcessingResult]:
        print(f"\n📄 {input_path.name}")
        
        # Extraire métadonnées
        info = self.extractor.extract(input_path.name, str(input_path))
        print(f"   🎓 {info.niveau} {info.serie} | {info.annee} | {info.matiere}")
        
        # Détecter filigranes
        zones = self.detector.detect(str(input_path))
        total_zones = sum(len(z) for z in zones.values())
        print(f"   🔍 {total_zones} filigrane(s) détecté(s)")
        
        # Nettoyer
        temp_clean = output_dir / f".temp_{input_path.name}"
        
        if total_zones > 0:
            if self.cleaner.clean(str(input_path), str(temp_clean), zones):
                print(f"   🧹 Nettoyé")
            else:
                print(f"   ⚠️ Échec nettoyage, copie")
                shutil.copy2(str(input_path), str(temp_clean))
        else:
            shutil.copy2(str(input_path), str(temp_clean))
        
        # Ajouter filigrane ExamensCam
        temp_wm = output_dir / f".wm_{input_path.name}"
        
        if self.watermarker.add(str(temp_clean), str(temp_wm), info):
            print(f"   ✅ Filigrane ajouté")
            filigrane_ajoute = "Oui"
        else:
            shutil.copy2(str(temp_clean), str(temp_wm))
            filigrane_ajoute = "Non"
        
        # Renommer
        nom_renomme = f"{info.niveau.replace(' ', '_')}_{info.serie}_{info.annee}_{info.matiere}.pdf"
        final_path = output_dir / nom_renomme
        
        compteur = 1
        while final_path.exists():
            nom_renomme = f"{info.niveau.replace(' ', '_')}_{info.serie}_{info.annee}_{info.matiere}_{compteur}.pdf"
            final_path = output_dir / nom_renomme
            compteur += 1
        
        shutil.move(str(temp_wm), str(final_path))
        print(f"   📁 {nom_renomme}")
        
        # Nettoyer
        temp_clean.unlink(missing_ok=True)
        
        # Compter pages
        try:
            with pdfplumber.open(str(final_path)) as pdf:
                pages_count = len(pdf.pages)
        except:
            pages_count = 0
        
        return ProcessingResult(
            fichier_original=input_path.name,
            fichier_renomme=nom_renomme,
            niveau=info.niveau,
            serie=info.serie,
            annee=info.annee,
            matiere=info.matiere,
            pages=pages_count,
            filigranes_supprimes=total_zones,
            filigrane_ajoute=filigrane_ajoute,
            date_traitement=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    
    def process_directory(self, input_dir: str, output_dir: str, csv_path: Optional[str] = None):
        entree = Path(input_dir)
        sortie = Path(output_dir)
        sortie.mkdir(parents=True, exist_ok=True)
        
        if csv_path is None:
            csv_path = sortie / f"rapport_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        else:
            csv_path = Path(csv_path)
        
        pdfs = sorted(entree.glob('*.pdf'))
        
        print("=" * 60)
        print("🎓 EXAMENSCAM ULTRA PRO")
        print("=" * 60)
        print(f"📂 {len(pdfs)} PDF(s)")
        print(f"   Entrée: {entree.absolute()}")
        print(f"   Sortie: {sortie.absolute()}")
        print("-" * 60)
        
        for pdf in pdfs:
            result = self.process_file(pdf, sortie)
            if result:
                self.results.append(result)
        
        # CSV
        self._save_csv(csv_path)
        
        # Résumé
        reussis = sum(1 for r in self.results if r.filigrane_ajoute == "Oui")
        echoues = len(self.results) - reussis
        total_supprimes = sum(r.filigranes_supprimes for r in self.results)
        
        print("\n" + "=" * 60)
        print("📊 RÉSUMÉ")
        print(f"  ✅ Réussis: {reussis}")
        print(f"  ❌ Échoués: {echoues}")
        print(f"  🧹 Supprimés: {total_supprimes}")
        print("=" * 60)
    
    def _save_csv(self, csv_path: Path):
        if not self.results:
            return
        
        fieldnames = [
            'fichier_original', 'fichier_renomme', 'niveau', 'serie',
            'annee', 'matiere', 'pages', 'filigranes_supprimes',
            'filigrane_ajoute', 'date_traitement', 'erreur'
        ]
        
        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in self.results:
                writer.writerow(asdict(r))
        
        print(f"\n📊 CSV: {csv_path}")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="ExamensCam Ultra Pro - Nettoie et filigrane les PDFs",
        epilog="Exemple: python examenscam_ultra_pro.py -i data/raw -o data/clean"
    )
    parser.add_argument('-i', '--input', required=True, help='Dossier avec les PDFs')
    parser.add_argument('-o', '--output', required=True, help='Dossier de sortie')
    parser.add_argument('-c', '--csv', help='Chemin du CSV')
    
    args = parser.parse_args()
    
    if not Path(args.input).exists():
        print(f"❌ Dossier '{args.input}' inexistant !")
        sys.exit(1)
    
    pipeline = ExamensCamUltraPro()
    pipeline.process_directory(args.input, args.output, args.csv)


if __name__ == '__main__':
    main()