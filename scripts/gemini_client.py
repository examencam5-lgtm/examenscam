# scripts/gemini_client.py
"""
Point d'entrée UNIQUE pour parler à l'API Gemini dans tout le
pipeline RAG Maths Terminale C -- extrait ici pour casser un import
circulaire : generer_epreuve_json.py importait
extraire_entete_personnalisable.py, qui importait à son tour
generer_avec_fallback() DEPUIS generer_epreuve_json.py. Python ne
peut pas finir de charger un module qui dépend d'un autre module en
train de le charger lui-même.

Ce fichier ne dépend d'AUCUN autre module du package scripts/ -- il
peut donc être importé sans risque par generer_epreuve_json.py,
extraire_entete_personnalisable.py, et extraire_entete_image.py, dans
n'importe quel ordre.

Gère :
  - le fallback multi-modèles (429 quota épuisé, 503 surcharge
    temporaire côté Google, 404 modèle retiré/renommé côté Google)
  - le fallback multi-clés API (jusqu'à 3 clés, une par compte Google,
    pour multiplier le quota gratuit journalier pendant la phase de
    test -- voir CLES_API_ENV)

FIX (25/08/2026) -- 404 NOT_FOUND sur gemini-2.5-flash-lite :
Google a retiré ce modèle pour les nouveaux projets ("no longer
available to new users"). Deux problèmes corrigés :
  1. "gemini-2.5-flash-lite" retiré de MODELES_FALLBACK -- inutile de
     garder dans la liste un modèle qui répondra 404 à chaque fois
     pour ce projet, ça ne fait que gaspiller un essai avant d'arriver
     au modèle suivant qui, lui, fonctionne.
  2. generer_avec_fallback() ne traitait QUE 429 et 503 comme des cas
     "passe au modèle suivant" -- un 404 (modèle inexistant ou retiré)
     remontait immédiatement et cassait toute la chaîne de fallback,
     même s'il restait des modèles valides plus loin dans la liste.
     Un modèle retiré par Google du jour au lendemain est exactement
     le genre de situation que ce fallback est censé absorber : ajouté
     à la détection, sans pause (contrairement au 503, un 404 ne se
     résout jamais en réessayant plus tard sur le même modèle).
"""

import os
import time

from google import genai

# Liste ordonnée de modèles à essayer -- le quota gratuit Gemini est
# compté séparément par modèle, donc si l'un est à sec (429), retiré
# par Google (404) ou surchargé (503), on bascule sur le suivant
# plutôt que de bloquer toute une session de travail. Ordre : du moins
# cher/plus rapide au plus robuste.
MODELES_FALLBACK = [
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash",
]
MODELE_PAR_DEFAUT = MODELES_FALLBACK[0]

# Plusieurs clés API pour multiplier le quota gratuit journalier
# pendant la phase de test (20 requêtes/jour/modèle/PROJET sur le
# free tier -- avec 3 clés issues de 3 comptes Google différents, on
# a 3x cette marge sans rien payer). Ignore silencieusement les
# variables absentes -- pour repasser à une seule clé en usage prod,
# il suffit de ne définir que GEMINI_API_KEY, rien à changer ici.
CLES_API_ENV = ["GEMINI_API_KEY", "GEMINI_API_KEY_SECONDAIRE", "GEMINI_API_KEY_TROISIEME"]


def construire_clients() -> list[tuple[str, "genai.Client"]]:
    """Construit un client Gemini par clé API présente dans
    l'environnement (voir CLES_API_ENV). Ignore silencieusement les
    variables absentes.

    Lève RuntimeError si AUCUNE clé n'est trouvée -- impossible de
    continuer sans au moins une clé API valide."""
    clients = []
    for nom_var in CLES_API_ENV:
        cle = os.environ.get(nom_var)
        if cle:
            clients.append((nom_var, genai.Client(api_key=cle)))
    if not clients:
        raise RuntimeError(
            f"Aucune clé API trouvée parmi {CLES_API_ENV} dans l'environnement."
        )
    return clients


def generer_avec_fallback(clients, contents, config):
    """Essaie chaque combinaison (clé API x modèle), clé par clé --
    on épuise TOUS les modèles d'une clé avant de basculer sur la clé
    suivante, pas l'inverse.

    Bascule sur la combinaison suivante si l'erreur est un 429 (quota
    épuisé), un 503 (surcharge temporaire côté Google), ou un 404
    (modèle inexistant/retiré côté Google -- voir note FIX en tête de
    fichier). Toute autre erreur (réseau, contenu invalide) remonte
    immédiatement.

    Sur un 503, courte pause avant de passer à la combinaison
    suivante -- sur un 404, aucune pause : réessayer plus tard ne
    changera rien, le modèle n'existe simplement plus pour ce projet.

    `clients` : liste de tuples (nom_var_env, client), voir
    construire_clients(). Accepte aussi un client Gemini unique
    (rétro-compatibilité).

    Retourne (response, modele_utilise, nom_cle_utilisee).
    Lève RuntimeError avec la dernière erreur rencontrée si toutes
    les combinaisons échouent."""
    if not isinstance(clients, list):
        clients = [("GEMINI_API_KEY", clients)]

    derniere_erreur = None
    for nom_cle, client in clients:
        for modele in MODELES_FALLBACK:
            try:
                reponse = client.models.generate_content(model=modele, contents=contents, config=config)
                return reponse, modele, nom_cle
            except Exception as e:
                message_erreur = str(e)
                est_quota_epuise = "RESOURCE_EXHAUSTED" in message_erreur or "429" in message_erreur
                est_surcharge = "UNAVAILABLE" in message_erreur or "503" in message_erreur
                est_modele_retire = "NOT_FOUND" in message_erreur or "404" in message_erreur
                if not (est_quota_epuise or est_surcharge or est_modele_retire):
                    raise
                if est_surcharge:
                    time.sleep(3)
                derniere_erreur = e
                continue

    raise RuntimeError(
        f"Tous les modèles sur toutes les clés API sont indisponibles (quota épuisé, "
        f"surcharge, ou modèle retiré). Dernière erreur : {derniere_erreur}"
    )