def metadonnees_defaut_eleve(type_document: str = "Sequence", serie: str | None = None) -> dict:
    """En-tête générique utilisé par le chat élève (RepetIA) -- pas de
    nom d'établissement réel, contrairement à l'ancien flux prof avec
    upload. construire_entete() dans construire_pdf_officiel.py a
    besoin de ces clés exactes pour ne pas lever de KeyError.

    coefficient/duree dépendent du type_document et de la série,
    exactement comme le fait déjà generer_epreuve_json() via
    COEFFICIENT_EXAMEN et DUREE_EXAMEN pour un Examen -- on réutilise
    la même logique ici plutôt que d'écrire une valeur fixe qui serait
    fausse pour la moitié des cas (ex: coefficient 7 ne vaut que pour
    la série C, jamais pour E ; 4 heures ne vaut que pour un Examen,
    jamais pour une séquence)."""
    if type_document == "Examen":
        coefficient = "7" if serie == "C" else "6"
        duree = "4 heures"
    else:
        coefficient = "7"
        duree = "3 heures"

    return {
        "region": "Extrême-Nord",
        "delegation": "RepetIA -- Assistant de révision",
        "etablissement": "Document de révision RepetIA",
        "annee_scolaire": "2025-2026",
        "duree": duree,
        "coefficient": coefficient,
        "bilingue": True,
    }