# scripts/parser_titre_sujetexa.py
"""
Parseur intelligent des titres d'articles sujetexa.

Format typique observé :
    MATIERE-ETABLISSEMENT-SEQUENCE X-MOIS ANNEE-CLASSE
    MATIERE-DRES DE L'OUEST-SEQUENCE 4-FEVRIER 2026-TLEC
    MATIERE-ETABLISSEMENT-DEVOIR HARMONISE-CLASSE

On découpe par '-' puis on classe chaque morceau selon ce qu'il contient.
Rien n'est deviné au hasard : chaque détection est basée sur un motif
identifiable (mot-clé, regex), donc si un titre ne correspond à aucun
motif connu, le champ reste simplement vide plutôt que de deviner faux.

Usage :
    from parser_titre_sujetexa import parser_titre
    resultat = parser_titre("MATHEMATIQUES-COLLEGE JEAN TABI D'ETOUDI-DEVOIR HARMONISE-TLEC")
"""

import re

# ═══════════════════════════════════════════════════════
# RÉFÉRENTIELS
# ═══════════════════════════════════════════════════════

# Les 10 régions du Cameroun, avec leurs variantes d'écriture courantes
REGIONS_CAMEROUN = {
    "ADAMAOUA": ["ADAMAOUA"],
    "CENTRE": ["CENTRE"],
    "EST": ["EST"],
    "EXTREME-NORD": ["EXTREME-NORD", "EXTRÊME-NORD", "EXTREME NORD"],
    "LITTORAL": ["LITTORAL"],
    "NORD": ["NORD"], # attention : à chercher APRÈS extreme-nord/nord-ouest (voir plus bas)
    "NORD-OUEST": ["NORD-OUEST", "NORD OUEST"],
    "OUEST": ["OUEST"],
    "SUD": ["SUD"],
    "SUD-OUEST": ["SUD-OUEST", "SUD OUEST"],
}
# Ordre de vérification : du plus spécifique au plus générique,
# pour éviter que "NORD" ne matche à tort dans "NORD-OUEST" ou "EXTREME-NORD"
ORDRE_VERIFICATION_REGIONS = [
    "EXTREME-NORD", "NORD-OUEST", "SUD-OUEST", "OUEST",
    "ADAMAOUA", "CENTRE", "EST", "LITTORAL", "SUD", "NORD",
]

MOTS_ETABLISSEMENT = ["COLLEGE", "COLLÈGE", "LYCEE", "LYCÉE", "INSTITUT", "COMPLEXE", "GROUPE SCOLAIRE"]

# Types d'évaluation reconnus, du plus spécifique au plus générique
TYPES_EVALUATION = [
    ("BACCALAUREAT BLANC", "Baccalauréat blanc"),
    ("BAC BLANC", "Baccalauréat blanc"),
    ("BEPC BLANC", "BEPC blanc"),
    ("PROBATOIRE BLANC", "Probatoire blanc"),
    ("DEVOIR HARMONISE", "Devoir harmonisé"),
    ("DEVOIR HARMONISÉ", "Devoir harmonisé"),
    ("OLYMPIADE", "Olympiade"),
    ("EPREUVE ZERO", "Épreuve zéro"),
    ("ÉPREUVE ZÉRO", "Épreuve zéro"),
    ("CONTROLE", "Contrôle"),
    ("CONTRÔLE", "Contrôle"),
    ("SEQUENCE", "Séquence"),
    ("SÉQUENCE", "Séquence"),
]

MOIS = [
    "JANVIER", "FEVRIER", "FÉVRIER", "MARS", "AVRIL", "MAI", "JUIN",
    "JUILLET", "AOUT", "AOÛT", "SEPTEMBRE", "OCTOBRE", "NOVEMBRE", "DECEMBRE", "DÉCEMBRE",
]

# Classes/séries reconnues (élargi pour couvrir les variantes combinées type TLeCD)
PATTERN_CLASSE = re.compile(
    r"\bT?Le?[ACD]{1,3}4?\b|\bP[ACD]{1,3}\b|\b[3456]\s*(?:e|ème|EME)\b",
    re.IGNORECASE
)


# ═══════════════════════════════════════════════════════
# FONCTIONS DE DÉTECTION UNITAIRES
# ═══════════════════════════════════════════════════════

def detecter_sequence(token: str) -> int | None:
    """Cherche un numéro de séquence : 'SÉQUENCE 6', 'SEQUENCE N°4'."""
    match = re.search(r"S[ÉE]QUENCE\s*N?°?\s*(\d+)", token, re.IGNORECASE)
    return int(match.group(1)) if match else None


def detecter_region(token: str) -> str | None:
    """
    Cherche une région camerounaise dans le token.
    Priorité aux régions composées (Extrême-Nord, Nord-Ouest, Sud-Ouest)
    pour ne pas les confondre avec 'Nord' ou 'Sud' seuls.
    """
    token_maj = token.upper()
    for region in ORDRE_VERIFICATION_REGIONS:
        for variante in REGIONS_CAMEROUN[region]:
            if variante in token_maj:
                return region
    return None


def est_token_dres(token: str) -> bool:
    """DRES = Délégation Régionale de l'Enseignement Secondaire.
    Un token 'DRES DE L'OUEST' n'est PAS un établissement,
    c'est un examen harmonisé au niveau régional."""
    return "DRES" in token.upper()


def detecter_etablissement(token: str) -> str | None:
    """Un établissement contient COLLEGE/LYCEE/etc., mais n'est pas une DRES."""
    if est_token_dres(token):
        return None
    token_maj = token.upper()
    if any(mot in token_maj for mot in MOTS_ETABLISSEMENT):
        return token.strip()
    return None


def detecter_type_evaluation(token: str) -> str | None:
    """Retourne le type d'évaluation le plus spécifique trouvé dans le token."""
    token_maj = token.upper()
    for mot_cle, label in TYPES_EVALUATION:
        if mot_cle in token_maj:
            return label
    return None


def detecter_date(token: str) -> tuple[str | None, int | None]:
    """
    Cherche 'MOIS ANNEE' (ex: MAI 2026) ou une année scolaire 'AAAA/AAAA'.
    Retourne (mois_ou_None, annee).
    """
    token_maj = token.upper()

    # Année scolaire type "2025/2026" ou "2025-2026"
    match_scolaire = re.search(r"(20[0-2]\d)\s*[/\-]\s*(20[0-2]\d)", token)
    if match_scolaire:
        return None, int(match_scolaire.group(2)) # on garde la 2e année (fin d'année scolaire)

    # Mois + année
    for mois in MOIS:
        if mois in token_maj:
            match_annee = re.search(r"(19[9]\d|20[0-2]\d)", token)
            annee = int(match_annee.group(1)) if match_annee else None
            return mois.capitalize(), annee

    # Juste une année seule
    match_annee_seule = re.search(r"\b(19[9]\d|20[0-2]\d)\b", token)
    if match_annee_seule:
        return None, int(match_annee_seule.group(1))

    return None, None


def detecter_classe(token: str) -> str | None:
    """Cherche un code de classe/série reconnu (TLeC, PD, 3e, etc.)."""
    match = PATTERN_CLASSE.search(token)
    return match.group(0) if match else None


# ═══════════════════════════════════════════════════════
# FONCTION PRINCIPALE
# ═══════════════════════════════════════════════════════

def parser_titre(titre: str) -> dict:
    """
    Découpe le titre par '-' et classe chaque morceau.
    Chaque champ reste None si rien de fiable n'a été détecté --
    on ne devine jamais à l'aveugle.
    """
    resultat = {
        "etablissement": None,
        "region": None,
        "sequence": None,
        "type_evaluation": None,
        "mois": None,
        "annee_detectee": None,
        "classe_detectee": None,
    }

    tokens = [t.strip() for t in titre.split("-") if t.strip()]

    for token in tokens:
        # Région (avant établissement, car un token DRES ne doit pas
        # être classé comme établissement)
        region = detecter_region(token)
        if region and (est_token_dres(token) or resultat["region"] is None):
            resultat["region"] = region

        etab = detecter_etablissement(token)
        if etab:
            resultat["etablissement"] = etab

        seq = detecter_sequence(token)
        if seq is not None:
            resultat["sequence"] = seq

        type_eval = detecter_type_evaluation(token)
        if type_eval:
            resultat["type_evaluation"] = type_eval

        mois, annee = detecter_date(token)
        if mois:
            resultat["mois"] = mois
        if annee:
            resultat["annee_detectee"] = annee

        classe = detecter_classe(token)
        if classe:
            resultat["classe_detectee"] = classe

    return resultat


# ═══════════════════════════════════════════════════════
# AUTO-TEST sur de vrais titres de ton CSV
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    titres_test = [
        "MATHEMATIQUES-COLLEGE PRIVE MONGO BETI-SÉQUENCE 6-MAI 2026-TLeC",
        "MATHEMATIQUES-COLLEGE JEAN TABI-DEVOIR HARMONISE-TLeC",
        "MATHEMATIQUES-DRES DE LOUEST-SEQUENCE 4-FEVRIER 2026-TLEC",
        "MATHEMATIQUES-DRES DE LOUEST-SEQUENCE 4-FEVRIER 2026-CLASSE DE TLEC",
        "OLYMPIADES-DE-MATHEMATIQUES-2026-NIVEAU-TLEC-TLEF-REGION-D",
        "MATHEMATIQUES-COLLEGE SAINTE THERESE DE MVAA-SEQUENCE 3",
        "PHILOSOPHIE-LYCEE DE NKOLMESSENG-SEQUENCE 4-FEVRIER-2026-TLECD",
        "MATHEMATIQUES-COLLEGE MONGO BETI-SEQUENCE 6-CLASSE DE 3ème-2025/2026",
    ]

    for titre in titres_test:
        print(f"\n📄 {titre}")
        resultat = parser_titre(titre)
        for cle, valeur in resultat.items():
            if valeur is not None:
                print(f" {cle:20s} -> {valeur}")

