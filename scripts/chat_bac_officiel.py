# scripts/chat_bac_officiel.py
"""
Récupération d'exercices RÉELS du Bac (1999-2025) pour le chat élève
-- voir importer_epreuves_bac_officielles.py pour le schéma.

DÉTECTION ÉLARGIE, PAS DE FUNCTION CALLING GEMINI (28/08/2026,
décision explicite -- voir échange du jour) : laisser Gemini décider
lui-même quand aller chercher un exercice réel (via function calling /
tool use du SDK) donnerait une détection plus naturelle, MAIS double
le coût -- un premier appel pour la décision d'outil, un second pour
la réponse finale avec le résultat -- au moment où le quota gratuit
est déjà sous tension. Tant que le produit tourne sur quota gratuit,
la détection reste locale et gratuite : vocabulaire élargi (pas
seulement "épreuve/sujet") + présence d'une année plausible, sans
appel API. Le jour où un quota payant existe, ce module peut être
exposé comme un outil (tool) au SDK Gemini sans changer sa logique
interne -- seule la décision de déclenchement changerait de place.

Table SOURCE : sections_bac_officielles / epreuves_bac_officielles
(contenu réel, OCR intégral, PAS le corpus de style 'epreuves' utilisé
par le générateur -- distinction déjà actée à l'import).
"""

import re
import sqlite3
import unicodedata
from pathlib import Path

DB_PATH = Path("data/rag_maths_bac_c/rag.db")

# Vocabulaire volontairement large -- toute formulation plausible de
# "je veux m'entraîner sur un vrai sujet", pas seulement les mots
# techniques "épreuve"/"sujet" déjà utilisés par chat_intent_epreuve.py
# (qui, lui, cherche dans les annales EXTERNES d'établissements, pas
# les vraies sessions officielles du Bac -- deux besoins différents,
# volontairement deux modules séparés).
MOTS_ENTRAINEMENT = [
    "entraine", "entrainement", "entrainer", "sujet", "epreuve",
    "exercice", "session", "ancien", "vieux", "pratique", "revise",
    "revision", "bac de", "bac ", "examen de",
]

MOTIF_ANNEE = re.compile(r"\b(19[9]\d|20[0-2]\d)\b")
MOTIF_NUMERO_EXERCICE = re.compile(r"exercice\s*n?°?\s*(\d)", re.IGNORECASE)

NB_RESULTATS_MAX = 1  # un seul exercice par défaut -- pas toute l'épreuve d'un coup

# Vocabulaire de demande de correction/résolution -- déclenche une
# consigne de fidélité renforcée dans chat_contexte.py (voir
# INSTRUCTION_CORRECTION_FIDELE), PAS un nouvel appel Gemini ici :
# l'énoncé réel montré au tour précédent est déjà dans l'historique de
# conversation envoyé par le front à chaque tour (voir
# assistant_eleve.html, etat.historique) -- Gemini l'a donc déjà sous
# les yeux, il ne manque qu'une consigne stricte pour qu'il ne dérive
# pas vers un exercice générique similaire.
MOTS_CORRECTION = [
    "corrige", "correction", "resous", "résous", "resoudre", "résoudre",
    "solution", "aide moi a resoudre", "comment resoudre",
    "explique la solution", "explique moi la correction",
]


def detecter_demande_correction(question: str) -> bool:
    q_norm = _normaliser(question)
    return any(mot in q_norm for mot in [_normaliser(m) for m in MOTS_CORRECTION])


def _normaliser(texte: str) -> str:
    texte = texte.lower()
    texte = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in texte if not unicodedata.combining(c))


def detecter_demande_exercice_bac(question: str) -> dict | None:
    """Détection LOCALE, gratuite -- voir note en tête de fichier.
    Déclenche si une année plausible (1990-2029, large marge autour
    des sessions réellement couvertes) ET un mot d'entraînement sont
    présents ensemble. L'année seule ne suffit jamais (éviter de
    détourner "en 2020, la population camerounaise était de...").

    Retourne {'annee': int, 'numero': int|None} ou None."""
    q_norm = _normaliser(question)

    match_annee = MOTIF_ANNEE.search(question)
    if not match_annee:
        return None

    if not any(mot in q_norm for mot in MOTS_ENTRAINEMENT):
        return None

    match_numero = MOTIF_NUMERO_EXERCICE.search(q_norm)

    return {
        "annee": int(match_annee.group()),
        "numero": int(match_numero.group(1)) if match_numero else None,
    }


def obtenir_exercice_bac(annee: int, numero: int | None = None) -> dict | None:
    """Retrouve UNE section (exercice) réelle pour cette session.

    Si `numero` est fourni, cherche le titre contenant "EXERCICE {numero}"
    (insensible à la casse) -- correspond au format réel observé dans
    le corpus OCR ("EXERCICE 1 : 5,5 points..."). Sinon, retourne le
    premier exercice de l'épreuve (le plus petit `ordre` de type
    'exercice') -- jamais l'épreuve entière par défaut, pour ne pas
    noyer l'élève sous plusieurs pages d'un coup.

    Retourne None si la session n'existe pas dans le corpus, ou si le
    numéro demandé n'existe pas pour cette session -- jamais une
    approximation sur une autre année ou un autre numéro."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # 'qualite' peut ne pas exister sur une base jamais passée par
        # retranscrire_epreuve_vision.py -- fallback 'ocr_brut' explicite
        # via try/except plutôt qu'un SELECT qui planterait sur une
        # colonne absente.
        try:
            epreuve = conn.execute(
                "SELECT id, session, series, qualite FROM epreuves_bac_officielles WHERE session=? AND matiere='Mathematiques'",
                (annee,)
            ).fetchone()
        except sqlite3.OperationalError:
            epreuve = conn.execute(
                "SELECT id, session, series FROM epreuves_bac_officielles WHERE session=? AND matiere='Mathematiques'",
                (annee,)
            ).fetchone()

        if not epreuve:
            return None

        if numero is not None:
            row = conn.execute("""
                SELECT titre, contenu_integral, bareme_annonce FROM sections_bac_officielles
                WHERE epreuve_id=? AND LOWER(type)='exercice' AND titre LIKE ?
                ORDER BY ordre LIMIT 1
            """, (epreuve["id"], f"%EXERCICE {numero}%")).fetchone()
        else:
            row = conn.execute("""
                SELECT titre, contenu_integral, bareme_annonce FROM sections_bac_officielles
                WHERE epreuve_id=? AND LOWER(type)='exercice'
                ORDER BY ordre LIMIT 1
            """, (epreuve["id"],)).fetchone()

        if not row:
            return None

        return {
            "session": epreuve["session"], "series": epreuve["series"],
            "titre": row["titre"], "contenu_integral": row["contenu_integral"],
            "bareme_annonce": row["bareme_annonce"],
            "qualite": epreuve["qualite"] if "qualite" in epreuve.keys() else "ocr_brut",
        }
    finally:
        conn.close()


def formuler_reponse_exercice_bac(exercice: dict | None, annee: int, numero: int | None) -> str:
    """Texte Markdown prêt pour le chat -- même contrat que les autres
    court-circuits déterministes ({'reponse': texte}), pas de nouveau
    format front à gérer.

    CORRECTIF (28/08/2026) : le contenu brut est du texte OCR (voir
    contenu_integral_ocr) -- jamais réécrit ou reformulé, MAIS jamais
    envoyé tel quel non plus. Deux problèmes constatés sur un vrai
    test (BAC C 2023 Exercice 3) :
      1. Le front passe la réponse assistant par marked.parse() --
         "1.", "2.", "3." en début de ligne sont interprétés comme une
         liste Markdown numérotée, qui RENUMÉROTE et réorganise le
         texte, cassant la numérotation réelle des questions.
      2. Artefacts de scan qui n'apportent rien à l'élève ("Scanné
         avec CamScanner", "page 1 sur 2") polluent visuellement.
    Fix : nettoyage des artefacts connus (jamais du contenu
    mathématique, uniquement du bruit de scan identifié), puis
    affichage dans un bloc de code Markdown (```) -- rendu en
    monospace préformaté par marked.js, donc IMMUNISÉ contre toute
    réinterprétation de "1.", "2." etc. comme liste, et préserve les
    sauts de ligne exacts du texte source."""
    if not exercice:
        precision = f" (exercice {numero})" if numero else ""
        return (
            f"Je n'ai pas d'exercice officiel du Bac {annee}{precision} dans mon corpus actuel. "
            f"Essaie une autre année entre 1999 et 2025, ou demande-moi d'en générer un inédit à la place."
        )

    entete = f"**BAC {exercice['series']} — Maths {exercice['session']} — {exercice['titre']}**"

    # CORRECTIF (29/08/2026) : maintenant que retranscrire_epreuve_vision.py
    # produit du vrai LaTeX propre ($...$), le bloc de code Markdown qui
    # protégeait contre la casse de numérotation devient CONTRE-PRODUCTIF
    # sur ce texte -- il empêche aussi KaTeX de rendre les formules (un
    # bloc ``` est affiché en monospace brut, jamais interprété comme
    # LaTeX), donc l'élève voit "$\\frac{29}{36}$" en texte au lieu de la
    # fraction affichée. Sur du texte vérifié (qualite='verifie_vision'),
    # on rend en Markdown normal -- exactement le même pipeline que les
    # réponses de Gemini (marked.parse() + KaTeX auto-render côté front),
    # numérotation propre car transcription propre. Le bloc de code reste
    # la protection par défaut UNIQUEMENT sur l'OCR brut non vérifié,
    # où la numérotation peut encore être cassée ou incohérente.
    if exercice.get("qualite") == "verifie_vision":
        note = (
            "\n\n*(Énoncé réel officiel MINESEC, relu et vérifié. "
            "Entraîne-toi dessus, puis demande-moi de le corriger si tu veux.)*"
        )
        return f"{entete}\n\n{exercice['contenu_integral']}{note}"

    texte_propre = nettoyer_texte_ocr_pour_affichage(exercice["contenu_integral"])

    if texte_ocr_douteux(exercice["contenu_integral"]):
        note = (
            "\n\n⚠️ *(Énoncé réel officiel MINESEC, mais l'OCR de cette session est "
            "particulièrement dégradé -- plusieurs coefficients ou expressions risquent d'être "
            "illisibles ci-dessus. Si tu me demandes de corriger, je te dirai clairement quelles "
            "valeurs je ne peux pas garantir plutôt que d'inventer un résultat. Le plus sûr "
            "reste de vérifier ces valeurs sur ton propre support papier.)*"
        )
    else:
        note = (
            "\n\n*(Énoncé réel officiel MINESEC, extrait par OCR -- la mise en page brute est "
            "préservée telle quelle, certains caractères peuvent être mal reconnus par le scanner "
            "d'origine. Entraîne-toi dessus, puis demande-moi de le corriger si tu veux.)*"
        )
    return f"{entete}\n\n```\n{texte_propre}\n```{note}"


# Artefacts de scan connus, systématiquement présents dans l'OCR mais
# sans aucune valeur pour l'élève -- JAMAIS de contenu mathématique
# retiré ici, uniquement du bruit identifié à l'oeil sur plusieurs
# exemples réels du corpus.
MOTIFS_BRUIT_OCR = [
    re.compile(r"scann[ée]\s+avec\s+camscanner", re.IGNORECASE),
    re.compile(r"page\s*\d+\s*sur\s*\d+", re.IGNORECASE),
]


# CORRECTIF (28/08/2026, après retour terrain sur BAC C/E 2024 Ex.2 et
# BAC C/E 2025 Ex.1) : certaines sections sont tellement corrompues
# par l'OCR que même la consigne de fidélité (voir
# chat_contexte.INSTRUCTION_CORRECTION_FIDELE) ne suffit pas à faire
# réagir Gemini -- au lieu de s'arrêter net, il reste vague/générique
# sans jamais donner de vrais chiffres, ce qui est PIRE qu'un arrêt
# franc (ça a l'air rigoureux sans l'être). Détection locale, gratuite,
# de ce niveau de corruption AVANT même la demande de correction, pour
# avertir l'élève dès l'affichage de l'énoncé plutôt que de découvrir
# le problème seulement après une tentative de correction ratée.
#
# "@" n'apparaît JAMAIS dans un vrai énoncé de maths camerounais --
# marqueur quasi certain de corruption OCR sévère dans ce corpus
# (ex: "op(f)=21+;+ketp(k)=3-3k" au lieu des vraies images de la base
# f(i), f(j), f(k) de l'endomorphisme). 3+ occurrences de "|" isolé
# au milieu du texte sont un artefact de colonne de scan très
# caractéristique du même phénomène.
def texte_ocr_douteux(texte: str) -> bool:
    if "@" in texte:
        return True
    if texte.count("|") >= 3:
        return True
    return False


def nettoyer_texte_ocr_pour_affichage(texte: str) -> str:
    """Retire le bruit de scan connu et normalise les espaces/sauts de
    ligne multiples -- ne touche JAMAIS au contenu mathématique ou
    textuel réel, uniquement aux motifs de MOTIFS_BRUIT_OCR et à un
    excès d'espacement introduit par l'OCR."""
    resultat = texte
    for motif in MOTIFS_BRUIT_OCR:
        resultat = motif.sub("", resultat)

    # Normalise les sauts de ligne multiples (3+ -> 2) laissés par le
    # retrait des artefacts ci-dessus, sans aplatir la structure
    # normale en paragraphes du texte.
    resultat = re.sub(r"\n{3,}", "\n\n", resultat)
    resultat = re.sub(r"[ \t]{2,}", " ", resultat)

    return resultat.strip()