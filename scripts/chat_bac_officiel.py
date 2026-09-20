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

GÉNÉRIQUE PAR MATIÈRE (12/09/2026, extension Physique) :
obtenir_exercice_bac() accepte désormais `matiere`, transmis par
app.py depuis la matière active de la conversation élève.

FILTRE NIVEAU (13/09/2026, correctif Probatoire Maths) :
obtenir_exercice_bac() accepte désormais aussi `niveau`, traduit via
NIVEAU_VERS_TABLE, pour éviter qu'une collision entre plusieurs
niveaux sur la même (session, matiere) ne retourne une épreuve du
mauvais niveau.

CORRECTIF AFFICHAGE (13/09/2026) : le libellé affiché ("BAC"/
"Probatoire"/"BEPC") vient de exercice['niveau'] traduit via
LIBELLE_NIVEAU_AFFICHAGE, plus jamais codé en dur.

CORRECTIF NUMÉROTATION ROMAINE + PARTIES (19/09/2026, Probatoire D) :
- Informatique numérote ses exercices en chiffres romains (EXERCICE I,
  II, III) -- MOTIF_NUMERO_EXERCICE ne capturait que des chiffres
  arabes, donc aucune requête n'aboutissait jamais pour cette matière.
  CHIFFRES_ROMAINS convertit le numéro arabe détecté dans la question
  vers son équivalent romain pour élargir le matching.
- SVT répète "Exercice 1", "Exercice 2" IDENTIQUEMENT sous Partie A et
  sous Partie B -- sans distinction, la requête retombait toujours sur
  la première occurrence (Partie A), rendant la Partie B invisible.
  Le nouveau paramètre `partie` ('A' ou 'B') filtre sur la bonne
  occurrence ; sans lui, repli sur la première trouvée (comportement
  historique).
- Le filtre `type` est élargi à ('exercice', 'sous_partie') pour
  couvrir les variantes de structuration observées selon les PDFs
  sources (voir guide d'import, section "Format type hétérogène").

CORRECTIF HONNÊTETÉ TRANSCRIPTION (19/09/2026) : certaines sections
contiennent des figures/graphiques/tableaux que Gemini Vision n'a pas
pu transcrire avec confiance (scan flou, valeurs illisibles) --
retranscrire_epreuve_vision.py consigne désormais cette limite dans
`elements_non_transcrits` au lieu de l'ignorer silencieusement ou
d'inventer une description. formuler_reponse_exercice_bac() affiche
cet avertissement à l'élève et l'oriente vers "Parcourir les épreuves"
pour consulter l'épreuve originale scannée -- déjà disponible ailleurs
sur le site, donc jamais un vrai blocage pour l'élève.

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
MOTIF_PARTIE = re.compile(r"partie\s*([ab])\b", re.IGNORECASE)

NB_RESULTATS_MAX = 1  # un seul exercice par défaut -- pas toute l'épreuve d'un coup

# Vocabulaire de demande de correction/résolution -- déclenche une
# consigne de fidélité renforcée dans chat_contexte.py (voir
# INSTRUCTION_CORRECTION_FIDELE), PAS un nouvel appel Gemini ici :
# l'énoncé réel montré au tour précédent est déjà dans l'historique de
# conversation envoyé par le front à chaque tour, À CONDITION que ce
# tour ait bien été enregistré (voir app.py, correctif du 19/09/2026 :
# enregistrer_tour() doit être appelé aussi pour ce chemin, pas
# seulement pour les réponses Gemini en streaming).
MOTS_CORRECTION = [
    "corrige", "correction", "resous", "résous", "resoudre", "résoudre",
    "solution", "aide moi a resoudre", "comment resoudre",
    "explique la solution", "explique moi la correction",
]

# Correspondance niveau compte élève -> niveau tel que stocké dans
# epreuves_bac_officielles (issu du découpage du JSON source MINESEC).
NIVEAU_VERS_TABLE = {
    "bepc": "3e",
    "probatoire": "premiere",
    "bac": "terminale",
}

# Sens inverse de NIVEAU_VERS_TABLE -- utilisé uniquement pour
# l'affichage du libellé à l'élève, jamais pour une requête SQL.
LIBELLE_NIVEAU_AFFICHAGE = {
    "terminale": "BAC",
    "premiere": "Probatoire",
    "3e": "BEPC",
}

CHIFFRES_ROMAINS = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V", 6: "VI"}


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

    Retourne {'annee': int, 'numero': int|None, 'partie': str|None}
    ou None."""
    q_norm = _normaliser(question)

    match_annee = MOTIF_ANNEE.search(question)
    if not match_annee:
        return None

    if not any(mot in q_norm for mot in MOTS_ENTRAINEMENT):
        return None

    match_numero = MOTIF_NUMERO_EXERCICE.search(q_norm)
    match_partie = MOTIF_PARTIE.search(q_norm)

    return {
        "annee": int(match_annee.group()),
        "numero": int(match_numero.group(1)) if match_numero else None,
        "partie": match_partie.group(1).upper() if match_partie else None,
    }


def obtenir_exercice_bac(
    annee: int,
    numero: int | None = None,
    matiere: str = "Mathematiques",
    niveau: str | None = None,
    partie: str | None = None,
) -> dict | None:
    """Retrouve UNE section (exercice) réelle pour cette session et
    cette matière.

    `matiere='Mathematiques'` par défaut -- rétrocompatible.

    `niveau` (ex: 'BAC', 'Probatoire', 'BEPC') est traduit via
    NIVEAU_VERS_TABLE. `niveau=None` conserve le comportement
    historique sans filtre.

    `partie` (ex: 'A' ou 'B') -- filtre sur la bonne occurrence quand
    un même numéro d'exercice apparaît sous plusieurs parties (cas
    SVT). Sans `partie`, repli sur la première occurrence trouvée.

    Le matching du numéro couvre les chiffres arabes ET romains
    (Informatique utilise EXERCICE I/II/III), avec vérification de
    frontière pour éviter qu'"exercice I" ne matche "exercice II".

    Retourne None si rien ne correspond. Le dict retourné inclut
    `niveau` et `elements_non_transcrits` (None si tout a été transcrit
    avec confiance, sinon description de ce qui manque -- voir
    retranscrire_epreuve_vision.py)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        niveau_table = NIVEAU_VERS_TABLE.get((niveau or "").strip().lower())

        if niveau_table:
            try:
                epreuve = conn.execute(
                    "SELECT id, session, series, qualite, niveau FROM epreuves_bac_officielles WHERE session=? AND matiere=? AND niveau=?",
                    (annee, matiere, niveau_table)
                ).fetchone()
            except sqlite3.OperationalError:
                epreuve = conn.execute(
                    "SELECT id, session, series, niveau FROM epreuves_bac_officielles WHERE session=? AND matiere=? AND niveau=?",
                    (annee, matiere, niveau_table)
                ).fetchone()
        else:
            try:
                epreuve = conn.execute(
                    "SELECT id, session, series, qualite, niveau FROM epreuves_bac_officielles WHERE session=? AND matiere=?",
                    (annee, matiere)
                ).fetchone()
            except sqlite3.OperationalError:
                epreuve = conn.execute(
                    "SELECT id, session, series, niveau FROM epreuves_bac_officielles WHERE session=? AND matiere=?",
                    (annee, matiere)
                ).fetchone()

        if not epreuve:
            return None

        # Colonne elements_non_transcrits ajoutee par
        # retranscrire_epreuve_vision.py -- absente sur une base pas
        # encore migree, fallback explicite plutot qu'un SELECT qui
        # planterait.
        try:
            colonnes_ok = True
            conn.execute("SELECT elements_non_transcrits FROM sections_bac_officielles LIMIT 1")
        except sqlite3.OperationalError:
            colonnes_ok = False

        champs_section = "identifiant, titre, type, contenu_integral, bareme_annonce, ordre"
        if colonnes_ok:
            champs_section += ", elements_non_transcrits"

        if numero is not None:
            toutes_sections = conn.execute(f"""
                SELECT {champs_section}
                FROM sections_bac_officielles
                WHERE epreuve_id=?
                ORDER BY ordre
            """, (epreuve["id"],)).fetchall()

            numero_romain = CHIFFRES_ROMAINS.get(numero)

            def _matche_numero(identifiant, titre):
                cible = f"exercice {numero}".lower()
                cible_romain = f"exercice {numero_romain}".lower() if numero_romain else None
                texte = f"{identifiant or ''} {titre or ''}".lower()
                if cible in texte:
                    return True
                if cible_romain and cible_romain in texte:
                    idx = texte.find(cible_romain)
                    fin = idx + len(cible_romain)
                    if fin >= len(texte) or not texte[fin].isalpha():
                        return True
                return False

            partie_courante = None
            candidats = []

            for row in toutes_sections:
                type_section = (row["type"] or "").lower()

                if type_section == "partie":
                    texte_partie = f"{row['identifiant'] or ''} {row['titre'] or ''}"
                    m = MOTIF_PARTIE.search(_normaliser(texte_partie))
                    if m:
                        partie_courante = m.group(1).upper()
                    continue

                if type_section in ("exercice", "sous_partie"):
                    if _matche_numero(row["identifiant"], row["titre"]):
                        candidats.append((partie_courante, row))

            row = None
            if partie:
                for p, r in candidats:
                    if p == partie.upper():
                        row = r
                        break
                if row is None and candidats:
                    row = candidats[0][1]
            elif candidats:
                row = candidats[0][1]

        else:
            row = conn.execute(f"""
                SELECT {champs_section} FROM sections_bac_officielles
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
            "niveau": epreuve["niveau"] if "niveau" in epreuve.keys() else None,
            "elements_non_transcrits": (
                row["elements_non_transcrits"] if "elements_non_transcrits" in row.keys() else None
            ),
        }
    finally:
        conn.close()


def formuler_reponse_exercice_bac(exercice: dict | None, annee: int, numero: int | None) -> str:
    """Texte Markdown prêt pour le chat -- même contrat que les autres
    court-circuits déterministes ({'reponse': texte}).

    CORRECTIF (28/08/2026) : nettoyage des artefacts de scan connus,
    puis affichage en bloc de code Markdown pour l'OCR brut non
    vérifié (protège contre la renumérotation par marked.parse()).

    CORRECTIF (13/09/2026) : le libellé niveau vient de
    exercice['niveau'] traduit via LIBELLE_NIVEAU_AFFICHAGE.

    CORRECTIF (19/09/2026) : si `elements_non_transcrits` est renseigné
    (figure/tableau/graphique que Gemini Vision n'a pas pu transcrire
    avec confiance), l'élève en est informé explicitement et orienté
    vers "Parcourir les épreuves" pour consulter le PDF original --
    déjà disponible ailleurs sur le site, jamais un vrai blocage."""
    if not exercice:
        precision = f" (exercice {numero})" if numero else ""
        return (
            f"Je n'ai pas d'exercice officiel du Bac {annee}{precision} dans mon corpus actuel. "
            f"Essaie une autre année entre 1999 et 2025, ou demande-moi d'en générer un inédit à la place."
        )

    libelle_niveau = LIBELLE_NIVEAU_AFFICHAGE.get(exercice.get("niveau"), "BAC")
    entete = f"**{libelle_niveau} {exercice['series']} — {exercice['session']} — {exercice['titre']}**"

    note_elements_manquants = ""
    if exercice.get("elements_non_transcrits"):
        note_elements_manquants = (
            "\n\n⚠️ *(Cet exercice contient un élément (figure, tableau ou graphique) que je "
            "n'ai pas pu retranscrire avec certitude : "
            f"{exercice['elements_non_transcrits']}. Pour être sûr de travailler sur l'énoncé "
            "exact, va dans « Consulter les épreuves » dans le menu pour voir le sujet original "
            "scanné.)*"
        )

    if exercice.get("qualite") == "verifie_vision":
        note = (
            "\n\n*(Énoncé réel officiel MINESEC, relu et vérifié. "
            "Entraîne-toi dessus, puis demande-moi de le corriger si tu veux.)*"
            + note_elements_manquants
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
            + note_elements_manquants
        )
    else:
        note = (
            "\n\n*(Énoncé réel officiel MINESEC, extrait par OCR -- la mise en page brute est "
            "préservée telle quelle, certains caractères peuvent être mal reconnus par le scanner "
            "d'origine. Entraîne-toi dessus, puis demande-moi de le corriger si tu veux.)*"
            + note_elements_manquants
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

    resultat = re.sub(r"\n{3,}", "\n\n", resultat)
    resultat = re.sub(r"[ \t]{2,}", " ", resultat)

    return resultat.strip()