# scripts/image_utils.py — ExamensCam
"""
Compression d'image cote serveur avant envoi a Gemini Vision.

RAISON : un eleve qui prend une photo avec l'appareil de son telephone
produit souvent un fichier de 3 a 8 Mo. Deux problemes distincts que
la compression resout d'un coup :

  1. Upload lent/instable sur une connexion Maroua -- un fichier plus
     petit part plus vite et echoue moins souvent en cours de route.
  2. Cout Gemini -- l'API facture par "tuile" d'image (des blocs de
     pixels fixes), pas par poids de fichier. Une image redimensionnee
     a une resolution raisonnable consomme moins de tuiles, donc moins
     de tokens factures a l'eleve, sans perte de lisibilite pour un
     exercice de maths/physique manuscrit ou imprime.

CHOIX DE RESOLUTION : 1600px de cote le plus long. Suffisant pour
qu'un texte manuscrit ou une formule reste lisible par Gemini Vision --
au-dela, on paie plus de tuiles sans gain de precision reel pour de
l'OCR de texte/formules (contrairement a une photo artistique ou un
plan detaille).

FORMAT DE SORTIE : JPEG qualite 82 -- bon compromis nettete/poids pour
du texte noir sur fond clair (le cas quasi systematique d'un exercice
photographie). Pas de PNG : inutilement lourd pour ce type de contenu.
"""

import io
from PIL import Image, ImageOps

RESOLUTION_MAX_COTE = 1600
QUALITE_JPEG = 82
POIDS_MAX_ENTREE_MO = 15  # limite de securite avant meme de tenter la compression


class ImageInvalideError(Exception):
    """Levee si le fichier recu n'est pas une image exploitable, ou
    depasse la limite de poids brute -- avant tout traitement Pillow,
    pour ne pas gaspiller de CPU sur un fichier absurde ou malveillant."""
    pass


def compresser_image_pour_gemini(donnees_brutes: bytes) -> bytes:
    """Prend les octets bruts d'une image uploadee (n'importe quel
    format courant : JPEG, PNG, HEIC via Pillow si le plugin est
    present, WEBP...), retourne des octets JPEG optimises.

    Leve ImageInvalideError si le fichier est trop lourd ou illisible
    -- a l'appelant (route Flask) de renvoyer une erreur claire a
    l'eleve plutot qu'un plantage serveur brut."""
    poids_mo = len(donnees_brutes) / (1024 * 1024)
    if poids_mo > POIDS_MAX_ENTREE_MO:
        raise ImageInvalideError(
            f"Image trop lourde ({poids_mo:.1f} Mo, maximum {POIDS_MAX_ENTREE_MO} Mo)."
        )

    try:
        image = Image.open(io.BytesIO(donnees_brutes))
        # exif_transpose : corrige l'orientation selon les metadonnees
        # EXIF -- essentiel pour les photos prises au telephone, qui
        # sont souvent stockees "a plat" avec juste un tag de rotation.
        # Sans ca, une photo prise en portrait peut arriver a Gemini
        # tournee de 90 degres.
        image = ImageOps.exif_transpose(image)
        image = image.convert('RGB')  # aplati transparence eventuelle (PNG) sur fond blanc
    except Exception as e:
        raise ImageInvalideError(f"Fichier image illisible : {e}")

    largeur, hauteur = image.size
    cote_max_actuel = max(largeur, hauteur)
    if cote_max_actuel > RESOLUTION_MAX_COTE:
        facteur = RESOLUTION_MAX_COTE / cote_max_actuel
        nouvelle_taille = (round(largeur * facteur), round(hauteur * facteur))
        image = image.resize(nouvelle_taille, Image.LANCZOS)

    tampon_sortie = io.BytesIO()
    image.save(tampon_sortie, format='JPEG', quality=QUALITE_JPEG, optimize=True)
    return tampon_sortie.getvalue()