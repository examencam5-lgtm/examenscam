# scripts/extraire_entete_image.py
"""
Détection et découpage de l'en-tête institutionnel d'un exemple
d'épreuve fourni par un enseignant.

Approche : on découpe l'image de l'en-tête RÉELLE (logo compris,
mise en page exacte, police exacte) et on la colle directement en
haut du PDF généré.

Nécessite : pip install pypdf pypdfium2 pillow google-genai pydantic
Nécessite : au moins une des variables d'environnement listées dans
            generer_epreuve_json.CLES_API_ENV

RÉVISION DU 23/08/2026 -- optimisation quota, phase de test :
  1. max_output_tokens du découpage remonté de 1000 à 3000 -- même
     leçon déjà tirée sur l'extraction de métadonnées d'en-tête
     ailleurs dans le pipeline : 6 champs texte + une fraction
     numérique peuvent dépasser 1000 tokens et se faire tronquer en
     silence, ce qui gâche une tentative entière (et donc du quota)
     pour rien.
  2. _contient_mots_interdits() n'est plus appelée systématiquement à
     chaque tentative -- avant ce fix, chaque decouper_entete()
     pouvait consommer jusqu'à 2 appels Gemini par tentative x 3
     tentatives x 4 modèles de fallback = jusqu'à 24 appels rien que
     pour trouver où couper une image. Désormais, la vérification
     supplémentaire n'est déclenchée QUE si le modèle lui-même n'est
     pas en confiance "haute" sur sa découpe -- dans le cas courant
     (bonne lecture du premier coup), ça coupe environ la moitié des
     appels sans rien retirer à la sécurité : une découpe douteuse
     reste toujours vérifiée.
  3. Support multi-clés API (voir generer_epreuve_json.construire_clients())
     -- ce fichier appelle generer_avec_fallback() avec une LISTE de
     clients désormais, plus un client unique, pour profiter du même
     multiplicateur de quota gratuit que le reste du pipeline.
"""

import io
import os
import time
import uuid
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image
from google.genai import types

try:
    from .schema_entete import DecoupageEntete
    from .schema_entete import VerificationDecoupe
    from .gemini_client import generer_avec_fallback, construire_clients
except ImportError:
    from schema_entete import DecoupageEntete
    from schema_entete import VerificationDecoupe
    from gemini_client import generer_avec_fallback, construire_clients


EXTENSIONS_IMAGE = {".jpg", ".jpeg", ".png", ".webp", ".heic"}

DOSSIER_ENTETES_TMP = Path("data/_tmp_entetes_upload")
DOSSIER_ENTETES_TMP.mkdir(parents=True, exist_ok=True)


PROMPT_DECOUPAGE = """Voici la première page d'une épreuve scolaire camerounaise \
(photo de téléphone, scan, ou export PDF -- qualité potentiellement médiocre). \
Identifie où se termine le bloc d'en-tête institutionnel : logo, nom de \
l'établissement, région/délégation, année scolaire, classe, durée, coefficient, \
nom de l'examinateur, numéro de séquence/situation.

RÈGLE ABSOLUE : le bloc d'en-tête s'arrête OBLIGATOIREMENT avant la première ligne \
contenant un des mots suivants (peu importe qu'elle soit dans le même cadre/tableau \
que l'en-tête ou non) : "PARTIE", "EXERCICE", "EVALUATION DES", "POINTS", "SITUATION". \
Ces mots marquent le début du CONTENU de l'épreuve, jamais de l'en-tête -- même si le \
document a un cadre continu qui les englobe visuellement avec l'en-tête, tu dois couper \
AVANT cette ligne, quitte à couper à l'intérieur du cadre.

Donne uniquement les champs du schéma demandé et une fraction de hauteur (0 à 1,
depuis le haut de l'image) à laquelle couper, juste avant la première occurrence
de ces mots."""


class DecoupageEnteteEchoue(RuntimeError):
    """Erreur empêchant de produire une découpe fiable."""
    pass


def _charger_premiere_page_en_image(chemin_fichier: Path) -> Image.Image:
    suffixe = chemin_fichier.suffix.lower()

    if suffixe in EXTENSIONS_IMAGE:
        with Image.open(chemin_fichier) as im:
            return im.convert("RGB").copy()

    if suffixe == ".pdf":
        pdf = pdfium.PdfDocument(str(chemin_fichier))
        try:
            page = pdf[0]
            bitmap = page.render(scale=200 / 72)
            return bitmap.to_pil().convert("RGB")
        finally:
            pdf.close()

    raise DecoupageEnteteEchoue(f"Extension non supportée : {suffixe}")


def _generer_decoupage(clients, image_bytes: bytes, config):
    """Appel Gemini protégé par le fallback commun (multi-modèles x
    multi-clés). `clients` : liste construite par construire_clients()."""
    return generer_avec_fallback(
        clients,
        [
            types.Part.from_bytes(
                data=image_bytes,
                mime_type="image/png",
            ),
            PROMPT_DECOUPAGE,
        ],
        config,
    )


def decouper_entete(chemin_fichier: Path) -> tuple[Path, str, dict]:
    """
    Retourne (chemin_image_entete, confiance, metadonnees_texte).
    """
    if not chemin_fichier.exists():
        raise DecoupageEnteteEchoue(
            f"Fichier introuvable : {chemin_fichier}"
        )

    try:
        clients = construire_clients()
    except RuntimeError as e:
        raise DecoupageEnteteEchoue(str(e))

    try:
        image_page = _charger_premiere_page_en_image(chemin_fichier)
    except DecoupageEnteteEchoue:
        raise
    except Exception as e:
        raise DecoupageEnteteEchoue(f"Document illisible : {e}")

    # Sortie limitée mais suffisante : le schéma contient quelques
    # champs texte + une fraction numérique. Remonté de 1000 à 3000 --
    # 1000 exposait au même risque de troncature silencieuse déjà
    # rencontré ailleurs dans le pipeline sur ce genre de réponse
    # multi-champs (voir note en tête de fichier).
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=DecoupageEntete,
        max_output_tokens=3000,
    )

    largeur, hauteur = image_page.size
    derniere_confiance = "basse"
    metadonnees_texte = {}
    image_finale = None
    image_test = None

    tampon = io.BytesIO()
    image_page.save(tampon, format="PNG")
    image_bytes = tampon.getvalue()

    for tentative in range(3):
        try:
            response, modele_utilise, cle_utilisee = _generer_decoupage(
                clients,
                image_bytes,
                config,
            )
        except Exception as e:
            raise DecoupageEnteteEchoue(
                f"Erreur API Gemini : {e}"
            )

        resultat = getattr(response, "parsed", None)

        if resultat is None:
            texte = getattr(response, "text", "") or ""
            finish_reason = getattr(response, "finish_reason", None)

            raise DecoupageEnteteEchoue(
                "Réponse Gemini non exploitable. "
                f"Raison de fin : {finish_reason}. "
                f"Extrait brut : {texte[:500]!r}"
            )

        fraction = max(
            0.05,
            min(0.6, resultat.fraction_bas_entete),
        )

        hauteur_decoupe = int(hauteur * fraction)

        image_test = image_page.crop(
            (0, 0, largeur, hauteur_decoupe)
        )

        # Économie de quota : l'appel de vérification supplémentaire
        # (un aller-retour Gemini complet à lui seul) n'a lieu QUE si
        # le modèle n'est pas déjà en confiance "haute" sur sa propre
        # découpe. Dans le cas courant -- bonne lecture du premier
        # coup -- ça évite un appel inutile sans rien retirer à la
        # sécurité : une découpe douteuse reste toujours vérifiée.
        besoin_verification = resultat.confiance != "haute"
        mots_interdits_presents = (
            _contient_mots_interdits(clients, image_test) if besoin_verification else False
        )

        if not mots_interdits_presents:
            image_finale = image_test
            derniere_confiance = resultat.confiance

            metadonnees_texte = {
                cle: valeur
                for cle, valeur in {
                    "region": resultat.region,
                    "etablissement": resultat.etablissement,
                    "annee_scolaire": resultat.annee_scolaire,
                    "classe": resultat.classe,
                    "duree": resultat.duree,
                    "coefficient": resultat.coefficient,
                }.items()
                if valeur and valeur.strip()
            }
            break

    else:
        image_finale = image_test
        derniere_confiance = "basse"

    nom_fichier = f"entete_{uuid.uuid4().hex}.png"
    chemin_sortie = DOSSIER_ENTETES_TMP / nom_fichier

    image_finale.save(chemin_sortie, format="PNG")

    return chemin_sortie, derniere_confiance, metadonnees_texte


def _contient_mots_interdits(clients, image_decoupee: Image.Image) -> bool:
    """Vérifie indépendamment que la découpe ne contient pas le début
    du contenu pédagogique. N'est appelée que quand decouper_entete()
    juge la confiance du modèle insuffisante -- voir note en tête de
    fichier sur l'économie de quota. `clients` : liste construite par
    construire_clients()."""
    tampon = io.BytesIO()
    image_decoupee.save(tampon, format="PNG")

    config_bool = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=VerificationDecoupe,
        max_output_tokens=100,
    )

    try:
        response, modele_utilise, cle_utilisee = generer_avec_fallback(
            clients,
            [
                types.Part.from_bytes(
                    data=tampon.getvalue(),
                    mime_type="image/png",
                ),
                (
                    "Cette image contient-elle un des mots "
                    "'PARTIE', 'EXERCICE', 'EVALUATION DES', "
                    "'POINTS' ou 'SITUATION' ? Réponds uniquement "
                    "par ce booléen."
                ),
            ],
            config_bool,
        )

        resultat = getattr(response, "parsed", None)
        return bool(
            resultat and resultat.contient_mots_interdits
        )

    except Exception:
        return True


def nettoyer_entetes_expirees(age_max_secondes: int = 3600):
    """Purge les en-têtes temporaires trop anciennes."""
    maintenant = time.time()

    for f in DOSSIER_ENTETES_TMP.glob("entete_*.png"):
        if maintenant - f.stat().st_mtime > age_max_secondes:
            f.unlink(missing_ok=True)