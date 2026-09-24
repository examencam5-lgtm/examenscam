# scripts/chat_contexte.py
"""
NIVEAU 1 de calibration du chat élève (26/08/2026) -- retrieval par
mots-clés sur les thèmes existants dans rag.db, PAS un vrai retrieval
sémantique (ChromaDB + embeddings, réservé à la Phase 2 si elle est
lancée).

EXTENSION MULTI-MATIÈRES (29/08/2026) :
- La matière est maintenant transmise à toutes les fonctions concernées.
- Le RAG est filtré par matière.
- Le programme injecté dans le prompt correspond à la matière choisie.
- Le streaming accepte `matiere=...`.
- Le comportement par défaut reste Mathématiques pour compatibilité.

PERSONNALISATION PERSISTANTE :
Le profil de l'élève (prénom, niveau, série, classe) est injecté
à chaque tour de conversation.

RÉFÉRENCES AUX ÉPREUVES OFFICIELLES (30/08/2026) :
En plus du contexte de style (extraits, jamais cités) et du
référentiel APC de la leçon, le mode RAG injecte maintenant une liste
de vrais exercices de BAC officiel déjà tagués (tags_exercices_bac)
en lien avec les leçons précises détectées dans la question -- le
tuteur peut alors les RECOMMANDER par leur nom exact plutôt que de
rester silencieux sur leur existence. Seule la référence (session,
série, identifiant) est injectée, jamais le contenu intégral de
l'exercice.

BRANCHEMENT CRÉDITS (05/09/2026) :
generer_texte_avec_fallback() (mode bloc) retourne désormais 5
valeurs -- (texte, fournisseur, source, tokens_entree, tokens_sortie)
au lieu de 3 -- voir scripts/chat_llm_client.py.

CORRECTIF (17/09/2026) -- FUITE CROISÉE MATIÈRE SUR LA CHRONOLOGIE :
repondre_chronologie_datee() appelait auparavant
_obtenir_chapitre_a_date(MATIERE_DEFAUT, ...) -- MATIERE_DEFAUT =
"Mathematiques" en dur, quelle que soit la matière réellement active
dans la conversation. Un élève en train de discuter Physique qui
demandait "on fait quoi le 12 janvier" recevait silencieusement la
chronologie de Mathématiques. C'était la SEULE vraie fuite croisée
matière du système -- database_progressions.py filtre déjà
correctement par matiere en SQL partout ailleurs (voir
obtenir_progression_du_jour). Corrigé en ajoutant `matiere` à la
signature -- l'appelant (app.py, assistant_eleve_repondre) doit
transmettre la matière active, voir le correctif correspondant dans
app.py.

Ajout aussi de detecter_date_relative() pour "aujourd'hui", "demain",
"semaine prochaine", "dans N semaines" -- calcul par Python
(timedelta), jamais demandé à Gemini, même discipline que le reste
du fichier (voir CORRESPONDANCE_NIVEAU_PROGRESSION plus bas : aucune
arithmétique de calendrier n'est jamais confiée au modèle).

PRINCIPE PÉDAGOGIQUE DE FRICTION (23/09/2026) :
Ajout d'un bloc pédagogique injecté dans TOUT prompt système (RAG et
générique) qui empêche le tuteur de résoudre un exercice avant
tentative de l'élève -- aide dégressive par paliers plutôt que
réponse complète immédiate, déclinée par matière (voir
PRINCIPE_PEDAGOGIQUE_PAR_MATIERE). Un mode "Révision rapide" explicite
(mode_revision=True, à activer côté élève depuis l'interface -- pas
encore câblé dans app.py) bypasse cette friction sur demande assumée
de l'élève. Ce principe est une instruction de comportement pour
Gemini, pas une détection Python : décider si une réponse constitue
une "tentative recevable" est un jugement pédagogique, pas une
arithmétique déterministe -- ça reste donc dans le prompt, pas dans
une regex, cohérent avec la répartition établie ailleurs dans ce
fichier (Python pour les dates, Gemini pour le raisonnement
pédagogique).
"""

import re
import json
import sqlite3
import unicodedata
from pathlib import Path


# ═══════════════════════════════════════════════════════
# IMPORTS
# ═══════════════════════════════════════════════════════

if __package__:
    from .chat_bac_officiel import detecter_demande_correction
else:
    from chat_bac_officiel import detecter_demande_correction

if __package__:
    from .chat_llm_client import (
        construire_pool_clients,
        generer_texte_avec_fallback,
        generer_texte_stream_avec_fallback,
    )
else:
    from chat_llm_client import (
        construire_pool_clients,
        generer_texte_avec_fallback,
        generer_texte_stream_avec_fallback,
    )

try:
    if __package__:
        from . import chat_scope
    else:
        import chat_scope
except ImportError:
    chat_scope = None
try:
    from database_progressions import texte_pour_prompt_systeme as _progression_du_jour
except Exception:
    _progression_du_jour = None
 


# ═══════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════

DB_PATH = Path("data/rag_maths_bac_c/rag.db")

NB_EXEMPLES_CONTEXTE = 2
LIMITE_CARACTERES_EXEMPLE_CHAT = 1200

MATIERE_DEFAUT = "Mathematiques"

NB_REFERENCES_EPREUVES_OFFICIELLES = 3
LIMITE_CARACTERES_JUSTIFICATION = 180


# ═══════════════════════════════════════════════════════
# PROMPT DE BASE
# ═══════════════════════════════════════════════════════

PROMPT_SYSTEME_BASE = """Tu es un tuteur de mathématiques camerounais, patient et bienveillant, qui \
aide un élève de Terminale C (programme MINESEC) à comprendre une notion.

RÈGLES DE CONTEXTE OBLIGATOIRES :
- Utilise TOUJOURS des FCFA, jamais des euros ou des dollars, dans tout exemple chiffré \
  (prix, argent, budget).
- Ancre tes exemples concrets dans un contexte camerounais plausible quand c'est pertinent \
  (activités courantes, scénarios locaux) -- sans le forcer artificiellement si l'exemple \
  mathématique n'a pas besoin de contexte.
- Reste rigoureux mathématiquement : ne simplifie jamais au point de rendre une affirmation \
  fausse.
- Adapte ton niveau de langage à un élève de Terminale, sans être condescendant.
- Si des extraits de vrais sujets MINESEC te sont donnés ci-dessous, utilise-les UNIQUEMENT \
  comme repère de style et de niveau d'exigence réel -- ne les recopie JAMAIS mot pour mot \
  dans ta réponse, ils servent à calibrer ton propre exemple, pas à être cités.

RÈGLE ANTI-HALLUCINATION CRITIQUE SUR LES CHIFFRES ET DONNÉES FACTUELLES :
- Si l'élève demande une donnée précise et vérifiable (horaire hebdomadaire, coefficient, \
  barème, date d'évaluation, durée d'épreuve, nombre de chapitres) et que cette donnée \
  N'APPARAÎT PAS explicitement dans les blocs injectés ci-dessous (PROGRESSION NATIONALE, \
  PROGRAMME OFFICIEL), tu DOIS dire clairement que tu n'as pas cette information vérifiée \
  et orienter l'élève vers son professeur ou son emploi du temps -- NE JAMAIS improviser un \
  chiffre plausible, même s'il semble raisonnable.
- Ne confonds JAMAIS deux séries différentes (ex: l'horaire de Première C n'est pas celui \
  de Terminale C) -- vérifie toujours que la donnée citée correspond exactement au niveau \
  ET à la série de l'élève tels qu'indiqués dans son profil.
"""

# ═══════════════════════════════════════════════════════
# PRINCIPE PÉDAGOGIQUE DE FRICTION (23/09/2026)
# ═══════════════════════════════════════════════════════
#
# Objectif : le tuteur ne doit jamais donner en premier ce que l'élève
# peut produire lui-même avec un minimum d'effort guidé. Ce bloc est
# injecté dans TOUT prompt système, RAG ou générique, matière par
# matière -- voir obtenir_bloc_pedagogique() plus bas.

PRINCIPE_PEDAGOGIQUE_COMMUN = """
PRINCIPE PÉDAGOGIQUE DIRECTEUR (prioritaire sur ton réflexe naturel de répondre complètement \
et vite) :

Tu ne donnes JAMAIS en premier ce que l'élève peut produire lui-même avec un minimum d'effort \
guidé. Face à une demande d'exercice ou de résolution, évalue d'abord ce qu'il manque \
précisément à l'élève pour trouver seul -- et ne comble que ce manque, jamais plus. La \
solution complète est un droit gagné par une tentative, pas un service rendu sur simple \
demande.

MÉCANISME :
1. Si l'élève soumet un exercice SANS montrer de tentative (juste l'énoncé, une photo seule, \
   ou "donne-moi la réponse") : ne résous pas. Relance avec UNE question ciblée pour situer \
   où il bloque (quelle notion/formule s'applique selon lui, où précisément il coince). Une \
   tentative fausse ou incomplète en retour te donne un point d'appui réel -- passe alors à \
   l'aide dégressive.
2. Aide dégressive, jamais binaire -- un seul palier à la fois, jamais plusieurs d'un coup :
   (1) reformulation de la question sous un angle différent
   (2) rappel de la notion/formule mobilisable, sans dire comment l'appliquer
   (3) exemple analogue résolu, structurellement proche mais pas identique
   (4) correction guidée pas à pas où l'élève exécute chaque étape
   (5) solution complète -- seulement si l'élève la demande explicitement après avoir \
       traversé les paliers précédents
3. Rends le chemin visible : demande à l'élève d'expliquer sa démarche ("pourquoi cette \
   formule ?") avant ou après avoir résolu -- ne livre jamais un résultat seul.
4. Pour les questions de compréhension ouvertes ("c'est quoi X", "pourquoi ça marche"), \
   réponds brièvement à l'essentiel puis relance systématiquement par une question qui teste \
   la compréhension, plutôt que d'empiler des explications non sollicitées.
5. Calibre-toi sur le niveau réel observé dans les tentatives de l'élève, pas sur sa classe \
   déclarée -- un élève de Terminale qui bloque sur une notion de Seconde a besoin qu'on le \
   fasse redescendre, pas qu'on maintienne artificiellement le niveau affiché.

CE QUI NE CHANGE PAS :
- Pour les tâches purement mécaniques sans enjeu d'apprentissage (formatage, récupération \
  d'un énoncé archivé, correction orthographique, question factuelle du type programme ou \
  dates), réponds directement -- la friction ne s'applique qu'aux moments où un raisonnement \
  est en jeu.
- Reste bienveillant et non punitif : la relance est une invitation ("essaie d'abord, je suis \
  là pour t'aider à avancer"), jamais un refus froid ou une sanction.
- Explique toujours en une phrase pourquoi tu ne réponds pas directement, pour que la friction \
  soit comprise comme pédagogique, jamais comme un bug ou un refus arbitraire.
"""

PRINCIPE_PEDAGOGIQUE_PAR_MATIERE = {
    "Mathematiques": """
SPÉCIFICITÉ MATHÉMATIQUES :
- Tentative recevable : poser l'équation ou identifier la formule à mobiliser, même sans \
  savoir résoudre jusqu'au bout.
- Paliers : (1) notion du cours concernée, (2) formule rappelée sans l'appliquer, (3) exercice \
  analogue avec des nombres différents, (4) calcul guidé étape par étape où l'élève exécute \
  chaque opération, (5) solution complète.
- Fais TOUJOURS vérifier le résultat par l'élève lui-même (ordre de grandeur, unité, cas \
  limite) plutôt que de valider à sa place -- la validation externe immédiate est justement \
  ce qui empêche l'élève de développer son propre sens critique du résultat.
""",
    "Physique": """
SPÉCIFICITÉ PHYSIQUE :
- Tentative recevable : décrire le phénomène en jeu avec ses propres mots, avant toute \
  formule.
- Paliers : (1) faire nommer le phénomène observé, (2) faire lister les grandeurs connues et \
  cherchées avec leurs unités, (3) rappeler la loi/formule applicable, (4) exemple analogue \
  résolu, (5) résolution guidée, (6) solution complète.
- Insiste sur l'étape de schématisation (faire décrire ou dessiner la situation) avant tout \
  calcul -- c'est le point où la récitation pure échoue le plus vite en physique, et où on a \
  tendance à sauter directement à la formule.
""",
    "Chimie": """
SPÉCIFICITÉ CHIMIE :
- Tentative recevable : identifier les réactifs/produits et le type de réaction avant tout \
  calcul.
- Paliers similaires à la physique, avec un palier spécifique sur la vérification de la \
  conservation (atomes, charges) plutôt que la seule vérification numérique.
- Demande fréquemment "pourquoi cette réaction se produit-elle" avant "combien", pour éviter \
  que la chimie soit vécue comme un exercice de manipulation de symboles sans réalité \
  physique.
""",
    "Francais": """
SPÉCIFICITÉ FRANÇAIS / LITTÉRATURE :
- Tentative recevable : une impression de lecture personnelle, même vague ("ce texte me \
  semble triste/ironique"), plutôt qu'un plan tout fait.
- Paliers : (1) faire relire un passage précis et demander ce que l'élève y remarque, (2) \
  faire formuler une hypothèse de lecture personnelle avant de proposer un axe d'analyse, (3) \
  proposer une piste d'analyse à confronter à l'hypothèse de l'élève (accord ou désaccord \
  argumenté), (4) aide à la structuration du plan une fois le fond dégagé, (5) relecture \
  critique d'un brouillon rédigé par l'élève -- jamais de rédaction à sa place.
- Ne rédige JAMAIS de paragraphe d'analyse ou de dissertation à la place de l'élève, y compris \
  au dernier palier -- il n'existe pas de solution complète unique récupérable en littérature ; \
  fournis uniquement une critique et des pistes sur ce que l'élève a lui-même écrit.
""",
    "Philosophie": """
SPÉCIFICITÉ PHILOSOPHIE :
- Tentative recevable : une reformulation du problème posé par le sujet, même naïve, avant \
  toute référence à un auteur.
- Paliers : (1) faire reformuler la question du sujet avec ses propres mots, (2) faire \
  chercher pourquoi cette question se pose, (3) proposer un auteur/une thèse pertinente en \
  demandant à l'élève de reconstruire lui-même l'enchaînement logique qui y mène, (4) proposer \
  une objection ou une thèse adverse à confronter, (5) aide à la structuration de la \
  dissertation.
- Demande systématiquement "et toi, qu'en penses-tu, et pourquoi" AVANT de livrer la position \
  d'un philosophe -- jamais l'inverse. Aucune citation ne doit être fournie sans son contexte \
  problématique.
""",
    "Anglais": """
SPÉCIFICITÉ LANGUES VIVANTES :
- Tentative recevable : une traduction ou une phrase même fautive, produite par l'élève.
- Paliers : (1) signaler qu'il y a une erreur sans dire laquelle ni où précisément, (2) \
  localiser le type d'erreur (conjugaison, accord, vocabulaire), (3) rappeler la règle \
  concernée sans corriger, (4) proposer un exemple correct sur une phrase différente utilisant \
  la même règle, (5) correction complète avec explication.
- Pour le vocabulaire et l'oral, privilégie la mise en situation (faire réemployer le mot dans \
  une phrase nouvelle) plutôt que la simple définition -- la restitution passive d'une \
  traduction est ici le piège le plus proche de la récitation pure.
""",
}

# Allemand et Espagnol suivent le même schéma que l'anglais (langue
# vivante) -- pas de duplication du texte, simple alias de lookup, voir
# obtenir_bloc_pedagogique().
MATIERES_LANGUES_ALIAS_ANGLAIS = {"Allemand", "Espagnol"}

MODE_REVISION_INSTRUCTION = """
MODE RÉVISION RAPIDE ACTIVÉ PAR L'ÉLÈVE :
L'élève a explicitement activé la vérification rapide d'un résultat, en dehors de tout \
entraînement guidé. Donne directement la solution complète et le calcul, sans passer par les \
paliers d'aide dégressive ni exiger de tentative préalable. Rappelle une seule fois, en une \
phrase, que ce mode ne remplace pas l'entraînement et qu'il peut repasser en mode normal pour \
les exercices qu'il n'a pas encore travaillés.
"""


def obtenir_bloc_pedagogique(
    matiere: str,
    mode_revision: bool = False,
) -> str:
    """
    Retourne le bloc pédagogique à injecter dans le prompt système :
    soit l'instruction de friction (mécanisme commun + déclinaison par
    matière), soit l'instruction de mode révision si l'élève l'a activé
    explicitement pour ce tour de conversation.
    """
    if mode_revision:
        return MODE_REVISION_INSTRUCTION

    specifique = PRINCIPE_PEDAGOGIQUE_PAR_MATIERE.get(matiere)

    if specifique is None and matiere in MATIERES_LANGUES_ALIAS_ANGLAIS:
        specifique = PRINCIPE_PEDAGOGIQUE_PAR_MATIERE.get("Anglais")

    return PRINCIPE_PEDAGOGIQUE_COMMUN + (specifique or "")


# ═══════════════════════════════════════════════════════
# NORMALISATION
# ═══════════════════════════════════════════════════════

def _normaliser(texte: str) -> str:
    """
    Minuscules + suppression des accents, pour un matching robuste
    aux variations d'écriture.
    """
    texte = texte.lower()
    texte = unicodedata.normalize("NFKD", texte)
    return "".join(
        c for c in texte
        if not unicodedata.combining(c)
    )


# ═══════════════════════════════════════════════════════
# DÉTECTION DES THÈMES
# ═══════════════════════════════════════════════════════

def detecter_themes_mentionnes(
    question: str,
    conn: sqlite3.Connection,
    matiere: str = MATIERE_DEFAUT,
) -> list[str]:
    """
    Retourne les noms de thèmes correspondant à la matière demandée.
    """
    question_normalisee = _normaliser(question)

    try:
        cur = conn.execute(
            """
            SELECT nom_theme
            FROM themes
            WHERE matiere=?
            ORDER BY numero_chapitre
            """,
            (matiere,),
        )
    except sqlite3.OperationalError:
        cur = conn.execute(
            "SELECT nom_theme FROM themes"
        )

    themes_trouves = []

    for (nom_theme,) in cur.fetchall():
        if _normaliser(nom_theme) in question_normalisee:
            themes_trouves.append(nom_theme)

    return themes_trouves


# ═══════════════════════════════════════════════════════
# DÉTECTION DES LEÇONS
# ═══════════════════════════════════════════════════════

def detecter_lecons_mentionnees(
    question: str,
    conn: sqlite3.Connection,
    matiere: str = MATIERE_DEFAUT,
) -> list[dict]:
    """
    Détecte directement les leçons correspondant à la matière choisie.
    """
    question_normalisee = _normaliser(question)

    try:
        cur = conn.execute(
            """
            SELECT
                identifiant,
                titre,
                chapitre_numero,
                lecon_numero
            FROM lecons
            WHERE matiere=?
            ORDER BY chapitre_numero, lecon_numero
            """,
            (matiere,),
        )
    except sqlite3.OperationalError:
        return []

    lecons_trouvees = []

    for (
        identifiant,
        titre,
        chapitre_numero,
        lecon_numero,
    ) in cur.fetchall():

        if _normaliser(titre) in question_normalisee:
            lecons_trouvees.append(
                {
                    "identifiant": identifiant,
                    "titre": titre,
                    "chapitre_numero": chapitre_numero,
                    "lecon_numero": lecon_numero,
                }
            )

    return lecons_trouvees


# ═══════════════════════════════════════════════════════
# CONTEXTE APC D'UNE LEÇON
# ═══════════════════════════════════════════════════════

def construire_contexte_lecon(
    conn: sqlite3.Connection,
    lecons_detectees: list[dict],
) -> str:
    """
    Récupère les informations APC disponibles pour les leçons détectées.
    """
    if not lecons_detectees:
        return ""

    blocs = []

    for lecon in lecons_detectees:
        try:
            row = conn.execute(
                """
                SELECT donnees_json
                FROM unites_pedagogiques
                WHERE lecon_identifiant=?
                """,
                (lecon["identifiant"],),
            ).fetchone()

        except sqlite3.OperationalError:
            return ""

        if not row:
            continue

        try:
            unite = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            continue

        lignes = [
            f"Leçon précise identifiée : "
            f"\"{lecon['titre']}\" ({lecon['identifiant']})"
        ]

        objectifs = unite.get("objectif_pedagogique") or []

        if objectifs:
            lignes.append(
                "Objectifs pédagogiques officiels : "
                + "; ".join(objectifs)
            )

        situation = unite.get("situation_de_vie") or {}

        if situation.get("contexte"):
            lignes.append(
                "Situation de vie de référence "
                f"(programme APC) : {situation['contexte']}"
            )

        exercices = unite.get("exercices_d_application") or []

        if exercices:
            lignes.append(
                f"{len(exercices)} exercice(s) d'application "
                "officiel(s) référencé(s) pour cette leçon."
            )

        if len(lignes) > 1:
            blocs.append("\n".join(lignes))

    if not blocs:
        return ""

    return (
        "\nRÉFÉRENTIEL APC OFFICIEL "
        "(issu du programme calibré par un enseignant, "
        "PAS une connaissance générique -- utilise-le comme base réelle, "
        "pas comme simple inspiration) :\n"
        + "\n\n".join(blocs)
        + "\n"
    )


# ═══════════════════════════════════════════════════════
# RÉFÉRENCES AUX ÉPREUVES OFFICIELLES (BAC RÉEL TAGUÉ)
# ═══════════════════════════════════════════════════════

def construire_references_epreuves_officielles(
    conn: sqlite3.Connection,
    lecons_detectees: list[dict],
) -> str:
    """
    Cherche, pour les leçons précises détectées, de vrais exercices de
    BAC officiel déjà tagués.
    """
    if not lecons_detectees:
        return ""

    identifiants = [l["identifiant"] for l in lecons_detectees]
    placeholders = ",".join("?" for _ in identifiants)

    try:
        cur = conn.execute(
            f"""
            SELECT e.session, e.series, s.identifiant, s.titre, s.bareme_annonce,
                   l.titre AS lecon_titre, t.justification, e.qualite
            FROM tags_exercices_bac t
            JOIN lecons l ON l.identifiant = t.lecon_identifiant
            JOIN sections_bac_officielles s ON s.id = t.section_id
            JOIN epreuves_bac_officielles e ON e.id = s.epreuve_id
            WHERE t.lecon_identifiant IN ({placeholders})
            ORDER BY (e.qualite = 'verifie_vision') DESC, e.session DESC
            LIMIT ?
            """,
            identifiants + [NB_REFERENCES_EPREUVES_OFFICIELLES],
        )
        lignes_brutes = cur.fetchall()
    except sqlite3.OperationalError:
        return ""

    if not lignes_brutes:
        return ""

    lignes = []
    for session, series, identifiant, titre, bareme, lecon_titre, justification, qualite in lignes_brutes:
        marque_qualite = "" if qualite == "verifie_vision" else " (relecture du texte source pas encore finalisée)"
        nom_exercice = identifiant or titre or "Exercice"
        justification_courte = (justification or "")[:LIMITE_CARACTERES_JUSTIFICATION]
        lignes.append(
            f"- BAC {series or '?'} {session}, {nom_exercice} ({bareme or '?'}){marque_qualite} "
            f"-- en lien avec « {lecon_titre} » : {justification_courte}"
        )
    bloc = "\n".join(lignes)

    return f"""
EXERCICES OFFICIELS RÉELS DISPONIBLES SUR CE THÈME (base ExamensCam, épreuves MINESEC) :
{bloc}

Tu PEUX recommander spontanément un de ces exercices à l'élève pour s'entraîner (ex: "tiens, \
sur ce thème, entraîne-toi sur l'Exercice 3 du BAC C/E 2024"), en citant sa provenance exacte \
(série et année). Si l'élève veut le voir en entier ou être corrigé dessus, dis-lui qu'il peut \
te le demander directement -- ne récite PAS ici le contenu intégral de l'exercice, seule la \
référence sert à orienter l'élève."""


# ═══════════════════════════════════════════════════════
# QUESTIONS MÉTA SUR LE PROGRAMME
# ═══════════════════════════════════════════════════════

MOTS_DECLENCHEURS_PROGRAMME = [
    "programme",
    "chapitres",
    "sommaire",
    "au programme",
]


def detecter_question_programme(question: str) -> bool:
    q_norm = _normaliser(question)

    return any(
        mot in q_norm
        for mot in MOTS_DECLENCHEURS_PROGRAMME
    )


# ═══════════════════════════════════════════════════════
# CONSIGNE DE FIDÉLITÉ
# ═══════════════════════════════════════════════════════

INSTRUCTION_CORRECTION_FIDELE = """
L'ÉLÈVE DEMANDE UNE CORRECTION/RÉSOLUTION D'UN EXERCICE DÉJÀ ÉVOQUÉ DANS CETTE CONVERSATION :

- Si un énoncé réel d'exercice (marqué "Énoncé réel officiel MINESEC" plus haut dans cet \
échange) apparaît dans l'historique, tu DOIS résoudre EXACTEMENT cet énoncé -- mêmes valeurs, \
mêmes nombres, mêmes fonctions, rien d'inventé ni de changé.

- Ne résous JAMAIS un exercice générique "similaire" à la place de celui montré.

- Si tu ne trouves AUCUN énoncé précis plus haut dans cette conversation, dis-le clairement \
et demande à l'élève de préciser l'année/le numéro ou de recoller l'énoncé.

RÈGLE CRITIQUE SUR UNE DONNÉE AMBIGUË :

- N'ESSAIE JAMAIS de "faire comme si" tu connaissais la valeur en poursuivant le calcul de \
façon vague ou narrative ("on résout le système et on retombe sur...", "on vérifie que...", \
sans montrer le calcul réel) -- c'est PIRE que de t'arrêter.

- Dès que tu rencontres une valeur ambiguë qui empêche un calcul EXACT et vérifiable, ARRÊTE-TOI \
à cette étape précise. Explique clairement quelle valeur est ambiguë et pourquoi.

- Si l'énoncé montré plus haut dans la conversation contient le symbole ⚠️ (avertissement de \
qualité OCR dégradée), c'est un signal FORT : plusieurs valeurs de cet énoncé sont probablement \
illisibles. Dans ce cas, NE TENTE AUCUN calcul chiffré -- demande à l'élève de recopier les \
coefficients/expressions exacts depuis son support.

- Une explication de MÉTHODE générale reste possible et utile, mais jamais un résultat chiffré \
présenté comme certain.

- Une fois la valeur confirmée par l'élève (ou si aucune ambiguïté n'existe), résous CHAQUE \
étape avec le calcul réel affiché (substitutions numériques, développements, résolutions de \
système explicites) -- jamais une conclusion donnée sans le calcul qui y mène.
"""


# ═══════════════════════════════════════════════════════
# PROGRAMME DÉTERMINISTE
# ═══════════════════════════════════════════════════════

def repondre_programme(
    matiere: str = MATIERE_DEFAUT,
) -> str:
    """
    Construit la liste complète chapitre -> leçons directement
    depuis la base.
    """
    if not DB_PATH.exists():
        raise RuntimeError(
            f"Base introuvable : {DB_PATH}"
        )

    conn = sqlite3.connect(DB_PATH)

    themes = conn.execute(
        """
        SELECT numero_chapitre, nom_theme
        FROM themes
        WHERE matiere=?
        ORDER BY numero_chapitre
        """,
        (matiere,),
    ).fetchall()

    lignes = [
        f"Voici le programme officiel de {matiere} Terminale C "
        f"(MINESEC, {len(themes)} chapitres) :\n"
    ]

    for numero, nom in themes:

        lignes.append(
            f"**{numero}. {nom}**"
        )

        try:
            lecons = conn.execute(
                """
                SELECT lecon_numero, titre
                FROM lecons
                WHERE matiere=?
                  AND chapitre_numero=?
                ORDER BY lecon_numero
                """,
                (matiere, numero),
            ).fetchall()

        except sqlite3.OperationalError:
            lecons = []

        for lecon_numero, titre_lecon in lecons:
            lignes.append(
                f"   {numero}.{lecon_numero} — {titre_lecon}"
            )

    conn.close()

    return "\n".join(lignes)


# ═══════════════════════════════════════════════════════
# CONTEXTE CAMEROUNAIS / EXTRAITS MINESEC
# ═══════════════════════════════════════════════════════

def construire_contexte_camerounais(
    conn: sqlite3.Connection,
    themes_detectes: list[str],
) -> str:
    """
    Récupère des extraits réels du corpus MINESEC correspondant aux
    thèmes détectés.
    """
    if not themes_detectes:
        return ""

    placeholders = ",".join(
        "?" for _ in themes_detectes
    )

    cur = conn.execute(
        f"""
        SELECT
            t.nom_theme,
            COUNT(DISTINCT e.id) as freq
        FROM epreuves e
        JOIN parties p
            ON p.epreuve_id = e.id
        JOIN exercices ex
            ON ex.partie_id = p.id
        JOIN exercice_themes et
            ON et.exercice_id = ex.id
        JOIN themes t
            ON t.id = et.theme_id
        WHERE t.nom_theme IN ({placeholders})
        GROUP BY t.nom_theme
        """,
        themes_detectes,
    )

    frequences = cur.fetchall()

    cur = conn.execute(
        f"""
        SELECT DISTINCT e.texte_extrait
        FROM epreuves e
        JOIN parties p
            ON p.epreuve_id = e.id
        JOIN exercices ex
            ON ex.partie_id = p.id
        JOIN exercice_themes et
            ON et.exercice_id = ex.id
        JOIN themes t
            ON t.id = et.theme_id
        WHERE t.nom_theme IN ({placeholders})
          AND e.matiere_suspecte = 0
          AND e.statut_extraction = 'ok'
          AND LENGTH(e.texte_extrait) > 300
        ORDER BY RANDOM()
        LIMIT ?
        """,
        themes_detectes + [NB_EXEMPLES_CONTEXTE],
    )

    extraits = [
        row[0][:LIMITE_CARACTERES_EXEMPLE_CHAT]
        for row in cur.fetchall()
    ]

    if not extraits:

        if frequences:
            freq_texte = ", ".join(
                f"{nom} (observé {n} fois dans le corpus)"
                for nom, n in frequences
            )

            return (
                "\nTHÈME(S) DÉTECTÉ(S) DANS LA QUESTION : "
                f"{freq_texte}\n"
                "(aucun extrait de style disponible pour ce thème actuellement)\n"
            )

        return ""

    freq_texte = ", ".join(
        f"{nom} (observé {n} fois dans le corpus)"
        for nom, n in frequences
    )

    extraits_texte = "\n\n".join(
        (
            f"--- EXTRAIT RÉEL {i + 1} "
            f"(MINESEC, thème : {', '.join(themes_detectes)}) ---\n"
            f"{ex}"
        )
        for i, ex in enumerate(extraits)
    )

    return f"""
THÈME(S) DÉTECTÉ(S) DANS LA QUESTION : {freq_texte}

EXTRAITS RÉELS DU CORPUS (repère de style et de contexte UNIQUEMENT -- ne pas recopier) :
{extraits_texte}
"""


# ═══════════════════════════════════════════════════════
# CONTEXTE ÉLÈVE
# ═══════════════════════════════════════════════════════

def construire_contexte_eleve(
    eleve: dict | None,
    historique: list[dict] | None,
) -> str:

    if not eleve:
        return ""

    prenom = (
        (eleve.get("nom") or "")
        .strip()
        .split(" ")[0]
        or None
    )

    niveau = eleve.get("niveau") or None
    serie = eleve.get("serie") or None
    classe = eleve.get("classe") or None

    premier_message = not historique

    lignes_profil = []

    if prenom:
        lignes_profil.append(
            f"  - Prénom : {prenom}"
        )

    if niveau:
        lignes_profil.append(
            f"  - Niveau/série : {niveau}"
            f"{(' ' + serie) if serie else ''}"
        )

    if classe:
        lignes_profil.append(
            f"  - Classe déclarée par l'élève : {classe}"
        )

    if not lignes_profil:
        return ""

    bloc = (
        "\nPROFIL DE L'ÉLÈVE "
        "(fiable, déjà connu -- NE JAMAIS le redemander) :\n"
    )

    bloc += "\n".join(lignes_profil)

    bloc += (
        "\nCes informations viennent du compte de l'élève, pas de la "
        "conversation -- ne demande JAMAIS \"en quelle classe es-tu ?\" "
        "ou \"quelle est ta série ?\", tu les connais déjà ci-dessus. "
        "Utilise-les pour adapter ton discours (registre, exemples), "
        "sans les répéter mécaniquement à chaque réponse."
    )

    if prenom:

        if premier_message:
            bloc += (
                f"\nC'est le DÉBUT de la conversation -- commence ta "
                f"réponse en saluant {prenom} par son prénom "
                f"(ex: \"Salut {prenom} !\"), une seule fois."
            )

        else:
            bloc += (
                f"\nLa conversation est déjà en cours -- NE RESALUE PAS "
                f"{prenom} par son prénom, réponds directement à sa "
                "question comme le ferait un tuteur en plein échange."
            )

    return bloc

# ═══════════════════════════════════════════════════════
# CORRESPONDANCE NIVEAU COMPTE ÉLÈVE -> NIVEAU PROGRESSION MINESEC
# ═══════════════════════════════════════════════════════

CORRESPONDANCE_NIVEAU_PROGRESSION = {
    "bepc": "3e",
    "probatoire": "premiere",
    "bac": "terminale",
}

NIVEAU_VERS_PROGRESSION = {
    "bepc": "3e",
    "probatoire": "premiere",
    "bac": "terminale",
    "3e": "3e",
    "premiere": "premiere",
    "terminale": "terminale",
}

# Cle en MAJUSCULES car serie_brute est deja .upper() avant consultation.
SERIE_VERS_PROGRESSION = {
    "A4": "A4",
    "C": "C",
    "D": "D",
    "TI": "TI",
}

# Matieres pour lesquelles une fiche de progression a ete importee dans
# database_progressions -- a completer au fur et a mesure (Chimie, SVT,
# etc.). Une matiere absente d'ici n'appelle jamais Postgres pour rien.
MATIERES_AVEC_PROGRESSION = {"Mathematiques", "Physique"}


def construire_bloc_progression_nationale(
    niveau: str,
    serie: str,
    matiere: str = MATIERE_DEFAUT,
) -> str:
    """
    Injecte le chapitre officiel MINESEC en cours a la date du jour,
    pour le niveau/serie/matiere exact de l'eleve.

    Degradation gracieuse totale : si le niveau, la serie ou la matiere
    ne sont pas reconnus/couverts, si database_progressions n'a pas pu
    etre importe, ou si la requete Postgres echoue pour une raison
    quelconque, cette fonction retourne une chaine vide -- elle ne doit
    JAMAIS faire planter une reponse eleve.
    """
    if _progression_du_jour is None:
        return ""

    if matiere not in MATIERES_AVEC_PROGRESSION:
        return ""

    niveau_brut = (niveau or "").strip().lower()
    niveau_norm = NIVEAU_VERS_PROGRESSION.get(niveau_brut)

    if niveau_norm is None:
        return ""

    serie_brute = (serie or "").strip().upper()
    if not serie_brute:
        serie_norm = None
    else:
        serie_norm = SERIE_VERS_PROGRESSION.get(serie_brute)
        if serie_norm is None and niveau_norm != "3e":
            return ""

    try:
        bloc = _progression_du_jour(matiere, niveau_norm, serie_norm)
    except Exception as e:
        print(f"construire_bloc_progression_nationale error: {e}")
        return ""

    return "\n" + bloc + "\n"


# ═══════════════════════════════════════════════════════
# SOMMAIRE DU PROGRAMME
# ═══════════════════════════════════════════════════════

def construire_sommaire_programme(
    matiere: str = MATIERE_DEFAUT,
) -> str:
    """
    Injecte en permanence le programme exact correspondant à la matière.
    """
    if not DB_PATH.exists():
        return ""

    conn = sqlite3.connect(DB_PATH)

    try:
        themes = conn.execute(
            """
            SELECT numero_chapitre, nom_theme
            FROM themes
            WHERE matiere=?
            ORDER BY numero_chapitre
            """,
            (matiere,),
        ).fetchall()

    except sqlite3.OperationalError:
        conn.close()
        return ""

    if not themes:
        conn.close()
        return ""

    lignes = []

    for numero, nom in themes:

        try:
            lecons = conn.execute(
                """
                SELECT titre
                FROM lecons
                WHERE matiere=?
                  AND chapitre_numero=?
                ORDER BY lecon_numero
                """,
                (matiere, numero),
            ).fetchall()

        except sqlite3.OperationalError:
            lecons = []

        if lecons:

            titres_lecons = "; ".join(
                titre
                for (titre,) in lecons
            )

            lignes.append(
                f"{numero}. {nom} — {titres_lecons}"
            )

        else:
            lignes.append(
                f"{numero}. {nom}"
            )

    conn.close()

    return (
        "\nPROGRAMME OFFICIEL COMPLET DE "
        + matiere.upper()
        + " TERMINALE C (MINESEC, APC) "
        "-- RÉFÉRENCE ABSOLUE ET EXACTE, ne jamais inventer un autre "
        "découpage, un autre chapitre ou une autre leçon que ceux "
        "listés ici. Utilise cette structure pour organiser tout "
        "cours, tout plan de révision, ou pour identifier à quel "
        "chapitre/leçon se rattache une question même formulée "
        "différemment du titre exact :\n"
        + "\n".join(lignes)
        + "\n"
    )


# ═══════════════════════════════════════════════════════
# PROMPT GÉNÉRIQUE
# ═══════════════════════════════════════════════════════

def construire_prompt_systeme_generique(
    matiere: str = MATIERE_DEFAUT,
) -> str:
    """
    Prompt utilisé lorsqu'aucun RAG spécifique n'est disponible
    pour la matière.
    """
    return f"""
Tu es un tuteur scolaire spécialisé en {matiere}, adapté au contexte
éducatif camerounais.

Tu aides un élève avec patience, rigueur et pédagogie.

RÈGLES :
- Explique progressivement.
- Adapte tes explications au niveau de l'élève.
- Ne prétends jamais avoir consulté une source que tu n'as pas consultée.
- Pour les exemples financiers, utilise les FCFA et non les euros ou dollars.
- Utilise le contexte camerounais lorsque cela est pertinent.
- Pour une correction, montre les calculs et ne saute pas les étapes importantes.
- Si une donnée de l'énoncé est ambiguë, demande confirmation plutôt que d'inventer.

RÈGLE ANTI-HALLUCINATION CRITIQUE SUR LES CHIFFRES ET DONNÉES FACTUELLES :
- Si l'élève demande une donnée précise et vérifiable (horaire hebdomadaire, coefficient,
  barème, date d'évaluation, durée d'épreuve, nombre de chapitres) et que cette donnée
  N'APPARAÎT PAS explicitement dans les blocs injectés dans ce prompt système (PROGRESSION
  NATIONALE, PROGRAMME OFFICIEL), tu DOIS dire clairement que tu n'as pas cette information
  vérifiée et orienter l'élève vers son professeur ou son emploi du temps -- NE JAMAIS
  improviser un chiffre plausible, même s'il semble raisonnable.
- Ne confonds JAMAIS deux séries différentes (ex: l'horaire de Première C n'est pas celui
  de Terminale C) -- vérifie toujours que la donnée citée correspond exactement au niveau
  ET à la série de l'élève tels qu'indiqués dans son profil.

MATIÈRE ACTUELLE : {matiere}
"""

def construire_contexte_systeme_image(
    matiere: str,
    eleve: dict | None,
    mode_revision: bool = False,
) -> str:
    """
    Prompt système pour le tuteur en mode image (photo d'exercice) --
    réutilise le même principe pédagogique de friction et le même
    contexte élève que le chat texte (chantier du 23/09/2026 : la photo
    contournait tout le principe de friction jusqu'ici, avec son propre
    contexte_systeme codé en dur dans app.py qui disait explicitement
    "sans juste donner le résultat final" -- exactement l'inverse de ce
    qu'on veut).

    Volontairement plus simple que _construire_prompt_systeme() : pas de
    détection de thèmes/leçons ni de références aux épreuves officielles
    taguées, ces mécanismes reposant sur un texte de question exploitable
    en base -- une photo d'exercice non transcrite n'a pas d'équivalent
    utile ici. Le prompt matière générique suffit.
    """
    matiere = (matiere or MATIERE_DEFAUT).strip() or MATIERE_DEFAUT

    prompt_matiere = construire_prompt_systeme_generique(matiere)
    bloc_pedagogique = obtenir_bloc_pedagogique(matiere, mode_revision)
    contexte_eleve = construire_contexte_eleve(eleve, historique=None)

    niveau = (eleve or {}).get("niveau") or "BAC"
    serie = (eleve or {}).get("serie") or "C"
    bloc_progression = construire_bloc_progression_nationale(
        niveau, serie, matiere,
    )

    return (
        prompt_matiere
        + "\n"
        + bloc_pedagogique
        + contexte_eleve
        + bloc_progression
        + "\nL'ÉLÈVE A JOINT UNE PHOTO D'EXERCICE À CE MESSAGE -- applique "
        "exactement le même principe pédagogique de friction qu'à une "
        "question texte : n'écris pas la résolution complète avant "
        "d'avoir vu une tentative, sauf si le mode révision ci-dessus "
        "est actif."
    )


def _construire_prompt_systeme(
    question: str,
    matiere: str,
    eleve: dict | None,
    historique: list[dict] | None,
    mode_revision: bool = False,
) -> str:
    """
    Construction commune utilisée par la réponse normale et le streaming.
    """
 
    niveau = (eleve or {}).get("niveau") or "BAC"
    serie = (eleve or {}).get("serie") or "C"
 
    mode = None
 
    if chat_scope is not None:
        try:
            mode = chat_scope.mode_pour(
                niveau,
                serie,
                matiere,
            )
        except Exception:
            mode = None
 
    mode_rag = (
        chat_scope is not None
        and hasattr(chat_scope, "MODE_RAG")
        and mode == chat_scope.MODE_RAG
    )
 
    if mode_rag:
 
        if not DB_PATH.exists():
            raise RuntimeError(
                f"Base introuvable : {DB_PATH}"
            )
 
        conn = sqlite3.connect(DB_PATH)
 
        themes_detectes = detecter_themes_mentionnes(
            question,
            conn,
            matiere,
        )
 
        contexte_camerounais = (
            construire_contexte_camerounais(
                conn,
                themes_detectes,
            )
        )
 
        lecons_detectees = detecter_lecons_mentionnees(
            question,
            conn,
            matiere,
        )
 
        contexte_lecon = construire_contexte_lecon(
            conn,
            lecons_detectees,
        )
 
        references_officielles = construire_references_epreuves_officielles(
            conn,
            lecons_detectees,
        )
 
        conn.close()
 
        sommaire_programme = (
            construire_sommaire_programme(
                matiere
            )
        )
 
        prompt_matiere = (
            PROMPT_SYSTEME_BASE
            + sommaire_programme
            + contexte_camerounais
            + contexte_lecon
            + references_officielles
        )
 
    else:
 
        prompt_matiere = (
            construire_prompt_systeme_generique(
                matiere
            )
        )

    # Bloc pédagogique de friction (ou mode révision) -- injecté après
    # le prompt matière, avant le contexte élève, pour les deux
    # chemins (RAG et générique) sans dupliquer la logique.
    bloc_pedagogique = obtenir_bloc_pedagogique(
        matiere,
        mode_revision,
    )

    prompt_matiere = prompt_matiere + "\n" + bloc_pedagogique

    contexte_eleve = construire_contexte_eleve(
        eleve,
        historique,
    )
 
    bloc_progression = construire_bloc_progression_nationale(
        niveau,
        serie,
        matiere,
    )
 
    instruction_correction = (
        INSTRUCTION_CORRECTION_FIDELE
        if detecter_demande_correction(question)
        else ""
    )
 
    return (
        prompt_matiere
        + contexte_eleve
        + bloc_progression
        + instruction_correction
    )
 

# ═══════════════════════════════════════════════════════
# RÉPONSE NON STREAMÉE
# ═══════════════════════════════════════════════════════

def repondre_eleve(
    question: str,
    historique: list[dict] | None = None,
    eleve: dict | None = None,
    matiere: str = MATIERE_DEFAUT,
    mode_revision: bool = False,
) -> tuple[str, str, str, int, int]:
    """
    Point d'entrée classique du chat élève.
    """

    if not DB_PATH.exists():
        raise RuntimeError(
            f"Base introuvable : {DB_PATH}"
        )

    matiere = (
        (matiere or MATIERE_DEFAUT)
        .strip()
        or MATIERE_DEFAUT
    )

    prompt_systeme = _construire_prompt_systeme(
        question,
        matiere,
        eleve,
        historique,
        mode_revision,
    )

    messages = [
        {
            "role": "system",
            "content": prompt_systeme,
        }
    ]

    messages.extend(
        historique or []
    )

    messages.append(
        {
            "role": "user",
            "content": question,
        }
    )

    pool = construire_pool_clients()

    texte, fournisseur, source, tokens_entree, tokens_sortie = (
        generer_texte_avec_fallback(
            pool,
            messages,
        )
    )

    return texte, fournisseur, source, tokens_entree, tokens_sortie


# ═══════════════════════════════════════════════════════
# RÉPONSE STREAMÉE
# ═══════════════════════════════════════════════════════

def repondre_eleve_stream(
    question: str,
    historique: list[dict] | None = None,
    eleve: dict | None = None,
    matiere: str = MATIERE_DEFAUT,
    stats: dict | None = None,
    mode_revision: bool = False,
):
    """
    Version streaming SSE du chat élève.
    """

    if not DB_PATH.exists():
        raise RuntimeError(
            f"Base introuvable : {DB_PATH}"
        )

    matiere = (
        (matiere or MATIERE_DEFAUT)
        .strip()
        or MATIERE_DEFAUT
    )

    prompt_systeme = _construire_prompt_systeme(
        question,
        matiere,
        eleve,
        historique,
        mode_revision,
    )

    messages = [
        {
            "role": "system",
            "content": prompt_systeme,
        }
    ]

    messages.extend(
        historique or []
    )

    messages.append(
        {
            "role": "user",
            "content": question,
        }
    )

    pool = construire_pool_clients()

    yield from generer_texte_stream_avec_fallback(
        pool,
        messages,
        stats=stats,
    )


# ═══════════════════════════════════════════════════════
# DEMANDE DE CHRONOLOGIE / DATE PRÉCISE — réponse déterministe,
# jamais laissée à l'improvisation du modèle.
# ═══════════════════════════════════════════════════════

import re as _re
from datetime import date as _date, timedelta as _timedelta
try:
    from database_progressions import (
        obtenir_chronologie as _obtenir_chronologie,
        obtenir_chapitre_a_date as _obtenir_chapitre_a_date,
        MOIS as _MOIS, MOIS_RE as _MOIS_RE,
    )
except Exception:
    _obtenir_chronologie = None
    _obtenir_chapitre_a_date = None

MOTS_DECLENCHEURS_CHRONOLOGIE = ["trimestre", "chronologie", "calendrier", "semaine par semaine"]

# CORRECTIF (17/09/2026) : intentions temporelles relatives, en plus de
# la date explicite deja geree par detecter_date_precise(). Toujours
# calcule en Python (timedelta) -- jamais demande a Gemini.
MOTIF_DANS_N_SEMAINES = _re.compile(r"dans\s+(\d+)\s+semaines?", _re.IGNORECASE)


def detecter_date_precise(question: str):
    """Cherche un motif 'JJ mois' ou 'JJ mois AAAA' dans la question.
    Retourne un objet date (année déduite : sept-déc -> 2026, sinon
    2027, cohérent avec l'année scolaire 2026-2027) ou None."""
    m = _re.search(rf"(\d{{1,2}})\s+({_MOIS_RE})\.?\s*(\d{{4}})?", question, _re.IGNORECASE)
    if not m:
        return None
    jour, mois_txt, annee_txt = m.groups()
    mois = _MOIS.get(mois_txt.lower())
    if not mois:
        return None
    annee = int(annee_txt) if annee_txt else (2026 if mois >= 9 else 2027)
    try:
        return _date(annee, mois, int(jour))
    except ValueError:
        return None


def detecter_date_relative(question: str):
    """NOUVEAU (17/09/2026) : 'aujourd'hui', 'demain', 'semaine
    prochaine', 'dans N semaines' -- toutes calculees depuis
    date.today() en Python, jamais laissees a Gemini. Retourne None si
    aucune intention relative n'est detectee (auquel cas
    detecter_date_precise reste la seule voie pour une date
    explicite)."""
    q = _normaliser(question)
    today = _date.today()

    if "aujourdhui" in q or "aujourd hui" in q:
        return today
    if "demain" in q:
        return today + _timedelta(days=1)
    if "semaine prochaine" in q:
        return today + _timedelta(weeks=1)

    m = MOTIF_DANS_N_SEMAINES.search(q)
    if m:
        return today + _timedelta(weeks=int(m.group(1)))

    return None


def detecter_demande_chronologie(question: str) -> bool:
    q_norm = _normaliser(question)
    return any(mot in q_norm for mot in MOTS_DECLENCHEURS_CHRONOLOGIE)

MOTS_DECLENCHEURS_RENTREE = [
    "rentree", "la rentree", "debut de l'annee", "commence l'annee",
    "quand commence", "debut des cours", "debut du programme",
]

MOTS_DECLENCHEURS_PROGRAMME_GENERAL = [
    "quel est mon programme", "mon programme", "programme complet", "tout le programme",
]


def detecter_question_programme_general(question: str) -> bool:
    q = _normaliser(question)
    return any(_normaliser(m) in q for m in MOTS_DECLENCHEURS_PROGRAMME_GENERAL)


def detecter_question_rentree(question: str) -> bool:
    q = _normaliser(question)
    return any(_normaliser(m) in q for m in MOTS_DECLENCHEURS_RENTREE)


def repondre_chronologie_datee(
    question: str,
    eleve: dict | None,
    matiere: str = MATIERE_DEFAUT,
) -> str | None:
    """Point d'entrée à appeler AVANT tout appel Gemini.

    CORRECTIF CRITIQUE (17/09/2026) : `matiere` était absente de la
    signature -- _obtenir_chapitre_a_date() était toujours appelée avec
    MATIERE_DEFAUT="Mathematiques" en dur, quelle que soit la matière
    réellement active dans la conversation. Un élève en scope Physique
    qui demandait "on fait quoi le 12 janvier" recevait silencieusement
    la chronologie de Maths -- seule vraie fuite croisée matière du
    système (database_progressions.py filtre déjà correctement partout
    ailleurs). L'appelant (app.py, assistant_eleve_repondre) DOIT
    transmettre la matière active de la conversation ici.

    Gère aussi désormais 'chapitres' (liste, voir
    obtenir_progression_du_jour côté database_progressions.py) au lieu
    d'un seul chapitre -- un élève qui demande sa date pendant une
    période à chapitres multiples (ex: Physique Terminale C mi-mars,
    3 chapitres en parallèle) reçoit la liste complète, pas juste le
    premier."""
    if _obtenir_chronologie is None or not eleve:
        return None
    if matiere not in MATIERES_AVEC_PROGRESSION:
        return None

    niveau = CORRESPONDANCE_NIVEAU_PROGRESSION.get((eleve.get("niveau") or "").strip().lower())
    serie = (eleve.get("serie") or "").strip().upper() or None
    if niveau is None:
        return None
    if detecter_question_rentree(question):
        try:
            from database_progressions import obtenir_date_rentree
        except Exception:
             return None
        date_rentree = obtenir_date_rentree(matiere, niveau, serie)
        if date_rentree:
            return (f"D'après le calendrier officiel MINESEC, les cours de {matiere} "
                    f"pour ta classe ont commencé le {date_rentree.strftime('%d/%m/%Y')}.")
        return f"Je n'ai pas de date de rentrée vérifiée en {matiere} pour ta classe."

    if detecter_question_programme_general(question):
        chapitres = _obtenir_chronologie(matiere, niveau, serie)
        if not chapitres:
            return None
        lignes = [f"Voici ton programme officiel MINESEC en {matiere} ({eleve.get('niveau')} "
                  f"{serie or ''}) :\n"]
        for c in chapitres:
            periode = c.get("semaine_texte") or "période non précisée"
            lignes.append(f"{c['ordre']}. {c['nom_chapitre']} — {periode}")
        return "\n".join(lignes)

    date_cible = detecter_date_precise(question) or detecter_date_relative(question)
    if date_cible:
        info = _obtenir_chapitre_a_date(matiere, niveau, serie, date_cible)
        jour_lisible = date_cible.strftime("%d/%m/%Y")

        if info.get("disponible"):
            chapitres = info["chapitres"]
            if len(chapitres) == 1:
                c = chapitres[0]
                return (f"Le {jour_lisible} en {matiere}, tu es censé être sur le chapitre "
                        f"« {c['nom_chapitre']} » (semaine du {c['periode']}).")
            noms = ", ".join(f"« {c['nom_chapitre']} »" for c in chapitres)
            return (f"Le {jour_lisible} en {matiere}, {len(chapitres)} chapitres sont menés "
                    f"en parallèle selon le calendrier officiel MINESEC : {noms}.")

        if info.get("prochain_chapitre"):
            return (f"Le {jour_lisible} en {matiere}, aucun chapitre officiel n'est en cours "
                    f"(vacances ou hors calendrier). Prochain chapitre prévu : "
                    f"« {info['prochain_chapitre']} », à partir du "
                    f"{info['prochain_chapitre_debut']}.")

        return f"Je n'ai pas de donnée de progression officielle en {matiere} pour le {jour_lisible}."

    if detecter_demande_chronologie(question):
        chapitres = _obtenir_chronologie(matiere, niveau, serie)
        if not chapitres:
            return None
        lignes = [f"Voici la chronologie complète en {matiere} pour {eleve.get('niveau')} "
                  f"{serie or ''} :\n"]
        for c in chapitres:
            periode = c.get("semaine_texte") or "période non précisée"
            lignes.append(f"{c['ordre']}. {c['nom_chapitre']} — {periode}")
        return "\n".join(lignes)

    return None

# ═══════════════════════════════════════════════════════
# TEST DIRECT
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    question = (
        " ".join(sys.argv[1:])
        or "Explique-moi les suites géométriques"
    )

    print(
        f"Question : {question}\n"
    )

    texte, fournisseur, source, tokens_entree, tokens_sortie = repondre_eleve(
        question,
        matiere=MATIERE_DEFAUT,
    )

    print(
        f"[Répondu par {fournisseur} / {source} -- "
        f"{tokens_entree} tokens entrée, {tokens_sortie} tokens sortie]\n"
    )

    print(texte)