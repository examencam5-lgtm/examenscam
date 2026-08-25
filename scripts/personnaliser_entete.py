from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import matplotlib.font_manager as fm

MARGE_SECURITE_HORIZONTALE_RATIO = 0.15
MARGE_SECURITE_VERTICALE_RATIO = 0.30
MARGE_SECURITE_MINIMALE_PX = 6

# FIX (24/08/2026, v2) -- texte fantôme malgré la marge en %% : le
# ratio est appliqué à la boîte DÉTECTÉE PAR GEMINI elle-même. Si
# Gemini sous-estime déjà la largeur réelle du texte d'origine (cas
# fréquent sur les champs courts -- une année, un chiffre de
# coefficient -- où l'incertitude de détection reste en gros
# constante en PIXELS, pas proportionnelle à la taille du champ), 15%
# d'une boîte déjà trop petite reste une marge trop petite en absolu.
# On ajoute donc un plancher de marge exprimé en fraction de la
# HAUTEUR de la boîte (proxy fiable de la taille de police réelle,
# donc de l'ampleur possible de l'erreur de mesure), qui prend le
# dessus sur le ratio quand ce dernier donnerait une marge trop
# maigre pour un texte court.
#
# FIX (24/08/2026, v3) -- RÉGRESSION DE LA v2 CORRIGÉE : ce plancher
# était appliqué SYMÉTRIQUEMENT (gauche ET droite). Cas observé en
# usage réel : le champ "Année scolaire :" (label statique) suivi de
# sa valeur -- la marge généreuse à GAUCHE de la boîte de la valeur
# mordait dans la fin du label ("...aire :"), le recouvrant, et
# laissait un "Année scol" tronqué visible avant la nouvelle valeur
# collée plus loin. Le label n'a jamais été identifié comme un champ
# éditable, il ne devrait donc JAMAIS être recouvert.
#
# Le point de départ (x) d'une valeur détecté par Gemini est presque
# toujours fiable -- l'incertitude de mesure porte sur la LARGEUR
# (donc la fin, à droite), pas sur le début. La marge de sécurité est
# maintenant asymétrique : généreuse à droite (là où une sous-
# estimation de largeur ferait déborder du texte fantôme), minimale à
# gauche (là où un excès mangerait dans le label voisin).
MARGE_PLANCHER_RATIO_HAUTEUR = 0.9  # appliqué uniquement à droite désormais
MARGE_GAUCHE_RATIO = 0.05  # marge gauche volontairement faible, fixe

# FIX (24/08/2026, v4) -- "T^leC" collé : la marge gauche minimale
# (v3) empêche de recouvrir le label, mais ne garantit aucun espace
# de RESPIRATION entre la fin du label et le texte redessiné -- si la
# boîte détectée par Gemini pour la valeur démarre pile contre le
# glyphe précédent (fréquent sur un champ court comme une lettre de
# classe collée à un exposant "T^le"), le texte réécrit hérite du
# même collage. On décale donc le point de départ du DESSIN (pas du
# recouvrement, qui reste inchangé) d'un petit padding fixe, sans quoi
# aucune marge horizontale ne corrige jamais ce cas précis.
PADDING_TEXTE_GAUCHE_RATIO = 0.12  # fraction de la hauteur de la boîte

# FIX (24/08/2026, v4) -- police qui jure avec le gabarit d'origine :
# DejaVu Sans est la police par défaut de matplotlib/Linux, pas celle
# des en-têtes d'établissement (généralement Arial/Helvetica ou une
# serif type Times New Roman/Cambria pour les gabarits MINESEC). Sur
# un champ réécrit au milieu d'un label resté intact, la différence de
# graisse et d'empattement est visible même quand la position au pixel
# est correcte -- c'est ce qui donne l'impression de "collage" en plus
# du problème d'espacement. Cette police par défaut reste un choix par
# défaut RAISONNABLE (large couverture Unicode, toujours disponible
# sans dépendance) mais devrait être remplaçable par établissement --
# voir POLICE_PAR_DEFAUT et le nouveau paramètre `police_nom` de
# personnaliser_entete_image(). Idéalement, la police à utiliser
# viendrait de schema_entete.py (métadonnée par gabarit), pas d'une
# constante globale ici -- ouvert tant que ce n'est pas branché.
POLICE_PAR_DEFAUT = "DejaVu Sans"


def _charger_police(taille_px: int, nom_police: str = POLICE_PAR_DEFAUT) -> ImageFont.FreeTypeFont:
    try:
        chemin_police = fm.findfont(nom_police, fallback_to_default=False)
    except Exception:
        # Police demandée introuvable sur le système -- on retombe
        # sur la police par défaut plutôt que de planter la
        # personnalisation pour un problème de police manquante.
        chemin_police = fm.findfont(POLICE_PAR_DEFAUT)
    return ImageFont.truetype(chemin_police, size=max(8, taille_px))


def _echantillonner_couleur_fond(image: Image.Image, x: int, y: int, w: int, h: int) -> tuple:
    marge = max(2, h // 4)
    y_echantillon = max(0, y - marge)
    bande = image.crop((x, y_echantillon, x + w, y_echantillon + marge))
    if bande.width == 0 or bande.height == 0:
        return (255, 255, 255)
    bande_rgb = bande.convert("RGB")
    pixels = list(bande_rgb.getdata())

    SEUIL_LUMINOSITE_BORDURE = 180
    pixels_fond = [p for p in pixels if sum(p[:3]) / 3 > SEUIL_LUMINOSITE_BORDURE]

    if not pixels_fond:
        return (255, 255, 255)

    r = sum(p[0] for p in pixels_fond) // len(pixels_fond)
    g = sum(p[1] for p in pixels_fond) // len(pixels_fond)
    b = sum(p[2] for p in pixels_fond) // len(pixels_fond)
    return (r, g, b)


def personnaliser_entete_image(
    image_page: Image.Image,
    champs_confirmes: list[dict],
    police_nom: str = POLICE_PAR_DEFAUT,
) -> Image.Image:
    """`police_nom` : nom de police à utiliser pour le texte réécrit.
    Reste optionnel avec DejaVu Sans par défaut (comportement
    inchangé) -- mais un appelant qui connaît la police du gabarit
    d'origine (via schema_entete.py, par établissement) peut désormais
    la passer pour éviter le contraste visuel avec le label d'origine.
    Voir note FIX v4 en tête de fichier."""
    image_modifiee = image_page.copy().convert("RGB")
    draw = ImageDraw.Draw(image_modifiee)
    largeur_img, hauteur_img = image_modifiee.size

    for champ in champs_confirmes:
        if champ.get("valeur_finale") == champ.get("valeur_originale"):
            continue
        boite = champ.get("boite")
        if boite is None:
            continue

        x = int(boite["x"] * largeur_img)
        y = int(boite["y"] * hauteur_img)
        w = max(1, int(boite["largeur"] * largeur_img))
        h = max(1, int(boite["hauteur"] * hauteur_img))

        # FIX (24/08/2026, v3) : marge asymétrique -- gauche minimale
        # (fixe, ne mord jamais dans un label voisin), droite généreuse
        # (absorbe une largeur de texte sous-estimée). Voir note FIX
        # en tête de fichier.
        marge_gauche = max(MARGE_SECURITE_MINIMALE_PX, int(w * MARGE_GAUCHE_RATIO))
        marge_droite = max(
            MARGE_SECURITE_MINIMALE_PX,
            int(w * MARGE_SECURITE_HORIZONTALE_RATIO),
            int(h * MARGE_PLANCHER_RATIO_HAUTEUR),
        )
        marge_v = max(MARGE_SECURITE_MINIMALE_PX, int(h * MARGE_SECURITE_VERTICALE_RATIO))
        x_recouvre = max(0, x - marge_gauche)
        y_recouvre = max(0, y - marge_v)
        w_recouvre = w + marge_gauche + marge_droite
        h_recouvre = h + 2 * marge_v

        couleur_fond = _echantillonner_couleur_fond(image_modifiee, x_recouvre, y_recouvre, w_recouvre, h_recouvre)
        draw.rectangle(
            [x_recouvre, y_recouvre, x_recouvre + w_recouvre, y_recouvre + h_recouvre],
            fill=couleur_fond,
        )

        # FIX (24/08/2026, v4) : point de départ du texte décalé d'un
        # petit padding fixe par rapport à x -- garantit une respiration
        # visuelle après le label voisin, indépendamment de la marge de
        # recouvrement (qui elle doit rester minimale à gauche pour ne
        # pas manger le label, voir v3). Sans ce décalage, un champ dont
        # la boîte détectée démarre pile contre le glyphe précédent
        # (ex: "C" contre l'exposant "le") reproduit le même collage
        # après réécriture.
        padding_texte_gauche = max(2, int(h * PADDING_TEXTE_GAUCHE_RATIO))
        x_texte = x + padding_texte_gauche

        police = _charger_police(int(h * 0.8), nom_police=police_nom)
        largeur_texte = draw.textlength(str(champ["valeur_finale"]), font=police)

        # FIX (24/08/2026, v2) : si la nouvelle valeur est plus longue
        # que l'ancienne (ex: "2026/2027" écrit dans une police dont
        # le rendu est plus large que l'estimation d'origine), le
        # texte peut dépasser à droite de la zone recouverte -- on
        # mesure sa largeur réelle avant de l'écrire et on élargit le
        # recouvrement à droite si besoin, plutôt que de laisser le
        # nouveau texte déborder sur du contenu non recouvert. Le
        # padding gauche ajouté ci-dessus fait partie de l'espace
        # occupé par le texte, donc il entre dans ce calcul.
        if x_texte + largeur_texte > x_recouvre + w_recouvre:
            surplus = int(x_texte + largeur_texte - (x_recouvre + w_recouvre)) + marge_droite
            draw.rectangle(
                [x_recouvre + w_recouvre, y_recouvre, x_recouvre + w_recouvre + surplus, y_recouvre + h_recouvre],
                fill=couleur_fond,
            )

        draw.text((x_texte, y), str(champ["valeur_finale"]), fill=(0, 0, 0), font=police)

    return image_modifiee


def decouper_a_la_fraction(image_page: Image.Image, fraction: float) -> Image.Image:
    largeur, hauteur = image_page.size
    return image_page.crop((0, 0, largeur, int(hauteur * fraction)))