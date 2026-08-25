from pydantic import BaseModel, Field
from typing import Optional


class BoiteTexte(BaseModel):
    x: float = Field(description="Position horizontale du coin haut-gauche du texte, fraction (0 à 1) de la largeur de la page complète.")
    y: float = Field(description="Position verticale du coin haut-gauche du texte, fraction (0 à 1) de la hauteur de la page complète.")
    largeur: float = Field(description="Largeur de la zone occupée par ce texte, fraction (0 à 1) de la largeur de la page.")
    hauteur: float = Field(description="Hauteur de la zone occupée par ce texte, fraction (0 à 1) de la hauteur de la page.")


class ChampEntete(BaseModel):
    label: str = Field(description="Nom court et clair du champ, ex: 'Année scolaire', 'Séquence', 'Classe', 'Durée', 'Coefficient', 'Examinateur', 'Établissement', 'Région'. Un champ par donnée distincte visible.")
    valeur: str = Field(description="Valeur textuelle lue à cet endroit, ex: '2025-2026', '2e SEQUENCE', '3 heures', '7', 'LE DEPARTEMENT'.")
    boite: Optional[BoiteTexte] = Field(
        default=None,
        description="Position de CE texte précis dans la page. Null UNIQUEMENT si sa position ne "
                    "peut vraiment pas être déterminée avec confiance (texte flou, coupé, superposé "
                    "à autre chose) -- dans ce cas la valeur reste quand même rapportée dans "
                    "`valeur`, seule l'édition visuelle automatique de ce champ ne sera pas possible."
    )


class ExtractionEnteteComplete(BaseModel):
    fraction_bas_entete: float = Field(
        description="Fraction (0.05 à 0.6) de la hauteur totale de la page, depuis le HAUT, à "
                    "laquelle se termine le bloc d'en-tête institutionnel. RÈGLE ABSOLUE : coupe "
                    "OBLIGATOIREMENT avant la première ligne contenant 'PARTIE', 'EXERCICE', "
                    "'EVALUATION DES', 'POINTS' ou 'SITUATION' -- ces mots marquent le contenu de "
                    "l'épreuve, jamais l'en-tête, même dans un cadre continu. RÈGLE TOUT AUSSI "
                    "IMPORTANTE : si l'en-tête est structuré en tableau (lignes/colonnes), la "
                    "coupure doit se faire APRÈS la dernière ligne du tableau entièrement visible, "
                    "JAMAIS au milieu d'une ligne ou d'une cellule -- mieux vaut inclure un peu de "
                    "marge blanche en trop après le tableau que de trancher une ligne en deux."
    )
    confiance: str = Field(description="'haute' si l'en-tête est net et bien lisible, 'basse' si flou/incliné/coupé.")
    champs: list[ChampEntete] = Field(
        description="TOUS les champs de données variables visibles dans le bloc d'en-tête (avant "
                    "la coupure) : établissement, région, délégation, année scolaire, séquence/"
                    "examen, classe, durée, coefficient, examinateur, et tout autre champ variable "
                    "présent sur ce document précis. Ne pas se limiter à une liste fixe -- chaque "
                    "établissement présente ses champs différemment."
    )


class VerificationDecoupe(BaseModel):
    contient_mots_interdits: bool = Field(
        description="True si l'image contient un des mots 'PARTIE', 'EXERCICE', "
                    "'EVALUATION DES', 'POINTS' ou 'SITUATION', False sinon."
    )
    contenu_visuellement_tronque: bool = Field(
        description="True si l'image se termine au milieu d'une ligne de tableau, d'une cellule, "
                    "ou d'un bloc de texte visiblement incomplet -- par exemple une ligne de "
                    "tableau dont on ne voit que le haut, une bordure noire tranchée avant sa fin "
                    "naturelle, ou un mot coupé en plein milieu. False si l'image se termine "
                    "proprement : ligne blanche, fin nette d'un tableau, ou juste avant le début "
                    "du contenu pédagogique de l'épreuve."
    )
    haut_de_page_deja_tronque: bool = Field(
        description="True si la toute première ligne visible en haut de l'image (logo, nom "
                    "d'établissement, première ligne du tableau) est elle-même coupée en plein "
                    "milieu d'un caractère, d'un mot, ou d'une bordure -- signe que la photo ou le "
                    "scan source ne contient pas le tout début de l'en-tête. False si le haut de "
                    "l'image commence proprement (même si c'est juste une marge blanche avant le "
                    "contenu, ou le tout début net du logo/texte)."
    )