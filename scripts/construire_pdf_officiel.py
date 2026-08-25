# scripts/construire_pdf_officiel.py
"""
ÉTAPE 4b (révision du 24/08/2026) du pipeline RAG Maths Terminale C.

Prend le JSON validé produit par generer_epreuve_json.py et construit
un vrai PDF, au format officiel camerounais, SOBRE (noir sur blanc),
avec les formules mathématiques rendues proprement.

Choix technique : matplotlib (rendu de chaque expression en image
vectorielle) + reportlab (mise en page) -- pas de LaTeX (pdflatex),
volontairement, pour rester léger à installer avec une connexion
instable comme celle de Maroua.

CHANGEMENT IMPORTANT PAR RAPPORT À LA VERSION PRÉCÉDENTE :
matplotlib.mathtext ne supporte qu'un sous-ensemble de LaTeX (pas
d'environnements matrice/cases, pas de \\pmod, pas de \\left/\\right).
La version précédente, quand le rendu d'une formule échouait, affichait
la chaîne LaTeX brute en texte monospace dans le PDF -- c'est EXACTEMENT
le bug de "LaTeX qui fuite" repéré dans l'audit du corpus généré.

generer_epreuve_json.py contraint maintenant Gemini à un sous-ensemble
LaTeX compatible (via schema_epreuve.py) ET valide le contenu avant de
l'écrire (via valider_epreuve.py) -- en théorie, ce script ne devrait
plus jamais recevoir de LaTeX hors du sous-ensemble supporté. Mais on
ne fait JAMAIS confiance uniquement à l'étage précédent : si un rendu
échoue quand même ici, on lève une exception avec l'expression fautive
au lieu de continuer silencieusement. Mieux vaut un échec de build
visible et immédiat qu'un PDF cassé livré à un prof.

NOTE (portée du 22/08/2026) : ce script ne construit plus de section
"CORRIGÉ DÉTAILLÉ" -- ce pipeline ne génère plus de corrigé pour le
moment (voir generer_epreuve_json.py).

NOTE (ajout du 23/08/2026) : deux chemins d'en-tête coexistent.
  1. meta contient 'chemin_image_entete' -> upload enseignant : on
     colle l'IMAGE RÉELLE de l'en-tête via construire_entete_image().
  2. meta contient region/delegation/etablissement/... -> saisie CLI,
     construire_entete() reconstruit le bloc texte bilingue.

  ATTENTION (ajout du 24/08/2026, audit visuel) : quand le chemin 1
  est utilisé, ce script n'a AUCUN contrôle sur la typographie de
  l'image collée -- si l'image source contient un bug (espacement,
  troncature, incohérence de date...), il se retrouve tel quel dans
  le PDF final. Un audit sur 3 générations réelles a trouvé de tels
  bugs dans des images d'en-tête (pas dans ce script). Tant qu'il n'y
  a pas de contrôle qualité sur les images uploadées en amont, ce
  risque reste ouvert -- voir échange du 24/08/2026.

NOTE (ajout du 24/08/2026) -- POLICE ET MISE EN PAGE "NIVEAU WORD" :
  1. Police : Times-Roman/Times-Bold au lieu de Helvetica. Toutes les
     vraies épreuves MINESEC comparées (Sainte Thérèse de Mva'a,
     Collège Bilingue Pascal Tohoua) utilisent une police serif
     (Times New Roman / Cambria) -- Helvetica se voyait à l'oeil nu
     comme "généré par ordinateur", même quand le contenu était
     irréprochable. Ce sont des polices de base PDF, aucune
     dépendance à installer.
  2. keepWithNext=1 sur les styles "section" et "exercice_titre" --
     empêche un titre d'exercice de rester seul en bas de page avec
     son contenu qui commence sur la page suivante (défaut classique
     des PDF mal maîtrisés, un des signes qui trahit le plus un
     document "pas fait dans Word").
  3. Logique "réduire pour ajuster" (construire_pdf_avec_ajustement) :
     reproduit ce que Word fait via "Aperçu avant impression > Réduire
     d'une page". Observé sur plusieurs générations réelles : le
     contenu déborde de 2-3 lignes sur une page 2 qui reste sinon
     presque vide (~85% de blanc) -- ça donne l'impression d'un
     document cassé. On mesure le remplissage réel de la dernière
     page (via pdfplumber, sur le PDF déjà construit) et, si elle est
     jugée trop vide, on reconstruit avec un espacement légèrement
     réduit, jusqu'à ce que ça rentre proprement ou qu'on atteigne la
     limite de réduction acceptable (pour ne jamais produire un texte
     illisible).

     CORRECTIF (24/08/2026, audit visuel) : ce raisonnement suppose
     que la page quasi-vide vient TOUJOURS d'un débordement de
     quelques lignes depuis la page précédente. Sur les générations
     auditées, ce n'est pas le cas : Partie A (~15 pts) remplit déjà
     la page 1 presque entièrement SANS déborder, et Partie B
     (~4.5 pts) est intrinsèquement courte -- réduire l'échelle
     globale ne rapproche pas ces deux sections, ça réduit aussi la
     hauteur de Partie B, donc ça peut FAIRE BAISSER le remplissage
     mesuré au lieu de l'augmenter. La boucle s'arrête maintenant dès
     qu'elle constate deux tentatives sans amélioration, plutôt que
     d'épuiser les 4 tentatives pour rien. Dans ce cas de figure
     structurel, la vraie réponse n'est pas la réduction d'échelle
     mais une clôture visuelle explicite (voir construire_corps --
     mention "FIN DE L'ÉPREUVE"), qui rend une dernière page courte
     légitime plutôt que "cassée". Un peu de blanc en bas de la
     dernière page d'une épreuve imprimée est normal et attendu --
     ce n'est pas en soi un défaut à corriger à tout prix.

Nécessite : pip install matplotlib reportlab pillow pdfplumber

Usage CLI (terminal) :
    python construire_pdf_officiel.py --fichier data/rag_maths_bac_c/epreuves_json/epreuve_seq2_XXXX.json

Usage programmatique (depuis Flask, voir app.py) :
    from scripts.construire_pdf_officiel import construire_pdf
    chemin_pdf = construire_pdf(chemin_json)
"""

import re
import json
import argparse
import hashlib
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# CORRECTIF (24/08/2026, audit visuel) : par défaut, matplotlib rend
# le mathtext avec le jeu de polices 'dejavusans' -- une sans-serif.
# Le corps du document est en Times-Roman (serif). Résultat observé
# sur 3 PDF réels : chaque formule ou variable inline (x = 3, A(1,0,2),
# 85000...) jure visuellement au milieu d'une phrase en Times, ligne
# après ligne -- un signal "généré par script" aussi fort que l'était
# Helvetica avant le passage à Times-Roman. 'stix' est le jeu de
# polices mathtext le plus proche de Times New Roman/Cambria ; c'est
# un réglage global valable pour tous les rendus de ce module, donc
# fixé une seule fois ici, au chargement.
matplotlib.rcParams["mathtext.fontset"] = "stix"

# Renommé en PILImage : reportlab.platypus expose aussi une classe
# "Image" (pour insérer une image bitmap dans le flux du PDF). Garder
# les deux sous le même nom "Image" écraserait silencieusement l'une
# des deux selon l'ordre des imports -- source d'un bug difficile à
# repérer (l'erreur ne serait pas au niveau de l'import, mais plus
# tard, sur un appel de méthode qui n'existe pas sur la mauvaise
# classe). On les distingue explicitement par leur nom.
from PIL import Image as PILImage

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
)

TMP_MATH_DIR = Path("data/rag_maths_bac_c/_tmp_math_images")
TMP_MATH_DIR.mkdir(parents=True, exist_ok=True)

FONT_SIZE_CORPS = 10.5
FONT_SIZE_MATH = 10.5

_cache_images = {}

# Alias LaTeX sûrs mais parfois écrits différemment de ce que
# matplotlib.mathtext attend précisément -- on les normalise ICI,
# en amont du rendu, plutôt que d'échouer dessus. Ce n'est PAS un
# élargissement du sous-ensemble autorisé : ce sont des synonymes
# strictement équivalents à des commandes déjà supportées.
ALIAS_SURS = {
    r"\le": r"\leq",
    r"\ge": r"\geq",
    r"\ne": r"\neq",
}

# ═══════════════════════════════════════════════════════
# PARAMÈTRES DE LA LOGIQUE "RÉDUIRE POUR AJUSTER"
# ═══════════════════════════════════════════════════════

# En dessous de ce taux de remplissage de la DERNIÈRE page, on juge
# que cette page est "presque vide" -- symptôme d'un léger débordement
# plutôt que d'un vrai besoin de cette page entière.
SEUIL_REMPLISSAGE_MINIMUM = 0.30

# Nombre maximum de reconstructions tentées. Chaque tentative réduit
# un peu plus l'espacement -- au-delà de ce nombre, on s'arrête même
# si le résultat n'est pas encore idéal, pour ne jamais tourner en
# boucle indéfiniment sur un cas limite.
NB_TENTATIVES_AJUSTEMENT = 4

# CORRECTIF (24/08/2026) : si deux tentatives de suite n'améliorent
# pas le remplissage mesuré, on arrête -- inutile de continuer à
# réduire la police si ça ne rapproche pas Partie A et Partie B (cas
# où Partie B est structurellement courte, voir note en tête de
# fichier). Continuer dans ce cas ne fait que dégrader la lisibilité
# pour rien.
NB_TENTATIVES_SANS_AMELIORATION_AVANT_ARRET = 2

# Facteur de réduction appliqué à chaque tentative (taille de police,
# interlignage, espacements avant/après paragraphe). 0.96 = -4% par
# tentative -- progressif et volontairement discret : après 4
# tentatives au pire, on est à ~85% de la taille d'origine, encore
# largement lisible. On ne descend JAMAIS plus bas que ÉCHELLE_MINIMALE.
FACTEUR_REDUCTION_PAR_TENTATIVE = 0.96
ECHELLE_MINIMALE = 0.85


class RenduMathEchoue(RuntimeError):
    """Levée quand une expression $...$ ne peut pas être rendue par
    matplotlib.mathtext. Porte l'expression fautive pour un diagnostic
    immédiat -- ne doit JAMAIS être avalée silencieusement."""
    pass


# ═══════════════════════════════════════════════════════
# RENDU DES FORMULES MATHÉMATIQUES (matplotlib mathtext)
# ═══════════════════════════════════════════════════════

def normaliser_alias(expression_latex: str) -> str:
    resultat = expression_latex
    for alias, forme_supportee in ALIAS_SURS.items():
        resultat = resultat.replace(alias, forme_supportee)
    return resultat


def rendre_math_en_image(expression_latex: str, fontsize: float = FONT_SIZE_MATH) -> Path:
    """Rend une expression LaTeX en image PNG transparente. Met en
    cache pour ne pas re-rendre deux fois la même expression -- y
    compris entre deux tentatives de la logique d'ajustement, puisque
    seule la taille de police change d'une tentative à l'autre (la
    clé de cache inclut fontsize, donc chaque échelle a ses propres
    images, mais on ne recalcule jamais deux fois la même).

    Lève RenduMathEchoue si matplotlib.mathtext ne sait pas parser
    l'expression -- AUCUN fallback texte brut. Une expression que le
    renderer ne sait pas afficher ne doit jamais atteindre le PDF
    sous quelque forme que ce soit."""
    expression_normalisee = normaliser_alias(expression_latex)
    cle = hashlib.md5(f"{expression_normalisee}_{fontsize}".encode()).hexdigest()
    if cle in _cache_images:
        return _cache_images[cle]

    chemin = TMP_MATH_DIR / f"math_{cle}.png"
    if chemin.exists():
        _cache_images[cle] = chemin
        return chemin

    try:
        fig = plt.figure(figsize=(0.01, 0.01))
        texte = fig.text(0, 0, f"${expression_normalisee}$", fontsize=fontsize)
        fig.canvas.draw()
        bbox = texte.get_window_extent()
        largeur_in = bbox.width / fig.dpi + 0.04
        hauteur_in = bbox.height / fig.dpi + 0.04
        plt.close(fig)

        fig = plt.figure(figsize=(largeur_in, hauteur_in))
        fig.text(0.02, 0.15, f"${expression_normalisee}$", fontsize=fontsize)
        fig.savefig(chemin, dpi=300, transparent=True, bbox_inches='tight', pad_inches=0.02)
        plt.close(fig)
    except Exception as e:
        raise RenduMathEchoue(
            f"Impossible de rendre l'expression LaTeX : \"{expression_latex}\" "
            f"(mathtext ne supporte qu'un sous-ensemble de LaTeX -- probablement un "
            f"environnement, \\pmod, ou \\left/\\right passé malgré la validation en amont). "
            f"Erreur d'origine : {e}"
        ) from e

    _cache_images[cle] = chemin
    return chemin


def texte_vers_markup_reportlab(texte: str, fontsize: float = FONT_SIZE_CORPS) -> str:
    """Convertit un texte contenant des segments $...$ (LaTeX) en
    markup reportlab (texte normal + balises <img> pour les formules).
    Ne capture PAS les exceptions de rendre_math_en_image -- une
    formule fautive doit interrompre la construction du PDF, pas
    être remplacée silencieusement par autre chose."""
    if texte is None:
        return ""

    segments = re.split(r'(\$[^$]+\$)', texte)
    markup = ""
    for seg in segments:
        if seg.startswith('$') and seg.endswith('$') and len(seg) > 2:
            expr = seg[1:-1]
            chemin_img = rendre_math_en_image(expr, fontsize)  # peut lever RenduMathEchoue
            with PILImage.open(chemin_img) as im:
                w_px, h_px = im.size
            hauteur_pt = fontsize * 1.35
            largeur_pt = w_px * (hauteur_pt / h_px)
            markup += (f'<img src="{chemin_img}" width="{largeur_pt:.1f}" '
                       f'height="{hauteur_pt:.1f}" valign="-3"/>')
        else:
            seg_echap = (seg.replace('&', '&amp;')
                            .replace('<', '&lt;')
                            .replace('>', '&gt;'))
            markup += seg_echap
    return markup


# ═══════════════════════════════════════════════════════
# STYLES DE PARAGRAPHE (sobres, noir et blanc uniquement)
# ═══════════════════════════════════════════════════════

def construire_styles(echelle: float = 1.0) -> dict:
    """`echelle` : facteur multiplicatif appliqué à la taille de
    police, l'interlignage et les espacements avant/après paragraphe.
    1.0 = taille normale. Utilisé UNIQUEMENT par la logique "réduire
    pour ajuster" (voir construire_pdf) pour absorber un léger
    débordement sur une page presque vide -- ne descend jamais sous
    ECHELLE_MINIMALE, appliqué par l'appelant avant de passer ici."""
    fs_corps = FONT_SIZE_CORPS * echelle

    return {
        "entete_petit": ParagraphStyle(
            "entete_petit", fontName="Times-Roman", fontSize=8.5 * echelle,
            alignment=TA_CENTER, leading=11 * echelle, textColor="black",
        ),
        "entete_titre": ParagraphStyle(
            "entete_titre", fontName="Times-Bold", fontSize=13 * echelle,
            alignment=TA_CENTER, leading=16 * echelle, textColor="black",
            spaceBefore=6 * echelle, spaceAfter=4 * echelle,
        ),
        "section": ParagraphStyle(
            "section", fontName="Times-Bold", fontSize=11.5 * echelle,
            alignment=TA_CENTER, leading=15 * echelle, textColor="black",
            spaceBefore=14 * echelle, spaceAfter=8 * echelle,
            keepWithNext=1,
        ),
        "exercice_titre": ParagraphStyle(
            "exercice_titre", fontName="Times-Bold", fontSize=fs_corps + 0.5 * echelle,
            alignment=TA_JUSTIFY, leading=14 * echelle, textColor="black",
            spaceBefore=10 * echelle, spaceAfter=4 * echelle,
            keepWithNext=1,
        ),
        "corps": ParagraphStyle(
            "corps", fontName="Times-Roman", fontSize=fs_corps,
            alignment=TA_JUSTIFY, leading=15 * echelle, textColor="black",
            spaceBefore=2 * echelle, spaceAfter=3 * echelle, leftIndent=10,
        ),
        "corps_intro": ParagraphStyle(
            "corps_intro", fontName="Times-Roman", fontSize=fs_corps,
            alignment=TA_JUSTIFY, leading=15 * echelle, textColor="black",
            spaceBefore=2 * echelle, spaceAfter=4 * echelle,
        ),
        "fin_epreuve": ParagraphStyle(
            "fin_epreuve", fontName="Times-Bold", fontSize=10.5 * echelle,
            alignment=TA_CENTER, leading=13 * echelle, textColor="black",
            spaceBefore=16 * echelle, spaceAfter=2 * echelle,
        ),
    }


# ═══════════════════════════════════════════════════════
# CONSTRUCTION DE L'EN-TÊTE -- IMAGE RÉELLE (upload enseignant)
# ═══════════════════════════════════════════════════════

def construire_entete_image(meta: dict, styles: dict) -> list:
    """Colle l'image réelle de l'en-tête (logo, mise en page, police
    d'origine) au lieu de reconstruire un bloc texte générique.

    IMPORTANT : largeur_utile doit correspondre à
    A4[0] - (leftMargin + rightMargin) du SimpleDocTemplate construit
    dans construire_pdf() -- actuellement 20mm + 20mm = 40mm.

    ATTENTION : ce script n'a aucun contrôle sur le contenu de
    l'image collée -- une typographie fautive ou une incohérence
    (ex. date) DANS l'image source ressortira telle quelle dans le
    PDF final. Si ce cas se reproduit souvent, la correction doit se
    faire en amont (contrôle qualité sur l'image à l'upload, ou bascule
    vers construire_entete() qui reconstruit le texte proprement),
    pas dans cette fonction.
    """
    elements = []

    chemin_image = Path(meta["chemin_image_entete"])
    if not chemin_image.exists():
        raise RuntimeError(f"Image d'en-tête introuvable : {chemin_image}")

    largeur_utile = A4[0] - 40 * mm
    with PILImage.open(chemin_image) as im:
        largeur_px, hauteur_px = im.size
    ratio = hauteur_px / largeur_px
    hauteur_utile = largeur_utile * ratio

    elements.append(Image(str(chemin_image), width=largeur_utile, height=hauteur_utile))
    elements.append(Spacer(1, 8))
    elements.append(HRFlowable(width="100%", thickness=0.6, color="black"))
    elements.append(Spacer(1, 10))

    return elements


# ═══════════════════════════════════════════════════════
# CONSTRUCTION DE L'EN-TÊTE -- TEXTE RECONSTRUIT (saisie manuelle CLI)
# ═══════════════════════════════════════════════════════

def construire_entete(meta: dict, styles: dict, sequence: int) -> list:
    """Reconstruit un en-tête officiel bilingue en texte. Utilisée
    uniquement quand meta ne contient PAS 'chemin_image_entete'."""
    elements = []

    if meta.get("bilingue", True):
        gauche = (
            "REPUBLIQUE DU CAMEROUN<br/>PAIX - TRAVAIL - PATRIE<br/>"
            "MINISTERE DES ENSEIGNEMENTS SECONDAIRES<br/>"
            f"{meta['delegation'].upper()}<br/>{meta['etablissement'].upper()}"
        )
        droite = (
            "REPUBLIC OF CAMEROON<br/>PEACE - WORK - FATHERLAND<br/>"
            "MINISTRY OF SECONDARY EDUCATION<br/>"
            f"REGIONAL DELEGATION FOR {meta['region'].upper()}<br/>{meta['etablissement'].upper()}"
        )
        table_entete = Table(
            [[Paragraph(gauche, styles["entete_petit"]),
              Paragraph(droite, styles["entete_petit"])]],
            colWidths=[85 * mm, 85 * mm],
        )
        table_entete.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(table_entete)
    else:
        entete_fr = (
            "REPUBLIQUE DU CAMEROUN<br/>PAIX - TRAVAIL - PATRIE<br/>"
            "MINISTERE DES ENSEIGNEMENTS SECONDAIRES<br/>"
            f"{meta['delegation'].upper()}<br/>{meta['etablissement'].upper()}"
        )
        elements.append(Paragraph(entete_fr, styles["entete_petit"]))

    elements.append(Spacer(1, 8))
    elements.append(HRFlowable(width="100%", thickness=0.6, color="black"))
    elements.append(Spacer(1, 6))

    ordinaux = {1: "1ere", 2: "2e", 3: "3e", 4: "4e"}
    titre = (f"EPREUVE DE MATHEMATIQUES - ANNEE SCOLAIRE {meta['annee_scolaire']}<br/>"
             f"EXAMEN : {ordinaux.get(sequence, sequence)} SEQUENCE - CLASSE : TERMINALE C<br/>"
             f"DUREE : {meta['duree'].upper()} - COEFFICIENT : {meta['coefficient']}")
    elements.append(Paragraph(titre, styles["entete_titre"]))
    elements.append(HRFlowable(width="100%", thickness=0.6, color="black"))
    elements.append(Spacer(1, 10))

    return elements


# ═══════════════════════════════════════════════════════
# CONSTRUCTION DU CORPS (sujet uniquement -- pas de corrigé)
# ═══════════════════════════════════════════════════════

def construire_corps(contenu: dict, styles: dict) -> list:
    elements = []

    for partie in contenu.get("parties", []):
        type_p = partie.get("type_partie", "")
        bareme = partie.get("bareme_points", "")

        if type_p == "ressources":
            elements.append(Paragraph(
                f"PARTIE A : EVALUATION DES RESSOURCES ({bareme} points)",
                styles["section"]
            ))
            for exercice in partie.get("exercices", []):
                elements.append(Paragraph(
                    f"{exercice.get('titre', 'EXERCICE')} ({exercice.get('bareme_points', '')} points)",
                    styles["exercice_titre"]
                ))
                if exercice.get("enonce_intro"):
                    markup = texte_vers_markup_reportlab(exercice["enonce_intro"], styles["corps_intro"].fontSize)
                    elements.append(Paragraph(markup, styles["corps_intro"]))
                for q in exercice.get("questions", []):
                    markup_q = texte_vers_markup_reportlab(q.get("texte", ""), styles["corps"].fontSize)
                    bareme_q = q.get("bareme", "")
                    ligne = f"{q.get('numero', '')} {markup_q} <i>({bareme_q} pt)</i>"
                    elements.append(Paragraph(ligne, styles["corps"]))

        elif type_p == "competences":
            elements.append(Paragraph(
                f"PARTIE B : EVALUATION DES COMPETENCES ({bareme} points)",
                styles["section"]
            ))
            if partie.get("situation_contexte"):
                markup = texte_vers_markup_reportlab(partie["situation_contexte"], styles["corps_intro"].fontSize)
                elements.append(Paragraph(f"<b>SITUATION :</b> {markup}", styles["corps_intro"]))
            for tache in partie.get("taches", []):
                markup_t = texte_vers_markup_reportlab(tache.get("texte", ""), styles["corps"].fontSize)
                bareme_t = tache.get("bareme", "")
                ligne = f"{tache.get('numero', '')} {markup_t} <i>({bareme_t} pt)</i>"
                elements.append(Paragraph(ligne, styles["corps"]))

    presentation = contenu.get("presentation_points", 0)
    if presentation:
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(f"<i>Presentation : {presentation} pt</i>", styles["corps_intro"]))

    # CORRECTIF (24/08/2026, audit visuel) : mention de clôture. Une
    # dernière page qui s'arrête net sur "Presentation : 0.5 pt" avec
    # du blanc en dessous donne l'impression d'un document coupé,
    # même quand le contenu est complet. Cette mention est un usage
    # standard des épreuves camerounaises réelles -- elle ferme
    # visuellement le document, que la page soit remplie à 95% ou à
    # 20%. Ne remplace pas la logique d'ajustement, la complète.
    elements.append(Paragraph("* * *  FIN DE L'ÉPREUVE  * * *", styles["fin_epreuve"]))

    return elements


# ═══════════════════════════════════════════════════════
# PAGINATION
# ═══════════════════════════════════════════════════════

def dessiner_pied_de_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Times-Roman", 8.5)
    canvas.drawCentredString(A4[0] / 2, 12 * mm, str(doc.page))
    canvas.restoreState()


# ═══════════════════════════════════════════════════════
# MESURE DU REMPLISSAGE DE LA DERNIÈRE PAGE
# ═══════════════════════════════════════════════════════

def _mesurer_remplissage_derniere_page(chemin_pdf: Path) -> tuple[int, float]:
    """Retourne (nombre_de_pages, fraction_remplissage_derniere_page).

    La fraction est calculée comme la position verticale du contenu le
    plus bas de la dernière page, divisée par la hauteur totale de la
    page -- une fraction basse (ex: 0.25) signifie que la dernière
    page est presque vide, symptôme d'un léger débordement de la page
    précédente plutôt que d'un vrai besoin de cette page entière.

    Import de pdfplumber fait ICI (pas en tête de fichier) : cette
    fonction n'est appelée que par la logique d'ajustement, pas par un
    usage simple du module -- évite d'imposer cette dépendance à qui
    n'a besoin que du rendu de base."""
    import pdfplumber

    with pdfplumber.open(str(chemin_pdf)) as pdf:
        nb_pages = len(pdf.pages)
        derniere = pdf.pages[-1]
        mots = derniere.extract_words()
        images_page = derniere.images

        positions_basses = [m["bottom"] for m in mots]
        positions_basses += [img["bottom"] for img in images_page]

        if not positions_basses:
            return nb_pages, 0.0

        bas_contenu = max(positions_basses)
        return nb_pages, bas_contenu / derniere.height


# ═══════════════════════════════════════════════════════
# FONCTION APPELABLE (Flask) + MAIN (CLI)
# ═══════════════════════════════════════════════════════

def _construire_elements(paquet: dict, echelle: float) -> tuple[list, dict]:
    """Reconstruit la liste de flowables à une échelle donnée -- isolé
    dans sa propre fonction pour être appelé plusieurs fois par la
    boucle d'ajustement sans dupliquer la logique de routage
    en-tête/corps."""
    meta = paquet["metadonnees"]
    contenu = paquet["contenu"]
    sequence = contenu.get("sequence", "?")

    styles = construire_styles(echelle)

    elements = []
    if meta.get("chemin_image_entete"):
        elements += construire_entete_image(meta, styles)
    else:
        elements += construire_entete(meta, styles, sequence)
    elements += construire_corps(contenu, styles)

    return elements, meta


def construire_pdf(chemin_json: Path) -> Path:
    """
    Lève RuntimeError (fichier introuvable, ou image d'en-tête
    manquante) ou RenduMathEchoue (une expression LaTeX n'a pas pu
    être rendue) en cas d'échec -- jamais de PDF partiellement
    construit avec du contenu dégradé écrit silencieusement sur
    disque.

    Applique la logique "réduire pour ajuster" (voir note en tête de
    fichier) : si la première construction laisse une dernière page
    presque vide, reconstruit avec un espacement légèrement réduit,
    jusqu'à NB_TENTATIVES_AJUSTEMENT tentatives -- jamais en dessous
    de ECHELLE_MINIMALE, pour ne jamais produire un texte illisible.
    S'arrête plus tôt si les tentatives n'améliorent plus le
    remplissage (cas où Partie B est structurellement courte -- voir
    note en tête de fichier, correctif du 24/08/2026).
    Si aucune tentative ne satisfait le seuil, on garde SIMPLEMENT LA
    MEILLEURE tentative observée plutôt que d'échouer : un léger blanc
    en fin de document reste un défaut cosmétique mineur, jamais une
    raison de bloquer la livraison d'une épreuve par ailleurs correcte.

    Retourne le chemin du PDF écrit (même dossier que le JSON, même
    nom avec extension .pdf) UNIQUEMENT si la construction a réussi
    intégralement.
    """
    if not chemin_json.exists():
        raise RuntimeError(f"Fichier JSON introuvable : {chemin_json}")

    paquet = json.loads(chemin_json.read_text(encoding="utf-8"))
    chemin_pdf = chemin_json.with_suffix(".pdf")

    def _construire_a_echelle(echelle: float) -> None:
        elements, _ = _construire_elements(paquet, echelle)
        doc = SimpleDocTemplate(
            str(chemin_pdf), pagesize=A4,
            topMargin=18 * mm, bottomMargin=18 * mm,
            leftMargin=20 * mm, rightMargin=20 * mm,
        )
        doc.build(elements, onFirstPage=dessiner_pied_de_page, onLaterPages=dessiner_pied_de_page)

    # Première construction, à taille normale -- peut lever
    # RenduMathEchoue ou RuntimeError, on laisse remonter tel quel,
    # aucune tentative d'ajustement n'a de sens si le contenu de base
    # est cassé.
    echelle = 1.0
    _construire_a_echelle(echelle)

    try:
        nb_pages, remplissage = _mesurer_remplissage_derniere_page(chemin_pdf)
    except Exception:
        # pdfplumber indisponible ou PDF illisible pour la mesure --
        # ne bloque JAMAIS la livraison pour cette seule raison, le
        # PDF construit à l'échelle 1.0 reste un résultat valide.
        return chemin_pdf

    meilleure_echelle = echelle
    meilleur_remplissage = remplissage

    tentative = 0
    tentatives_sans_amelioration = 0
    while (
        nb_pages > 1
        and remplissage < SEUIL_REMPLISSAGE_MINIMUM
        and tentative < NB_TENTATIVES_AJUSTEMENT
        and echelle * FACTEUR_REDUCTION_PAR_TENTATIVE >= ECHELLE_MINIMALE
        and tentatives_sans_amelioration < NB_TENTATIVES_SANS_AMELIORATION_AVANT_ARRET
    ):
        echelle *= FACTEUR_REDUCTION_PAR_TENTATIVE
        _construire_a_echelle(echelle)
        try:
            nb_pages, remplissage = _mesurer_remplissage_derniere_page(chemin_pdf)
        except Exception:
            break

        # On garde en mémoire la meilleure tentative vue jusqu'ici --
        # si on n'atteint jamais le seuil idéal, on reconstruira avec
        # celle-ci plutôt que de rester sur la toute dernière (qui
        # pourrait être pire si la réduction a, par exemple, fait
        # basculer le contenu sur une page supplémentaire au lieu
        # d'une de moins, cas limite mais possible).
        if nb_pages == 1 or remplissage > meilleur_remplissage:
            meilleure_echelle = echelle
            meilleur_remplissage = remplissage
            tentatives_sans_amelioration = 0
        else:
            # CORRECTIF (24/08/2026) : cette tentative n'a rien
            # amélioré (voire dégradé le remplissage) -- typiquement
            # le cas où Partie B est structurellement courte plutôt
            # qu'un débordement. Continuer à réduire ne fait que
            # perdre en lisibilité sans gagner en remplissage.
            tentatives_sans_amelioration += 1

        tentative += 1

    if echelle != meilleure_echelle:
        _construire_a_echelle(meilleure_echelle)

    return chemin_pdf


def main():
    parser = argparse.ArgumentParser(description="Construit le PDF officiel à partir du JSON généré")
    parser.add_argument("--fichier", required=True, help="Chemin du fichier JSON produit par generer_epreuve_json.py")
    args = parser.parse_args()

    chemin_json = Path(args.fichier)
    print(f"🖨️  Construction du PDF...")

    try:
        chemin_pdf = construire_pdf(chemin_json)
    except RenduMathEchoue as e:
        print(f"❌ Échec de rendu mathématique -- le JSON contient du LaTeX non supporté :\n   {e}")
        print("   Ce contenu n'aurait pas dû passer la validation dans generer_epreuve_json.py --")
        print("   vérifie valider_epreuve.py (regarde si un nouveau pattern doit être ajouté à")
        print("   PATTERNS_LATEX_INTERDITS) plutôt que de retoucher ce PDF à la main.")
        return
    except RuntimeError as e:
        print(f"❌ {e}")
        return

    print(f"✅ PDF généré : {chemin_pdf}")


if __name__ == "__main__":
    main()