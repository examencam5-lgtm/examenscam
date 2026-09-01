# scripts/schema_epreuve.py
"""
Schéma structuré de l'épreuve générée -- utilisé comme response_schema
pour l'appel Gemini dans generer_epreuve_json.py.

Pourquoi un vrai schéma Pydantic plutôt que du JSON décrit en texte
dans le prompt (ancienne version) :

  - Le SDK google-genai contraint la génération pour qu'elle respecte
    CE schéma, champ par champ -- ce n'est plus une consigne que le
    modèle peut suivre approximativement.
  - Le JSON renvoyé est garanti syntaxiquement valide par construction
    (c'est l'API qui sérialise, pas le modèle qui doit s'auto-échapper
    en écrivant du texte) -- reparer_echappements_latex() n'est donc
    plus nécessaire.
  - Chaque champ texte porte sa propre consigne de format (via
    `description=`), au lieu d'une seule règle générale noyée dans un
    long prompt -- le modèle la voit au moment précis où il remplit
    CE champ.

IMPORTANT (portée du 22/08/2026) : le corrigé n'est PLUS généré par ce
pipeline pour l'instant (décision explicite -- se concentrer sur des
énoncés fiables et bien mis en forme avant de rouvrir le sujet de la
correction). Aucun champ "corrige" dans ce schéma.

FIX du 23/08/2026 : la description de presentation_points ne disait
pas explicitement que sa valeur est imposée par le prompt (contrainte
chiffrée calculée en Python, voir calculer_repartition_bareme() dans
generer_epreuve_json.py) -- elle suggérait "généralement 0.5" comme
une option parmi d'autres. Reformulée pour que le modèle comprenne
que ce n'est pas à lui de choisir cette valeur.

EXTENSION du 26/08/2026 -- Examens officiels (Baccalauréat) :
Jusqu'ici ce schéma ne couvrait que les épreuves de séquence interne
d'établissement. Deux ajouts, chacun avec une valeur par défaut qui ne
change RIEN au comportement existant pour les épreuves de séquence :

  1. EpreuveGeneree.type_document ('Sequence' par défaut) -- permet de
     distinguer un Examen officiel MINESEC d'une épreuve de séquence
     normale. Alimente rag.db (colonne type_document déjà existante,
     valeur 'examen' déjà utilisée pour la classification du corpus
     scrapé -- voir Scrape_rag_maths_tc.py) et sert de garde dans
     construire_prompt() / valider_epreuve.py.
  2. Question.serie_applicable ('toutes' par défaut) -- les vrais
     sujets de Bac C/E observés (sessions 2019-2025) contiennent
     parfois des questions réservées à une série précise (ex: bloc
     "Série C exclusivement" / "Série E exclusivement" vu dans les
     sujets 2020 et 2021). Cette notion n'existe pas pour une épreuve
     de séquence, d'où le défaut 'toutes' qui la rend invisible sauf
     si explicitement utilisée.

Ces deux champs sont ignorés par le rendu PDF et par la logique de
séquence existante tant que type_document reste 'Sequence' -- aucune
migration de comportement pour l'usage actuel.
"""

from pydantic import BaseModel, Field
from typing import Literal, Optional


# ═══════════════════════════════════════════════════════
# Consigne de notation mathématique, réutilisée sur chaque
# champ texte -- c'est ICI que se joue le fix du bug de fuite
# LaTeX (matplotlib.mathtext ne supporte qu'un sous-ensemble
# de LaTeX, pas les environnements ni \pmod ni \left/\right).
# ═══════════════════════════════════════════════════════

CONSIGNE_LATEX = (
    "Notation mathématique en LaTeX simple entre signes dollar $...$. "
    "AUTORISE : \\frac{a}{b}, exposants x^{2}, indices x_{n}, racines \\sqrt{x}, "
    "lettres grecques (\\alpha, \\theta, \\Omega...), comparateurs \\leq \\geq \\neq \\equiv, "
    "\\in \\mathbb{R} \\mathbb{C} \\mathbb{Z} \\mathbb{N}, parenthèses/crochets normaux ( ) [ ]. "
    "STRICTEMENT INTERDIT : \\begin{...} et \\end{...} (aucun environnement matrice/cases/array), "
    "\\pmod (INTERDIT même sur les exercices de congruences/PGCD/PPCM -- écris plutôt "
    "'a ≡ 3 (mod 5)' comme texte normal, avec le '(mod n)' HORS des signes $...$ ; "
    "exemple concret -- NE JAMAIS écrire $a \\equiv 3 \\pmod{5}$, ÉCRIRE $a \\equiv 3$ (mod 5)), "
    "\\left et \\right (utilise des parenthèses simples). "
    "Pour un système de plusieurs équations ou congruences : NE JAMAIS les mettre dans une "
    "seule expression $...$ avec une accolade -- écris-les comme deux phrases ou deux lignes "
    "de texte normal séparées, chacune avec ses propres $...$ pour les seules parties "
    "mathématiques (ex : \"les entiers a et b vérifient $a \\equiv 3$ (mod 5) et "
    "$a \\equiv 2$ (mod 7)\")."
)


class Question(BaseModel):
    numero: str = Field(description="Numérotation type '1.a)', '2.', '3.b)' -- jamais juste '1' seul.")
    texte: str = Field(description=f"Énoncé de la sous-question. {CONSIGNE_LATEX}")
    bareme: float = Field(
        description="Barème en points de cette sous-question uniquement (ex: 0.25, 0.5, 0.75, 1.0). "
                     "Ne dépasse JAMAIS 1.5 point pour une seule sous-question."
    )
    serie_applicable: Literal["C", "E", "toutes"] = Field(
        default="toutes",
        description="Uniquement pertinent si l'épreuve est un Examen officiel (Bac) -- laisser "
                     "'toutes' pour une épreuve de séquence normale, où cette notion n'existe pas. "
                     "Mettre 'C' ou 'E' UNIQUEMENT si cette question est explicitement réservée à "
                     "une série précise (ex: une question de spécialité mathématique propre à la "
                     "série C, absente en série E). La quasi-totalité des questions d'un Examen "
                     "officiel restent 'toutes' (communes aux deux séries) -- ne marque une "
                     "question 'C' ou 'E' que si le contenu mathématique lui-même l'exige."
    )


class Exercice(BaseModel):
    titre: str = Field(description="Ex: 'EXERCICE 1', 'EXERCICE 2'.")
    bareme_points: float = Field(
        description="Barème total de cet exercice (somme exacte des sous-questions). "
                     "La somme des bareme_points de TOUS les exercices de la Partie A doit "
                     "correspondre exactement à la valeur imposée par la répartition obligatoire "
                     "donnée dans le prompt -- ne choisis pas librement ce total."
    )
    enonce_intro: Optional[str] = Field(
        default=None,
        description=f"Texte d'introduction avant les sous-questions, si nécessaire (contexte, définition "
                     f"de la fonction/suite étudiée...). {CONSIGNE_LATEX} Laisser null si l'exercice "
                     f"commence directement par la question 1."
    )
    questions: list[Question] = Field(
        description="5 à 9 sous-questions selon le barème total de l'exercice, granularité MINESEC "
                     "réelle (chaque étape de raisonnement séparée : 'calculer' puis 'en déduire' sont "
                     "deux sous-questions distinctes, pas une seule)."
    )


class Tache(BaseModel):
    numero: str = Field(description="Ex: '1.', '2.', '3.'")
    texte: str = Field(description=f"Énoncé de la tâche. {CONSIGNE_LATEX}")
    bareme: float = Field(
        description="Barème en points de cette tâche. La somme des bareme de TOUTES les tâches "
                     "de la Partie B doit correspondre exactement à la valeur imposée par la "
                     "répartition obligatoire donnée dans le prompt."
    )


class Partie(BaseModel):
    type_partie: Literal["ressources", "competences"]
    bareme_points: float = Field(
        description="Barème total de cette partie -- valeur EXACTE imposée par la répartition "
                     "obligatoire donnée dans le prompt (calculée pour que le total général de "
                     "l'épreuve fasse 20 points), jamais une valeur choisie librement ni une moyenne "
                     "approximative reprise d'un exemple de style."
    )

    # Rempli uniquement si type_partie == "ressources"
    exercices: Optional[list[Exercice]] = Field(
        default=None,
        description="Obligatoire si type_partie='ressources' (3 à 4 exercices indépendants). "
                     "Laisser null si type_partie='competences'."
    )

    # Remplis uniquement si type_partie == "competences"
    situation_contexte: Optional[str] = Field(
        default=None,
        description=f"Obligatoire si type_partie='competences' : texte introduisant la situation-problème "
                     f"(contexte concret, personnage, données). {CONSIGNE_LATEX} Les 2-3 tâches qui suivent "
                     f"doivent réutiliser une variable ou un résultat commun issu de ce contexte -- éviter "
                     f"trois calculs complètement indépendants juste habillés du même personnage."
    )
    taches: Optional[list[Tache]] = Field(
        default=None,
        description="Obligatoire si type_partie='competences' (2 à 3 tâches). Laisser null si type_partie='ressources'."
    )


class EpreuveGeneree(BaseModel):
    sequence: int = Field(
        description="Numéro de séquence (1 à 6) si type_document='Sequence'. Sans objet pour un "
                     "Examen officiel (mettre 0 dans ce cas -- ce champ n'est pas utilisé dans le "
                     "rendu ni la validation d'un Examen)."
    )
    type_document: Literal["Sequence", "Examen"] = Field(
        default="Sequence",
        description="'Examen' UNIQUEMENT si cette épreuve est un vrai sujet de Baccalauréat "
                     "officiel MINESEC (session complète, 4 heures, barème 20 points réparti selon "
                     "la répartition obligatoire donnée dans le prompt). 'Sequence' pour toute "
                     "évaluation interne d'établissement (devoir de séquence normal). Ne choisis "
                     "jamais cette valeur toi-même : elle est imposée par le contexte de génération "
                     "donné dans le prompt, recopie-la telle quelle."
    )
    parties: list[Partie] = Field(
        description="Exactement 2 éléments : une partie type_partie='ressources' puis une partie "
                     "type_partie='competences', dans cet ordre."
    )
    presentation_points: float = Field(
        default=0.5,
        description="Points de présentation -- valeur EXACTE imposée par la répartition obligatoire "
                     "donnée dans le prompt (généralement 0.5point). Ce n'est PAS un choix libre : "
                     "le total (ressources + competences + presentation) doit faire exactement 20, "
                     "et ce champ est la variable d'ajustement calculée pour que ça tombe juste."
    )