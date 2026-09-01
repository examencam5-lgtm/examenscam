# scripts/chat_scope.py
"""
Périmètre réel du chat élève (29/08/2026, révisé -- granularité
matière ajoutée) -- séparé de chat_contexte.py et chat_intent_epreuve.py
à dessein : quand une nouvelle matière, série ou niveau sera activé
(RAG réel ou simplement mode générique), la SEULE chose à modifier est
SCOPE_ACTIF ci-dessous. Aucun autre fichier n'a besoin de connaître
cette structure -- ils appellent uniquement les fonctions publiques.

RÉVISION (29/08/2026) -- granularité par matière : la version
précédente ne distinguait que (niveau, série), pas la matière -- ce
qui autorisait implicitement N'IMPORTE QUELLE matière dès que le
niveau/série était actif, alors que seule Mathématiques dispose d'un
vrai corpus RAG (data/rag_maths_bac_c/rag.db, 70 épreuves). Ce fichier
introduit deux modes explicites par matière :

  - MODE_RAG       : corpus réel disponible (thèmes + extraits MINESEC
                      authentiques injectés dans le prompt) -- voir
                      chat_contexte.py. Uniquement Mathématiques pour
                      l'instant (voir MATIERE_RAG_PRINCIPALE).
  - MODE_GENERIQUE : aucun corpus dédié, mais le tuteur reste actif
                      avec un prompt calibré (FCFA, ancrage
                      camerounais, fidélité au programme MINESEC) --
                      sans extraits réels, dégradation assumée et
                      annoncée au modèle lui-même (voir
                      chat_contexte.construire_prompt_systeme_generique).

RÉTROCOMPATIBILITÉ (important) : `chat_disponible_pour(niveau, serie)`
et `message_indisponible(niveau, serie)` gardent EXACTEMENT leur
signature à 2 arguments -- app.py les appelle ainsi à 2 endroits qui
concernent la génération de PDF (toujours Mathématiques uniquement,
voir generer_epreuve_json.py) et jamais la matière choisie dans le
chat :
  - route `/`                        : active/désactive les boutons de
    génération (Examen/Séquence) + ton du message d'accueil.
  - route `/assistant-eleve/generer` : génération de PDF elle-même.
Ces deux fonctions équivalent maintenant à "le mode RAG Mathématiques
est actif pour ce niveau/série" -- comportement bit à bit identique à
la version précédente de ce fichier (qui ne connaissait que ça).

Le nouveau contrôle par matière (chat conversationnel, pas génération)
passe par `matiere_disponible_pour(niveau, serie, matiere)`, utilisé
UNIQUEMENT par `/assistant-eleve/repondre`.

POURQUOI CETTE VÉRIFICATION EXISTE : sans elle, un élève pourrait
déclencher un appel Gemini réel (coût réel, quota réel) sur un
niveau/série/matière que le site ne couvre pas du tout -- le tuteur
répondrait alors avec des connaissances génériques du modèle, SANS
AUCUN calibrage MINESEC/camerounais. Mieux vaut un message honnête
"pas encore disponible" qu'une réponse plausible mais non calibrée.
"""

MODE_RAG = "rag"
MODE_GENERIQUE = "generique"

# Seule matière avec un corpus RAG réel aujourd'hui -- référencée par
# nom plutôt que codée en dur à chaque usage, pour qu'un futur second
# corpus RAG (ex: Physique, le jour où il existera) n'oblige pas à
# fouiller tout le fichier pour trouver où "Mathematiques" est
# supposé implicitement.
MATIERE_RAG_PRINCIPALE = "Mathematiques"

# Clé : (niveau, serie). serie=None signifie "toutes les séries de ce
# niveau" (utile le jour où un niveau sans distinction de série, comme
# BEPC, sera activé).
#
# Valeur : dict {matiere: mode}. Une matière absente de ce dict pour
# un niveau/série actif est TOUJOURS considérée indisponible -- pas de
# repli implicite sur MODE_GENERIQUE, pour ne jamais activer une
# matière par oubli plutôt que par décision explicite.
#
# Noms de matières alignés sur CATALOGUE['BAC']['C'] dans app.py.
SCOPE_ACTIF = {
    ("BAC", "C"): {
        "Mathematiques": MODE_RAG,
        "Physique": MODE_GENERIQUE,
        "Chimie": MODE_GENERIQUE,
        "SVT": MODE_GENERIQUE,
        "Philosophie": MODE_GENERIQUE,
        "Français": MODE_GENERIQUE,
        "Anglais": MODE_GENERIQUE,
    },
}


def _matieres_du_scope(niveau: str, serie: str | None) -> dict | None:
    """Retourne le dict {matiere: mode} applicable, en tenant compte
    du repli serie=None. None si aucune entrée ne couvre ce
    niveau/série du tout."""
    if (niveau, serie) in SCOPE_ACTIF:
        return SCOPE_ACTIF[(niveau, serie)]
    if (niveau, None) in SCOPE_ACTIF:
        return SCOPE_ACTIF[(niveau, None)]
    return None


def mode_pour(niveau: str, serie: str | None, matiere: str) -> str | None:
    """Retourne MODE_RAG, MODE_GENERIQUE, ou None si indisponible --
    utilisé par chat_contexte.py pour savoir s'il doit interroger
    rag.db ou se contenter d'un prompt générique calibré."""
    matieres = _matieres_du_scope(niveau, serie)
    if not matieres:
        return None
    return matieres.get(matiere)


def matiere_disponible_pour(niveau: str, serie: str | None, matiere: str) -> bool:
    """NOUVEAU (29/08/2026) -- True si CETTE matière précise est
    couverte (RAG ou générique) pour ce niveau/série. Utilisé
    uniquement par /assistant-eleve/repondre, où l'élève choisit sa
    matière de discussion dans la sidebar."""
    return mode_pour(niveau, serie, matiere) is not None


def matieres_disponibles(niveau: str, serie: str | None) -> list[str]:
    """Liste triée des matières couvertes (tous modes confondus) pour
    ce niveau/série -- alimente le sélecteur de matière du chat
    (sidebar assistant_eleve.html). Liste vide si rien n'est couvert
    pour ce niveau/série."""
    matieres = _matieres_du_scope(niveau, serie)
    return sorted(matieres.keys()) if matieres else []


def chat_disponible_pour(niveau: str, serie: str | None) -> bool:
    """SIGNATURE INCHANGÉE (2 arguments) depuis avant l'extension
    multi-matières -- voir note de rétrocompatibilité en tête de
    fichier. Équivaut à : le mode RAG Mathématiques est actif pour ce
    niveau/série. NE PAS étendre cette fonction à un 3e argument --
    créer plutôt une fonction dédiée (voir matiere_disponible_pour)
    pour ne jamais changer le comportement des 2 appelants existants
    par effet de bord."""
    return mode_pour(niveau, serie, MATIERE_RAG_PRINCIPALE) == MODE_RAG


def message_indisponible(niveau: str, serie: str | None, matiere: str | None = None) -> str:
    """`matiere=None` (comportement historique, les 2 sites d'appel
    liés à la génération PDF appellent toujours ainsi) -> message
    générique sur le niveau/série, TEXTE IDENTIQUE à la version
    précédente de ce fichier -- aucun appelant existant ne voit son
    message changer.

    `matiere` fourni (nouveau, /assistant-eleve/repondre uniquement)
    -> distingue "niveau/série pas actif du tout" de "matière pas
    encore couverte pour cette série active", avec la liste des
    matières réellement disponibles pour aider l'élève à se rabattre
    sur autre chose immédiatement."""
    libelle_niveau = f"{niveau} {serie}" if serie else niveau
    matieres = _matieres_du_scope(niveau, serie)

    if not matieres or matiere is None:
        return (
            f"Je ne connais pour l'instant que le programme de Terminale C "
            f"(Mathématiques) en détail. La {libelle_niveau} arrive bientôt -- "
            f"reviens un peu plus tard, ou pose-moi une question générale "
            f"en attendant."
        )

    liste = ", ".join(sorted(matieres.keys()))
    return (
        f"Je ne couvre pas encore {matiere} en {libelle_niveau} -- "
        f"pour l'instant je peux t'aider en : {liste}."
    )