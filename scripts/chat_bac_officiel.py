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
  II, III) -- le matching du numéro couvre les chiffres arabes ET
  romains, avec vérification de frontière (\\b) pour éviter qu'
  "exercice I" ne matche "exercice II".
- SVT répète "Exercice 1", "Exercice 2" IDENTIQUEMENT sous Partie A et
  sous Partie B -- le paramètre `partie` ('A' à 'D', voir 22/09/2026)
  filtre sur la bonne occurrence ; sans lui, repli sur la première
  trouvée (comportement historique).

CORRECTIF HONNÊTETÉ TRANSCRIPTION (19/09/2026) : certaines sections
contiennent des figures/graphiques/tableaux que Gemini Vision n'a pas
pu transcrire avec confiance (scan flou, valeurs illisibles) --
retranscrire_epreuve_vision.py consigne désormais cette limite dans
`elements_non_transcrits` au lieu de l'ignorer silencieusement ou
d'inventer une description. formuler_reponse_exercice_bac() affiche
cet avertissement à l'élève et l'oriente vers "Parcourir les épreuves"
pour consulter l'épreuve originale scannée -- déjà disponible ailleurs
sur le site, donc jamais un vrai blocage pour l'élève.

═══════════════════════════════════════════════════════════════════
CHANTIER CORRESPONDANCE ÉLÈVE <-> EXERCICES BAC, ÉTAPE 2 (22/09/2026)
═══════════════════════════════════════════════════════════════════
Un audit complet du corpus a montré que la structure interne des
épreuves varie énormément selon la matière : SECTION A-D (Anglais),
Teil I-IV (Allemand), PARTIE A/B (Maths/Chimie), Sujet de type I/II/III
(Littérature), parfois une seule section sans découpage du tout
(Littérature 2017/2020). Trois correctifs apportés ici :

a) DÉTECTION ÉLARGIE -- un élève ne connaît pas le mot exact utilisé
   par SA matière : il dit "partie 2" ou "section 2" aussi
   naturellement que "exercice 2". MOTIF_NUMERO_EXERCICE couvre
   maintenant exercice/partie/section/sujet, et MOTIF_PARTIE couvre
   A-D (pas seulement A-B) pour SECTION A-D en Anglais.

b) PARAMÈTRE `serie` AJOUTÉ à obtenir_exercice_bac() -- sans lui,
   Chimie C et Chimie D (même matiere, même niveau) pouvaient se
   mélanger au hasard de l'ordre retourné par SQLite. Repli en LIKE
   si aucune série EXACTE ne correspond, pour couvrir les séries
   composites observées dans l'audit ('C et E', 'C/E' coexistant avec
   'C' pour Maths Terminale). Pour le BEPC (niveau_table == '3e'), la
   série est forcée à 'NA' en interne (comportement de stockage
   observé dans retranscrire_lot_robuste.lister_pdfs()).

c) FILTRAGE PAR LISTE NOIRE + REPLI ORDINAL -- l'ancienne liste
   blanche ("exercice", "sous_partie") excluait par un simple
   `continue` tout ce qui était type='partie', cassant Espagnol /
   Langue Française / Littérature, où le contenu réel de l'exercice
   est stocké DIRECTEMENT sous type='partie' (identifiants I, II,
   III, IV), sans sous-niveau 'exercice' en dessous. TYPES_FRONT_MATTER
   liste au contraire ce qui n'est JAMAIS du contenu exploitable
   (en-tête, texte introductif...) -- tout le reste devient candidat.
   Un repli ORDINAL (n-ième section de contenu dans l'ordre
   d'apparition, colonne `ordre`) prend le relais quand aucune
   correspondance textuelle n'est trouvée -- nécessaire pour
   SECTION A-D / Teil I-IV / Sujet de type I-III que l'élève ne
   nommera jamais littéralement ainsi dans sa question.

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

# ÉLARGI (étape 2a, 22/09/2026) : un élève dit aussi naturellement
# "partie 2" ou "section 2" que "exercice 2" -- il ne connaît pas la
# structure interne de sa matière. Les quatre mots sont acceptés
# indifféremment pour capturer le numéro.
MOTIF_NUMERO_EXERCICE = re.compile(
    r"(?:exercice|partie|section|sujet)\s*n?°?\s*(\d)", re.IGNORECASE
)
# ÉLARGI A-D (étape 2a, 22/09/2026), pas seulement A-B : SECTION A-D
# en Anglais notamment. "section" accepté en plus de "partie" pour la
# même raison que ci-dessus.
MOTIF_PARTIE = re.compile(r"(?:partie|section)\s*([a-d])\b", re.IGNORECASE)

LETTRE_VERS_ORDINAL = {"A": 1, "B": 2, "C": 3, "D": 4}
ROMAIN_VERS_ORDINAL = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6}

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

# NOUVEAU (étape 2c, 22/09/2026) : liste NOIRE des types de section qui
# ne sont JAMAIS du contenu d'exercice exploitable -- tout type absent
# de cette liste devient un candidat valable. Remplace l'ancienne
# liste BLANCHE ("exercice", "sous_partie") qui excluait par erreur
# type='partie' quand celui-ci PORTE directement le contenu réel
# (Espagnol, Littérature, Langue Française). Comparé sur texte
# normalisé (accents retirés, "_"/"-" réduits à un espace) pour
# absorber la corruption d'encodage connue sur cette colonne (voir
# chantier, étape 3 -- "en-tÛte" etc.) sans dépendre de la graphie
# exacte stockée.
TYPES_FRONT_MATTER = {
    "entete", "en tete", "header",
    "texte introductif", "texte support", "texte principal", "texte",
}


def detecter_demande_correction(question: str) -> bool:
    q_norm = _normaliser(question)
    return any(mot in q_norm for mot in [_normaliser(m) for m in MOTS_CORRECTION])


def _normaliser(texte: str) -> str:
    texte = texte.lower()
    texte = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in texte if not unicodedata.combining(c))


def _colonne_existe(conn: sqlite3.Connection, table: str, colonne: str) -> bool:
    """Vrai si `colonne` existe dans `table` -- utilisé pour dégrader
    gracieusement sur une base plus ancienne pas encore migrée
    (colonnes 'qualite', 'elements_non_transcrits'), sans dépendre
    d'un try/except SELECT différent à chaque endroit du fichier."""
    try:
        cur = conn.execute(f"PRAGMA table_info({table})")
        return any(row[1] == colonne for row in cur.fetchall())
    except sqlite3.OperationalError:
        return False


def detecter_demande_exercice_bac(question: str) -> dict | None:
    """Détection LOCALE, gratuite -- voir note en tête de fichier.
    Déclenche si une année plausible (1990-2029, large marge autour
    des sessions réellement couvertes) ET un mot d'entraînement sont
    présents ensemble. L'année seule ne suffit jamais (éviter de
    détourner "en 2020, la population camerounaise était de...").

    ÉLARGI (étape 2a) : `numero` peut venir de "exercice N", "partie N",
    "section N" ou "sujet N" -- l'élève ne connaît pas le mot exact de
    sa matière. `partie` couvre les lettres A à D.

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


# ═══════════════════════════════════════════════════════
# SÉLECTION DE L'ÉPREUVE (session + matiere + niveau + serie)
# ═══════════════════════════════════════════════════════

def _selectionner_epreuve(
    conn: sqlite3.Connection,
    annee: int,
    matiere: str,
    niveau_table: str | None,
    serie_recherche: str | None,
) -> sqlite3.Row | None:
    """Retrouve LA ligne d'épreuve pour (session, matiere[, niveau][,
    serie]). Voir docstring de obtenir_exercice_bac() pour le
    raisonnement complet sur `serie` (étape 2b) : tentative EXACTE
    d'abord, repli LIKE ensuite pour les séries composites, jamais de
    repli silencieux sur n'importe quelle série si `serie_recherche`
    est fourni et qu'aucune des deux tentatives n'aboutit -- mieux
    vaut retourner None (message "je n'ai pas cet exercice") qu'une
    épreuve de la mauvaise série."""
    champs = "id, session, series, niveau"
    if _colonne_existe(conn, "epreuves_bac_officielles", "qualite"):
        champs += ", qualite"

    conditions = ["session=?", "matiere=?"]
    params = [annee, matiere]
    if niveau_table:
        conditions.append("niveau=?")
        params.append(niveau_table)

    base_where = " AND ".join(conditions)

    if serie_recherche:
        row = conn.execute(
            f"SELECT {champs} FROM epreuves_bac_officielles WHERE {base_where} AND series=?",
            params + [serie_recherche],
        ).fetchone()
        if row:
            return row

        row = conn.execute(
            f"SELECT {champs} FROM epreuves_bac_officielles WHERE {base_where} AND series LIKE ?",
            params + [f"%{serie_recherche}%"],
        ).fetchone()
        if row:
            return row

        # Aucune série ne correspond, ni exactement ni en LIKE -- on
        # ne relâche PAS la contrainte série ici : c'est exactement le
        # bug que `serie` est censé corriger (mélange Chimie C/D).
        return None

    return conn.execute(
        f"SELECT {champs} FROM epreuves_bac_officielles WHERE {base_where}", params
    ).fetchone()


# ═══════════════════════════════════════════════════════
# SÉLECTION DE LA SECTION (numéro / partie, liste noire + repli ordinal)
# ═══════════════════════════════════════════════════════

def _type_est_front_matter(type_section: str) -> bool:
    t = (type_section or "").replace("_", " ").replace("-", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return _normaliser(t) in TYPES_FRONT_MATTER


def _matche_numero_texte(identifiant, titre, numero: int, numero_romain: str | None) -> bool:
    """Vrai si l'identifiant/titre de la section nomme explicitement
    ce numéro, sous n'importe laquelle des étiquettes plausibles
    (exercice/partie/section/sujet -- l'élève ne connaît pas le mot
    exact utilisé par sa matière), en chiffres arabes OU romains, avec
    frontière de mot (\\b) pour ne jamais confondre "exercice I" et
    "exercice II"."""
    texte = _normaliser(f"{identifiant or ''} {titre or ''}")
    etiquettes = ("exercice", "partie", "section", "sujet")

    motifs = [rf"\b{etq}\s*{numero}\b" for etq in etiquettes]
    if numero_romain:
        motifs += [rf"\b{etq}\s*{numero_romain.lower()}\b" for etq in etiquettes]

    return any(re.search(m, texte) for m in motifs)


def _selectionner_section(
    toutes_sections: list[sqlite3.Row],
    numero: int | None,
    partie: str | None,
):
    """Sélectionne LA section correspondant à la demande de l'élève
    parmi toutes les sections d'une épreuve (déjà triées par `ordre`).

    Remplace l'ancienne liste BLANCHE de types ('exercice',
    'sous_partie') par une liste NOIRE (TYPES_FRONT_MATTER) : tout
    type de section qui n'est pas explicitement du "front-matter"
    (en-tête, texte introductif...) est un candidat valable -- corrige
    le cas Espagnol/Littérature/Langue Française où le contenu réel
    est stocké directement sous type='partie' (identifiants I/II/III/IV),
    sans sous-niveau 'exercice' en dessous.

    Stratégie, dans l'ordre :
      1. Correspondance TEXTUELLE explicite (l'identifiant/titre de la
         section nomme littéralement le numéro ou la lettre demandés)
         -- la plus fiable quand elle existe.
      2. Repli ORDINAL : n-ième section de contenu dans l'ordre
         d'apparition (colonne `ordre`) -- nécessaire pour
         SECTION A-D / Teil I-IV / Sujet de type I-III, que l'élève ne
         nommera jamais littéralement ainsi dans sa question.

    Retourne None si rien ne correspond, y compris après repli
    ordinal (ex: numéro demandé au-delà du nombre de sections réelles)."""
    candidats_ordonnes: list[tuple[str | None, sqlite3.Row]] = []
    partie_courante: str | None = None
    sections_partie_elles_memes: dict[str, sqlite3.Row] = {}

    for row in toutes_sections:
        type_section = row["type"] or ""

        if _type_est_front_matter(type_section):
            continue

        if _normaliser(type_section) == "partie":
            texte_partie = f"{row['identifiant'] or ''} {row['titre'] or ''}"
            m = MOTIF_PARTIE.search(_normaliser(texte_partie))
            if m:
                partie_courante = m.group(1).upper()
                sections_partie_elles_memes[partie_courante] = row
            # Une section type='partie' est TOUJOURS elle-même un
            # candidat de contenu potentiel (cas Espagnol/Littérature),
            # en plus de servir de marqueur pour les sous-sections
            # suivantes -- c'est exactement le correctif de l'étape 2c.
            candidats_ordonnes.append((partie_courante, row))
            continue

        candidats_ordonnes.append((partie_courante, row))

    if not candidats_ordonnes:
        return None

    numero_romain = CHIFFRES_ROMAINS.get(numero) if numero else None

    # ── 1. Un numéro est demandé ─────────────────────────────────
    if numero is not None:
        candidats_numero = [
            (p, r) for p, r in candidats_ordonnes
            if _matche_numero_texte(r["identifiant"], r["titre"], numero, numero_romain)
        ]

        if candidats_numero:
            if partie:
                for p, r in candidats_numero:
                    if p == partie.upper():
                        return r
            # Repli historique : première occurrence trouvée si la
            # partie précisée ne matche aucun candidat textuel (comme
            # avant l'étape 2, pour ne jamais renvoyer un échec sec
            # sur un simple souci de partie mal reconnue).
            return candidats_numero[0][1]

        # Aucune correspondance textuelle -- repli ORDINAL, dans le
        # sous-ensemble de la bonne partie si elle est précisée.
        sous_ensemble = (
            [(p, r) for p, r in candidats_ordonnes if p == partie.upper()]
            if partie else candidats_ordonnes
        )
        if 1 <= numero <= len(sous_ensemble):
            return sous_ensemble[numero - 1][1]
        return None

    # ── 2. Pas de numéro, juste une partie/section-lettre ────────
    if partie:
        lettre = partie.upper()
        if lettre in sections_partie_elles_memes:
            return sections_partie_elles_memes[lettre]
        ordinal = LETTRE_VERS_ORDINAL.get(lettre)
        if ordinal and 1 <= ordinal <= len(candidats_ordonnes):
            return candidats_ordonnes[ordinal - 1][1]
        return None

    # ── 3. Ni numéro ni partie : comportement historique -- la
    # première section de contenu, peu importe son type exact.
    return candidats_ordonnes[0][1]


def obtenir_exercice_bac(
    annee: int,
    numero: int | None = None,
    matiere: str = "Mathematiques",
    niveau: str | None = None,
    partie: str | None = None,
    serie: str | None = None,
) -> dict | None:
    """Retrouve UNE section (exercice) réelle pour cette session et
    cette matière.

    `matiere='Mathematiques'` par défaut -- rétrocompatible.

    `niveau` (ex: 'BAC', 'Probatoire', 'BEPC') est traduit via
    NIVEAU_VERS_TABLE. `niveau=None` conserve le comportement
    historique sans filtre.

    `partie` (ex: 'A' à 'D') -- filtre sur la bonne occurrence quand
    un même numéro d'exercice apparaît sous plusieurs parties (cas
    SVT), ou sélectionne directement le contenu d'une partie/section
    lettrée quand `numero` n'est pas fourni (cas Anglais SECTION A-D).
    Sans `partie`, repli sur la première occurrence trouvée.

    `serie` (NOUVEAU, étape 2b, 22/09/2026) : filtre la série (ex:
    'C', 'D') pour éviter qu'une collision entre deux séries de la
    même (session, matiere, niveau) -- fréquent en Chimie/Physique --
    ne retourne une épreuve au hasard de l'ordre SQLite. Repli en LIKE
    si aucune correspondance EXACTE n'est trouvée, pour couvrir les
    séries composites observées dans l'audit ('C et E', 'C/E'
    coexistant avec 'C' pour Maths Terminale). Pour le BEPC
    (niveau_table == '3e'), la série de recherche est forcée à 'NA' en
    interne quelle que soit la valeur de `serie` fournie par
    l'appelant (comportement de stockage observé dans
    retranscrire_lot_robuste.lister_pdfs()) -- un niveau qui ne
    distingue pas de série ne doit jamais filtrer dessus par erreur.
    `serie=None` (comportement historique) ne filtre pas.

    Le matching du numéro couvre désormais exercice/partie/section/
    sujet, en chiffres arabes ET romains (étape 2a), et la sélection
    de section remplace l'ancienne liste blanche de types par une
    liste noire de "front-matter" + un repli ordinal (étape 2c) --
    voir _selectionner_section().

    Retourne None si rien ne correspond. Le dict retourné inclut
    `niveau` et `elements_non_transcrits` (None si tout a été transcrit
    avec confiance, sinon description de ce qui manque -- voir
    retranscrire_epreuve_vision.py)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        niveau_table = NIVEAU_VERS_TABLE.get((niveau or "").strip().lower())

        serie_recherche = (serie or "").strip() or None
        if niveau_table == "3e":
            serie_recherche = "NA"

        epreuve = _selectionner_epreuve(conn, annee, matiere, niveau_table, serie_recherche)
        if not epreuve:
            return None

        champs_section = "identifiant, titre, type, contenu_integral, bareme_annonce, ordre"
        if _colonne_existe(conn, "sections_bac_officielles", "elements_non_transcrits"):
            champs_section += ", elements_non_transcrits"

        toutes_sections = conn.execute(
            f"""
            SELECT {champs_section}
            FROM sections_bac_officielles
            WHERE epreuve_id=?
            ORDER BY ordre
            """,
            (epreuve["id"],),
        ).fetchall()

        row = _selectionner_section(toutes_sections, numero, partie)
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