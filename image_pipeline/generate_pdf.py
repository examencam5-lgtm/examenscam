"""
Génère un PDF professionnel à partir d'images et/ou de texte reconstruit.
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Optional
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, PageBreak
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
import tempfile


def creer_style_exercice():
    """Crée les styles pour un exercice bien formaté."""
    styles = getSampleStyleSheet()
    
    style_titre = ParagraphStyle(
        'TitreExercice',
        parent=styles['Heading1'],
        fontSize=16,
        textColor='#1a1a2e',
        spaceAfter=20,
        spaceBefore=10,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    style_sous_titre = ParagraphStyle(
        'SousTitre',
        parent=styles['Heading2'],
        fontSize=13,
        textColor='#16213e',
        spaceAfter=12,
        spaceBefore=8,
        fontName='Helvetica-Bold'
    )
    
    style_corps = ParagraphStyle(
        'CorpsExercice',
        parent=styles['BodyText'],
        fontSize=11,
        leading=16,
        alignment=TA_JUSTIFY,
        spaceAfter=8,
        fontName='Helvetica'
    )
    
    style_maths = ParagraphStyle(
        'Maths',
        parent=styles['BodyText'],
        fontSize=11,
        leading=18,
        alignment=TA_LEFT,
        spaceAfter=6,
        leftIndent=20,
        fontName='Helvetica-Oblique'
    )
    
    return {
        'titre': style_titre,
        'sous_titre': style_sous_titre,
        'corps': style_corps,
        'maths': style_maths
    }


def image_vers_pdf_element(image: np.ndarray, max_width: float = 16*cm):
    """Convertit une image numpy en élément ReportLab."""
    img_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp_path = tmp.name
    
    from PIL import Image as PILImage
    pil_img = PILImage.fromarray(img_rgb)
    pil_img.save(tmp_path, 'PNG', quality=95)
    
    img_rl = RLImage(tmp_path, width=max_width, height=max_width*0.75)
    img_rl.hAlign = 'CENTER'
    
    return img_rl, tmp_path


def generer_pdf_exercice(images, 
                         textes_reconstruits=None,
                         numero_exercice=1,
                         output_path="exercice.pdf",
                         titre="Exercices de Mathématiques"):
    """
    Génère un PDF professionnel pour un exercice.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    styles = creer_style_exercice()
    story = []
    fichiers_temp = []
    
    story.append(Paragraph(titre, styles['titre']))
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(f"Exercice {numero_exercice}", styles['sous_titre']))
    story.append(Spacer(1, 0.3*cm))
    
    if textes_reconstruits and textes_reconstruits.get('textes'):
        for texte in textes_reconstruits['textes']:
            if any(c in texte for c in ['=', '∫', '∑', '√', '²', '³', '×', '÷', 'lim', '→']):
                story.append(Paragraph(texte, styles['maths']))
            else:
                story.append(Paragraph(texte, styles['corps']))
    else:
        for i, img in enumerate(images):
            if i > 0:
                story.append(PageBreak())
            
            img_elem, tmp_path = image_vers_pdf_element(img)
            fichiers_temp.append(tmp_path)
            story.append(img_elem)
            story.append(Spacer(1, 0.5*cm))
    
    doc.build(story)
    
    for tmp in fichiers_temp:
        Path(tmp).unlink(missing_ok=True)
    
    print(f"   📄 PDF généré: {output_path}")


def generer_pdf_complet(images_exercices,
                        infos_exercices,
                        output_path,
                        titre_global="Annales de Mathématiques"):
    """
    Génère un PDF complet avec tous les exercices.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )
    
    styles = creer_style_exercice()
    story = []
    fichiers_temp = []
    
    story.append(Paragraph(titre_global, styles['titre']))
    story.append(Spacer(1, 2*cm))
    
    for i, (images, info) in enumerate(zip(images_exercices, infos_exercices), 1):
        story.append(PageBreak())
        story.append(Paragraph(f"Exercice {i}", styles['sous_titre']))
        story.append(Spacer(1, 0.5*cm))
        
        if info.get('textes'):
            for texte in info['textes'][:20]:
                story.append(Paragraph(texte, styles['corps']))
            story.append(Spacer(1, 0.5*cm))
        
        for img in images[:2]:
            img_elem, tmp_path = image_vers_pdf_element(img, max_width=14*cm)
            fichiers_temp.append(tmp_path)
            story.append(img_elem)
            story.append(Spacer(1, 0.3*cm))
    
    doc.build(story)
    
    for tmp in fichiers_temp:
        Path(tmp).unlink(missing_ok=True)
    
    print(f" 📚 PDF complet généré: {output_path}")