#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
============================================================
🎓 EXAMENSCAM WATERMARKER PRO
============================================================

Fonctionnalités :
✅ Ajout de watermark professionnel
✅ Lien cliquable vers ExamensCam
✅ Génération automatique CSV
✅ Extraction infos depuis nom du PDF
✅ Métadonnées PDF
✅ Compatible upload site web
✅ Pipeline automatisé

Exemple :
python examenscam_watermarker.py -i "./pdfs" -o "./out"

============================================================
"""

import re
import csv
import argparse
import sys

from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, Tuple, Dict, List
from datetime import datetime

import pikepdf
from pikepdf import Pdf, Stream, Object


# ============================================================
# CONFIGURATION GLOBALE
# ============================================================

BASE_URL = "https://examenscam.onrender.com"


# ============================================================
# CONFIG WATERMARK
# ============================================================

@dataclass
class WatermarkConfig:

    TEXTE_TEMPLATE: str = (
        "ExamensCam | {niveau} {annee} | examenscam.onrender.com"
    )

    # Taille moyenne visible
    TAILLE_POLICE: int = 9

    # Bleu professionnel
    COULEUR: Tuple[float, float, float] = (0.1, 0.35, 0.75)

    # Plus visible sans être agressif
    OPACITE: float = 0.78

    # Position verticale
    MARGE_BAS: float = 20

    # Police
    POLICE: str = "Helvetica-Bold"


# ============================================================
# PARSER NOM FICHIER
# ============================================================

class FilenameParser:
    """
    Extrait :
    - niveau
    - série
    - année
    - matière

    Exemple :
    Probatoire_A_2023_Mathematiques.pdf
    """

    PATTERN = re.compile(
        r'^(?P<niveau>[A-Za-z_]+)_(?P<serie>[A-C])_(?P<annee>\d{4})_(?P<matiere>[A-Za-z]+)',
        re.IGNORECASE
    )

    @classmethod
    def parse(cls, filename: str) -> Dict[str, str]:

        base = Path(filename).stem
        base = base.replace('-', '_').replace(' ', '_')

        match = cls.PATTERN.match(base)

        if match:
            return {
                'niveau': f"{match.group('niveau').replace('_', ' ').title()} {match.group('serie').upper()}",
                'annee': match.group('annee'),
                'matiere': match.group('matiere').capitalize(),
                'raw_niveau': match.group('niveau'),
                'serie': match.group('serie').upper(),
            }

        return cls._fallback_parse(base)

    @classmethod
    def _fallback_parse(cls, base: str) -> Dict[str, str]:

        parts = base.split('_')

        niveau = "Inconnu"
        annee = "0000"
        matiere = "Inconnu"
        serie = "?"

        for part in parts:

            if part.upper() in ['A', 'B', 'C']:
                serie = part.upper()

            elif part.isdigit() and len(part) == 4:
                annee = part

            elif part.lower() in [
                'probatoire',
                'baccalaureat',
                'baccalauréat'
            ]:
                niveau = part.capitalize()

            elif part.lower() in [
                'mathematiques',
                'mathematique',
                'maths'
            ]:
                matiere = "Mathematiques"

            elif part.lower() in ['physique', 'physiques']:
                matiere = "Physique"

            elif part.lower() in ['chimie', 'chimies']:
                matiere = "Chimie"

        return {
            'niveau': f"{niveau} {serie}",
            'annee': annee,
            'matiere': matiere,
            'raw_niveau': niveau,
            'serie': serie,
        }


# ============================================================
# RESULTAT TRAITEMENT
# ============================================================

@dataclass
class ProcessingResult:

    fichier: str
    pdf_path: str

    niveau: str
    serie: str
    annee: str
    matiere: str

    pages: int

    url: str
    slug: str

    filigrane_ajoute: str
    date_traitement: str

    erreur: str = ""


# ============================================================
# WATERMARKER
# ============================================================

class ExamensCamWatermarker:

    def __init__(self, config: Optional[WatermarkConfig] = None):
        self.config = config or WatermarkConfig()

    def _create_watermark_content(
        self,
        page_width: float,
        info: Dict[str, str]
    ):

        cfg = self.config

        texte = cfg.TEXTE_TEMPLATE.format(
            niveau=info['niveau'],
            annee=info['annee']
        )

        font_size = cfg.TAILLE_POLICE

        # meilleure estimation largeur
        text_width = len(texte) * font_size * 0.52

        # centrage sécurisé
        x_center = max((page_width - text_width) / 2, 40)

        y_pos = cfg.MARGE_BAS

        r, g, b = cfg.COULEUR

        link_rect = [
            x_center - 8,
            y_pos - 2,
            x_center + text_width + 8,
            y_pos + font_size + 2
        ]

        content = f"""
        q
        {cfg.OPACITE} gs
        BT
        /{cfg.POLICE} {font_size} Tf
        {r} {g} {b} rg
        {x_center} {y_pos} Td
        ({texte}) Tj
        ET
        Q
        """

        return content.encode('latin-1'), link_rect, texte

    def _add_link_annotation(
        self,
        page,
        link_rect: List[float],
        url: str,
        texte: str
    ):

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
                    '/URI': url
                }),

                '/H': '/I',
                '/Contents': texte,
            })

            if '/Annots' in page:
                page['/Annots'].append(annot)
            else:
                page['/Annots'] = pikepdf.Array([annot])

        except Exception as e:
            print(f"   ⚠️ Lien non ajouté : {e}")

    def _add_metadata(self, pdf: Pdf, info: Dict[str, str]):

        try:

            with pdf.open_metadata() as meta:

                meta['dc:title'] = (
                    f"{info['niveau']} "
                    f"{info['annee']} - "
                    f"{info['matiere']}"
                )

                meta['dc:creator'] = "ExamensCam"

                meta['dc:publisher'] = BASE_URL

                meta['dc:description'] = (
                    f"Annales {info['niveau']} "
                    f"{info['annee']} - "
                    f"{info['matiere']}"
                )

                meta['xmp:CreatorTool'] = (
                    "ExamensCam Watermarker Pro"
                )

        except:
            pass

    def process_file(
        self,
        input_path: Path,
        output_path: Path
    ) -> ProcessingResult:

        print(f"\n📄 {input_path.name}")

        info = FilenameParser.parse(input_path.name)

        print(
            f"   🎓 {info['niveau']} | "
            f"{info['annee']} | "
            f"{info['matiere']}"
        )

        try:

            with pikepdf.open(str(input_path)) as pdf:

                self._add_metadata(pdf, info)

                pages_count = len(pdf.pages)

                for i, page in enumerate(pdf.pages):

                    mediabox = page.mediabox

                    width = (
                        float(mediabox[2]) -
                        float(mediabox[0])
                    )

                    content, link_rect, texte = (
                        self._create_watermark_content(
                            width,
                            info
                        )
                    )

                    stream = Stream(pdf, content)

                    existing = page.get('/Contents')

                    if existing is None:
                        page['/Contents'] = stream

                    elif isinstance(existing, pikepdf.Array):
                        existing.append(stream)

                    else:
                        page['/Contents'] = (
                            pikepdf.Array([existing, stream])
                        )

                    self._add_link_annotation(
                        page,
                        link_rect,
                        BASE_URL,
                        texte
                    )

                    print(f"   Page {i + 1} ✅")

                pdf.save(str(output_path))

                print("   💾 Sauvegardé")

                slug = (
                    f"{info['raw_niveau']}-"
                    f"{info['serie']}-"
                    f"{info['annee']}-"
                    f"{info['matiere']}"
                ).lower()

                return ProcessingResult(

                    fichier=input_path.name,

                    pdf_path=str(output_path).replace("\\", "/"),

                    niveau=info['niveau'],
                    serie=info['serie'],
                    annee=info['annee'],
                    matiere=info['matiere'],

                    pages=pages_count,

                    url=f"{BASE_URL}/pdfs/{output_path.name}",

                    slug=slug,

                    filigrane_ajoute="Oui",

                    date_traitement=datetime.now().strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                )

        except Exception as e:

            print(f"   ❌ Erreur : {e}")

            return ProcessingResult(

                fichier=input_path.name,

                pdf_path="",

                niveau=info.get('niveau', 'Erreur'),
                serie=info.get('serie', '?'),
                annee=info.get('annee', '0000'),
                matiere=info.get('matiere', 'Erreur'),

                pages=0,

                url="",
                slug="",

                filigrane_ajoute="Non",

                date_traitement=datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),

                erreur=str(e)
            )


# ============================================================
# CSV REPORTER
# ============================================================

class CSVReporter:

    def __init__(self, output_path: Path):

        self.output_path = output_path
        self.results: List[ProcessingResult] = []

    def add(self, result: ProcessingResult):
        self.results.append(result)

    def save(self):

        if not self.results:
            print("⚠️ Aucun résultat à sauvegarder")
            return

        fieldnames = [

            'fichier',
            'pdf_path',

            'niveau',
            'serie',
            'annee',
            'matiere',

            'pages',

            'url',
            'slug',

            'filigrane_ajoute',
            'date_traitement',
            'erreur'
        ]

        with open(
            self.output_path,
            'w',
            newline='',
            encoding='utf-8-sig'
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=fieldnames
            )

            writer.writeheader()

            for r in self.results:
                writer.writerow(asdict(r))

        print(f"\n📊 CSV généré : {self.output_path}")
        print(f"   {len(self.results)} ligne(s)")


# ============================================================
# PIPELINE
# ============================================================

class WatermarkPipeline:

    def __init__(self):

        self.watermarker = (
            ExamensCamWatermarker()
        )

        self.reporter: Optional[
            CSVReporter
        ] = None

    def process_directory(
        self,
        input_dir: str,
        output_dir: str,
        csv_path: Optional[str] = None
    ):

        entree = Path(input_dir)
        sortie = Path(output_dir)

        sortie.mkdir(
            parents=True,
            exist_ok=True
        )

        if csv_path is None:

            csv_path = (
                sortie /
                f"rapport_examenscam_"
                f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            )

        else:
            csv_path = Path(csv_path)

        self.reporter = CSVReporter(csv_path)

        pdfs = sorted(entree.glob('*.pdf'))

        print("=" * 60)
        print("🎓 EXAMENSCAM WATERMARKER PRO")
        print("=" * 60)

        print(f"📂 {len(pdfs)} PDF(s) à traiter")

        print(f"   Entrée :  {entree.absolute()}")
        print(f"   Sortie :  {sortie.absolute()}")
        print(f"   CSV :     {csv_path.absolute()}")

        print("-" * 60)

        for pdf in pdfs:

            out_file = sortie / pdf.name

            result = self.watermarker.process_file(
                pdf,
                out_file
            )

            self.reporter.add(result)

        self.reporter.save()

        reussis = sum(
            1
            for r in self.reporter.results
            if r.filigrane_ajoute == "Oui"
        )

        echoues = (
            len(self.reporter.results) - reussis
        )

        print("\n" + "=" * 60)
        print("📊 RÉSUMÉ")
        print("=" * 60)

        print(f"  ✅ Réussis :  {reussis}")
        print(f"  ❌ Échoués :  {echoues}")

        print(f"  📁 Sortie :   {sortie.absolute()}")
        print(f"  📊 CSV :      {csv_path.absolute()}")

        print("=" * 60)


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Ajoute le watermark ExamensCam "
            "avec lien cliquable"
        )
    )

    parser.add_argument(
        '-i',
        '--input',
        required=True,
        help='Dossier avec les PDFs'
    )

    parser.add_argument(
        '-o',
        '--output',
        required=True,
        help='Dossier de sortie'
    )

    parser.add_argument(
        '-c',
        '--csv',
        help='Chemin CSV optionnel'
    )

    args = parser.parse_args()

    if not Path(args.input).exists():

        print(
            f"❌ Le dossier "
            f"'{args.input}' n'existe pas !"
        )

        sys.exit(1)

    pipeline = WatermarkPipeline()

    pipeline.process_directory(
        args.input,
        args.output,
        args.csv
    )


# ============================================================
# ENTRYPOINT
# ============================================================

if __name__ == '__main__':
    main()