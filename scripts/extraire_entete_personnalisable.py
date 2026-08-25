# scripts/extraire_entete_personnalisable.py
"""
Extraction PUIS personnalisation de l'en-tête d'une épreuve réelle
uploadée par le prof -- garde l'image (logo, mise en page exacte de
l'établissement) tout en rendant modifiables les données variables
(année, séquence, classe, durée, coefficient, examinateur...).

Deux étapes obligatoires, dans cet ordre :
  1. extraire_entete_pour_upload() : lit l'en-tête (page complète, PAS
     encore découpée), stocke le résultat sous un jeton temporaire,
     retourne les champs trouvés pour que le prof les édite.
  2. personnaliser_et_decouper() : recharge ce qui a été stocké, fusionne
     avec les valeurs éditées par le prof, RETOUCHE l'image (recouvre +
     réécrit chaque champ modifié), DÉCOUPE, sauvegarde le résultat final.

Coût maîtrisé volontairement : 1 appel Gemini principal (extraction) +
au plus 1 appel de vérification du découpage + un repli purement local
(pas d'appel API) si la vérification échoue encore.

FIX (24/08/2026) -- en-tête coupée en plein milieu d'un tableau,
perdant des champs entiers (classe, durée, coefficient...) : la
vérification post-découpage ne savait que RÉTRÉCIR la zone (en cas de
mots interdits détectés), jamais l'ÉLARGIR. Si l'estimation initiale
de Gemini était déjà trop courte, rien ne rattrapait ça. On vérifie
maintenant aussi si le contenu est visiblement tronqué (nouveau champ
VerificationDecoupe.contenu_visuellement_tronque, voir schema_entete.py)
et on élargit la zone dans ce cas -- en cas de doute, on préfère
toujours garder un peu de marge blanche en trop plutôt que de perdre
une information d'identification de l'épreuve.

Nécessite : pip install -U google-genai pillow pypdfium2 matplotlib
Nécessite : la variable d'environnement GEMINI_API_KEY

Ce fichier n'a pas d'usage CLI direct (pas de argparse/main()) -- il
n'est utilisé que par import, donc l'import relatif pur (`from
.schema_entete import ...`) est sans risque ici, contrairement à
generer_epreuve_json.py qui a besoin du repli absolu pour son usage CLI.
"""

import os
import io
import json
import time
import uuid
from pathlib import Path

from PIL import Image
from google.genai import types

from .schema_entete import ExtractionEnteteComplete, VerificationDecoupe
from .personnaliser_entete import personnaliser_entete_image, decouper_a_la_fraction
from .gemini_client import construire_clients, generer_avec_fallback

DOSSIER_ENTETES_TMP = Path("data/_tmp_entetes_upload")
DOSSIER_ENTETES_TMP.mkdir(parents=True, exist_ok=True)

DUREE_VIE_MAX_SEC = 3600  # 1 heure

MARGE_RESSERRAGE_LOCALE = 0.03
# FIX (24/08/2026, v4) : avec moins de tentatives disponibles (budget
# réduit pour ne pas exploser le quota Gemini gratuit, voir plus bas),
# chaque tentative doit couvrir plus de terrain d'un coup. 0.05 -> 0.08.
MARGE_ELARGISSEMENT_LOCALE = 0.08

# FIX (24/08/2026, v3) -- RÉGRESSION DE LA v2 CORRIGÉE : la v2 utilisait
# un seul compteur global (NB_TENTATIVES_RECADRAGE_MAX=5) pour les DEUX
# directions. Résultat observé en usage réel : un en-tête où Gemini
# signalait (à tort ou de façon répétée) des "mots interdits" pouvait
# resserrer 5 fois de suite (5 x 3% = 15% de la page perdue) au lieu de
# 2 fois avant (6%) -- au point de ne garder que le nom de
# l'établissement, perdant logo/année/classe/durée/coefficient. Le
# budget donné à l'élargissement (nécessaire, cf FIX v2) a été
# accidentellement aussi donné au resserrage, qui n'a AUCUN garde-fou
# empêchant de descendre trop bas.
#
# Les deux directions ont maintenant des budgets INDÉPENDANTS : le
# resserrage garde son budget d'origine (prudent, l'objectif est juste
# d'exclure du contenu pédagogique visible, pas de comprimer l'en-tête
# au minimum), l'élargissement garde le budget élargi (nécessaire pour
# rattraper une sous-estimation initiale).
NB_TENTATIVES_RESSERRAGE_MAX = 1
NB_TENTATIVES_ELARGISSEMENT_MAX = 2
NB_TENTATIVES_RECADRAGE_MAX = NB_TENTATIVES_RESSERRAGE_MAX + NB_TENTATIVES_ELARGISSEMENT_MAX

# Garde-fou supplémentaire, indépendant du nombre d'itérations : quoi
# qu'il arrive, on ne descend jamais sous ce pourcentage de la
# fraction ESTIMÉE INITIALEMENT par Gemini. L'estimation initiale de
# Gemini regarde la page complète et identifie correctement le bloc
# d'en-tête dans l'immense majorité des cas -- une boucle de resserrage
# qui finit par descendre à moins de 60% de cette estimation initiale
# est presque certainement en train de sur-corriger sur un faux
# positif, pas de trouver une vraie limite plus précise.
PLANCHER_RATIO_ESTIMATION_INITIALE = 0.60

# Sécurité finale : si le budget de tentatives est épuisé et que la
# DERNIÈRE vérification connue indiquait encore une troncature, on
# élargit une dernière fois par cette marge fixe, SANS revérifier
# (aucun appel Gemini de plus -- coût maîtrisé). Perdre un champ
# d'identification (classe, durée, coefficient) est strictement pire
# qu'une marge blanche en trop dans le PDF final.
MARGE_SECURITE_FINALE = 0.06

PROMPT_EXTRACTION = """Voici la première page d'une épreuve scolaire camerounaise \
(photo de téléphone, scan, ou export PDF -- qualité potentiellement médiocre).

Fais deux choses en même temps :

1. Identifie où se termine le bloc d'en-tête institutionnel (logo, établissement, \
région/délégation, année scolaire, classe, durée, coefficient, examinateur, séquence). \
RÈGLE ABSOLUE : le bloc d'en-tête s'arrête OBLIGATOIREMENT avant la première ligne \
contenant un des mots suivants : "PARTIE", "EXERCICE", "EVALUATION DES", "POINTS", \
"SITUATION". Ces mots marquent le début du contenu pédagogique, jamais de l'en-tête -- \
même si le document a un cadre continu qui les englobe visuellement avec l'en-tête. \
RÈGLE TOUT AUSSI IMPORTANTE : si l'en-tête est un tableau, ne coupe JAMAIS au milieu \
d'une ligne ou d'une cellule -- inclus la ligne entière même si ça ajoute un peu de \
marge, la coupure doit tomber juste après la dernière ligne complète du tableau.

2. Repère CHAQUE champ de donnée variable dans ce bloc d'en-tête (année scolaire, \
séquence, classe, durée, coefficient, nom de l'examinateur, établissement, région, \
délégation -- et tout autre champ variable présent sur ce document précis), avec sa \
position précise dans la page (coordonnées en fraction 0-1 de la page COMPLÈTE, \
pas de la zone découpée)."""

PROMPT_VERIFICATION = """Cette image est le haut d'une épreuve scolaire, découpée pour \
n'en garder que le bloc d'en-tête institutionnel.

Réponds à trois questions :
1. Cette image contient-elle un des mots 'PARTIE', 'EXERCICE', 'EVALUATION DES', \
'POINTS' ou 'SITUATION' (contenu pédagogique qui n'a rien à faire dans un en-tête) ?
2. Cette image se termine-t-elle en plein milieu d'une ligne de tableau, d'une cellule, \
ou d'un bloc de texte visiblement incomplet (ex: on ne voit que le haut d'une ligne, une \
bordure tranchée avant sa fin, un mot coupé) ? Réponds False si l'image se termine \
proprement (ligne blanche, fin nette de tableau, ou juste avant le contenu pédagogique).
3. La toute première ligne visible EN HAUT de l'image (logo, nom d'établissement, \
première ligne d'un tableau) est-elle elle-même coupée en plein milieu d'un caractère, \
d'un mot, ou d'une bordure ? Réponds False si le haut commence proprement, même si c'est \
juste une marge blanche avant le contenu."""


class EnteteSourceIncomplete(RuntimeError):
    """Levée quand le HAUT de l'en-tête est déjà coupé dans la photo/
    scan uploadé par le prof -- aucun recadrage de fraction ne peut
    réparer ça, la donnée manquante n'existe simplement pas dans
    l'image source. Doit remonter jusqu'à app.py pour afficher un
    message clair ("recadre ta photo") plutôt qu'une tentative de
    correction automatique vouée à l'échec."""
    pass


class ExtractionEnteteEchouee(RuntimeError):
    pass


def _charger_premiere_page_en_image(chemin_fichier: Path) -> Image.Image:
    suffixe = chemin_fichier.suffix.lower()
    if suffixe == ".pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(str(chemin_fichier))
        page = pdf[0]
        bitmap = page.render(scale=200 / 72)
        image_pil = bitmap.to_pil().convert("RGB")
        pdf.close()
        return image_pil
    return Image.open(chemin_fichier).convert("RGB")


def _verifier_decoupe(clients, image_decoupee: Image.Image) -> tuple[bool, bool, bool]:
    """Retourne (contient_mots_interdits, contenu_visuellement_tronque,
    haut_de_page_deja_tronque). En cas d'échec de l'appel de
    vérification (réseau, quota épuisé sur TOUTES les clés/modèles...),
    on retourne (True, False, False) -- prudence : on force un
    resserrage plutôt qu'un élargissement par défaut, car un échec
    silencieux de cette vérification ne doit jamais risquer de laisser
    du contenu pédagogique dans l'en-tête.

    `clients` : voir gemini_client.construire_clients() -- fallback
    automatique multi-modèles ET multi-clés en cas de 429/503, au lieu
    d'un seul client codé en dur (FIX 24/08/2026, v4 -- avant, un seul
    quota épuisé bloquait toute vérification, forçant une repli
    systématique sur le resserrage prudent, donc des en-têtes
    inutilement rognées dès que le quota gratuit était entamé)."""
    tampon = io.BytesIO()
    image_decoupee.save(tampon, format="PNG")
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=VerificationDecoupe,
        max_output_tokens=150,
    )
    contents = [
        types.Part.from_bytes(data=tampon.getvalue(), mime_type="image/png"),
        PROMPT_VERIFICATION,
    ]
    try:
        response, _modele, _cle = generer_avec_fallback(clients, contents, config)
        resultat = getattr(response, "parsed", None)
        if resultat is None:
            return True, False, False
        return (
            bool(resultat.contient_mots_interdits),
            bool(resultat.contenu_visuellement_tronque),
            bool(resultat.haut_de_page_deja_tronque),
        )
    except Exception:
        return True, False, False


def extraire_entete(chemin_fichier: Path) -> tuple[Image.Image, float, list[dict], str]:
    if not chemin_fichier.exists():
        raise ExtractionEnteteEchouee(f"Fichier introuvable : {chemin_fichier}")

    try:
        clients = construire_clients()
    except RuntimeError as e:
        raise ExtractionEnteteEchouee(str(e))

    try:
        image_page = _charger_premiere_page_en_image(chemin_fichier)
    except ExtractionEnteteEchouee:
        raise
    except Exception as e:
        raise ExtractionEnteteEchouee(f"Document illisible : {e}")

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=ExtractionEnteteComplete,
        max_output_tokens=3000,
    )

    tampon = io.BytesIO()
    image_page.save(tampon, format="PNG")

    try:
        response, _modele, _cle = generer_avec_fallback(
            clients,
            [
                types.Part.from_bytes(data=tampon.getvalue(), mime_type="image/png"),
                PROMPT_EXTRACTION,
            ],
            config,
        )
    except Exception as e:
        raise ExtractionEnteteEchouee(f"Erreur API Gemini : {e}")

    resultat = getattr(response, "parsed", None)
    if resultat is None:
        raison = None
        try:
            raison = response.candidates[0].finish_reason
        except Exception:
            pass
        extrait = (response.text or "")[:300] if getattr(response, "text", None) else "(aucun texte)"
        raise ExtractionEnteteEchouee(
            f"Réponse Gemini non exploitable. Raison de fin : {raison}. Extrait brut : {extrait}"
        )

    largeur, hauteur = image_page.size
    fraction_initiale = max(0.05, min(0.6, resultat.fraction_bas_entete))
    fraction = fraction_initiale

    # FIX (24/08/2026, v3) : plancher absolu -- quoi qu'il arrive, on
    # ne descend jamais sous ce pourcentage de l'estimation initiale de
    # Gemini (voir constante PLANCHER_RATIO_ESTIMATION_INITIALE plus
    # haut). Coupe court à un resserrage qui s'emballerait sur un faux
    # positif répété.
    plancher_absolu = max(0.05, fraction_initiale * PLANCHER_RATIO_ESTIMATION_INITIALE)

    dernier_tronque = False
    fractions_vues = set()
    convergence_propre = False
    nb_resserrages = 0
    nb_elargissements = 0

    for _ in range(NB_TENTATIVES_RECADRAGE_MAX):
        if fraction in fractions_vues:
            fraction = min(0.6, fraction + MARGE_ELARGISSEMENT_LOCALE)
        fractions_vues.add(fraction)

        image_test = image_page.crop((0, 0, largeur, int(hauteur * fraction)))
        contient_interdits, tronque, haut_tronque = _verifier_decoupe(clients, image_test)
        dernier_tronque = tronque

        # FIX (24/08/2026, v2) : si le HAUT est déjà coupé, aucun
        # ajustement de fraction (qui ne joue que sur le BAS) ne peut
        # réparer ça -- la donnée manquante n'existe pas dans la photo
        # source. On arrête tout de suite plutôt que de tourner pour
        # rien dans la boucle, et on remonte une erreur explicite.
        if haut_tronque:
            raise EnteteSourceIncomplete(
                "Le haut de l'en-tête (logo ou première ligne) est coupé dans la photo "
                "envoyée -- reprends la photo en cadrant un peu plus large en haut."
            )

        if contient_interdits:
            # FIX (24/08/2026, v3) : budget de resserrage indépendant
            # ET jamais sous le plancher absolu -- avant, ce chemin
            # pouvait grignoter 5 fois de suite (15% de la page) sans
            # aucune limite basse, au point de ne garder que le nom de
            # l'établissement. Un faux positif répété de Gemini ne doit
            # plus pouvoir démolir un en-tête par ailleurs correct.
            nb_resserrages += 1
            if nb_resserrages > NB_TENTATIVES_RESSERRAGE_MAX or fraction <= plancher_absolu:
                # On accepte cette fraction telle quelle -- redescendre
                # encore risque de perdre plus d'information utile que
                # ce que ça vaut la peine d'exclure comme contenu
                # pédagogique. Mieux vaut un peu de contenu pédagogique
                # visible en trop (rare, cf le mot détecté est souvent
                # dans une bordure de tableau) qu'un en-tête décapité.
                break
            fraction = max(plancher_absolu, fraction - MARGE_RESSERRAGE_LOCALE)
            continue
        if tronque:
            nb_elargissements += 1
            if nb_elargissements > NB_TENTATIVES_ELARGISSEMENT_MAX:
                break
            nouvelle_fraction = min(0.6, fraction + MARGE_ELARGISSEMENT_LOCALE)
            if nouvelle_fraction == fraction:
                break
            fraction = nouvelle_fraction
            continue
        convergence_propre = True
        break

    # FIX (24/08/2026, v2) -- LE CORRECTIF PRINCIPAL : le budget de
    # tentatives est épuisé SANS que la dernière image testée ait été
    # revérifiée propre. Avant, ce cas livrait silencieusement une
    # image potentiellement encore tronquée. On élargit maintenant une
    # dernière fois, sans appel API, par sécurité -- jamais l'inverse
    # (on ne resserre jamais sans vérification, un excès de contenu
    # pédagogique visible est pire qu'une marge blanche).
    if not convergence_propre and dernier_tronque:
        fraction = min(0.6, fraction + MARGE_SECURITE_FINALE)

    champs = [
        {
            "label": c.label,
            "valeur": c.valeur,
            "boite": (
                {"x": c.boite.x, "y": c.boite.y, "largeur": c.boite.largeur, "hauteur": c.boite.hauteur}
                if c.boite else None
            ),
        }
        for c in resultat.champs
    ]

    return image_page, fraction, champs, resultat.confiance


def nettoyer_entetes_expirees(age_max_secondes: int = DUREE_VIE_MAX_SEC):
    maintenant = time.time()
    for chemin in DOSSIER_ENTETES_TMP.glob("*"):
        try:
            if maintenant - chemin.stat().st_mtime > age_max_secondes:
                chemin.unlink(missing_ok=True)
        except OSError:
            continue


def extraire_entete_pour_upload(chemin_fichier: Path) -> tuple[str, str, list[dict]]:
    image_page, fraction, champs, confiance = extraire_entete(chemin_fichier)

    jeton = uuid.uuid4().hex
    image_page.save(DOSSIER_ENTETES_TMP / f"{jeton}_page.png", format="PNG")
    (DOSSIER_ENTETES_TMP / f"{jeton}_contexte.json").write_text(
        json.dumps({"fraction": fraction, "champs": champs}, ensure_ascii=False),
        encoding="utf-8",
    )
    return jeton, confiance, champs


def personnaliser_et_decouper(jeton: str, valeurs_editees: dict) -> tuple[Path, dict]:
    chemin_page = DOSSIER_ENTETES_TMP / f"{jeton}_page.png"
    chemin_contexte = DOSSIER_ENTETES_TMP / f"{jeton}_contexte.json"
    if not chemin_page.exists() or not chemin_contexte.exists():
        raise ExtractionEnteteEchouee("Session d'en-tête expirée ou introuvable -- réuploade l'épreuve.")

    image_page = Image.open(chemin_page)
    contexte = json.loads(chemin_contexte.read_text(encoding="utf-8"))
    fraction = contexte["fraction"]
    champs = contexte["champs"]

    champs_confirmes = [
        {
            "label": c["label"],
            "valeur_originale": c["valeur"],
            "valeur_finale": str(valeurs_editees.get(c["label"], c["valeur"]))[:200].strip() or c["valeur"],
            "boite": c.get("boite"),
        }
        for c in champs
    ]

    image_personnalisee = personnaliser_entete_image(image_page, champs_confirmes)
    image_decoupee = decouper_a_la_fraction(image_personnalisee, fraction)

    chemin_final = DOSSIER_ENTETES_TMP / f"{jeton}_final.png"
    image_decoupee.save(chemin_final, format="PNG")

    contexte_regional = {}
    for c in champs_confirmes:
        label_bas = c["label"].lower()
        if "region" in label_bas or "région" in label_bas:
            contexte_regional["region"] = c["valeur_finale"]
        elif "classe" in label_bas:
            contexte_regional["classe"] = c["valeur_finale"]

    return chemin_final, contexte_regional


def generer_apercu_brut(jeton: str) -> bytes:
    chemin_page = DOSSIER_ENTETES_TMP / f"{jeton}_page.png"
    chemin_contexte = DOSSIER_ENTETES_TMP / f"{jeton}_contexte.json"
    if not chemin_page.exists() or not chemin_contexte.exists():
        raise ExtractionEnteteEchouee("Session d'en-tête expirée ou introuvable -- réuploade l'épreuve.")

    image_page = Image.open(chemin_page)
    contexte = json.loads(chemin_contexte.read_text(encoding="utf-8"))
    image_decoupee = decouper_a_la_fraction(image_page, contexte["fraction"])

    tampon = io.BytesIO()
    image_decoupee.convert("RGB").save(tampon, format="PNG")
    return tampon.getvalue()


def supprimer_extraction_temporaire(jeton: str):
    for suffixe in ("_page.png", "_contexte.json", "_final.png"):
        (DOSSIER_ENTETES_TMP / f"{jeton}{suffixe}").unlink(missing_ok=True)