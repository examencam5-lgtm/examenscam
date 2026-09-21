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
                      chat_contexte.py.
  - MODE_GENERIQUE : aucun corpus dédié, mais le tuteur reste actif
                      avec un prompt calibré (FCFA, ancrage
                      camerounais, fidélité au programme MINESEC) --
                      sans extraits réels, dégradation assumée et
                      annoncée au modèle lui-même (voir
                      chat_contexte.construire_prompt_systeme_generique).

CORRECTIF (13/09/2026) : ("Probatoire", "C")["Mathematiques"] passe de
MODE_GENERIQUE à MODE_RAG -- le corpus rag.db contient désormais 25
épreuves Probatoire C Mathématiques réellement transcrites, ainsi que
la progression MINESEC Première C importée dans themes/lecons. Laisser
ce niveau/série en MODE_GENERIQUE alors que la donnée réelle existait
déjà en base était la cause du bug observé en production.

CORRECTIF (19/09/2026) -- DÉCOUPLAGE GÉNÉRATION PDF / MODE RAG :
`chat_disponible_pour(niveau, serie)` déduisait auparavant la
disponibilité de la génération PDF (boutons Examen/Séquence) du mode
RAG de Mathématiques pour ce niveau/série. Ça marchait tant que seul
BAC C avait Mathématiques en MODE_RAG. Dès qu'un autre niveau/série a
Mathématiques en MODE_RAG (chat conversationnel), ce raccourci
activerait À TORT les boutons de génération PDF, alors que
generer_epreuve_json.py ne sait générer un PDF calibré (barème,
format) que pour BAC C. Le mode RAG d'une matière (peut-on discuter
avec un vrai corpus ?) et la capacité de génération PDF (peut-on
produire un examen structuré en PDF pour ce niveau/série ?) sont deux
choses indépendantes -- l'une ne doit jamais se déduire de l'autre.
GENERATION_PDF_ACTIF ci-dessous remplace cette déduction implicite par
une liste explicite.

CORRECTIF (19/09/2026) -- PROBATOIRE D COMPLET : les 5 matières
importées et transcrites pour Probatoire D (Mathematiques 1999-2025,
Physique, Informatique, SVT, Chimie) sont toutes verifie_vision en
base -- confirmé par requête directe. Passées en MODE_RAG.

CORRECTIF (19/09/2026) -- BAC D COMPLET : même travail que Probatoire D
appliqué à Bac D -- import et transcription des 5 matières (79
sessions au total : Mathematiques 1999-2024, Physique, Chimie, SVT,
Informatique), toutes verifie_vision sauf une session isolée (SVT
2015, échec de segmentation Gemini après 3 tentatives -- ligne en
base non écrasée, à retenter plus tard). Les 5 matières passent en
MODE_RAG malgré ce trou isolé : une session manquante ou en échec
d'une matière ne bloque jamais le mode RAG de la matière entière, elle
sera simplement absente des résultats de recherche d'exercice réel
pour cette année précise (voir chat_bac_officiel.obtenir_exercice_bac,
qui retourne None proprement dans ce cas, jamais une erreur).

RÉTROCOMPATIBILITÉ (important) : `chat_disponible_pour(niveau, serie)`
et `message_indisponible(niveau, serie)` gardent EXACTEMENT leur
signature à 2 arguments -- app.py les appelle ainsi à 2 endroits :
  - route `/`                        : active/désactive les boutons de
    génération (Examen/Séquence) + ton du message d'accueil.
  - route `/assistant-eleve/generer` : génération de PDF elle-même.
Depuis le 19/09/2026, ces deux fonctions répondent uniquement d'après
GENERATION_PDF_ACTIF -- plus aucun lien avec le mode RAG.

Le contrôle par matière pour le chat conversationnel passe par
`matiere_disponible_pour(niveau, serie, matiere)`, utilisé UNIQUEMENT
par `/assistant-eleve/repondre`.

POURQUOI CETTE VÉRIFICATION EXISTE : sans elle, un élève pourrait
déclencher un appel Gemini réel (coût réel, quota réel) sur un
niveau/série/matière que le site ne couvre pas du tout -- le tuteur
répondrait alors avec des connaissances génériques du modèle, SANS
AUCUN calibrage MINESEC/camerounais. Mieux vaut un message honnête
"pas encore disponible" qu'une réponse plausible mais non calibrée.
"""

MODE_RAG = "rag"
MODE_GENERIQUE = "generique"

# Seule matière avec un corpus RAG "historique" -- conservée pour
# rétrocompatibilité de mode_pour(), mais n'a plus aucun lien avec la
# génération PDF depuis le découplage du 19/09/2026 (voir
# GENERATION_PDF_ACTIF).
MATIERE_RAG_PRINCIPALE = "Mathematiques"

# ═══════════════════════════════════════════════════════
# Génération de PDF (Examen/Séquence) -- INDÉPENDANT de SCOPE_ACTIF.
#
# SCOPE_ACTIF dit "je peux discuter avec un corpus RAG sur cette
# matière" ; ça ne dit RIEN sur la capacité de generer_epreuve_json.py
# à produire un PDF avec le bon barème/format pour ce niveau/série.
# Ne JAMAIS déduire l'un de l'autre implicitement (voir piège du
# 19/09/2026 documenté en tête de fichier).
#
# Pour activer la génération PDF sur un nouveau niveau/série, il faut
# D'ABORD étendre generer_epreuve_json.py pour ce niveau/série, PUIS
# ajouter l'entrée ici -- jamais l'inverse.
# ═══════════════════════════════════════════════════════
GENERATION_PDF_ACTIF = {
    ("BAC", "C"),
}

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
        "Physique": MODE_RAG,
        "Chimie": MODE_RAG,
        "SVT": MODE_RAG,
        "Informatique": MODE_RAG,
        "Philosophie": MODE_GENERIQUE,
        "Français": MODE_GENERIQUE,
        "Anglais": MODE_GENERIQUE,
    },
    ("BAC", "D"): {
        "Mathematiques": MODE_RAG,
        "Physique": MODE_RAG,
        "Chimie": MODE_RAG,
        "SVT": MODE_RAG,
        "Informatique": MODE_RAG,
    },
    ("BAC", "TI"): {
        "Mathematiques": MODE_GENERIQUE,
        "Physique": MODE_RAG,
    },
    ("BAC", "A4"): {
        "Mathematiques": MODE_GENERIQUE,
    },
    ("Probatoire", "C"): {
        "Mathematiques": MODE_RAG,
        "Physique": MODE_RAG,
    },
    ("Probatoire", "D"): {
        "Mathematiques": MODE_RAG,
        "Physique": MODE_RAG,
        "Informatique": MODE_RAG,
        "SVT": MODE_RAG,
        "Chimie": MODE_RAG,
    },
    ("Probatoire", "TI"): {
        "Mathematiques": MODE_GENERIQUE,
        "Physique": MODE_RAG,
    },
    ("Probatoire", "A4"): {
        "Mathematiques": MODE_GENERIQUE,
    },
    ("BEPC", None): {
        "Mathematiques": MODE_GENERIQUE,
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
    """True si CETTE matière précise est couverte (RAG ou générique)
    pour ce niveau/série. Utilisé uniquement par
    /assistant-eleve/repondre, où l'élève choisit sa matière de
    discussion dans la sidebar."""
    return mode_pour(niveau, serie, matiere) is not None


def matieres_disponibles(niveau: str, serie: str | None) -> list[str]:
    """Liste triée des matières couvertes (tous modes confondus) pour
    ce niveau/série -- alimente le sélecteur de matière du chat
    (sidebar assistant_eleve.html). Liste vide si rien n'est couvert
    pour ce niveau/série."""
    matieres = _matieres_du_scope(niveau, serie)
    return sorted(matieres.keys()) if matieres else []


def chat_disponible_pour(niveau: str, serie: str | None) -> bool:
    """SIGNATURE INCHANGÉE (2 arguments). DEPUIS LE 19/09/2026 :
    contrôle UNIQUEMENT la génération de PDF (Examen/Séquence) via
    GENERATION_PDF_ACTIF -- découplé du mode RAG du chat
    conversationnel (voir piège documenté en tête de fichier). NE PAS
    réintroduire de lien avec SCOPE_ACTIF/mode_pour ici : ça
    recréerait exactement le bug corrigé."""
    return (niveau, serie) in GENERATION_PDF_ACTIF


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