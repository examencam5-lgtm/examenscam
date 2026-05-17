"""
Pipeline maître ultime:
Screenshots → Analyse intelligente → Dédoublonnage → LaTeX → PDFs nommés
"""

import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict
import shutil

from ocr_exercice import analyser_exercice
from detecteur_doublons import ExerciceCandidate, dedupliquer_exercices
from latex_generator import sauver_latex
from intelligent_crop import decouper_exercices, sauver_exercices
from fusion_pages import grouper_pages_consecutives, fusionner_images_verticale
from remove_watermark_image import nettoyer_image
from generate_pdf import generer_pdf_exercice, generer_pdf_complet


def pipeline_maitre(dossier_input='data/screenshots',
                    dossier_temp='data/temp_master',
                    dossier_output='data/output_final'):
    """
    Pipeline complet intelligent:
    1. Nettoyage filigranes
    2. Découpe & fusion pages
    3. Analyse OCR (nom, sujet, contenu)
    4. Dédoublonnage intelligent
    5. Génération LaTeX
    6. Génération PDFs nommés correctement
    """
    input_dir = Path(dossier_input)
    temp_dir = Path(dossier_temp)
    output_dir = Path(dossier_output)
    
    for d in [temp_dir, output_dir]:
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True, exist_ok=True)
    
    images = []
    for ext in ['*.png', '*.jpg', '*.jpeg', '*.bmp']:
        images.extend(input_dir.glob(ext))
        images.extend(input_dir.glob(ext.upper()))
    images = sorted(set(images))
    
    if not images:
        print("❌ Aucune image trouvée")
        return
    
    print("=" * 70)
    print("  🤖 PIPELINE MAÎTRE: Intelligence Ultime")
    print("=" * 70)
    print(f"\n📂 {len(images)} image(s) source")
    
    # ============================================================
    # ÉTAPE 1: Nettoyage
    # ============================================================
    print("\n" + "━" * 60)
    print("🔷 ÉTAPE 1: Nettoyage des filigranes")
    print("━" * 60)
    
    clean_dir = temp_dir / 'clean'
    clean_dir.mkdir(exist_ok=True)
    
    for img_path in images:
        out = clean_dir / img_path.name
        try:
            nettoyer_image(str(img_path), str(out), methode='inpaint')
        except Exception as e:
            print(f"   ⚠️ {img_path.name}: {e}")
            shutil.copy2(img_path, out)
    
    # ============================================================
    # ÉTAPE 2: Découpe & Fusion
    # ============================================================
    print("\n" + "━" * 60)
    print("🔷 ÉTAPE 2: Découpe intelligente & fusion pages")
    print("━" * 60)
    
    cropped_dir = temp_dir / 'cropped'
    cropped_dir.mkdir(exist_ok=True)
    
    fragments = []
    for img_path in sorted(clean_dir.glob('*')):
        if img_path.suffix.lower() not in ['.png', '.jpg', '.jpeg', '.bmp']:
            continue
        prefix = img_path.stem
        chemins = sauver_exercices(str(img_path), str(cropped_dir), prefix)
        fragments.extend([(c, prefix) for c in chemins])
    
    fusion_dir = temp_dir / 'fusion'
    fusion_dir.mkdir(exist_ok=True)
    
    par_prefix = {}
    for chemin, prefix in fragments:
        par_prefix.setdefault(prefix, []).append(chemin)
    
    exercices_bruts = []
    for prefix, chemins in sorted(par_prefix.items()):
        if len(chemins) == 1:
            img = cv2.imread(chemins[0])
            if img is not None:
                exercices_bruts.append((chemins[0], prefix, img))
        else:
            groupes = grouper_pages_consecutives(chemins)
            for i, groupe in enumerate(groupes):
                img = cv2.imread(groupe[0])
                for c in groupe[1:]:
                    img_suiv = cv2.imread(c)
                    if img_suiv is not None:
                        img = fusionner_images_verticale(img, img_suiv)
                
                nom = f"{prefix}_fusion_{i+1}"
                chemin_out = fusion_dir / f"{nom}.png"
                cv2.imwrite(str(chemin_out), img)
                exercices_bruts.append((str(chemin_out), nom, img))
                print(f"   🔗 Fusion: {nom}")
    
    print(f"\n   📄 {len(exercices_bruts)} exercice(s) à analyser")
    
    # ============================================================
    # ÉTAPE 3: Analyse OCR intelligente
    # ============================================================
    print("\n" + "━" * 60)
    print("🔷 ÉTAPE 3: Analyse OCR (nom, sujet, contenu)")
    print("━" * 60)
    
    candidates = []
    for chemin, nom_brut, img in exercices_bruts:
        print(f"\n   🔍 {nom_brut}:")
        analyse = analyser_exercice(img)
        
        print(f"      Nom détecté: {analyse['nom']}")
        print(f"      Sujet: {analyse['sujet']}")
        print(f"      Qualité OCR: {analyse['qualite']:.2f}")
        print(f"      Blocs: {analyse['nb_blocs']}")
        
        candidate = ExerciceCandidate(
            chemin=chemin,
            nom=analyse['nom'],
            numero=analyse['numero'],
            sujet=analyse['sujet'],
            contenu=analyse['texte_brut'],
            qualite=analyse['qualite'],
            image=img,
            analyse=analyse
        )
        candidates.append(candidate)
    
    # ============================================================
    # ÉTAPE 4: Dédoublonnage
    # ============================================================
    print("\n" + "━" * 60)
    print("🔷 ÉTAPE 4: Dédoublonnage intelligent")
    print("━" * 60)
    
    uniques = dedupliquer_exercices(candidates)
    print(f"\n   ✅ {len(uniques)} exercice(s) unique(s) après dédoublonnage")
    
    # ============================================================
    # ÉTAPE 5: Génération LaTeX
    # ============================================================
    print("\n" + "━" * 60)
    print("🔷 ÉTAPE 5: Génération LaTeX")
    print("━" * 60)
    
    latex_dir = output_dir / 'latex'
    latex_dir.mkdir(exist_ok=True)
    
    analyses = [ex.analyse for ex in uniques]
    chemin_latex = sauver_latex(analyses, str(latex_dir), "probatoire_mathematiques")
    
    # ============================================================
    # ÉTAPE 6: Génération PDFs nommés
    # ============================================================
    print("\n" + "━" * 60)
    print("🔷 ÉTAPE 6: Génération PDFs (nommés correctement)")
    print("━" * 60)
    
    pdfs_dir = output_dir / 'pdfs'
    pdfs_dir.mkdir(exist_ok=True)
    
    images_pdf = []
    infos_pdf = []
    
    for i, ex in enumerate(uniques, 1):
        nom_propre = ex.nom
        sujet = ex.sujet
        
        nom_fichier = f"{nom_propre}_{sujet}.pdf"
        chemin_pdf = pdfs_dir / nom_fichier
        
        compteur = 1
        while chemin_pdf.exists():
            nom_fichier = f"{nom_propre}_{sujet}_{compteur}.pdf"
            chemin_pdf = pdfs_dir / nom_fichier
            compteur += 1
        
        generer_pdf_exercice(
            images=[ex.image],
            textes_reconstruits=ex.analyse,
            numero_exercice=i,
            output_path=str(chemin_pdf),
            titre=f"Probatoire - {sujet.replace('_', ' ').title()}"
        )
        
        images_pdf.append([ex.image])
        infos_pdf.append(ex.analyse)
        
        print(f"   📄 {nom_fichier}")
    
    # PDF combiné
    generer_pdf_complet(
        images_exercices=images_pdf,
        infos_exercices=infos_pdf,
        output_path=str(pdfs_dir / "TOUS_EXERCICES.pdf"),
        titre_global="Annales Complètes Probatoire"
    )
    
    # ============================================================
    # RÉSUMÉ FINAL
    # ============================================================
    print("\n" + "=" * 70)
    print("  ✅ PIPELINE MAÎTRE TERMINÉ")
    print("=" * 70)
    
    print(f"\n📁 Résultats dans: {output_dir.absolute()}")
    print(f"\n   📄 PDFs individuels ({len(uniques)} fichiers):")
    for pdf in sorted(pdfs_dir.glob('Exercice_*.pdf')) + sorted(pdfs_dir.glob('Probleme_*.pdf')) + sorted(pdfs_dir.glob('Question_*.pdf')):
        taille = pdf.stat().st_size / 1024
        print(f"      • {pdf.name} ({taille:.1f} Ko)")
    
    print(f"\n   📚 PDF combiné: TOUS_EXERCICES.pdf")
    print(f"\n   📝 LaTeX: {chemin_latex}")
    print(f"      └─ + {len(uniques)} fichiers .tex individuels")
    
    sujets = {}
    for ex in uniques:
        sujets[ex.sujet] = sujets.get(ex.sujet, 0) + 1
    
    print(f"\n📊 Répartition par sujet:")
    for sujet, count in sorted(sujets.items(), key=lambda x: -x[1]):
        print(f"      • {sujet.replace('_', ' ').title()}: {count}")


if __name__ == '__main__':
    pipeline_maitre()