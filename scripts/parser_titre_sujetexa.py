"""
scripts/parser_titre_sujetexa.py
"""

import re

REGIONS_CAMEROUN = {
    "ADAMAOUA": ["ADAMAOUA"],
    "CENTRE": ["CENTRE"],
    "EST": ["EST"],
    "EXTREME-NORD": ["EXTREME-NORD", "EXTRÊME-NORD", "EXTREME NORD"],
    "LITTORAL": ["LITTORAL"],
    "NORD": ["NORD"],
    "NORD-OUEST": ["NORD-OUEST", "NORD OUEST"],
    "OUEST": ["OUEST"],
    "SUD": ["SUD"],
    "SUD-OUEST": ["SUD-OUEST", "SUD OUEST"],
}
ORDRE_VERIFICATION_REGIONS = [
    "EXTREME-NORD", "NORD-OUEST", "SUD-OUEST", "OUEST",
    "ADAMAOUA", "CENTRE", "EST", "LITTORAL", "SUD", "NORD",
]

MOTS_ETABLISSEMENT = ["COLLEGE", "COLLÈGE", "LYCEE", "LYCÉE", "INSTITUT", "COMPLEXE", "GROUPE SCOLAIRE"]

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

PATTERN_CLASSE = re.compile(
    r"\bT?Le?[ACD]{1,3}4?\b|\bP[ACD]{1,3}\b|\b[3456]\s*(?:e|ème|EME)\b",
    re.IGNORECASE
)

# Toutes les variantes de tiret rencontrees dans les titres scrapes :
# tiret ASCII (-), cadratin (—), demi-cadratin/en dash (–). Certains
# titres epreuvesetcorriges melangent les deux dans le meme titre
# selon la source d'origine du document -- on normalise tout vers
# le tiret ASCII avant le split, pour un decoupage previsible.
CARACTERES_TIRET = ["–", "—", "‑"]


def normaliser_tirets(titre: str) -> str:
    for car in CARACTERES_TIRET:
        titre = titre.replace(car, "-")
    return titre


def detecter_sequence(token: str) -> int | None:
    match = re.search(r"S[ÉE]QUENCE\s*N?°?\s*(\d+)", token, re.IGNORECASE)
    return int(match.group(1)) if match else None


def detecter_region(token: str) -> str | None:
    token_maj = token.upper()
    for region in ORDRE_VERIFICATION_REGIONS:
        for variante in REGIONS_CAMEROUN[region]:
            if variante in token_maj:
                return region
    return None


def est_token_dres(token: str) -> bool:
    return "DRES" in token.upper()


def detecter_etablissement(token: str) -> str | None:
    if est_token_dres(token):
        return None
    token_maj = token.upper()
    if any(mot in token_maj for mot in MOTS_ETABLISSEMENT):
        return token.strip()
    return None


def detecter_type_evaluation(token: str) -> str | None:
    token_maj = token.upper()
    for mot_cle, label in TYPES_EVALUATION:
        if mot_cle in token_maj:
            return label
    return None


def detecter_date(token: str) -> tuple[str | None, int | None]:
    token_maj = token.upper()

    match_scolaire = re.search(r"(20[0-2]\d)\s*[/\-]\s*(20[0-2]\d)", token)
    if match_scolaire:
        return None, int(match_scolaire.group(2))

    for mois in MOIS:
        if mois in token_maj:
            match_annee = re.search(r"(19[9]\d|20[0-2]\d)", token)
            annee = int(match_annee.group(1)) if match_annee else None
            return mois.capitalize(), annee

    match_annee_seule = re.search(r"\b(19[9]\d|20[0-2]\d)\b", token)
    if match_annee_seule:
        return None, int(match_annee_seule.group(1))

    return None, None


def detecter_classe(token: str) -> str | None:
    match = PATTERN_CLASSE.search(token)
    return match.group(0) if match else None


def parser_titre(titre: str) -> dict:
    """
    Decoupe le titre par '-' (apres normalisation des variantes de
    tiret) et classe chaque morceau. Chaque champ reste None si rien
    de fiable n'a ete detecte -- on ne devine jamais a l'aveugle.
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

    titre_normalise = normaliser_tirets(titre)
    tokens = [t.strip() for t in titre_normalise.split("-") if t.strip()]

    for token in tokens:
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


if __name__ == "__main__":
    titres_test = [
        "MATHEMATIQUES-COLLEGE PRIVE MONGO BETI-SÉQUENCE 6-MAI 2026-TLeC",
        "MATHEMATIQUES-DRES DE LOUEST-SEQUENCE 4-FEVRIER 2026-TLEC",
        # Titres epreuvesetcorriges (tirets cadratins/en-dash) :
        "SVTEEHB et Corrigé Harmonisé – Baccalauréat Blanc Régional N°1 – Série C & TI – Session Février 2026 – Délégation Régionale du Sud",
        "Mathématiques – Épreuve zéro régionale – Baccalauréat Série C – Février 2026 – Région du Nord",
        "Épreuve de Philosophie + Corrigé – Baccalauréat 2025 – Série C, D, E, TI – Cameroun",
    ]

    for titre in titres_test:
        print(f"\n{titre}")
        resultat = parser_titre(titre)
        for cle, valeur in resultat.items():
            if valeur is not None:
                print(f"  {cle:20s} -> {valeur}")