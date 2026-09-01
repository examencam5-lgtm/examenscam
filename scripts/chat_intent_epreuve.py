# scripts/chat_intent_epreuve.py
"""
NIVEAU 1 de détection d'intention pour le chat élève (27/08/2026,
réécrit le même jour après correction) -- distingue une demande
d'épreuve EXISTANTE ("montre-moi le sujet de maths lycée VOG 2022")
d'une question conversationnelle normale ("explique-moi les suites
géométriques"), AVANT d'appeler le LLM.

RÉVISION (27/08/2026, même jour) : la première version de ce fichier
réinventait un filtre de recherche maison (requête SQL directe +
filtre par mots-clés sur etablissement/region) au lieu d'utiliser le
moteur de recherche déjà construit et éprouvé du site
(database_search.rechercher_avec_scoring -- alias, scoring par
pertinence/fraîcheur/vues, gestion unifiée officiel+externe). Cette
réécriture élimine complètement le filtre maison et délègue
entièrement la recherche à rechercher_avec_scoring(), qui gère déjà
correctement les noms d'établissement, la région, les alias de
matière/niveau/série (voir database_search.py) -- ce module ne fait
plus QUE la détection d'intention (déclencher ou non la recherche) et
le formatage de la réponse pour le chat.

POLITIQUE DE LIEN (confirmée le 27/08/2026, cohérente avec le reste du
site -- voir generer_search_index.py) : TOUJOURS passer par la page de
redirection interne, JAMAIS un lien brut vers le PDF ou le site tiers
directement dans le chat.
  - type_source == 'officiel' -> destination pointe déjà vers une page
    du site (/annales/.../enonces#card-ANNEE) -- jamais le PDF/Drive
    en direct, c'est déjà la politique existante d'annales.html.
  - type_source == 'externe'  -> destination vaut /redirection/{id} --
    JAMAIS r['lien_externe'] directement. Le chat suit exactement la
    même règle que le reste du site, aucune exception.

SCOPE ACTUEL : le chat élève est positionné sur Terminale C Maths
(générateur d'épreuves), mais rien n'empêche un élève de chercher une
épreuve d'une autre matière de sa série -- la recherche filtre donc
sur niveau='BAC' + serie='C' uniquement (pas de restriction supplémentaire
sur la matière), cohérent avec le programme réel d'un élève de
Terminale C qui a aussi Physique, Chimie, etc.
"""

import re
import unicodedata

# database_search.py et database.py vivent à la RACINE du projet (à
# côté de app.py), PAS dans le package scripts/ -- import absolu
# direct, jamais relatif ici. Fonctionne car app.py (à la racine) est
# le point d'entrée Flask, donc la racine du projet est déjà sur
# sys.path au moment où ce module est chargé (même situation que
# database_externes.py dans la version précédente de ce fichier).
from database_search import rechercher_avec_scoring, enregistrer_recherche_infructueuse

# Scope figé du chat élève -- voir note en tête de fichier.
NIVEAU_FIGE = "BAC"
SERIE_FIGEE = "C"

# Mots qui signalent une demande d'épreuve existante plutôt qu'une
# question de cours. Liste volontairement courte et sans ambiguïté --
# un faux négatif (on rate une demande d'épreuve, l'élève retombe sur
# le LLM conversationnel) est bien moins grave qu'un faux positif (on
# bloque une vraie question de cours contenant le mot "sujet" par
# hasard).
MOTS_DECLENCHEURS = [
    "epreuve", "epreuves", "sujet", "sujets", "devoir", "devoirs",
    "examen", "annale", "annales",
]

NB_RESULTATS_MAX = 4


def _normaliser(texte: str) -> str:
    texte = texte.lower()
    texte = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in texte if not unicodedata.combining(c))


def detecter_demande_epreuve(question: str) -> bool:
    """True si la question ressemble à une demande d'épreuve existante
    -- la présence d'un mot déclencheur est le seul critère, toute la
    finesse (alias, niveau/série/matière/année détectés, scoring de
    pertinence) est déjà gérée par rechercher_avec_scoring() elle-même,
    pas besoin de la dupliquer ici."""
    q_norm = _normaliser(question)
    return any(mot in q_norm for mot in MOTS_DECLENCHEURS)


def chercher_epreuves(question: str) -> dict:
    """Délègue entièrement au moteur de recherche existant du site,
    filtré sur le scope figé (BAC série C) -- voir note en tête de
    fichier. Enregistre aussi une recherche infructueuse quand rien
    n'est trouvé, exactement comme le reste du site (signal
    stratégique pour prioriser le scraping, voir doc section 3.5)."""
    resultat = rechercher_avec_scoring(question, limite=NB_RESULTATS_MAX,
                                        niveau=NIVEAU_FIGE, serie=SERIE_FIGEE)
    if not resultat["resultats"]:
        enregistrer_recherche_infructueuse(question)
    return resultat


def preparer_resultats_epreuves(resultat_recherche: dict) -> dict:
    """RÉVISION (27/08/2026, même jour) : ne construit plus une chaîne
    Markdown à parser -- retourne une structure que le front transforme
    en vraies cartes (voir ajouterCarteResultats() dans
    assistant_eleve.html), cohérent avec le style déjà utilisé par le
    bouton Parcourir. Un simple lien Markdown souligné, titre sur
    plusieurs lignes, sans distinction visuelle, était illisible en
    pratique (constat du 27/08/2026 sur un vrai test).

    Retourne soit :
      {'type': 'resultats', 'intro': '...', 'resultats': [...]}
      {'type': 'texte', 'reponse': '...'}  (rien trouvé -- reste un
      simple message conversationnel, pas une liste vide à afficher
      en cartes)

    TOUJOURS `destination` (page interne ou /redirection/{id}),
    JAMAIS un lien brut vers un PDF ou un site tiers -- voir la note
    de politique en tête de fichier. Chaque élément de `resultats`
    inclut aussi `type_source` (officiel/externe) pour que le front
    puisse distinguer visuellement les deux sans requête supplémentaire."""
    resultats = resultat_recherche["resultats"]

    if not resultats:
        suggestions = resultat_recherche.get("suggestions") or []
        texte = "Je n'ai pas trouvé d'épreuve correspondant à ta recherche dans ce que j'ai indexé pour l'instant."
        if suggestions:
            texte += f" Tu voulais peut-être dire : {', '.join(suggestions)} ?"
        texte += "\n\nTu peux aussi me demander de t'en générer une inédite à la place."
        return {"type": "texte", "reponse": texte}

    return {
        "type": "resultats",
        "intro": "Voici ce que j'ai trouvé :",
        "resultats": [
            {"libelle": r["libelle"], "destination": r["destination"], "type_source": r.get("type_source", "")}
            for r in resultats
        ],
    }