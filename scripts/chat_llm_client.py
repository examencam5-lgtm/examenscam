# scripts/chat_llm_client.py
"""
Point d'entrée UNIQUE pour la génération de TEXTE LIBRE (conversation,
pas de schéma JSON strict) dans le futur module de chat élève -- voir
la discussion du 26/08/2026 sur l'extension du RAG vers un vrai chat
conversationnel, en plus du générateur d'épreuves existant.

POURQUOI CE FICHIER EST SÉPARÉ DE gemini_client.py (décision
délibérée, pas un oubli) :

  gemini_client.py alimente generer_epreuve_json.py, qui dépend de
  response_schema (Pydantic) pour garantir un JSON structurellement
  valide -- c'est la fondation du principe "fail loudly, jamais
  patcher en silence" sur ce pipeline (voir schema_epreuve.py,
  valider_epreuve.py). Les modèles ouverts servis par Hugging Face
  (Llama, Qwen, Gemma...) ne offrent PAS la même garantie de sortie
  contrainte par schéma. Les mélanger dans le même pool de fallback
  que Gemini pour la génération d'épreuves romprait cette garantie
  sans que ce soit détectable avant le parsing JSON -- un échec
  silencieux de structure, exactement ce qu'on cherche à éviter.

  Ce fichier-ci sert un usage différent : de la génération de texte
  libre (réponse conversationnelle à un élève), où il n'y a pas de
  schéma à respecter -- Gemini et Hugging Face peuvent y cohabiter
  sans risque, et c'est exactement le pool qu'on veut ici pour
  maximiser la capacité gratuite en phase de bootstrap (plusieurs
  clés Gemini + plusieurs clés Hugging Face).

  generer_epreuve_json.py et gemini_client.py restent INCHANGÉS par
  ce fichier -- aucune dépendance croisée dans un sens ou dans l'autre.

FOURNISSEURS GÉRÉS :
  - Gemini (google-genai) -- mêmes clés que gemini_client.py
    (GEMINI_API_KEY, GEMINI_API_KEY_SECONDAIRE, GEMINI_API_KEY_TROISIEME),
    réutilisées ici pour éviter d'avoir à dupliquer la configuration
    Render : les clés servent aux DEUX pools indépendamment.
  - Hugging Face (huggingface_hub.InferenceClient, passerelle
    "router" compatible OpenAI -- voir HF_CLES_API_ENV) -- offre
    gratuite mais non garantie en volume exact (limite de taux non
    publiée précisément par Hugging Face, de l'ordre de quelques
    centaines à ~1000 requêtes/jour selon le modèle et la charge).
    Modèles choisis sous la barre des ~10 milliards de paramètres
    (MODELES_HF_FALLBACK) -- au-delà, la disponibilité sur le tiers
    gratuit devient nettement moins fiable.

ORDRE DE FALLBACK : Gemini d'abord (quota plus prévisible et plus
généreux en pratique), Hugging Face en secours si toutes les clés
Gemini sont épuisées -- pas l'inverse, pour ne pas dégrader la
qualité de réponse par défaut alors que Gemini a encore du quota.

Nécessite : pip install -U google-genai huggingface_hub
Nécessite : au moins une clé listée dans CLES_API_ENV_GEMINI ou
            HF_CLES_API_ENV.

FIX (01/09/2026) -- worker gunicorn tué en plein appel Gemini
(/assistant-eleve/repondre, mode streaming) :
Même cause que le FIX du 01/09/2026 dans gemini_client.py -- un appel
Gemini sans timeout HTTP peut bloquer indéfiniment sur un socket SSL
en lecture (voir traceback Render : ssl.py recv -> httpcore ->
httpx). Gunicorn finit par tuer le worker via son propre timeout, et
le message "SIGKILL! Perhaps out of memory?" dans les logs est
trompeur -- ce n'est pas l'OOM killer, c'est gunicorn qui devine la
cause après coup.

_appeler_gemini() et _appeler_gemini_stream() portent maintenant un
timeout HTTP explicite (TIMEOUT_HTTP_MS). En mode bloc, un dépassement
est une exception ordinaire, absorbée par generer_texte_avec_fallback()
comme n'importe quelle erreur (voir sa docstring -- ici, contrairement
à gemini_client.py, toute exception fait basculer sur l'option
suivante). En mode streaming, la règle de generer_texte_stream_avec_fallback()
s'applique normalement : si le timeout survient avant le premier
morceau, on bascule ; s'il survient après, l'erreur remonte telle
quelle (texte partiel déjà envoyé à l'élève).
"""

import os

from google import genai
from google.genai import types as genai_types
from huggingface_hub import InferenceClient

# Charge .env explicitement -- nécessaire pour le test CLI direct
# (python scripts/chat_llm_client.py), car rien d'autre ne charge ce
# fichier dans ce cas (contrairement à app.py, lancé via Flask, qui a
# déjà son propre chargement de .env quelque part dans son démarrage).
# python-dotenv ignore silencieusement l'appel si .env est absent
# (ex: en production sur Render, où les variables viennent directement
# de l'environnement du service) -- donc sans danger à laisser ici.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ═══════════════════════════════════════════════════════
# Fournisseur Gemini -- mêmes variables d'environnement que
# gemini_client.py (voir CLES_API_ENV là-bas). Dupliquées ici
# volontairement plutôt qu'importées : ce fichier ne doit dépendre
# d'AUCUN autre module du package scripts/, exactement le même
# principe qui a motivé l'extraction de gemini_client.py à l'origine
# (éviter tout risque d'import circulaire futur).
# ═══════════════════════════════════════════════════════

CLES_API_ENV_GEMINI = ["GEMINI_API_KEY", "GEMINI_API_KEY_SECONDAIRE", "GEMINI_API_KEY_TROISIEME"]
MODELE_GEMINI_CHAT = "gemini-flash-lite-latest"  # rapide, adapté à un usage conversationnel

# Timeout HTTP par tentative, en millisecondes -- voir FIX 01/09/2026
# en tête de fichier. Volontairement plus court qu'en génération
# d'épreuves JSON (25s dans gemini_client.py) : un chat élève est un
# usage conversationnel, une réponse qui traîne plus de 20s dégrade
# l'expérience même si elle finit par arriver.
TIMEOUT_HTTP_MS = 20_000

# ═══════════════════════════════════════════════════════
# Fournisseur Hugging Face -- passerelle "router" compatible OpenAI
# (https://router.huggingface.co/v1), gérée par huggingface_hub.
# Un jeton Hugging Face se crée sur huggingface.co/settings/tokens
# (permissions "read" suffisantes pour de l'inférence).
# ═══════════════════════════════════════════════════════

HF_CLES_API_ENV = ["HF_API_KEY", "HF_API_KEY_SECONDAIRE", "HF_API_KEY_TROISIEME"]

# Modèles ouverts sous ~10B paramètres -- zone de meilleure fiabilité
# sur le tiers gratuit Hugging Face. Ordre : capacité décroissante,
# mais toujours dans la zone fiable (pas de modèle >10B ici, qui
# tomberait plus souvent en indisponibilité sur l'API gratuite).
# Qwen2.5 et Gemma2 ont un bon niveau de français, pertinent pour un
# usage élève au Cameroun francophone.
MODELES_HF_FALLBACK = [
    "Qwen/Qwen2.5-7B-Instruct",
    "google/gemma-2-9b-it",
    "meta-llama/Llama-3.1-8B-Instruct",
]

# Timeout HTTP pour les appels Hugging Face, en secondes cette fois --
# huggingface_hub.InferenceClient prend son timeout au constructeur,
# en secondes, pas en millisecondes comme google-genai. Cette
# différence d'unité entre les deux SDK est une source d'erreur
# facile si on copie la valeur telle quelle -- vérifié explicitement
# ici pour ne pas tomber dedans.
TIMEOUT_HF_SECONDES = 20


def construire_pool_clients() -> list[tuple[str, str, object]]:
    """Construit le pool complet, tous fournisseurs confondus.

    Retourne une liste de tuples (fournisseur, nom_var_env, client) :
      - fournisseur : "gemini" ou "huggingface"
      - nom_var_env : nom de la variable d'environnement d'origine
        (utile pour le logging -- savoir quelle clé a servi)
      - client : instance genai.Client (Gemini) ou chaîne du jeton
        brut (Hugging Face -- InferenceClient est reconstruit à la
        volée par génération, voir generer_texte_avec_fallback, car
        il prend le modèle en paramètre de construction et le modèle
        varie à chaque tentative de fallback)

    L'ORDRE compte : tous les clients Gemini d'abord, puis tous les
    clients Hugging Face -- voir la note d'ordre de fallback en tête
    de fichier.

    Lève RuntimeError si AUCUNE clé, tous fournisseurs confondus,
    n'est trouvée -- impossible de continuer sans un seul provider
    disponible."""
    pool = []

    for nom_var in CLES_API_ENV_GEMINI:
        cle = os.environ.get(nom_var)
        if cle:
            pool.append(("gemini", nom_var, genai.Client(api_key=cle)))

    for nom_var in HF_CLES_API_ENV:
        cle = os.environ.get(nom_var)
        if cle:
            pool.append(("huggingface", nom_var, cle))

    if not pool:
        raise RuntimeError(
            f"Aucune clé trouvée parmi {CLES_API_ENV_GEMINI + HF_CLES_API_ENV} "
            f"dans l'environnement -- au moins une clé Gemini ou Hugging Face est requise."
        )
    return pool


def _construire_contenus_et_config(messages: list[dict]):
    """Factorise la conversion messages -> (contenus, config) partagée
    par _appeler_gemini() et _appeler_gemini_stream() -- avant ce fix,
    la même logique de conversion était dupliquée dans les deux
    fonctions, avec le risque qu'un futur correctif (ex: le fix du
    26/08/2026 sur system_instruction) soit appliqué dans l'une et
    oublié dans l'autre."""
    instructions_systeme = [m["content"] for m in messages if m["role"] == "system"]
    system_instruction = "\n\n".join(instructions_systeme) if instructions_systeme else None

    contenus = []
    for m in messages:
        if m["role"] == "system":
            continue
        role_genai = "model" if m["role"] == "assistant" else "user"
        contenus.append(genai_types.Content(role=role_genai, parts=[genai_types.Part(text=m["content"])]))

    http_options = genai_types.HttpOptions(timeout=TIMEOUT_HTTP_MS)
    config = genai_types.GenerateContentConfig(
        system_instruction=system_instruction,
        http_options=http_options,
    )
    return contenus, config


def _appeler_gemini(client, messages: list[dict]) -> str:
    """`messages` au format [{"role": "system"|"user"|"assistant", "content": "..."}]
    -- converti vers le format attendu par google-genai.

    FIX (26/08/2026) : le rôle "system" est extrait et passé via
    system_instruction, PAS mélangé dans `contents` comme un message
    utilisateur normal -- avant ce fix, un message système (voir
    chat_contexte.PROMPT_SYSTEME_BASE) aurait été traité par Gemini
    comme une simple question de l'utilisateur, sans le poids
    d'instruction qu'il doit avoir (risque concret : les règles
    "utilise des FCFA, pas d'euros" auraient pu être diluées plutôt
    que respectées strictement).

    FIX (01/09/2026) : timeout HTTP explicite -- voir TIMEOUT_HTTP_MS
    en tête de fichier."""
    contenus, config = _construire_contenus_et_config(messages)
    reponse = client.models.generate_content(model=MODELE_GEMINI_CHAT, contents=contenus, config=config)
    if not reponse.text:
        raise ValueError("Réponse Gemini vide.")
    return reponse.text


def _appeler_huggingface(jeton: str, modele: str, messages: list[dict]) -> str:
    """Passerelle OpenAI-compatible de Hugging Face -- `messages` est
    déjà au bon format (role "user"/"assistant"/"system"), aucune
    conversion nécessaire contrairement à Gemini.

    FIX (01/09/2026) : timeout explicite au constructeur du client --
    unité en SECONDES ici, pas en millisecondes (voir
    TIMEOUT_HF_SECONDES en tête de fichier)."""
    client = InferenceClient(api_key=jeton, timeout=TIMEOUT_HF_SECONDES)
    completion = client.chat.completions.create(model=modele, messages=messages, max_tokens=1024)
    contenu = completion.choices[0].message.content
    if not contenu:
        raise ValueError(f"Réponse Hugging Face vide (modèle {modele}).")
    return contenu


def generer_texte_avec_fallback(pool: list[tuple[str, str, object]], messages: list[dict]) -> tuple[str, str, str]:
    """Essaie chaque entrée du pool dans l'ordre -- pour Hugging Face,
    essaie en plus chaque modèle de MODELES_HF_FALLBACK avant de
    passer à la clé suivante (même logique qu'un modèle Gemini
    épuisé : on épuise les options de LA clé actuelle avant de
    basculer sur la clé/fournisseur suivant).

    Bascule sur l'option suivante pour toute exception -- contrairement
    à gemini_client.generer_avec_fallback(), qui ne bascule que sur
    des erreurs précises (429/503/404/timeout) parce que la génération
    JSON structurée doit distinguer une vraie erreur API d'un contenu
    invalide. Ici, en texte libre, il n'y a pas de distinction fine à
    faire : n'importe quelle exception (quota, réseau, timeout, modèle
    indisponible) justifie un simple passage à l'option suivante.

    Retourne (texte, fournisseur, identifiant_source) où
    identifiant_source est le nom de variable d'env pour Gemini, ou
    "nom_var_env/nom_modele" pour Hugging Face (pour distinguer quel
    modèle a répondu dans les logs).

    Lève RuntimeError avec la dernière erreur rencontrée si TOUTES
    les options du pool échouent."""
    derniere_erreur = None

    for fournisseur, nom_var, client_ou_jeton in pool:
        if fournisseur == "gemini":
            try:
                texte = _appeler_gemini(client_ou_jeton, messages)
                return texte, fournisseur, nom_var
            except Exception as e:
                derniere_erreur = e
                continue

        elif fournisseur == "huggingface":
            for modele in MODELES_HF_FALLBACK:
                try:
                    texte = _appeler_huggingface(client_ou_jeton, modele, messages)
                    return texte, fournisseur, f"{nom_var}/{modele}"
                except Exception as e:
                    derniere_erreur = e
                    continue

    raise RuntimeError(
        f"Toutes les options du pool (Gemini + Hugging Face) ont échoué. "
        f"Dernière erreur : {derniere_erreur}"
    )


def _appeler_gemini_stream(client, messages: list[dict]):
    """Version streaming de _appeler_gemini() -- même conversion de
    messages, mais utilise generate_content_stream() et yield le
    texte morceau par morceau au lieu de tout attendre puis retourner
    un bloc. Lève ValueError si le flux se termine sans avoir jamais
    produit de texte (réponse vide).

    FIX (01/09/2026) : timeout HTTP explicite -- voir TIMEOUT_HTTP_MS
    en tête de fichier. C'est précisément l'appel qui a provoqué le
    WORKER TIMEOUT du 01/09/2026 sur /assistant-eleve/repondre (voir
    traceback Render : blocage sur ssl.py recv à l'intérieur de ce
    generate_content_stream)."""
    contenus, config = _construire_contenus_et_config(messages)
    flux = client.models.generate_content_stream(model=MODELE_GEMINI_CHAT, contents=contenus, config=config)

    recu_du_texte = False
    for morceau in flux:
        if morceau.text:
            recu_du_texte = True
            yield morceau.text
    if not recu_du_texte:
        raise ValueError("Réponse Gemini vide (stream).")


def _appeler_huggingface_stream(jeton: str, modele: str, messages: list[dict]):
    """Version streaming de _appeler_huggingface() -- stream=True sur
    la passerelle OpenAI-compatible, yield le delta de chaque morceau
    reçu.

    Certains événements du flux Hugging Face peuvent ne pas contenir
    de choix (`choices=[]`). Ils doivent être ignorés plutôt que de
    provoquer un IndexError.

    FIX (01/09/2026) : timeout explicite au constructeur du client --
    même remarque d'unité que _appeler_huggingface() (secondes, pas
    millisecondes)."""
    client = InferenceClient(api_key=jeton, timeout=TIMEOUT_HF_SECONDES)
    flux = client.chat.completions.create(model=modele, messages=messages, max_tokens=1024, stream=True)

    recu_du_texte = False
    for morceau in flux:
        if not morceau.choices:
            continue

        delta = morceau.choices[0].delta
        if not delta:
            continue

        contenu = delta.content
        if contenu:
            recu_du_texte = True
            yield contenu

    if not recu_du_texte:
        raise ValueError(f"Réponse Hugging Face vide (stream, modèle {modele}).")


def generer_texte_stream_avec_fallback(pool: list[tuple[str, str, object]], messages: list[dict]):
    """Version streaming de generer_texte_avec_fallback() -- yield le
    texte au fur et à mesure plutôt que de retourner un bloc complet.

    RÈGLE DE FALLBACK EN STREAMING (différente du mode bloc) : on ne
    bascule sur l'option suivante du pool QUE si aucun morceau n'a
    encore été envoyé pour la tentative en cours. Si l'échec survient
    après que du texte a déjà été streamé vers l'élève, on ne peut
    plus "reprendre proprement" avec un autre fournisseur sans
    dupliquer du texte à l'écran -- dans ce cas, l'erreur remonte
    telle quelle, et l'appelant (voir app.py) garde le texte partiel
    déjà envoyé et affiche un message d'erreur en complément, plutôt
    que de tout recommencer.

    Un timeout HTTP (voir TIMEOUT_HTTP_MS / TIMEOUT_HF_SECONDES) suit
    exactement cette même règle -- s'il survient avant le premier
    morceau, bascule normale ; après, remontée telle quelle.

    Ne retourne rien -- ne peut pas retourner (fournisseur, source)
    comme la version bloc, puisqu'un générateur ne peut pas produire
    de valeur de retour consommable par `yield from`. Si ce diagnostic
    devient nécessaire, il faudra le faire remonter autrement (ex: un
    dict mutable passé en argument)."""
    tentatives = []
    for fournisseur, nom_var, client_ou_jeton in pool:
        if fournisseur == "gemini":
            tentatives.append((nom_var, lambda c=client_ou_jeton: _appeler_gemini_stream(c, messages)))
        elif fournisseur == "huggingface":
            for modele in MODELES_HF_FALLBACK:
                tentatives.append((f"{nom_var}/{modele}",
                                    lambda j=client_ou_jeton, m=modele: _appeler_huggingface_stream(j, m, messages)))

    derniere_erreur = None
    for source, fabrique_generateur in tentatives:
        premier_morceau_envoye = False
        try:
            for morceau in fabrique_generateur():
                premier_morceau_envoye = True
                yield morceau
            return  # généré entièrement avec succès
        except Exception as e:
            derniere_erreur = e
            if premier_morceau_envoye:
                raise  # texte partiel déjà envoyé -- pas de reprise possible, voir docstring
            continue  # rien envoyé pour cette tentative -- on peut basculer sans risque

    raise RuntimeError(
        f"Toutes les options du pool (Gemini + Hugging Face) ont échoué. "
        f"Dernière erreur : {derniere_erreur}"
    )


if __name__ == "__main__":
    # Test manuel rapide en CLI -- ne fait pas partie du pipeline Flask.
    # Usage : python chat_llm_client.py "Explique-moi les suites géométriques"
    import sys

    question = " ".join(sys.argv[1:]) or "Bonjour, peux-tu te présenter en une phrase ?"
    pool = construire_pool_clients()
    print(f"Pool construit : {[(f, n) for f, n, _ in pool]}\n")

    texte, fournisseur, source = generer_texte_avec_fallback(pool, [{"role": "user", "content": question}])
    print(f"[Répondu par {fournisseur} / {source}]\n")
    print(texte)